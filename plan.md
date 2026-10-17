# MVP Build Plan — Coaching Test Generator

| | |
|---|---|
| **Scope** | MVP = PRD features **F1–F6** only (see [LLD](docs/LLD.md)) |
| **Start** | Sat 17 Oct 2026, evening (IST) |
| **Hard deadline** | Mon 19 Oct 2026, 12:29 PM IST — publish target 10:00 AM |
| **Rule** | Riskiest parts first: question quality, Hindi, Devanagari PDF. P1 work starts only if the MVP is done by Sun 3 PM. |

---

## MVP definition of done

A teacher can, on one laptop with no internet:

1. Upload a text PDF, photo(s) or pasted notes **(F1)**.
2. Pick 5–50 questions, types, difficulty **(F2)** and Hindi / English / bilingual **(F3)**.
3. Generate questions that each have options, answer, explanation and a **source quote that has passed the check** **(F4)**.
4. Edit, delete or regenerate any question, and tick "reviewed" **(F5)**.
5. Download a **student paper PDF** and an **answer key PDF** with Hindi rendering correctly **(F6)**.
6. Get a 10-question bilingual test from a real chapter in **under 5 minutes** on the target laptop.

**Out of MVP:** presets (F7), Set A/B (F8), question bank (F9), Word/WhatsApp (F10), Render landing page. These are deferred and the design keeps hooks for them.

---

## Milestones

| # | Milestone | When (IST) | Exit check |
|---|---|---|---|
| M0 | Setup and risk spikes | Sat 17, 8 PM – 12 AM | Gemma returns valid bilingual JSON; Hindi PDF renders correctly |
| M1 | Core pipeline (F1–F4) | Sun 18, 8 AM – 1 PM | `pytest` green; CLI run on the sample chapter gives N checked questions |
| M2 | UI and export (F5–F6) | Sun 18, 1 PM – 5 PM | End-to-end in Streamlit: upload → PDFs |
| M3 | First user session | Sun 18, 6 PM – 8 PM | Timed session notes recorded |
| M4 | Fix, demo, post | Sun 18, 8 PM – Mon 19, 10 AM | Top issue fixed, video recorded, DEV post drafted |
| M5 | Publish | Mon 19, by 12:29 PM | Repo public, post live |

---

## M0 — Setup and risk spikes (Sat night)

### 0.1 Outreach (do first, ~15 min)
- [ ] Message 2–3 teachers or tutors. Ask each for one chapter they teach and 15 minutes on Sunday evening.

### 0.2 Environment
- [ ] Install Ollama, run `ollama pull gemma3:4b`, and smoke-test with `ollama run gemma3:4b "hi"`.
- [ ] Create the repo `coaching-test-generator` (public, MIT `LICENSE`, `.gitignore` with `outputs/ data/ logs/ .venv/ config/institute.toml`).
- [ ] Python 3.11 venv and `requirements.txt` (LLD §19). Run `pip install`.
- [ ] Create the layout from LLD §1 with empty modules and `.streamlit/config.toml` (`gatherUsageStats=false`).
- [ ] Download the Noto Sans and Noto Sans Devanagari TTFs into `assets/fonts/`, along with the OFL licence file.

### 0.3 Spike A — generation quality (highest risk)
- [ ] Write the throwaway script `scripts/spike_gen.py`: one hard-coded chunk (~1,200 chars of polity or history) → `/api/chat` with a hand-written JSON schema (LLD §8) → print the result.
- [ ] Try it in **English**, **Hindi** and **bilingual** for 5 MCQs each.
- [ ] Record: seconds per call, valid JSON (y/n), quotes word for word (y/n), Hindi quality (1–5).
- [ ] Adjust the system prompt (LLD §7.1) and write the **one bilingual few-shot example** in exam-style Hindi.
- **Exit:** at least 4/5 questions per run pass a by-eye quote check, and the Hindi reads naturally.
- **If it fails:** cut to 3 questions per call, lower the temperature to 0.2, put the few-shot example right before the extract, and try `gemma3:12b` if the hardware allows.

### 0.4 Spike B — Devanagari PDF
- [ ] Write `scripts/spike_pdf.py`: a tiny Jinja2 HTML file with the Noto `@font-face` and the conjuncts क्ष त्र ज्ञ श्र द्ध plus matras → WeasyPrint → `spike.pdf`.
- [ ] Open the PDF and check by eye that the conjuncts are joined correctly and no tofu boxes appear.
- **If WeasyPrint won't install:** switch to the Playwright Chromium `page.pdf()` fallback (LLD §13) and decide now.

### 0.5 Benchmark baseline
- [ ] Note tokens/sec and seconds per 5-question bilingual call. Work out the expected time for 10 questions. If it's over 4 minutes, set the default to 10 questions and plan for `CTG_TEXT_MODEL`.

---

## M1 — Core pipeline (Sun morning)

Build in this order. Each step comes with its tests.

| # | File | Task | Tests | LLD |
|---|---|---|---|---|
| 1 | `ctg/config.py` | `Settings` (pydantic-settings, `CTG_` env), `InstituteProfile`, `load_institute()` | — | §2 |
| 2 | `ctg/models.py` | All models and invariant `model_validator`s | invalid MCQ/TF/mode combos raise errors | §3 |
| 3 | `ctg/textutil.py` | `norm()`, `detect_script()`, `contains_fuzzy()` | NFC, ZWJ, danda, en/hi/mixed | §5, §10.1 |
| 4 | `ctg/llm.py` | `LLMClient` protocol, `OllamaClient` (`chat_json`, `chat_text`, `health`), `FakeLLMClient`, error classes | fake returns queued fixtures | §4 |
| 5 | `ctg/ingest.py` | `from_text`, `from_pdf` (pypdf + scanned-page detection + header strip), `from_images` (resize → vision OCR) | sample PDF text extraction; header removal | §5 |
| 6 | `ctg/chunker.py` | `chunk()` (headings, max split at `.?!।`, tail merge), `allocate()` (largest remainder; N < chunks), `type_plan()` round-robin | quotas sum to N; splits | §6 |
| 7 | `ctg/schema.py` | `build_schema(mode, k)` — require `en`/`hi` per mode | schema snapshot per mode | §8 |
| 8 | `ctg/prompts.py` | system prompt, user template, difficulty hints, mode instructions, retry add-on, few-shot from M0 | prompt contains extract / avoid list | §7 |
| 9 | `ctg/generator.py` | `generate_for_chunk()` — batches of up to 5, `avoid` capped at 15, parse into `Question`; bad JSON → `[]` | with fake client | §9 |
| 10 | `ctg/validate.py` | `check_question()` with all hard codes + soft warnings; `dedupe()` | **one pass and one fail fixture per code** | §10 |
| 11 | `ctg/pipeline.py` | `run()` with over-generation, retry once per chunk, top-up (≤ 2 calls), trim, `GenerationReport`, `Progress` callbacks, per-chunk error isolation; `regenerate_one()` | happy / retry-pass / retry-drop / bad-JSON / exception | §11 |
| 12 | `scripts/cli.py` | `python scripts/cli.py samples/sample.pdf -n 10 --mode bilingual` prints questions + report as JSON | manual | — |

**M1 exit:**
- [ ] `pytest` is green.
- [ ] The CLI on the sample chapter returns at least 8 of 10 requested questions in bilingual mode, and every quote is visibly in the chapter.
- [ ] The run takes under 5 minutes on this laptop. If not, apply the M0.5 fallbacks.
- [ ] Commit and push.

---

## M2 — UI and export (Sun afternoon)

### 2.1 Export first (risk already reduced by Spike B)
| File | Task | LLD |
|---|---|---|
| `ctg/export/templates/base.css` | A4 `@page`, margins, page counter, Noto `@font-face`, `break-inside: avoid`, 2-column options grid | §13 |
| `ctg/export/templates/paper.html.j2` | Header (institute en/hi, title, date, time, max marks, Name/Roll line), instructions, questions per type and mode, `(a)–(d)` / `(क)–(घ)` labels | §13 |
| `ctg/export/templates/key.html.j2` | Table: Q#, answer, explanation, source line (italic) | §13 |
| `ctg/export/pdf.py` | `render_paper`, `render_key`, `save()` to `outputs/<date>_<slug>/`; HTML fallback on `ExportError` | §13 |
| `tests/test_export.py` | Hindi fixture renders; NotoSansDevanagari is embedded | §18 |

### 2.2 Streamlit app (`app.py`)
- [ ] **Sidebar:** institute profile form (saves to `config/institute.toml`) and model health light (green / red / amber with the fix command).
- [ ] **Model warm-up** on first load (`keep_alive=30m`), cached with `st.cache_resource`.
- [ ] **Step 1 — Chapter:** tabs for PDF / Photo(s) / Paste, then "Extract", then an info line ("4 pages, 6 chunks, 1 page OCR'd") and a preview expander. Enforce size limits.
- [ ] **Step 2 — Settings:** count slider (5–50, default 10), types multiselect (default MCQ), difficulty radio (default medium), language radio (default bilingual). Widgets are disabled while a run is going.
- [ ] **Generate:** `st.status` + `st.progress` driven by `Progress`. Report banner: "Kept X of Y — reasons".
- [ ] **Step 3 — Review:** one card per question showing stems, options with ✓, explanation, source line and ⚠ warnings. Buttons: **Edit** (inline form → `status="edited"` → re-check and show warnings without blocking), **Delete**, **Regenerate** (spinner, then toast on failure). Checkbox "I have reviewed all questions" sets `reviewed`.
- [ ] **Step 4 — Export** (disabled until `reviewed`): title, date, time, marks per question → **Create PDFs** → two `st.download_button`s plus a "saved to …" path.
- [ ] Map each error class to its friendly message (LLD §16). Set up the rotating log at `logs/ctg.log` with no chapter text.

**M2 exit:**
- [ ] End to end in the browser with the sample chapter: text PDF, photo and pasted text all work.
- [ ] Both PDFs print correctly in all 3 language modes, and the Hindi is visually correct.
- [ ] Export can't be clicked before review.
- [ ] Turn off Wi-Fi and repeat once to confirm it works offline.
- [ ] Commit, push, and tag `v0.1.0-mvp`.

---

## M3 — First user session (Sun evening, 15 min)

- [ ] Before: set the institute name to theirs, warm up the model, have a printer or PDF viewer ready.
- [ ] The teacher uploads their own chapter → 10-question bilingual test. **Time it** from upload to PDFs.
- [ ] The teacher marks each question **keep / edit / wrong**. Note counts and the reason for each "wrong".
- [ ] Ask: *"How long would this normally take you?"*, *"Would you pay ₹199/month? ₹999 for the institute?"*, *"What should it do next?"*
- [ ] With permission, take a photo of the printed paper (no student names).
- [ ] Write everything into `docs/first-user.md` right away.
- **Fallback if no teacher:** a student or a sibling's school chapter, and say so honestly in the post.

---

## M4 — Fix, demo, post (Sun night → Mon morning)

- [ ] Fix the **one** biggest issue from the session (likely: Hindi tone, a too-strict quote threshold, or speed).
- [ ] Polish the README: real clone URL, screenshots, sample outputs in `samples/output/`.
- [ ] Add `scripts/setup.sh` (and `setup.ps1` if time allows) for the one-time install.
- [ ] Record a 1–2 minute demo video: chapter in → review → printed test out.
- [ ] Draft the DEV post (Week 2 template, tags `#devchallenge #hf26challenge`) with sections for: problem, demo, how it works, **Who would pay** (tested price and the teacher's real answer), **Why open innovation matters**, **My First User** (numbers from M3), prize category **Best Use of Gemma**.

## M5 — Publish (Mon, by 10 AM; hard stop 12:29 PM)

- [ ] Final check: public repo, MIT licence, README, shareable sample chapter, no copyrighted textbook content, no personal data.
- [ ] Optional, only if everything else is done: .tech domain + static Render landing page.
- [ ] Proofread and publish the DEV post. Submit.

---

## Cut lines (if behind schedule)

Cut in this order and keep the definition of done intact:

1. Photo / scanned-PDF OCR → text PDF and paste only (keep the upload tab with a "coming soon" note).
2. Question types beyond MCQ → MCQ only, with T/F second.
3. Top-up pass in the pipeline → accept fewer questions and show the report.
4. Inline edit form → delete + regenerate only.
5. Windows setup script → document the manual steps.

**Never cut:** the source-quote check, the review-before-export gate, the answer key source line, or correct Hindi rendering in the PDF.

## Risk watch

| Risk | Check at | Trigger → action |
|---|---|---|
| Gemma output quality | M0 Spike A | Under 4/5 quotes valid → smaller batches, more few-shot examples, larger model |
| Speed | M0.5, M1 exit | Over 5 min for 10 Q → default 10, text model for text input, cap `num_predict` |
| Devanagari PDF | M0 Spike B | Broken shaping → Chromium fallback |
| No first user | Sun noon | No confirmations → line up the fallback person |
| Time overrun | Sun 3 PM | MVP not done → apply cut lines, skip all P1 |
