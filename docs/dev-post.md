<!--
DEV post draft — Week 2 "Side Hustle".
Paste into the official Week 2 submission template on DEV and move these sections into its headings.
Fill every [BRACKET] from docs/first-user.md. Delete this comment before publishing.
Tags: #devchallenge #hf26challenge (plus e.g. #ai #python #opensource if allowed)
Check the challenge rules for any required AI-assistance disclosure, and keep the note at the end if it applies.
-->

# Prashn Patra: a ₹199/month practice-test maker for Patna's coaching centres, running Gemma on their own laptop

## What I built

Teachers at small coaching centres in Patna spend hours every week writing practice tests for board, BPSC, SSC and Railway students, often late at night after classes. Hindi-medium students need the same test in Hindi, which doubles the work.

**Coaching Test Generator** (working Hindi name: *Prashn Patra*, प्रश्न पत्र) turns a chapter into a ready-to-print test:

- **In:** a chapter PDF, photos of book pages, or the teacher's own notes
- **Out:** a student paper and an answer key, in **Hindi, English or bilingual**, with MCQ, true/false, fill-in-the-blank or short-answer questions

It runs **Gemma 3 (4B) locally through Ollama**. There's no cloud bill, no internet needed after setup, and the institute's notes never leave the laptop.

## Demo

[VIDEO LINK — 1–2 min, chapter in → printed test out]

[SCREENSHOT: review screen with source line]
[PHOTO: printed bilingual paper from the first-user session]

**Code:** https://github.com/ThePlator/Coaching_Test_Generator- (MIT)

## How it works

1. **Read the chapter.** `pypdf` handles text PDFs. Photos and scanned pages go to Gemma's vision model for OCR.
2. **Split it into topic-sized chunks**, so each question is grounded in one small piece of text.
3. **Generate.** For each chunk, Gemma writes questions as JSON (enforced with Ollama structured outputs). Each question carries a **`source_quote`**: the exact sentence that proves the answer.
4. **Check in code, not with another LLM.** The source quote must actually appear in the chunk (a fuzzy match that handles Devanagari). Each question needs exactly 4 distinct options with the answer among them, no "all of the above" / उपरोक्त सभी, real Devanagari in the Hindi version, matching Hindi and English versions, and no near-duplicates. A question that fails is **regenerated once, then dropped**, and the teacher sees how many were kept.
5. **Teacher review is mandatory.** They can edit, delete or regenerate any question, and export is locked until they confirm they've reviewed it.
6. **Print.** HTML templates go to PDF through WeasyPrint with an embedded **Noto Sans Devanagari** font, so Hindi conjuncts (क्ष, त्र, श्र…) print correctly. The answer key shows the source line for every answer.

Stack: Python, Streamlit, Ollama + `gemma3:4b`, Pydantic, rapidfuzz, Jinja2 + WeasyPrint.

**Two things I learned:**

- A wrong answer key hurts a teacher's credibility in front of students, so "every answer must quote the chapter" mattered more than any prompt trick.
- [ONE REAL LESSON FROM THE SPIKES, e.g. how often Gemma's quotes were word-for-word, or what fixed the Hindi tone]

## My first user

[FROM docs/first-user.md, for example:]

> I sat with **[name/role]**, who teaches **[subject]** to **[exam]** students in Patna. Starting from their own chapter, they had a printed **10-question bilingual test** with an answer key in **[time]**. Normally that takes them **[their answer]**.
>
> Of the 10 questions, they **kept [k]**, **edited [e]** and marked **[w] wrong**, mostly because **[reason]**. Their verdict on the Hindi: "[quote]".
>
> Their top request: **[next feature]**.

[PHOTO of the printed paper, no student names]

## Who would pay

| Plan | Who | Price |
|---|---|---|
| Free | Try it | 3 tests / month |
| Tutor | Home tutors | ₹199 / month |
| Institute | Coaching centres | ₹999 / month, set up on their laptop |
| One-time setup | Institutes without tech help | ₹1,500 install + training |

I asked my first user directly. **"Would you pay ₹199 a month?"** → "[their answer]". **"₹999 for the institute?"** → "[their answer]".

[ONE HONEST SENTENCE ON WHAT THIS TELLS YOU, e.g. "Tutors balk at monthly fees but would pay for setup", or "the institute price landed better than the tutor price"]

## Why open innovation matters here

- **Near-zero running cost.** The model runs on hardware the institute already owns, so a ₹199 price can still make money. A per-call cloud API at this volume would eat the margin.
- **Private notes.** A teacher's own notes are their competitive edge, and here they never leave the laptop.
- **Works with bad internet.** Power cuts and patchy mobile data are normal. Once set up, this needs neither.
- **Can be tuned for exam styles.** Open weights mean the model can later be fine-tuned on BPSC/SSC-style questions written by teachers themselves.
- **Open source** means another developer in another city can adapt it for their local exams and languages.

## What's next

- Exam style presets (Bihar Board, BPSC, SSC, Railway)
- Set A / Set B shuffling to stop copying
- A question bank per chapter
- WhatsApp-friendly text quizzes
- [THE TEACHER'S REQUEST]

## Prize categories

- **Best Use of Gemma.** Gemma 3 4B does all the question writing and the photo/scan OCR, fully offline.
- [IF LIVE: .tech domain / Render landing page]

---

*[If required by the challenge rules: note how AI tools were used, e.g. "I used an AI coding assistant to help write the code and docs; the product decisions, testing and first-user session were mine."]*
