"""Export tests. PDF rendering tests are skipped if WeasyPrint can't load."""

from datetime import date

import pytest

from ctg import models as m
from ctg.export.pdf import default_instructions, fmt_num, key_html, paper_html, save, slugify
from tests.factories import make_cfg, make_q

CONJUNCTS = "क्ष त्र ज्ञ श्र द्ध — क्षत्रिय, श्रद्धा, द्वितीय, हृदय, प्रत्यक्षीकरण"


def _meta(**kw) -> m.PaperMeta:
    en, hi = default_instructions(1)
    base = dict(institute="Sharma Coaching Centre", institute_hi="शर्मा कोचिंग सेंटर",
                title="Polity — Fundamental Rights", date=date(2026, 10, 18), time_min=30,
                instructions_en=en, instructions_hi=hi)
    return m.PaperMeta(**{**base, **kw})


def _test(mode="bilingual", **qkw) -> m.Test:
    qs = [make_q(**qkw), make_q(en=m.LocalizedQ(stem=f"Fill: Article 17 abolishes ____ ({CONJUNCTS[:3]})",
                                               answer_text="untouchability", explanation="x"),
                                hi=m.LocalizedQ(stem=f"रिक्त स्थान भरें: {CONJUNCTS} ____",
                                                answer_text="अस्पृश्यता", explanation="x"),
                                qtype="fill_blank", answer_index=None)]
    return m.Test(config=make_cfg(mode=mode, qtypes=["mcq", "fill_blank"]), questions=qs)


def _chunks():
    from tests.factories import CHUNK_TEXT
    return {"c01": m.Chunk(id="c01", index=0, text=CHUNK_TEXT, heading="Right to Equality", script="en")}


def test_paper_hides_answers_and_sources():
    html = paper_html(_test(), _meta())
    assert "Article 17 abolishes untouchability and forbids" not in html   # source quote
    assert "Stated in the extract." not in html                            # explanation
    assert "(b/ख)" in html and "Article 17 / अनुच्छेद 17" in html
    assert 'class="blank"' in html
    assert "Name / नाम" in html and "Max. Marks / पूर्णांक: 2" in html


def test_key_shows_answer_explanation_and_source():
    html = key_html(_test(), _meta(), _chunks())
    assert "ANSWER KEY / उत्तर कुंजी" in html
    assert "(b/ख)" in html and "अनुच्छेद 17" in html
    assert "Article 17 abolishes untouchability and forbids its practice in any form." in html
    assert "Right to Equality" in html
    assert "Name / नाम" not in html


def test_english_only_paper_has_no_hindi_labels():
    html = paper_html(_test(mode="en"), _meta())
    assert "(b)" in html and "/ख" not in html and "पूर्णांक" not in html
    assert "अनुच्छेद" not in html


def test_hindi_only_paper_uses_hindi_labels():
    html = paper_html(_test(mode="hi"), _meta())
    assert "(ख)" in html and "पूर्णांक" in html
    assert "Which Article abolishes untouchability?" not in html


def test_set_label_and_html_escaping():
    t = _test()
    t.set_label = "B"
    t.questions[0].en.stem = "Is <b>this</b> escaped?"
    html = paper_html(t, _meta())
    assert "Set B" in html
    assert "&lt;b&gt;this&lt;/b&gt;" in html


def test_helpers(tmp_path):
    assert fmt_num(1.0) == "1" and fmt_num(0.5) == "0.5"
    assert slugify("Polity — Fundamental Rights!") == "polity-fundamental-rights"
    assert slugify("मौलिक अधिकार") == "मौलिक-अधिकार"
    folder = save(tmp_path, _meta(), {"a.pdf": b"%PDF-1"})
    assert folder.name == "2026-10-18_polity-fundamental-rights"
    assert (folder / "a.pdf").read_bytes() == b"%PDF-1"
    en, hi = default_instructions(2, negative=0.5)
    assert "2 marks" in en and "0.5" in hi


def test_pdf_embeds_devanagari_font():
    pytest.importorskip("weasyprint")
    import io

    from pypdf import PdfReader

    from ctg.export.pdf import render_key, render_paper

    for pdf in (render_paper(_test(), _meta()), render_key(_test(), _meta(), _chunks())):
        assert pdf.startswith(b"%PDF")
        fonts = set()
        for page in PdfReader(io.BytesIO(pdf)).pages:
            for f in (page.get("/Resources") or {}).get("/Font", {}).values():
                fonts.add(str(f.get_object().get("/BaseFont")))
        assert any("Devanagari" in f for f in fonts), fonts
