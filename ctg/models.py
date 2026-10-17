"""Domain models (LLD §3).

Models are deliberately lenient about cross-field rules: a question straight
from the model may break them, and validate.check_question() is what reports
the exact failure code so the pipeline can retry or drop it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["en", "hi"]
Script = Literal["en", "hi", "mixed"]
OutputMode = Literal["en", "hi", "bilingual"]
QType = Literal["mcq", "true_false", "fill_blank", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]
ExamPreset = Literal["generic", "bihar_board", "bpsc", "ssc", "railway"]
QStatus = Literal["ok", "edited", "regenerated"]

QTYPE_LABELS: dict[str, str] = {
    "mcq": "Multiple choice",
    "true_false": "True / False",
    "fill_blank": "Fill in the blank",
    "short_answer": "Short answer",
}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


class SourceDocument(BaseModel):
    title: str
    text: str                        # NFC-normalised full text
    pages: list[str]                 # per page / per image text, paragraphs split by blank lines
    ocr_pages: list[int] = []        # page indexes that went through vision OCR
    script: Script


class Chunk(BaseModel):
    id: str                          # "c03"
    index: int
    text: str
    heading: str | None = None
    script: Script
    from_ocr: bool = False
    quota: int = 0                   # questions assigned (before over-generation)


class LocalizedQ(BaseModel):
    stem: str
    options: list[str] = []          # MCQ: 4, T/F: 2, others: []
    answer_text: str
    explanation: str = ""


class Question(BaseModel):
    id: str = Field(default_factory=new_id)
    chunk_id: str
    qtype: str                       # a QType when valid; kept as str so bad output can be reported
    difficulty: Difficulty
    answer_index: int | None = None  # MCQ/TF only; shared across languages
    en: LocalizedQ | None = None
    hi: LocalizedQ | None = None
    source_quote: str
    status: QStatus = "ok"
    warnings: list[str] = []
    marks: float = 1.0

    def primary(self) -> LocalizedQ:
        """The version used for de-duplication and display fallbacks."""
        loc = self.en or self.hi
        if loc is None:
            raise ValueError(f"question {self.id} has no language version")
        return loc


class TestConfig(BaseModel):
    num_questions: int = Field(default=10, ge=5, le=50)
    qtypes: list[QType] = Field(default_factory=lambda: ["mcq"], min_length=1)
    difficulty: Difficulty = "medium"
    mode: OutputMode = "bilingual"
    preset: ExamPreset = "generic"
    allow_aota: bool = False


class PaperMeta(BaseModel):
    institute: str
    institute_hi: str | None = None
    title: str
    date: date
    time_min: int
    marks_per_q: float = 1.0
    instructions_en: str = ""
    instructions_hi: str = ""


class Test(BaseModel):
    config: TestConfig
    meta: PaperMeta | None = None
    questions: list[Question]
    set_label: str | None = None


REASON_LABELS: dict[str, str] = {
    "schema": "incomplete question",
    "wrong_type": "wrong question type",
    "quote_short": "source quote too short",
    "quote_not_found": "source not found in chapter",
    "options_count": "wrong number of options",
    "options_dup": "repeated options",
    "answer_mismatch": "answer not among options",
    "aota": "'all/none of the above' option",
    "bilingual_mismatch": "Hindi and English versions differ",
    "blank_missing": "blank missing",
    "empty_text": "empty text",
    "wrong_script": "wrong language",
    "duplicate": "duplicate",
    "bad_output": "model output unreadable",
    "chunk_error": "error in one part of the chapter",
}


class GenerationReport(BaseModel):
    requested: int
    generated: int = 0               # candidates parsed from model output
    kept: int = 0
    retried: int = 0                 # questions asked for again after a failed check
    drop_reasons: dict[str, int] = {}
    seconds: float = 0.0

    @property
    def dropped(self) -> int:
        return sum(self.drop_reasons.values())

    def reject(self, reason: str, n: int = 1) -> None:
        if n > 0:
            self.drop_reasons[reason] = self.drop_reasons.get(reason, 0) + n

    def summary(self) -> str:
        """e.g. 'Kept 12 of 15 — dropped: 2 source not found in chapter, 1 duplicate'."""
        head = f"Kept {self.kept} of {self.requested}"
        if not self.drop_reasons:
            return head
        parts = ", ".join(
            f"{n} {REASON_LABELS.get(r, r)}"
            for r, n in sorted(self.drop_reasons.items(), key=lambda kv: -kv[1])
        )
        return f"{head} — dropped: {parts}"
