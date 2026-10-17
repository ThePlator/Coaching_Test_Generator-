import json

from ctg import models as m
from ctg.session import SessionLog
from tests.factories import make_cfg, make_q


def test_session_flow(tmp_path):
    s = SessionLog.start("pdf")
    s.chapter_ready(pages=4, ocr_pages=1, chunks=3)
    report = m.GenerationReport(requested=10, kept=9, seconds=95.0, drop_reasons={"duplicate": 1})
    s.generated(report, make_cfg(num_questions=10))
    s.edited += 1
    s.deleted += 1

    qs = [make_q(), make_q(status="edited")]
    s.exported(qs)
    first = s.exported_s
    s.exported(qs)                       # re-export keeps the first "chapter in → PDFs out" time

    assert s.exported_s == first and s.exports == 2
    assert s.final_questions == 2 and s.final_unchanged == 1
    assert s.requested == 10 and s.kept == 9 and s.mode == "bilingual"
    lines = "\n".join(s.summary_lines())
    assert "Asked for 10, model kept 9" in lines and "1 edited" in lines and "1 deleted" in lines

    data = json.loads(s.save(tmp_path).read_text(encoding="utf-8"))
    assert "t0" not in data and data["input_kind"] == "pdf"
    assert not any(isinstance(v, str) and "Article" in v for v in data.values())   # no chapter text


def test_regenerate_resets_review_counts():
    s = SessionLog.start("text")
    s.edited = 3
    s.generated(m.GenerationReport(requested=5, kept=5), make_cfg())
    assert s.edited == 0 and s.generations == 1
