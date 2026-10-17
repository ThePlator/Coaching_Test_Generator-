"""First-user session log (plan M3): timings and review counts, never chapter text."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class SessionLog(BaseModel):
    started_at: str = ""                 # wall-clock ISO time the chapter was submitted
    t0: float = 0.0                      # perf counter at start (not meaningful across runs)
    input_kind: str = ""
    pages: int = 0
    ocr_pages: int = 0
    chunks: int = 0
    chapter_ready_s: float | None = None
    generated_s: float | None = None
    exported_s: float | None = None      # first export only: "chapter in → PDFs out"
    mode: str = ""
    qtypes: list[str] = []
    difficulty: str = ""
    requested: int = 0
    kept: int = 0
    generation_seconds: float = 0.0
    drop_reasons: dict[str, int] = {}
    generations: int = 0                 # how many times "Generate" was pressed
    edited: int = 0
    deleted: int = 0
    regenerated: int = 0
    regenerate_failed: int = 0
    final_questions: int = 0
    final_unchanged: int = 0
    exports: int = 0

    @classmethod
    def start(cls, input_kind: str) -> "SessionLog":
        return cls(started_at=datetime.now().isoformat(timespec="seconds"), t0=time.perf_counter(),
                   input_kind=input_kind)

    def elapsed(self) -> float:
        return round(time.perf_counter() - self.t0, 1)

    def chapter_ready(self, pages: int, ocr_pages: int, chunks: int) -> None:
        self.pages, self.ocr_pages, self.chunks = pages, ocr_pages, chunks
        self.chapter_ready_s = self.elapsed()

    def generated(self, report, cfg) -> None:
        self.generations += 1
        self.generated_s = self.elapsed()
        self.mode, self.qtypes, self.difficulty = cfg.mode, list(cfg.qtypes), cfg.difficulty
        self.requested, self.kept = report.requested, report.kept
        self.generation_seconds = report.seconds
        self.drop_reasons = dict(report.drop_reasons)
        # a fresh test resets the review counters
        self.edited = self.deleted = self.regenerated = self.regenerate_failed = 0

    def exported(self, questions) -> None:
        self.exports += 1
        if self.exported_s is None:
            self.exported_s = self.elapsed()
        self.final_questions = len(questions)
        self.final_unchanged = sum(q.status == "ok" for q in questions)

    def summary_lines(self) -> list[str]:
        def mmss(s: float | None) -> str:
            return "—" if s is None else f"{int(s // 60)}m {int(s % 60):02d}s"

        return [
            f"Chapter in → PDFs out: **{mmss(self.exported_s)}** (target under 5 min)",
            f"Chapter read in {mmss(self.chapter_ready_s)} · questions written in {mmss(self.generation_seconds)}",
            f"Asked for {self.requested}, model kept {self.kept} after checks",
            f"Teacher review: {self.final_unchanged} kept as-is · {self.edited} edited · "
            f"{self.regenerated} regenerated · {self.deleted} deleted",
            f"Final paper: {self.final_questions} questions · {self.mode} · {', '.join(self.qtypes)} · {self.difficulty}",
        ]

    def save(self, folder: Path) -> Path:
        path = folder / "session.json"
        data = self.model_dump(exclude={"t0"})
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
