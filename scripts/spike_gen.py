"""M0 Spike A — can Gemma write grounded bilingual questions?

Sends one chapter chunk to Ollama with the real prompts (ctg.prompts) and
JSON schema (ctg.schema), then runs quick automatic checks and prints the
questions for an eyeball check of the Hindi.

Usage (Ollama must be running and the model pulled):
    .venv/bin/python scripts/spike_gen.py                     # all 3 modes, 5 MCQs each
    .venv/bin/python scripts/spike_gen.py --mode bilingual --runs 3
    .venv/bin/python scripts/spike_gen.py --file samples/sample_chapter_hi.txt --mode hi

Results are saved to scripts/spike_out/ and summarised at the end.
Record the numbers in docs/spike-results.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctg import prompts  # noqa: E402
from ctg.schema import build_schema, languages  # noqa: E402
from ctg.textutil import detect_script, devanagari_ratio, norm, quote_score  # noqa: E402

OUT_DIR = ROOT / "scripts" / "spike_out"
QUOTE_THRESHOLD = 90


def take_chunk(text: str, max_chars: int) -> str:
    """First paragraphs of the file, up to about max_chars (paragraph-aligned)."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: list[str] = []
    size = 0
    for p in paras:
        if out and size + len(p) > max_chars:
            break
        out.append(p)
        size += len(p) + 2
    return "\n\n".join(out)


def call_ollama(args, system: str, user: str, schema: dict) -> tuple[dict, dict]:
    payload = {
        "model": args.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": args.temperature,
            "num_ctx": args.num_ctx,
            "num_predict": args.num_predict,
            "top_p": 0.9,
        },
    }
    r = httpx.post(f"{args.host}/api/chat", json=payload, timeout=args.timeout)
    r.raise_for_status()
    body = r.json()
    content = body.get("message", {}).get("content", "")
    stats = {
        "total_s": body.get("total_duration", 0) / 1e9,
        "load_s": body.get("load_duration", 0) / 1e9,
        "prompt_tokens": body.get("prompt_eval_count", 0),
        "prompt_s": body.get("prompt_eval_duration", 0) / 1e9,
        "gen_tokens": body.get("eval_count", 0),
        "gen_s": body.get("eval_duration", 0) / 1e9,
    }
    stats["gen_tok_per_s"] = round(stats["gen_tokens"] / stats["gen_s"], 2) if stats["gen_s"] else 0
    stats["raw"] = content
    try:
        return json.loads(content), stats
    except json.JSONDecodeError:
        return {}, stats


def check_question(q: dict, chunk: str, mode: str) -> dict:
    """Subset of LLD §10 hard checks — enough to judge the spike."""
    problems: list[str] = []
    score = quote_score(q.get("source_quote", ""), chunk)
    if score < QUOTE_THRESHOLD:
        problems.append(f"quote_not_found({score})")
    idx = q.get("answer_index")
    for lang in languages(mode):
        loc = q.get(lang) or {}
        opts = loc.get("options") or []
        if q.get("qtype") == "mcq":
            if len(opts) != 4:
                problems.append(f"{lang}:options_count={len(opts)}")
            if len({norm(o) for o in opts}) != len(opts):
                problems.append(f"{lang}:options_dup")
            if not isinstance(idx, int) or not 0 <= idx < len(opts):
                problems.append(f"{lang}:bad_answer_index")
            elif norm(opts[idx]) != norm(loc.get("answer_text", "")):
                problems.append(f"{lang}:answer_mismatch")
        if any(x in norm(o) for o in opts for x in ("all of the above", "none of the above", "उपरोक्त सभी", "इनमें से कोई नहीं")):
            problems.append(f"{lang}:aota")
        stem = loc.get("stem", "")
        if lang == "hi" and devanagari_ratio(stem) < 0.5:
            problems.append("hi:wrong_script")
        if lang == "en" and devanagari_ratio(stem) > 0.2:
            problems.append("en:wrong_script")
    if mode == "bilingual":
        en_n = len((q.get("en") or {}).get("options") or [])
        hi_n = len((q.get("hi") or {}).get("options") or [])
        if en_n != hi_n:
            problems.append("bilingual_mismatch")
    return {"quote_score": score, "problems": problems, "ok": not problems}


def print_question(i: int, q: dict, res: dict, mode: str) -> None:
    mark = "PASS" if res["ok"] else "FAIL " + ", ".join(res["problems"])
    print(f"\n  Q{i} [{q.get('qtype')}] {mark}")
    idx = q.get("answer_index")
    for lang in languages(mode):
        loc = q.get(lang) or {}
        print(f"    {lang}: {loc.get('stem', '')}")
        for j, o in enumerate(loc.get("options") or []):
            tick = "✓" if j == idx else " "
            print(f"        {tick} ({'abcd'[j] if j < 4 else j}) {o}")
        print(f"        → {loc.get('explanation', '')}")
    print(f"    quote ({res['quote_score']}): {q.get('source_quote', '')}")


def run_once(args, mode: str, chunk: str, run_no: int) -> dict:
    plan = ["mcq"] * args.n
    system = prompts.system_prompt(allow_aota=False)
    user = prompts.user_prompt(
        chunk_text=chunk,
        chunk_script=detect_script(chunk),
        plan=plan,
        difficulty=args.difficulty,
        mode=mode,
    )
    schema = build_schema(mode, args.n)

    print(f"\n=== mode={mode} run={run_no} model={args.model} n={args.n} ===")
    t0 = time.perf_counter()
    try:
        data, stats = call_ollama(args, system, user, schema)
    except httpx.HTTPError as e:
        print(f"  Ollama call failed: {e!r}")
        return {"mode": mode, "run": run_no, "error": repr(e)}
    wall = time.perf_counter() - t0

    questions = data.get("questions") if isinstance(data, dict) else None
    valid_json = isinstance(questions, list)
    results = [check_question(q, chunk, mode) for q in (questions or [])]
    passed = sum(r["ok"] for r in results)

    print(f"  wall {wall:.1f}s | gen {stats['gen_tokens']} tok @ {stats['gen_tok_per_s']} tok/s "
          f"| prompt {stats['prompt_tokens']} tok | load {stats['load_s']:.1f}s")
    print(f"  valid JSON: {valid_json} | questions: {len(questions or [])}/{args.n} | passed checks: {passed}")
    if not valid_json:
        print("  raw output (first 500 chars):", stats["raw"][:500])
    for i, (q, res) in enumerate(zip(questions or [], results), 1):
        print_question(i, q, res, mode)

    return {
        "mode": mode,
        "run": run_no,
        "wall_s": round(wall, 2),
        "stats": {k: v for k, v in stats.items() if k != "raw"},
        "valid_json": valid_json,
        "requested": args.n,
        "returned": len(questions or []),
        "passed": passed,
        "questions": questions,
        "checks": results,
        "raw": stats["raw"] if not valid_json else None,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", default=str(ROOT / "samples" / "sample_chapter.txt"))
    p.add_argument("--chars", type=int, default=1500, help="chunk size taken from the file")
    p.add_argument("--mode", choices=["en", "hi", "bilingual", "all"], default="all")
    p.add_argument("--n", type=int, default=5, help="questions per call")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--difficulty", choices=["easy", "medium", "hard"], default="medium")
    p.add_argument("--model", default="gemma3:4b")
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--temperature", type=float, default=0.4)
    p.add_argument("--num-ctx", type=int, default=4096)
    p.add_argument("--num-predict", type=int, default=2048)
    p.add_argument("--timeout", type=float, default=600)
    args = p.parse_args()

    chunk = take_chunk(Path(args.file).read_text(encoding="utf-8"), args.chars)
    print(f"Chunk: {len(chunk)} chars, script={detect_script(chunk)}")
    print("-" * 60 + "\n" + chunk + "\n" + "-" * 60)

    modes = ["en", "hi", "bilingual"] if args.mode == "all" else [args.mode]
    records = [run_once(args, m, chunk, r) for m in modes for r in range(1, args.runs + 1)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{args.mode}.json"
    out.write_text(json.dumps({"args": vars(args), "chunk": chunk, "records": records},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60 + "\nSUMMARY")
    print(f"{'mode':<10}{'run':>4}{'wall s':>9}{'tok/s':>8}{'json':>6}{'ret':>5}{'pass':>6}")
    for r in records:
        if "error" in r:
            print(f"{r['mode']:<10}{r['run']:>4}   ERROR {r['error'][:40]}")
            continue
        print(f"{r['mode']:<10}{r['run']:>4}{r['wall_s']:>9}{r['stats']['gen_tok_per_s']:>8}"
              f"{'y' if r['valid_json'] else 'n':>6}{r['returned']:>5}{r['passed']:>6}")
    print(f"\nExit criterion: ≥ {max(1, round(args.n * 0.8))}/{args.n} pass per run, and Hindi reads naturally (judge by eye).")
    print("Speed estimate for 10 bilingual Qs ≈ 2–3 × the bilingual wall time above (+ retries).")
    print(f"Saved: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
