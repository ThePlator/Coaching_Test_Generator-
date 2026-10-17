"""Chunk → candidate questions via the LLM (LLD §9). No validation here."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from pydantic import ValidationError

from ctg import prompts
from ctg.llm import LLMBadOutput, LLMClient, LLMTimeout
from ctg.models import Chunk, LocalizedQ, Question, QType, TestConfig
from ctg.schema import build_schema, languages

log = logging.getLogger("ctg.generator")

TF_OPTIONS = {"en": ["True", "False"], "hi": ["सही", "गलत"]}
AVOID_LIMIT = 15


def generate_for_chunk(
    llm: LLMClient,
    chunk: Chunk,
    plan: list[QType],
    cfg: TestConfig,
    avoid: Iterable[str] = (),
    feedback: list[str] | None = None,
    max_per_call: int = 5,
) -> tuple[list[Question], int]:
    """Return (candidates, lost) where `lost` counts planned questions that never came back
    (failed batch or unparseable item)."""
    avoid_list = list(avoid)[-AVOID_LIMIT:]
    system = prompts.system_prompt(cfg.allow_aota)
    out: list[Question] = []
    lost = 0
    for start in range(0, len(plan), max_per_call):
        batch = plan[start:start + max_per_call]
        user = prompts.user_prompt(
            chunk_text=chunk.text,
            chunk_script=chunk.script,
            plan=batch,
            difficulty=cfg.difficulty,
            mode=cfg.mode,
            avoid=avoid_list + [q.primary().stem for q in out if q.en or q.hi],
            feedback=feedback,
        )
        try:
            data = llm.chat_json(system, user, build_schema(cfg.mode, len(batch)))
        except (LLMBadOutput, LLMTimeout) as e:
            log.info("chunk=%s batch failed: %s", chunk.id, type(e).__name__)
            lost += len(batch)
            continue
        items = data.get("questions") if isinstance(data, dict) else None
        parsed = [q for q in (to_question(it, chunk, cfg) for it in (items or [])) if q]
        lost += max(0, len(batch) - len(parsed))
        out += parsed
    return out, lost


def to_question(item: Any, chunk: Chunk, cfg: TestConfig) -> Question | None:
    """Map one raw model item to a Question. Returns None if it can't be parsed at all."""
    if not isinstance(item, dict):
        return None
    langs = languages(cfg.mode)
    qtype = str(item.get("qtype", "")).strip()
    idx = item.get("answer_index")
    idx = idx if isinstance(idx, int) and not isinstance(idx, bool) else None
    try:
        locs = {lang: _localized(item.get(lang)) for lang in langs}
        q = Question(
            chunk_id=chunk.id,
            qtype=qtype,
            difficulty=cfg.difficulty,
            answer_index=idx,
            source_quote=str(item.get("source_quote", "")).strip(),
            **{k: v for k, v in locs.items() if v is not None},
        )
    except ValidationError:
        return None
    if qtype == "true_false":
        _canonical_true_false(q)
    if qtype in ("fill_blank", "short_answer"):
        q.answer_index = None
    return q


def _localized(raw: Any) -> LocalizedQ | None:
    if not isinstance(raw, dict):
        return None
    opts = raw.get("options") or []
    return LocalizedQ(
        stem=str(raw.get("stem", "")).strip(),
        options=[str(o).strip() for o in opts] if isinstance(opts, list) else [],
        answer_text=str(raw.get("answer_text", "")).strip(),
        explanation=str(raw.get("explanation", "")).strip(),
    )


def _canonical_true_false(q: Question) -> None:
    """Force T/F options to the fixed labels so small wording drift doesn't fail checks."""
    if q.answer_index not in (0, 1):
        return
    for lang in ("en", "hi"):
        loc: LocalizedQ | None = getattr(q, lang)
        if loc is not None:
            loc.options = list(TF_OPTIONS[lang])
            loc.answer_text = TF_OPTIONS[lang][q.answer_index]
