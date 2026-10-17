"""Code-side checks on generated questions, and de-duplication (LLD §10)."""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ctg.models import Chunk, LocalizedQ, Question, TestConfig
from ctg.schema import languages
from ctg.textutil import devanagari_ratio, detect_script, norm, quote_score

QTYPES = {"mcq", "true_false", "fill_blank", "short_answer"}
MIN_QUOTE = 15
AOTA_PHRASES = [norm(p) for p in (
    "all of the above", "none of the above", "both a and b", "both (a) and (b)",
    "उपरोक्त सभी", "उपर्युक्त सभी", "इनमें से कोई नहीं", "इनमें से कोई भी नहीं",
)]


@dataclass
class CheckResult:
    reasons: list[str] = field(default_factory=list)    # hard failures → retry / drop
    warnings: list[str] = field(default_factory=list)   # soft → shown in review UI

    @property
    def ok(self) -> bool:
        return not self.reasons

    def fail(self, code: str) -> None:
        if code not in self.reasons:
            self.reasons.append(code)


def check_question(q: Question, chunk: Chunk, cfg: TestConfig, quote_threshold: int = 90) -> CheckResult:
    r = CheckResult()
    langs = languages(cfg.mode)

    # schema: the right language versions, a known type
    if any(getattr(q, lang) is None for lang in langs):
        r.fail("schema")
        return r
    if q.qtype not in QTYPES:
        r.fail("schema")
        return r
    if q.qtype not in cfg.qtypes:
        r.fail("wrong_type")

    # source quote
    nq = norm(q.source_quote)
    if len(nq) < MIN_QUOTE:
        r.fail("quote_short")
    elif quote_score(q.source_quote, chunk.text) < quote_threshold:
        r.fail("quote_not_found")

    locs: dict[str, LocalizedQ] = {lang: getattr(q, lang) for lang in langs}
    for lang, loc in locs.items():
        _check_localized(r, q, loc, lang, cfg)

    if cfg.mode == "bilingual":
        en, hi = locs["en"], locs["hi"]
        if len(en.options) != len(hi.options):
            r.fail("bilingual_mismatch")

    if r.ok:
        r.warnings = _warnings(q, chunk, locs)
    return r


def _check_localized(r: CheckResult, q: Question, loc: LocalizedQ, lang: str, cfg: TestConfig) -> None:
    if not loc.stem.strip() or not loc.answer_text.strip() or any(not o.strip() for o in loc.options):
        r.fail("empty_text")
        return

    if q.qtype in ("mcq", "true_false"):
        expected = 4 if q.qtype == "mcq" else 2
        if len(loc.options) != expected:
            r.fail("options_count")
        normed = [norm(o) for o in loc.options]
        if len(set(normed)) != len(normed) or any(
            fuzz.ratio(a, b) >= 95 for i, a in enumerate(normed) for b in normed[i + 1:]
        ):
            r.fail("options_dup")
        idx = q.answer_index
        if idx is None or not 0 <= idx < len(loc.options) or norm(loc.options[idx]) != norm(loc.answer_text):
            r.fail("answer_mismatch")
        if not cfg.allow_aota and any(p in o for o in normed for p in AOTA_PHRASES):
            r.fail("aota")
    elif loc.options:
        r.fail("options_count")

    if q.qtype == "fill_blank" and "___" not in loc.stem:
        r.fail("blank_missing")

    ratio = devanagari_ratio(loc.stem)
    if (lang == "hi" and ratio < 0.5) or (lang == "en" and ratio > 0.2):
        r.fail("wrong_script")


def _warnings(q: Question, chunk: Chunk, locs: dict[str, LocalizedQ]) -> list[str]:
    w: list[str] = []
    quote_lang = detect_script(q.source_quote)
    loc = locs.get(quote_lang) if quote_lang in ("en", "hi") else None
    if loc and q.qtype != "true_false" and fuzz.partial_ratio(norm(loc.answer_text), norm(q.source_quote)) < 70:
        w.append("answer_not_in_quote")
    if any(len(l.stem) > 300 for l in locs.values()):
        w.append("long_stem")
    if chunk.from_ocr:
        w.append("ocr_source")
    return w


def dedupe_key(q: Question) -> str:
    return norm(q.primary().stem)


def dedupe(questions: list[Question], existing: list[Question] = (), threshold: int = 90
           ) -> tuple[list[Question], list[Question]]:
    """Keep the first of any near-duplicate pair. Returns (kept, dropped).

    token_sort_ratio, not token_set_ratio: set-based matching scores stems that differ
    in one key word (\"...Right to Equality?\" vs \"...Right to Freedom?\") as duplicates.
    """
    seen = [dedupe_key(q) for q in existing]
    kept: list[Question] = []
    dropped: list[Question] = []
    for q in questions:
        key = dedupe_key(q)
        if any(fuzz.token_sort_ratio(key, s) >= threshold for s in seen):
            dropped.append(q)
        else:
            kept.append(q)
            seen.append(key)
    return kept, dropped
