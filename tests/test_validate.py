from ctg import models as m
from ctg.validate import check_question, dedupe
from tests.factories import make_cfg, make_q

EN_OPTS = ["Article 14", "Article 17", "Article 21", "Article 32"]


def en(stem="Which Article abolishes untouchability?", options=None, answer="Article 17"):
    return m.LocalizedQ(stem=stem, options=EN_OPTS if options is None else options,
                        answer_text=answer, explanation="x")


def reasons(q, chunk, **cfg):
    return check_question(q, chunk, make_cfg(**cfg)).reasons


def test_valid_question_passes(chunk):
    res = check_question(make_q(), chunk, make_cfg())
    assert res.ok, res.reasons


def test_english_only_mode_ignores_missing_hindi(chunk):
    assert reasons(make_q(hi=None), chunk, mode="en") == []


def test_schema_missing_language(chunk):
    assert reasons(make_q(hi=None), chunk) == ["schema"]


def test_schema_unknown_type(chunk):
    assert reasons(make_q(qtype="essay"), chunk) == ["schema"]


def test_wrong_type(chunk):
    assert "wrong_type" in reasons(make_q(), chunk, qtypes=["true_false"])


def test_quote_not_found(chunk):
    q = make_q(source_quote="Article 99 gives every citizen a free bicycle on Sundays.")
    assert reasons(q, chunk) == ["quote_not_found"]


def test_quote_short(chunk):
    assert reasons(make_q(source_quote="Article 17."), chunk) == ["quote_short"]


def test_quote_with_small_differences_passes(chunk):
    q = make_q(source_quote="Article 17 abolishes untouchability, and forbids its practice in any form")
    assert reasons(q, chunk) == []


def test_options_count(chunk):
    q = make_q(en=en(options=EN_OPTS[:3]))
    assert "options_count" in reasons(q, chunk, mode="en")


def test_options_dup(chunk):
    q = make_q(en=en(options=["Article 17", "Article 17.", "Article 21", "Article 32"]), answer_index=0)
    assert "options_dup" in reasons(q, chunk, mode="en")


def test_answer_mismatch(chunk):
    assert "answer_mismatch" in reasons(make_q(answer_index=2), chunk)


def test_answer_index_out_of_range(chunk):
    assert "answer_mismatch" in reasons(make_q(answer_index=7), chunk)


def test_aota_blocked_unless_allowed(chunk):
    q = make_q(en=en(options=["Article 14", "Article 17", "Article 21", "All of the above"]))
    assert "aota" in reasons(q, chunk, mode="en")
    assert "aota" not in reasons(q, chunk, mode="en", allow_aota=True)


def test_hindi_aota_blocked(chunk):
    hi = m.LocalizedQ(stem="कौन-सा अनुच्छेद अस्पृश्यता का अंत करता है?",
                      options=["अनुच्छेद 14", "अनुच्छेद 17", "अनुच्छेद 21", "उपरोक्त सभी"],
                      answer_text="अनुच्छेद 17")
    assert "aota" in reasons(make_q(hi=hi), chunk)


def test_bilingual_mismatch(chunk):
    hi = m.LocalizedQ(stem="कौन-सा अनुच्छेद अस्पृश्यता का अंत करता है?",
                      options=["अनुच्छेद 14", "अनुच्छेद 17", "अनुच्छेद 21"], answer_text="अनुच्छेद 17")
    assert "bilingual_mismatch" in reasons(make_q(hi=hi), chunk)


def test_wrong_script_hindi_written_in_english(chunk):
    hi = m.LocalizedQ(stem="Which Article abolishes untouchability?",
                      options=["अनुच्छेद 14", "अनुच्छेद 17", "अनुच्छेद 21", "अनुच्छेद 32"],
                      answer_text="अनुच्छेद 17")
    assert "wrong_script" in reasons(make_q(hi=hi), chunk)


def test_empty_text(chunk):
    assert "empty_text" in reasons(make_q(en=en(stem="  ")), chunk, mode="en")


def test_fill_blank_needs_blank(chunk):
    q = make_q(qtype="fill_blank", answer_index=None,
               en=m.LocalizedQ(stem="Article 17 abolishes what?", answer_text="untouchability"))
    assert "blank_missing" in reasons(q, chunk, mode="en", qtypes=["fill_blank"])
    q.en.stem = "Article 17 abolishes ____."
    assert reasons(q, chunk, mode="en", qtypes=["fill_blank"]) == []


def test_true_false_valid(chunk):
    q = make_q(qtype="true_false", answer_index=0,
               en=m.LocalizedQ(stem="Article 17 abolishes untouchability.", options=["True", "False"],
                               answer_text="True"))
    assert reasons(q, chunk, mode="en", qtypes=["true_false"]) == []


def test_ocr_warning(chunk):
    c = chunk.model_copy(update={"from_ocr": True})
    assert "ocr_source" in check_question(make_q(), c, make_cfg()).warnings


def test_dedupe_drops_near_duplicates():
    a = make_q()
    b = make_q(en=en(stem="Which Article abolishes untouchability ?"))
    c = make_q(en=en(stem="Who called Article 32 the heart and soul of the Constitution?"))
    kept, dropped = dedupe([a, b, c])
    assert kept == [a, c] and dropped == [b]


def test_dedupe_against_existing():
    kept, dropped = dedupe([make_q()], existing=[make_q()])
    assert kept == [] and len(dropped) == 1
