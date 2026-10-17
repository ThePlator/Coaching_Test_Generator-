"""Final pre-publish check (plan M5). Read-only: it never changes or pushes anything.

    .venv/bin/python scripts/release_check.py           # repo + docs checks
    .venv/bin/python scripts/release_check.py --tests   # also run pytest

Prints PASS / WARN / FAIL per item; exit code 1 if anything FAILs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["LICENSE", "README.md", "requirements.txt", "app.py", "assets/fonts/OFL.txt",
            "samples/sample_chapter.txt", "docs/HLD.md", "docs/LLD.md"]
FORBIDDEN = re.compile(r"^(outputs|data|logs)/|institute\.toml$|(^|/)\.env$|spike_out/|__pycache__/")
SECRETS = re.compile(r"sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|api[_-]?key\s*=\s*['\"]\w+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
PHONE = re.compile(r"(?<!\d)(\+91[ -]?)?[6-9]\d{9}(?!\d)")
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9 /,.'’—–:-]{2,}[^\]]*\]")
BLANK_LINE = re.compile(r"_{6,}")
MAX_FILE_MB = 5

results: list[str] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append(status)
    icon = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[status]
    print(f"  {icon} {status:<4} {name}" + (f" — {detail}" if detail else ""))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def check_files(tracked: list[str]) -> None:
    missing = [f for f in REQUIRED if f not in tracked]
    record("FAIL" if missing else "PASS", "Required files", f"missing {missing}" if missing else "")
    bad = [f for f in tracked if FORBIDDEN.search(f)]
    record("FAIL" if bad else "PASS", "No private/generated files tracked", ", ".join(bad[:5]))
    big = [f for f in tracked if (ROOT / f).is_file() and (ROOT / f).stat().st_size > MAX_FILE_MB * 2**20]
    record("WARN" if big else "PASS", f"No files over {MAX_FILE_MB} MB", ", ".join(big))


def check_content(tracked: list[str]) -> None:
    secrets, personal = [], []
    for f in tracked:
        p = ROOT / f
        if not p.is_file() or p.suffix in {".ttf", ".png", ".jpg", ".pdf"} or f.endswith("OFL.txt"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if SECRETS.search(text):
            secrets.append(f)
        hits = [m for m in EMAIL.findall(text) if "noreply" not in m and not m.endswith("example.com")]
        if hits or PHONE.search(text):
            personal.append(f)
    record("FAIL" if secrets else "PASS", "No API keys / tokens", ", ".join(secrets))
    record("WARN" if personal else "PASS", "No emails / phone numbers", ", ".join(personal) + (
        " — check these are OK to publish" if personal else ""))


def check_docs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "TODO before publishing" in readme:
        record("WARN", "README", "screenshots / demo link TODO still there")
    else:
        imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
        missing = [i for i in imgs if not i.startswith("http") and not (ROOT / i).exists()]
        record("FAIL" if missing else "PASS", "README", f"images not found: {missing}" if missing else "")

    post = ROOT / "docs" / "dev-post.md"
    if post.exists():
        left = sorted(set(PLACEHOLDER.findall(post.read_text(encoding="utf-8"))))
        record("WARN" if left else "PASS", "DEV post placeholders",
               f"{len(left)} left: " + "; ".join(x[:40] for x in left[:6]) if left else "all filled")

    fu = ROOT / "docs" / "first-user.md"
    if fu.exists():
        blanks = len(BLANK_LINE.findall(fu.read_text(encoding="utf-8")))
        record("WARN" if blanks > 5 else "PASS", "First-user results",
               f"{blanks} blanks still empty" if blanks > 5 else "filled in")


def check_git() -> None:
    dirty = git("status", "--porcelain").strip()
    record("WARN" if dirty else "PASS", "Working tree clean", f"{len(dirty.splitlines())} uncommitted change(s)" if dirty else "")
    git("fetch", "-q", "origin")
    ahead = git("rev-list", "--count", "origin/main..HEAD").strip() or "?"
    record("WARN" if ahead not in ("0",) else "PASS", "Pushed to origin/main",
           f"{ahead} commit(s) not pushed" if ahead != "0" else "")


def check_tests() -> None:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    record("PASS" if r.returncode == 0 else "FAIL", "Tests", last)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tests", action="store_true", help="also run pytest")
    args = ap.parse_args()

    print("Coaching Test Generator — release check\n")
    tracked = git("ls-files").split()
    check_files(tracked)
    check_content(tracked)
    check_docs()
    check_git()
    if args.tests:
        check_tests()

    fails, warns = results.count("FAIL"), results.count("WARN")
    print(f"\n{'READY TO PUBLISH' if not fails and not warns else 'NOT READY' if fails else 'OK WITH WARNINGS'}"
          f" — {fails} fail, {warns} warning(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
