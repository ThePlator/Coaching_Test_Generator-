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
