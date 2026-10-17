"""JSON schema sent to Ollama's `format` field (LLD §8).

Language blocks are required for the chosen mode so constrained decoding
cannot leave them out; the other language is simply not in the schema.
"""

from __future__ import annotations

from typing import Literal

OutputMode = Literal["en", "hi", "bilingual"]

QTYPES = ["mcq", "true_false", "fill_blank", "short_answer"]

_LOCALIZED = {
    "type": "object",
    "properties": {
        "stem": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer_text": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["stem", "options", "answer_text", "explanation"],
}


def languages(mode: OutputMode) -> list[str]:
    return ["en", "hi"] if mode == "bilingual" else [mode]


def build_schema(mode: OutputMode, k: int) -> dict:
    """Schema for a batch of `k` questions in the given output mode."""
    langs = languages(mode)
    item_props: dict = {
        "qtype": {"type": "string", "enum": QTYPES},
        "answer_index": {"type": ["integer", "null"], "minimum": 0, "maximum": 3},
    }
    for lang in langs:
        item_props[lang] = _LOCALIZED
    item_props["source_quote"] = {"type": "string", "minLength": 15}

    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": max(1, k),
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "required": ["qtype", "answer_index", *langs, "source_quote"],
                },
            }
        },
        "required": ["questions"],
    }
