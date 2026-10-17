"""Settings (env, prefix CTG_) and institute profile (LLD §2)."""

from __future__ import annotations

import json
import logging
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CTG_", env_file=".env", extra="ignore")

    ollama_host: str = "http://localhost:11434"
    model: str = "gemma3:4b"            # must be vision-capable for photos
    text_model: str | None = None       # optional faster text-only model
    num_ctx: int = 4096
    num_predict: int = 2048
    temperature: float = 0.4
    request_timeout_s: int = 180
    keep_alive: str = "30m"

    chunk_target_chars: int = 1500
    chunk_max_chars: int = 2200
    overgen_factor: float = 1.3
    max_questions_per_call: int = 5
    quote_match_threshold: int = 90
    dedupe_threshold: int = 90

    max_pdf_pages: int = 30
    max_pdf_mb: int = 20
    max_images: int = 10

    outputs_dir: Path = ROOT / "outputs"
    bank_path: Path = ROOT / "data" / "bank.db"
    logs_dir: Path = ROOT / "logs"
    institute_file: Path = ROOT / "config" / "institute.toml"


class InstituteProfile(BaseModel):
    name: str = "My Coaching Centre"
    name_hi: str | None = None
    default_time_min: int = 30
    default_marks_per_q: float = 1.0
    negative_marking: float = 0.0


def load_institute(path: Path) -> InstituteProfile:
    if not path.exists():
        return InstituteProfile()
    with path.open("rb") as f:
        return InstituteProfile(**tomllib.load(f))


def save_institute(profile: InstituteProfile, path: Path) -> None:
    """Write a flat TOML file. JSON string escaping is valid TOML basic-string escaping."""
    lines = []
    for key, value in profile.model_dump().items():
        if value is None:
            continue
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup_logging(settings: Settings) -> None:
    """Rotating file log. Only counts, timings and failure codes are logged — never chapter text."""
    logger = logging.getLogger("ctg")
    if logger.handlers:
        return
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(settings.logs_dir / "ctg.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
