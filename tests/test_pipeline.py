from collections import deque

import pytest

from ctg.ingest import SourceInput
from ctg.llm import FakeLLMClient, LLMBadOutput, LLMUnavailable
from ctg.pipeline import regenerate_one, run
from ctg.textutil import quote_score
from tests.factories import make_cfg
from tests.fakes import GroundedResponder


def _src(text: str) -> SourceInput:
    return SourceInput(kind="text", title="Sample", text=text)


def _all_grounded(result) -> bool:
    return all(quote_score(q.source_quote, result.chunks[q.chunk_id].text) >= 90
               for q in result.test.questions)


def test_happy_path_bilingual(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder())
    progress = []
    result = run(_src(sample_text), make_cfg(num_questions=5), llm, settings, on_progress=progress.append)
    assert len(result.test.questions) == 5
    assert result.report.kept == 5
    assert result.report.summary().startswith("Kept 5 of 5")
    assert _all_grounded(result)
    assert all(q.en and q.hi for q in result.test.questions)
    assert progress[-1].stage == "done"


def test_english_mode_has_no_hindi(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder())
    result = run(_src(sample_text), make_cfg(num_questions=5, mode="en"), llm, settings)
    assert len(result.test.questions) == 5
    assert all(q.hi is None for q in result.test.questions)


def test_mixed_types(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder())
    cfg = make_cfg(num_questions=6, qtypes=["mcq", "true_false"])
    result = run(_src(sample_text), cfg, llm, settings)
    types = [q.qtype for q in result.test.questions]
    assert len(types) == 6 and set(types) == {"mcq", "true_false"}


def test_failed_quotes_are_retried_once(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder(bad_calls={1}))
    result = run(_src(sample_text), make_cfg(num_questions=5), llm, settings)
    assert result.report.drop_reasons.get("quote_not_found", 0) >= 1
    assert result.report.retried >= 1
    assert len(result.test.questions) == 5
    assert _all_grounded(result)


def test_questions_failing_twice_are_dropped_never_kept(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder(bad_calls={1, 2}))
    result = run(_src(sample_text), make_cfg(num_questions=5), llm, settings)
    assert result.report.drop_reasons["quote_not_found"] >= 3
    assert _all_grounded(result)


def test_bad_json_batch_is_counted_and_recovered(sample_text, settings):
    llm = FakeLLMClient(json_queue=deque([LLMBadOutput("broken")]), responder=GroundedResponder())
    result = run(_src(sample_text), make_cfg(num_questions=5), llm, settings)
    assert result.report.drop_reasons["bad_output"] >= 1
    assert len(result.test.questions) == 5


def test_error_in_one_chunk_does_not_stop_run(sample_text, settings):
    llm = FakeLLMClient(json_queue=deque([RuntimeError("boom")]), responder=GroundedResponder())
    result = run(_src(sample_text), make_cfg(num_questions=5), llm, settings)
    assert "chunk_error" in result.report.drop_reasons
    assert len(result.test.questions) == 5


def test_ollama_down_stops_run(sample_text, settings):
    llm = FakeLLMClient(json_queue=deque([LLMUnavailable("down")]), responder=GroundedResponder())
    with pytest.raises(LLMUnavailable):
        run(_src(sample_text), make_cfg(num_questions=5), llm, settings)


def test_never_more_than_requested(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder())
    result = run(_src(sample_text), make_cfg(num_questions=7), llm, settings)
    assert len(result.test.questions) == 7


def test_regenerate_one(sample_text, settings):
    llm = FakeLLMClient(responder=GroundedResponder())
    result = run(_src(sample_text), make_cfg(num_questions=5), llm, settings)
    old = result.test.questions[0]
    new = regenerate_one(result.test, old.id, result.chunks, llm, settings)
    assert new is not None
    assert new.id != old.id and new.status == "regenerated"
    assert new.chunk_id == old.chunk_id and new.qtype == old.qtype
    assert quote_score(new.source_quote, result.chunks[new.chunk_id].text) >= 90


def test_regenerate_one_returns_none_when_all_attempts_fail(sample_text, settings):
    good = FakeLLMClient(responder=GroundedResponder())
    result = run(_src(sample_text), make_cfg(num_questions=5), good, settings)
    bad = FakeLLMClient(responder=GroundedResponder(bad_calls={1, 2}))
    assert regenerate_one(result.test, result.test.questions[0].id, result.chunks, bad, settings) is None
