"""Test data builders shared across test modules."""

from __future__ import annotations

from ctg import models as m

CHUNK_TEXT = (
    "Article 17 abolishes untouchability and forbids its practice in any form. "
    "Article 18 abolishes titles, except military and academic distinctions. "
    "Dr. B. R. Ambedkar called Article 32 the heart and soul of the Constitution."
)


def make_cfg(**kw) -> m.TestConfig:
    base = {"num_questions": 5, "qtypes": ["mcq"], "mode": "bilingual"}
    return m.TestConfig(**{**base, **kw})


def make_q(**kw) -> m.Question:
    """A valid bilingual MCQ grounded in CHUNK_TEXT; override any field."""
    base = dict(
        chunk_id="c01",
        qtype="mcq",
        difficulty="medium",
        answer_index=1,
        en=m.LocalizedQ(stem="Which Article abolishes untouchability?",
                        options=["Article 14", "Article 17", "Article 21", "Article 32"],
                        answer_text="Article 17", explanation="Stated in the extract."),
        hi=m.LocalizedQ(stem="कौन-सा अनुच्छेद अस्पृश्यता का अंत करता है?",
                        options=["अनुच्छेद 14", "अनुच्छेद 17", "अनुच्छेद 21", "अनुच्छेद 32"],
                        answer_text="अनुच्छेद 17", explanation="गद्यांश में बताया गया है।"),
        source_quote="Article 17 abolishes untouchability and forbids its practice in any form.",
    )
    return m.Question(**{**base, **kw})
