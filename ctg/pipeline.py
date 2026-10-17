"""Orchestration: ingest → chunk → generate → check, retry once, then drop (LLD §11)."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Callable, Literal

from ctg.chunker import allocate, chunk, expand_plan, type_plan
from ctg.config import Settings
from ctg.generator import generate_for_chunk
from ctg.ingest import SourceInput, ingest
from ctg.llm import LLMClient, LLMUnavailable, ModelMissing
from ctg.models import REASON_LABELS, Chunk, GenerationReport, Question, SourceDocument, Test, TestConfig
from ctg.validate import check_question, dedupe

log = logging.getLogger("ctg.pipeline")

TOP_UP_CALLS = 2
FEEDBACK_LIMIT = 6


@dataclass
class Progress:
    stage: Literal["extract", "ocr", "chunk", "generate", "check", "done"]
    current: int
    total: int
    kept: int
    message: str


ProgressFn = Callable[[Progress], None]


@dataclass
class RunResult:
    test: Test
    report: GenerationReport
    chunks: dict[str, Chunk]
    doc: SourceDocument


def prepare(src: SourceInput, llm: LLMClient, settings: Settings,
            on_progress: ProgressFn | None = None) -> tuple[SourceDocument, list[Chunk]]:
    """Extract text and split into chunks (step 1 of the UI)."""
    emit = on_progress or (lambda p: None)
    emit(Progress("extract", 0, 1, 0, "Reading the chapter"))
    doc = ingest(src, llm, settings,
                 on_progress=lambda msg, i, n: emit(Progress("ocr", i, n, 0, msg)))
    chunks = chunk(doc, settings.chunk_target_chars, settings.chunk_max_chars)
    emit(Progress("chunk", 1, 1, 0, f"Split into {len(chunks)} parts"))
    return doc, chunks


def generate(doc: SourceDocument, chunks: list[Chunk], cfg: TestConfig, llm: LLMClient,
             settings: Settings, on_progress: ProgressFn | None = None) -> RunResult:
    """Generate and check questions for an already-chunked chapter."""
    emit = on_progress or (lambda p: None)
    t0 = time.perf_counter()
    report = GenerationReport(requested=cfg.num_questions)
    allocated = [c for c in allocate(chunks, cfg.num_questions) if c.quota > 0]
    plans = type_plan(allocated, cfg.qtypes)
    kept: list[Question] = []

    for i, c in enumerate(allocated):
        emit(Progress("generate", i, len(allocated), len(kept),
                      f"Writing questions for part {i + 1} of {len(allocated)}"))
        try:
            kept += _fill_chunk(c, plans[c.id], cfg, llm, settings, kept, report)
        except (LLMUnavailable, ModelMissing):
            raise
        except Exception:
            log.exception("chunk=%s failed", c.id)
            report.reject("chunk_error", c.quota)

    missing = cfg.num_questions - len(kept)
    if missing > 0:
        emit(Progress("check", len(allocated), len(allocated), len(kept),
                      f"Writing {missing} more question(s)"))
        kept += _top_up(chunks, missing, cfg, llm, settings, kept, report)

    kept = kept[:cfg.num_questions]
    report.kept = len(kept)
    report.seconds = round(time.perf_counter() - t0, 1)
    log.info("run requested=%d kept=%d generated=%d retried=%d drops=%s seconds=%.1f",
             report.requested, report.kept, report.generated, report.retried,
             report.drop_reasons, report.seconds)
    emit(Progress("done", len(allocated), len(allocated), len(kept), report.summary()))
    return RunResult(Test(config=cfg, questions=kept), report, {c.id: c for c in chunks}, doc)


def run(src: SourceInput, cfg: TestConfig, llm: LLMClient, settings: Settings,
        on_progress: ProgressFn | None = None) -> RunResult:
    doc, chunks = prepare(src, llm, settings, on_progress)
    return generate(doc, chunks, cfg, llm, settings, on_progress)


def regenerate_one(test: Test, qid: str, chunks: dict[str, Chunk], llm: LLMClient,
                   settings: Settings, attempts: int = 2) -> Question | None:
    """Replace one question with a fresh one from the same chunk, same type.
    Returns None if no valid question came back."""
    old = next((q for q in test.questions if q.id == qid), None)
    if old is None or old.chunk_id not in chunks:
        return None
    c = chunks[old.chunk_id]
    others = [q for q in test.questions if q.id != qid]
    cfg = test.config.model_copy(update={"difficulty": old.difficulty})
    for _ in range(attempts):
        cands, _lost = generate_for_chunk(llm, c, [old.qtype], cfg, avoid=_stems(test.questions),
                                          max_per_call=1)
        good, _failures = _screen(cands, c, cfg, settings, others, report=None)
        if good:
            new = good[0]
            new.status = "regenerated"
            new.marks = old.marks
            return new
    return None


# -- internals --------------------------------------------------------------


def _fill_chunk(c: Chunk, plan, cfg: TestConfig, llm: LLMClient, settings: Settings,
                existing: list[Question], report: GenerationReport) -> list[Question]:
    k = math.ceil(c.quota * settings.overgen_factor)
    cands, lost = generate_for_chunk(llm, c, expand_plan(plan, k, cfg.qtypes), cfg,
                                     avoid=_stems(existing), max_per_call=settings.max_questions_per_call)
    report.reject("bad_output", lost)
    good, failures = _screen(cands, c, cfg, settings, existing, report)

    missing = c.quota - len(good)
    if missing > 0:                              # retry ONCE for this chunk
        report.retried += missing
        cands2, lost2 = generate_for_chunk(
            llm, c, expand_plan(plan, missing, cfg.qtypes), cfg,
            avoid=_stems(existing + good), feedback=failures[:FEEDBACK_LIMIT],
            max_per_call=settings.max_questions_per_call)
        report.reject("bad_output", lost2)
        good2, _ = _screen(cands2, c, cfg, settings, existing + good, report)
        good += good2
    return good[:c.quota]


def _top_up(chunks: list[Chunk], missing: int, cfg: TestConfig, llm: LLMClient, settings: Settings,
            existing: list[Question], report: GenerationReport) -> list[Question]:
    """Bounded extra pass on the largest chunks when the test is still short."""
    added: list[Question] = []
    for c in sorted(chunks, key=lambda c: len(c.text), reverse=True)[:TOP_UP_CALLS]:
        need = missing - len(added)
        if need <= 0:
            break
        k = min(math.ceil(need * settings.overgen_factor), settings.max_questions_per_call)
        try:
            cands, lost = generate_for_chunk(llm, c, expand_plan([], k, cfg.qtypes), cfg,
                                             avoid=_stems(existing + added),
                                             max_per_call=settings.max_questions_per_call)
        except (LLMUnavailable, ModelMissing):
            raise
        except Exception:
            log.exception("top-up chunk=%s failed", c.id)
            continue
        report.reject("bad_output", lost)
        good, _ = _screen(cands, c, cfg, settings, existing + added, report)
        added += good[:need]
    return added


def _screen(cands: list[Question], c: Chunk, cfg: TestConfig, settings: Settings,
            existing: list[Question], report: GenerationReport | None) -> tuple[list[Question], list[str]]:
    """Run checks + dedupe. Returns (passing questions, feedback lines for a retry prompt)."""
    good: list[Question] = []
    failures: list[str] = []
    if report:
        report.generated += len(cands)
    for q in cands:
        res = check_question(q, c, cfg, settings.quote_match_threshold)
        if res.ok:
            q.warnings = res.warnings
            good.append(q)
        else:
            if report:
                report.reject(res.reasons[0])
            stem = (q.en or q.hi).stem[:60] if (q.en or q.hi) else q.qtype
            failures.append(f"\"{stem}\": " + ", ".join(REASON_LABELS.get(x, x) for x in res.reasons))
    good, dups = dedupe(good, existing, settings.dedupe_threshold)
    if report:
        report.reject("duplicate", len(dups))
    failures += [f"\"{d.primary().stem[:60]}\": duplicate of an earlier question" for d in dups]
    return good, failures


def _stems(questions: list[Question]) -> list[str]:
    return [q.primary().stem for q in questions if q.en or q.hi]
