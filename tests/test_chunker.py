from ctg import models as m
from ctg.chunker import MIN_TAIL, _split_long, allocate, chunk, expand_plan, type_plan
from ctg.ingest import from_text


def _chunks(n: int) -> list[m.Chunk]:
    return [m.Chunk(id=f"c{i:02d}", index=i, text="x" * (300 + 100 * i), script="en") for i in range(n)]


def test_chunk_sample_keeps_all_text_and_respects_size(sample_text):
    doc = from_text(sample_text, "Sample")
    chunks = chunk(doc, target=600, max_=900)
    assert len(chunks) >= 3
    assert set(doc.text.split()) == set(" ".join(c.text for c in chunks).split())
    for c in chunks[:-1]:
        assert len(c.text) <= 900
    assert [c.id for c in chunks] == [f"c{i + 1:02d}" for i in range(len(chunks))]


def test_chunk_starts_new_chunk_at_heading(sample_text):
    chunks = chunk(from_text(sample_text), target=600, max_=900)
    assert any(c.heading == "Right to Equality" for c in chunks)


def test_tiny_tail_is_merged(sample_text):
    chunks = chunk(from_text(sample_text), target=600, max_=900)
    assert len(chunks) == 1 or len(chunks[-1].text) >= MIN_TAIL


def test_hindi_chunk_script(sample_text_hi):
    chunks = chunk(from_text(sample_text_hi), target=600, max_=900)
    assert all(c.script == "hi" for c in chunks)


def test_split_long_block_at_danda():
    block = "यह एक लंबा वाक्य है जिसमें कई शब्द हैं। " * 100
    pieces = _split_long(block.strip(), 300)
    assert len(pieces) > 1
    assert all(len(p) <= 300 for p in pieces)
    assert all(p.endswith("।") for p in pieces)


def test_split_long_cuts_giant_sentence():
    pieces = _split_long("word " * 500, 200)
    assert all(len(p) <= 200 for p in pieces)


def test_allocate_sums_to_n():
    for n in (5, 10, 50):
        assert sum(c.quota for c in allocate(_chunks(6), n)) == n


def test_allocate_fewer_questions_than_chunks_spreads_out():
    out = allocate(_chunks(8), 5)
    quotas = [c.quota for c in out]
    assert sum(quotas) == 5 and set(quotas) == {0, 1}
    assert quotas[0] == 1 or quotas[1] == 1      # not all bunched at the end
    assert quotas[-1] == 1 or quotas[-2] == 1


def test_allocate_favours_longer_chunks():
    out = allocate(_chunks(3), 9)
    assert out[2].quota >= out[0].quota


def test_type_plan_round_robin_across_test():
    cs = [c.model_copy(update={"quota": q}) for c, q in zip(_chunks(2), (3, 2))]
    plan = type_plan(cs, ["mcq", "true_false"])
    assert plan == {"c00": ["mcq", "true_false", "mcq"], "c01": ["true_false", "mcq"]}


def test_expand_plan():
    assert expand_plan(["mcq", "true_false"], 5) == ["mcq", "true_false", "mcq", "true_false", "mcq"]
    assert expand_plan([], 2, ["true_false"]) == ["true_false", "true_false"]
