from ctg.textutil import detect_script, is_heading, norm, quote_score, reflow


def test_norm_strips_zero_width_and_maps_danda():
    assert norm("भारत‍ का संविधान।") == norm("भारत का संविधान.")
    assert norm("  Hello,   World! ") == "hello world"


def test_norm_keeps_devanagari_marks():
    assert norm("क्षत्रिय") == "क्षत्रिय"
    assert norm("हृदय") == "हृदय"


def test_detect_script():
    assert detect_script("The Constitution came into force in 1950.") == "en"
    assert detect_script("भारत का संविधान 1950 में लागू हुआ।") == "hi"
    assert detect_script("Article 17 यानी अनुच्छेद 17 untouchability") == "mixed"


def test_quote_score_exact_despite_punctuation_and_spacing():
    chunk = "Article 17 abolishes untouchability and forbids its practice in any form."
    assert quote_score("Article 17 abolishes untouchability, and forbids its  practice", chunk) == 100


def test_quote_score_low_for_made_up_quote():
    chunk = "Article 17 abolishes untouchability and forbids its practice in any form."
    assert quote_score("The Prime Minister appoints the Chief Election Commissioner.", chunk) < 90


def test_quote_score_hindi():
    chunk = "डॉ. भीमराव अंबेडकर ने अनुच्छेद 32 को संविधान का हृदय और आत्मा कहा था।"
    assert quote_score("अनुच्छेद 32 को संविधान का हृदय और आत्मा कहा था", chunk) == 100


def test_is_heading():
    assert is_heading("Right to Equality")
    assert is_heading("1.2 Fundamental Rights")
    assert is_heading("समानता का अधिकार")
    assert not is_heading("This is a sentence.")
    assert not is_heading("यह एक वाक्य है।")
    assert not is_heading("x" * 90)


def test_reflow_joins_wrapped_lines_and_keeps_headings():
    text = ("This is a long line of wrapped paragraph text that continues\n"
            "on the next line and ends here.\n"
            "Short heading\n"
            "Another paragraph line that is long enough to be typical text\n"
            "goes on.")
    paras = reflow(text).split("\n\n")
    assert paras == [
        "This is a long line of wrapped paragraph text that continues on the next line and ends here.",
        "Short heading",
        "Another paragraph line that is long enough to be typical text goes on.",
    ]


def test_reflow_rejoins_hyphenated_words():
    out = reflow("The inter-\nnational order was discussed at length in this long paragraph.")
    assert "international" in out
