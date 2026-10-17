"""Fake model behaviour for pipeline tests: builds well-formed questions grounded
in the CHAPTER EXTRACT that the real prompt sends."""

from __future__ import annotations

import re

from ctg.textutil import SENTENCE_SPLIT

_TYPES = re.compile(r"(\d+) (mcq|true_false|fill_blank|short_answer)")


def extract_from_prompt(user: str) -> str:
    body = user.split("CHAPTER EXTRACT", 1)[1]
    return body.split('"""')[1]


def planned_types(user: str) -> list[str]:
    line = next(ln for ln in user.splitlines() if ln.startswith("QUESTION TYPES:"))
    out: list[str] = []
    for n, t in _TYPES.findall(line.split("(")[0]):
        out += [t] * int(n)
    return out


def schema_langs(schema: dict) -> list[str]:
    props = schema["properties"]["questions"]["items"]["properties"]
    return [lang for lang in ("en", "hi") if lang in props]


class GroundedResponder:
    """Callable for FakeLLMClient.responder. `bad_calls` = call numbers (1-based)
    whose questions get a made-up source quote."""

    def __init__(self, bad_calls: set[int] | None = None):
        self.bad_calls = bad_calls or set()
        self.calls = 0
        self.used: set[str] = set()
        self.counter = 0

    def __call__(self, system, user, schema, images):
        self.calls += 1
        sentences = [s.strip() for s in SENTENCE_SPLIT.split(extract_from_prompt(user)) if len(s.strip()) > 30]
        langs = schema_langs(schema)
        questions = []
        for qtype in planned_types(user):
            fresh = [s for s in sentences if s not in self.used] or sentences
            sent = fresh[0]
            self.used.add(sent)
            self.counter += 1
            quote = sent if self.calls not in self.bad_calls else "This sentence was invented and is not in the chapter."
            questions.append(make_item(qtype, self.counter, sent, quote, langs))
        return {"questions": questions}


HI_WORDS = ["संविधान", "अधिकार", "समानता", "स्वतंत्रता", "धर्म", "शिक्षा", "न्यायालय", "नागरिक",
            "संपत्ति", "श्रम", "बालक", "उपाधि", "रिट", "संशोधन", "कानून", "जीवन"]


def make_item(qtype: str, n: int, sentence: str, quote: str, langs: list[str]) -> dict:
    words = " ".join(sentence.split()[:12])
    item: dict = {"qtype": qtype, "source_quote": quote}
    if qtype == "true_false":
        item["answer_index"] = 0
        texts = {"en": (f"True or false: {words}", ["True", "False"], "True"),
                 "hi": (f"सही या गलत: {HI_WORDS[n % len(HI_WORDS)]} कथन {n}", ["सही", "गलत"], "सही")}
    elif qtype in ("fill_blank", "short_answer"):
        item["answer_index"] = None
        blank = " ____" if qtype == "fill_blank" else ""
        texts = {"en": (f"Complete from the extract: {words}{blank}", [], "answer"),
                 "hi": (f"गद्यांश से पूरा करें: {HI_WORDS[n % len(HI_WORDS)]} {n}{blank}", [], "उत्तर")}
    else:
        idx = n % 4
        en_opts = [f"Choice {c}{n}" for c in "ABCD"]
        hi_opts = [f"विकल्प {c}{n}" for c in "कखगघ"]
        item["answer_index"] = idx
        texts = {"en": (f"Which fact is stated: {words}?", en_opts, en_opts[idx]),
                 "hi": (f"गद्यांश के अनुसार {HI_WORDS[n % len(HI_WORDS)]} के बारे में कथन {n} क्या है?",
                        hi_opts, hi_opts[idx])}
    for lang in langs:
        stem, opts, ans = texts[lang]
        item[lang] = {"stem": stem, "options": opts, "answer_text": ans, "explanation": "From the extract."}
    return item
