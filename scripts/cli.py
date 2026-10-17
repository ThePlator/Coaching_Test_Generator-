"""Run the full pipeline from the command line (M1 exit check, no UI).

Usage (Ollama must be running):
    .venv/bin/python scripts/cli.py samples/sample_chapter.txt -n 10 --mode bilingual
    .venv/bin/python scripts/cli.py chapter.pdf -n 15 --types mcq true_false --difficulty easy
    .venv/bin/python scripts/cli.py page1.jpg page2.jpg -n 10 --mode hi

Prints progress to stderr, then the questions and report as JSON to stdout
(or to --out FILE).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctg.config import Settings, setup_logging  # noqa: E402
from ctg.ingest import SourceInput  # noqa: E402
from ctg.llm import LLMError, OllamaClient  # noqa: E402
from ctg.models import TestConfig  # noqa: E402
from ctg.pipeline import Progress, run  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def source_from_paths(paths: list[Path]) -> SourceInput:
    title = paths[0].stem.replace("_", " ").title()
    suffix = paths[0].suffix.lower()
    if suffix == ".pdf":
        return SourceInput(kind="pdf", title=title, data=paths[0].read_bytes())
    if suffix in IMAGE_EXT:
        return SourceInput(kind="images", title=title, images=[p.read_bytes() for p in paths])
    return SourceInput(kind="text", title=title, text=paths[0].read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", type=Path, help="one PDF / text file, or several photos")
    p.add_argument("-n", "--num", type=int, default=10)
    p.add_argument("--mode", choices=["en", "hi", "bilingual"], default="bilingual")
    p.add_argument("--types", nargs="+", default=["mcq"],
                   choices=["mcq", "true_false", "fill_blank", "short_answer"])
    p.add_argument("--difficulty", choices=["easy", "medium", "hard"], default="medium")
    p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    args = p.parse_args()

    settings = Settings()
    setup_logging(settings)
    llm = OllamaClient(settings)
    health = llm.health()
    if not health.ok:
        print(health.message, file=sys.stderr)
        return 2

    cfg = TestConfig(num_questions=args.num, qtypes=args.types, difficulty=args.difficulty, mode=args.mode)

    def show(pr: Progress) -> None:
        print(f"[{pr.stage:>8}] {pr.current}/{pr.total} kept={pr.kept} — {pr.message}", file=sys.stderr)

    try:
        result = run(source_from_paths(args.files), cfg, llm, settings, on_progress=show)
    except LLMError as e:
        print(f"Model error: {e}", file=sys.stderr)
        return 1

    payload = {
        "report": {**result.report.model_dump(), "dropped": result.report.dropped,
                   "summary": result.report.summary()},
        "chunks": [{"id": c.id, "heading": c.heading, "chars": len(c.text), "script": c.script}
                   for c in result.chunks.values()],
        "questions": [q.model_dump() for q in result.test.questions],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Saved {args.out}", file=sys.stderr)
    else:
        print(text)
    print(result.report.summary() + f" in {result.report.seconds}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
