from __future__ import annotations

from pathlib import Path

import pytest

from ctg import models as m
from ctg.config import Settings
from tests.factories import CHUNK_TEXT

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(logs_dir=tmp_path / "logs", outputs_dir=tmp_path / "out")


@pytest.fixture
def sample_text() -> str:
    return (SAMPLES / "sample_chapter.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_text_hi() -> str:
    return (SAMPLES / "sample_chapter_hi.txt").read_text(encoding="utf-8")


@pytest.fixture
def chunk() -> m.Chunk:
    return m.Chunk(id="c01", index=0, text=CHUNK_TEXT, script="en", quota=3)
