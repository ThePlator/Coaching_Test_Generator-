# First User Session

Plan M3 · Sun 18 Oct 2026, evening · about 15 minutes with the teacher

> **Privacy:** no student names or faces in notes or photos. Use the teacher's name or institute in the DEV post **only if they agree**. Don't commit their chapter to the repo.

---

## Before (about 20 min ahead)

- [ ] Charge the laptop. Close Chrome, VS Code and anything else heavy. This laptop has 6.6 GB RAM.
- [ ] Start Ollama:
  ```bash
  ollama serve
  ```
- [ ] Run the preflight check. It loads Gemma and times a small test:
  ```bash
  .venv/bin/python scripts/preflight.py --warm
  ```
  Fix every FAIL. Open the preflight PDF and check the Hindi by eye.
- [ ] Start the app:
  ```bash
  .venv/bin/streamlit run app.py
  ```
- [ ] In the sidebar, set the **teacher's institute name** in English and Hindi, their usual time, and marks per question.
- [ ] Have the teacher's chapter ready (PDF, photos or text). If there are photos, take them flat, in good light, one page each.
- [ ] Keep a printer or PDF viewer ready, plus a phone for the photo of the printed paper.
- [ ] Optional: turn Wi-Fi off to show that it works offline.

## Session script (15 min)

1. **Explain (1 min).** "You give it your chapter. It writes a practice test in Hindi and English with an answer key. Everything stays on this laptop."
2. **Upload (teacher drives).** Load **their own chapter**. The app starts its clock automatically at this point.
3. **Generate.** Choose 10 questions, MCQ, medium, **bilingual**.
4. **Review.** For each question, the teacher says **keep**, **edit** or **wrong**. Edits, deletes and regenerates are counted automatically. Also tally the spoken verdicts below, because "wrong" is a judgement the app can't see.
5. **Export.** Tick reviewed, then Create PDFs. Open or print the student paper and the answer key.
6. **Questions (3–4 min).** Write down the teacher's exact words.
   - "How long would this normally take you?"
   - "Would you pay ₹199 a month? What about ₹999 a month for the whole institute?"
   - "What should it do next?"
   - "Can I mention your name or institute in my post?"
7. **Photo.** With permission, photograph the printed paper. No student names.
8. **Save numbers.** Open the **"Session numbers"** box under the download buttons and copy it here. It's also saved as `outputs/<date>_<title>/session.json`.

---

## Results

**Who:** ______________ (role: coaching owner / tutor / school teacher) · **Subject / exam:** ______________
**Chapter:** ______________ · **Input:** ☐ PDF ☐ photos ☐ pasted text · **Laptop:** ______________
**Permission to name them in the post:** ☐ yes ☐ first name only ☐ no

### From the app (copy from "Session numbers")

| Measure | Value |
|---|---|
| Chapter in → PDFs out | |
| Chapter read in | |
| Questions written in | |
| Asked for / kept after checks | / |
| Kept as-is / edited / regenerated / deleted | / / / |
| Final paper | |

### Teacher's verdict per question

| Q | Keep | Edit | Wrong | Why (if edit/wrong) |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |
| 6 | | | | |
| 7 | | | | |
| 8 | | | | |
| 9 | | | | |
| 10 | | | | |
| **Total** | | | | |

**Hindi quality (teacher's opinion, 1–5):** ___ · comment: ______________

### Their answers (exact words)

- **Normally takes:** ______________
- **₹199/month?** ______________
- **₹999/month for the institute?** ______________
- **What next?** ______________
- **Anything else:** ______________

### Biggest issue to fix tonight (M4)

> ______________

---

## For the DEV post ("My First User")

> I sat with **[name/role]**, who teaches **[subject]** to **[exam]** students in Patna. Starting from their own chapter, they had a printed 10-question bilingual test with an answer key in **[time]**. Normally that takes them **[their answer]**. Of the 10 questions, they kept **[k]**, edited **[e]** and marked **[w]** wrong, mainly because **[reason]**. On pricing they said: "**[quote]**". Their top request: **[next feature]**.
