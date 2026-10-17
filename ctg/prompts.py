"""Prompt builders for question generation (LLD §7)."""

from __future__ import annotations

import json

from ctg.schema import OutputMode

AOTA_FORBIDDEN = (
    "Never use 'All of the above', 'None of the above', 'Both A and B', "
    "'उपरोक्त सभी', 'उपर्युक्त सभी' or 'इनमें से कोई नहीं' as an option."
)
AOTA_ALLOWED = "'All of the above' / 'None of the above' may be used only when truly needed."

SYSTEM_PROMPT = """You are an expert question-paper setter for Indian competitive and board exams.
You write questions ONLY from the CHAPTER EXTRACT given by the user.

RULES
1. Use only facts stated in the extract. Never add outside facts, dates or names.
2. MCQ: exactly 4 options, exactly one correct. Wrong options must be plausible
   but clearly wrong according to the extract.
3. source_quote: copy, word for word, the one sentence from the extract that
   proves the answer. Do not translate or paraphrase it, even if the question
   is in another language.
4. {aota_rule}
5. Hindi must be natural standard exam Hindi in Devanagari (as in BPSC/SSC papers),
   not word-by-word translation.
6. Explanation: one line, refers to the extract.
7. answer_text must be exactly the text of the correct option.
8. Do not repeat or rephrase any question listed under AVOID.
Return JSON only, matching the schema."""

DIFFICULTY_HINTS = {
    "easy": "direct recall of one fact stated in the extract",
    "medium": "needs understanding of one or two sentences of the extract",
    "hard": "combines facts from different sentences of the extract",
}

MODE_INSTRUCTIONS = {
    "en": "Write every question in English only (field `en`).",
    "hi": "Write every question in Hindi only (field `hi`), in Devanagari.",
    "bilingual": (
        "Write every question in BOTH English (field `en`) and Hindi (field `hi`). "
        "Both versions must have the same options in the same order and share one answer_index."
    ),
}

TYPE_HINTS = {
    "mcq": "mcq = 4 options, answer_index 0-3",
    "true_false": "true_false = options [\"True\",\"False\"] / [\"सही\",\"गलत\"], answer_index 0 or 1",
    "fill_blank": "fill_blank = stem contains ____ , options [], answer_index null",
    "short_answer": "short_answer = 1-2 sentence model answer, options [], answer_index null",
}

# One hand-written bilingual MCQ, on a topic unrelated to typical test chapters,
# so it teaches format and Hindi tone without leaking content.
FEW_SHOT = {
    "questions": [
        {
            "qtype": "mcq",
            "answer_index": 2,
            "en": {
                "stem": "According to the passage, which gas do green plants release during photosynthesis?",
                "options": ["Carbon dioxide", "Nitrogen", "Oxygen", "Hydrogen"],
                "answer_text": "Oxygen",
                "explanation": "The passage states that plants release oxygen as a by-product of photosynthesis.",
            },
            "hi": {
                "stem": "गद्यांश के अनुसार, प्रकाश संश्लेषण के दौरान हरे पौधे कौन-सी गैस मुक्त करते हैं?",
                "options": ["कार्बन डाइऑक्साइड", "नाइट्रोजन", "ऑक्सीजन", "हाइड्रोजन"],
                "answer_text": "ऑक्सीजन",
                "explanation": "गद्यांश में बताया गया है कि प्रकाश संश्लेषण में पौधे उप-उत्पाद के रूप में ऑक्सीजन छोड़ते हैं।",
            },
            "source_quote": "Green plants release oxygen as a by-product of photosynthesis.",
        }
    ]
}


def system_prompt(allow_aota: bool = False) -> str:
    return SYSTEM_PROMPT.format(aota_rule=AOTA_ALLOWED if allow_aota else AOTA_FORBIDDEN)


def few_shot_for(mode: OutputMode) -> str:
    """Few-shot JSON trimmed to the languages of the requested mode."""
    langs = ["en", "hi"] if mode == "bilingual" else [mode]
    q = FEW_SHOT["questions"][0]
    trimmed = {k: v for k, v in q.items() if k not in ("en", "hi") or k in langs}
    return json.dumps({"questions": [trimmed]}, ensure_ascii=False, indent=1)


def type_plan_text(plan: list[str]) -> str:
    counts: dict[str, int] = {}
    for t in plan:
        counts[t] = counts.get(t, 0) + 1
    parts = ", ".join(f"{n} {t}" for t, n in counts.items())
    hints = "; ".join(TYPE_HINTS[t] for t in counts)
    return f"{parts}  ({hints})"


def user_prompt(
    chunk_text: str,
    chunk_script: str,
    plan: list[str],
    difficulty: str,
    mode: OutputMode,
    style_text: str = "Clear, neutral school-test language.",
    avoid: list[str] | None = None,
    feedback: list[str] | None = None,
) -> str:
    avoid_lines = "\n".join(f"- {s}" for s in (avoid or [])[-15:]) or "- (none)"
    parts = [
        f"EXAM STYLE: {style_text}",
        f"DIFFICULTY: {difficulty} — {DIFFICULTY_HINTS[difficulty]}",
        f"LANGUAGE: {MODE_INSTRUCTIONS[mode]}",
        f"QUESTION TYPES: {type_plan_text(plan)}",
        f"COUNT: {len(plan)}",
        "",
        "EXAMPLE (format and Hindi tone only — do not reuse its content):",
        few_shot_for(mode),
        "",
        "AVOID (already asked):",
        avoid_lines,
    ]
    if feedback:
        parts += [
            "",
            "Your previous questions failed these checks:",
            *[f"- {f}" for f in feedback],
            f"Write {len(plan)} NEW questions that pass all rules.",
        ]
    parts += [
        "",
        f"CHAPTER EXTRACT (language: {chunk_script}):",
        '"""',
        chunk_text.strip(),
        '"""',
    ]
    return "\n".join(parts)


OCR_SYSTEM = "You are a careful OCR engine for Indian school and exam textbooks."
OCR_USER = (
    "Transcribe all text on this book page exactly as printed. Keep Hindi in Devanagari. "
    "Keep headings on their own lines. Output plain text only, no commentary."
)
