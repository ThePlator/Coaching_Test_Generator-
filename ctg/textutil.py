"""Text normalisation, script detection and fuzzy matching (LLD §5, §10.1)."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍­﻿"), None)
_PUNCT_MAP = str.maketrans({"।": ".", "॥": ".", "“": '"', "”": '"', "‘": "'", "’": "'"})
_WS = re.compile(r"\s+")


def _is_devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def norm(text: str) -> str:
    """Normalise for comparison: NFC, lowercase, no zero-width chars, no punctuation."""
    t = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH).translate(_PUNCT_MAP).lower()
    # Drop punctuation (category P*) and symbols, but never Devanagari marks (matras, nukta, virama).
    t = "".join(
        ch for ch in t
        if _is_devanagari(ch) or not unicodedata.category(ch).startswith(("P", "S"))
    )
    return _WS.sub(" ", t).strip()


def devanagari_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha() or _is_devanagari(ch)]
    if not letters:
        return 0.0
    return sum(_is_devanagari(ch) for ch in letters) / len(letters)


def detect_script(text: str) -> str:
    r = devanagari_ratio(text)
    if r >= 0.6:
        return "hi"
    if r <= 0.1:
        return "en"
    return "mixed"


def quote_score(quote: str, chunk: str) -> int:
    """0-100 score for how well `quote` appears in `chunk` (100 = exact substring)."""
    q, c = norm(quote), norm(chunk)
    if not q:
        return 0
    if q in c:
        return 100
    return round(fuzz.partial_ratio(q, c))


def contains_fuzzy(quote: str, chunk: str, threshold: int = 90) -> bool:
    return quote_score(quote, chunk) >= threshold


_SENTENCE_END = (".", "?", "!", "।", "॥", ":", ";")
_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
SENTENCE_SPLIT = re.compile(r"(?<=[.?!।])\s+")


def is_heading(line: str) -> bool:
    """Short single line with no sentence-ending punctuation, or a numbered heading."""
    s = line.strip()
    if not s or "\n" in s or len(s) >= 80 or s.endswith(("-", ",")):
        return False
    if _NUMBERED_HEADING.match(s):
        return True
    return not s.endswith(_SENTENCE_END) and len(s.split()) <= 10


def reflow(text: str) -> str:
    """Join hard-wrapped lines (as pypdf returns them) into paragraphs separated by blank lines.

    Headings stay on their own paragraph. A line ending a sentence that is clearly
    shorter than a typical line is treated as the end of a paragraph.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    lengths = sorted(len(ln) for ln in lines if ln)
    typical = lengths[len(lengths) // 2] if lengths else 0

    paras: list[str] = []
    cur: list[str] = []

    def flush() -> None:
        if cur:
            paras.append(" ".join(cur))
            cur.clear()

    for ln in lines:
        if not ln:
            flush()
            continue
        if is_heading(ln) and len(ln) < 0.7 * max(typical, 1):
            flush()
            paras.append(ln)
            continue
        if cur and cur[-1].endswith("-") and ln[:1].islower():
            cur[-1] = cur[-1][:-1] + ln          # re-join word hyphenated across lines
        else:
            cur.append(ln)
        if ln.endswith(_SENTENCE_END) and len(ln) < 0.7 * typical:
            flush()
    flush()
    return "\n\n".join(paras)


def clean_text(text: str) -> str:
    """NFC, strip zero-width/BOM, collapse spaces inside lines (keeps line breaks)."""
    t = unicodedata.normalize("NFC", text).replace("﻿", "").replace("​", "")
    return "\n".join(re.sub(r"[ \t ]+", " ", ln).strip() for ln in t.splitlines())


def garbage_ratio(text: str) -> float:
    """Share of replacement / private-use glyphs — high for legacy Hindi fonts like Kruti Dev."""
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    bad = sum(ch == "�" or "" <= ch <= "" for ch in chars)
    return bad / len(chars)
