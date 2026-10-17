from collections import deque

from ctg.generator import generate_for_chunk, to_question
from ctg.llm import FakeLLMClient, LLMBadOutput
from tests.factories import make_cfg
from tests.fakes import make_item


def test_to_question_true_false_is_canonicalised(chunk):
    item = make_item("true_false", 1, chunk.text, chunk.text, ["en", "hi"])
    item["answer_index"] = 1
    item["en"]["options"] = ["Yes", "No"]
    q = to_question(item, chunk, make_cfg(qtypes=["true_false"]))
    assert q.en.options == ["True", "False"] and q.en.answer_text == "False"
    assert q.hi.options == ["सही", "गलत"] and q.hi.answer_text == "गलत"


def test_to_question_drops_unrequested_language(chunk):
    item = make_item("mcq", 1, chunk.text, chunk.text, ["en", "hi"])
    q = to_question(item, chunk, make_cfg(mode="en"))
    assert q.en is not None and q.hi is None


def test_to_question_rejects_non_dict(chunk):
    assert to_question("not a question", chunk, make_cfg()) is None


def test_to_question_sets_chunk_and_difficulty(chunk):
    item = make_item("mcq", 2, chunk.text, chunk.text, ["en", "hi"])
    q = to_question(item, chunk, make_cfg(difficulty="hard"))
    assert q.chunk_id == "c01" and q.difficulty == "hard" and q.answer_index == 2


def test_generate_counts_lost_questions(chunk):
    item = make_item("mcq", 1, chunk.text, chunk.text, ["en", "hi"])
    llm = FakeLLMClient(json_queue=deque([LLMBadOutput("broken"), {"questions": [item]}]))
    qs, lost = generate_for_chunk(llm, chunk, ["mcq"] * 6, make_cfg(), max_per_call=3)
    assert len(qs) == 1
    assert lost == 3 + 2
    assert len(llm.calls) == 2


def test_generate_sends_avoid_and_feedback(chunk):
    llm = FakeLLMClient(json_queue=deque([{"questions": []}]))
    generate_for_chunk(llm, chunk, ["mcq"], make_cfg(), avoid=["Old question?"],
                       feedback=["Q1: source not found in chapter"])
    user = llm.calls[0]["user"]
    assert "- Old question?" in user
    assert "Q1: source not found in chapter" in user
    assert chunk.text in user


def test_schema_matches_mode(chunk):
    llm = FakeLLMClient(json_queue=deque([{"questions": []}]))
    generate_for_chunk(llm, chunk, ["mcq"], make_cfg(mode="hi"))
    props = llm.calls[0]["schema"]["properties"]["questions"]["items"]["properties"]
    assert "hi" in props and "en" not in props
