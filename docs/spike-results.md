# M0 Spike Results

Fill this in after running the spikes (see [plan.md](../plan.md) M0).

**Machine:** ______ (RAM / CPU / GPU) · **Model:** gemma3:4b · **Date:** ______

> This laptop has 6.6 GB RAM and was using swap during setup. Close Chrome and VS Code before running Spike A, or the timings will be far slower than on a teacher's laptop.

## Spike A — generation quality

```bash
.venv/bin/python scripts/spike_gen.py --runs 2
```

```bash
.venv/bin/python scripts/spike_gen.py --file samples/sample_chapter_hi.txt --mode hi
```

| Mode | Run | Wall (s) | tok/s | Valid JSON | Returned | Passed checks | Hindi quality (1–5) | Notes |
|---|---|---|---|---|---|---|---|---|
| en | 1 | | | | /5 | | — | |
| en | 2 | | | | /5 | | — | |
| hi | 1 | | | | /5 | | | |
| hi | 2 | | | | /5 | | | |
| bilingual | 1 | | | | /5 | | | |
| bilingual | 2 | | | | /5 | | | |
| hi (Hindi chunk) | 1 | | | | /5 | | | |

**Exit:** at least 4/5 pass per run, and the Hindi reads naturally → ☐ met / ☐ not met

**Most common failure codes:** ______

**Prompt changes made:** ______ (edit `ctg/prompts.py`, then re-run)

If not met, try in this order: `--n 3` → `--temperature 0.2` → move the few-shot example right above the extract → a bigger model if RAM allows.

## Spike B — Devanagari PDF

```bash
.venv/bin/python scripts/spike_pdf.py
```

- [ ] NotoSansDevanagari embedded: YES
- [ ] Conjuncts correct (क्ष त्र ज्ञ श्र द्ध …), no tofu boxes, matras attached
- [ ] Bilingual option grid readable

**Decision:** ☐ WeasyPrint · ☐ Chromium fallback

## M0.5 — speed baseline

- Bilingual 5-question call: ____ s → estimated 10-question test (×2–3 + retries): ____ s
- Under 4 min? ☐ yes → default 10–15 Q · ☐ no → default 10 Q, consider `CTG_TEXT_MODEL=gemma3:1b`, cap `num_predict`
