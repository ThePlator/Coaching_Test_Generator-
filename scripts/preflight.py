"""Pre-session check (plan M3): run ~10 minutes before the teacher arrives.

    .venv/bin/python scripts/preflight.py            # quick checks + Hindi PDF render
    .venv/bin/python scripts/preflight.py --warm     # also load Gemma and time one small generation

Every line prints PASS / WARN / FAIL with what to do.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    icon = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[status]
    print(f"  {icon} {status:<4} {name}" + (f" — {detail}" if detail else ""))


def check_imports() -> None:
    missing = []
    for mod in ("streamlit", "pydantic", "pypdf", "pypdfium2", "PIL", "rapidfuzz", "jinja2", "httpx"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        record("FAIL", "Python packages", f"missing {', '.join(missing)} → pip install -r requirements.txt")
    else:
        record("PASS", "Python packages")


def check_fonts() -> None:
    fonts = ROOT / "assets" / "fonts"
    need = ["NotoSans-Regular.ttf", "NotoSans-Bold.ttf",
            "NotoSansDevanagari-Regular.ttf", "NotoSansDevanagari-Bold.ttf"]
    missing = [f for f in need if not (fonts / f).exists()]
    record("FAIL" if missing else "PASS", "Fonts", f"missing {missing}" if missing else "")


def check_memory() -> None:
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        avail_gb = int(info["MemAvailable"].split()[0]) / 1024 / 1024
    except (OSError, KeyError, ValueError):
        record("WARN", "Free memory", "could not read (not Linux?) — close other apps anyway")
        return
    if avail_gb < 3.5:
        record("WARN", "Free memory", f"{avail_gb:.1f} GB free — close Chrome/VS Code; gemma3:4b needs ~3.5 GB")
    else:
        record("PASS", "Free memory", f"{avail_gb:.1f} GB free")


def check_institute(settings) -> None:
    from ctg.config import load_institute

    p = load_institute(settings.institute_file)
    if p.name == "My Coaching Centre":
        record("WARN", "Institute profile", "still the default — set the teacher's institute name in the sidebar")
    else:
        record("PASS", "Institute profile", p.name + (f" / {p.name_hi}" if p.name_hi else ""))


def check_pdf(settings) -> None:
    from ctg import models as m
    from ctg.export.pdf import ExportError, default_instructions, render_paper, save

    q = m.Question(
        chunk_id="c01", qtype="mcq", difficulty="easy", answer_index=0,
        en=m.LocalizedQ(stem="Who called Article 32 the heart and soul of the Constitution?",
                        options=["Dr. B. R. Ambedkar", "Jawaharlal Nehru", "Sardar Patel", "Rajendra Prasad"],
                        answer_text="Dr. B. R. Ambedkar"),
        hi=m.LocalizedQ(stem="अनुच्छेद 32 को संविधान का हृदय और आत्मा किसने कहा? (क्ष त्र ज्ञ श्र द्ध)",
                        options=["डॉ. भीमराव अंबेडकर", "जवाहरलाल नेहरू", "सरदार पटेल", "डॉ. राजेन्द्र प्रसाद"],
                        answer_text="डॉ. भीमराव अंबेडकर"),
        source_quote="Dr. B. R. Ambedkar called Article 32 the heart and soul of the Constitution.",
    )
    test = m.Test(config=m.TestConfig(num_questions=5, mode="bilingual"), questions=[q])
    en, hi = default_instructions(1)
    meta = m.PaperMeta(institute="Preflight", institute_hi="पूर्व-जाँच", title="Preflight check",
                       date=date.today(), time_min=5, instructions_en=en, instructions_hi=hi)
    try:
        t = time.perf_counter()
        pdf = render_paper(test, meta)
        folder = save(settings.outputs_dir, meta, {"preflight_paper.pdf": pdf})
        record("PASS", "Hindi PDF export", f"{time.perf_counter() - t:.1f}s → open {folder / 'preflight_paper.pdf'} "
                                           "and check the Hindi by eye")
    except ExportError as e:
        record("FAIL", "Hindi PDF export", f"{e} — the app will fall back to HTML (print from browser)")


def check_ollama(settings, warm: bool) -> None:
    from ctg.llm import OllamaClient

    llm = OllamaClient(settings)
    h = llm.health()
    if not h.server_up:
        record("FAIL", "Ollama", "not running → `ollama serve`")
        return
    if not h.model_present:
        record("FAIL", "Model", h.message)
        return
    record("PASS" if h.vision else "WARN", f"Model {settings.model}",
           "can read photos" if h.vision else "cannot read photos — use PDF or pasted text")
    if not warm:
        record("WARN", "Model warm-up", "skipped — run with --warm so the first real test isn't slow")
        return

    from ctg.ingest import SourceInput
    from ctg.models import TestConfig
    from ctg.pipeline import run

    t = time.perf_counter()
    llm.warm_up()
    record("PASS", "Model loaded", f"{time.perf_counter() - t:.0f}s")
    text = (ROOT / "samples" / "sample_chapter.txt").read_text(encoding="utf-8")
    cfg = TestConfig(num_questions=5, mode="bilingual")
    t = time.perf_counter()
    try:
        result = run(SourceInput(kind="text", title="Preflight", text=text), cfg, llm, settings)
    except Exception as e:  # report, don't crash the checklist
        record("FAIL", "Test generation", f"{type(e).__name__}: {e}")
        return
    secs = time.perf_counter() - t
    est10 = secs * 2
    status = "PASS" if est10 < 300 and result.report.kept >= 4 else "WARN"
    record(status, "Test generation", f"{result.report.summary()} in {secs:.0f}s "
                                      f"→ ~{est10 / 60:.1f} min for a 10-question test"
                                      + ("" if est10 < 300 else " (over 5 min: default to fewer questions)"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warm", action="store_true", help="load Gemma and time a 5-question bilingual run")
    args = ap.parse_args()

    print("Coaching Test Generator — preflight\n")
    check_imports()
    from ctg.config import Settings, setup_logging

    settings = Settings()
    setup_logging(settings)
    check_fonts()
    check_memory()
    check_institute(settings)
    check_pdf(settings)
    check_ollama(settings, args.warm)

    fails = sum(s == "FAIL" for s, _, _ in results)
    warns = sum(s == "WARN" for s, _, _ in results)
    print(f"\n{'READY' if not fails else 'NOT READY'} — {fails} fail, {warns} warning(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
