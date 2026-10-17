import io
from collections import deque

import pytest
from PIL import Image

from ctg.ingest import (IngestError, TooLarge, from_images, from_text, prepare_image,
                        strip_repeated_lines)
from ctg.llm import FakeLLMClient, NoVisionModel

OCR_TEXT = ("Right to Constitutional Remedies\n\n"
            "Article 32 gives every citizen the right to move the Supreme Court.")


def _png(w=50, h=50) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_strip_repeated_lines_removes_headers_and_page_numbers():
    pages = ["Polity Notes\nbody one\n1", "Polity Notes\nbody two\n2", "Polity Notes\nbody three\nPage 3"]
    assert strip_repeated_lines(pages) == ["body one", "body two", "body three"]


def test_strip_repeated_lines_keeps_short_documents():
    assert strip_repeated_lines(["Title\nbody", "Title\nmore"]) == ["Title\nbody", "Title\nmore"]


def test_from_text_detects_script(sample_text, sample_text_hi):
    assert from_text(sample_text).script == "en"
    assert from_text(sample_text_hi).script == "hi"


def test_from_text_too_short():
    with pytest.raises(IngestError):
        from_text("Too short.")


def test_from_images_uses_vision_ocr(settings):
    llm = FakeLLMClient(text_queue=deque([OCR_TEXT]))
    doc = from_images([_png()], llm, settings)
    assert doc.ocr_pages == [0]
    assert "Article 32" in doc.text
    assert llm.calls[0]["images"]


def test_from_images_needs_vision_model(settings):
    with pytest.raises(NoVisionModel):
        from_images([_png()], FakeLLMClient(vision=False), settings)


def test_from_images_unreadable_photo(settings):
    with pytest.raises(IngestError):
        from_images([_png()], FakeLLMClient(text_queue=deque(["??"])), settings)


def test_from_images_limit(settings):
    with pytest.raises(TooLarge):
        from_images([_png()] * (settings.max_images + 1), FakeLLMClient(), settings)


def test_prepare_image_shrinks_long_edge():
    out = Image.open(io.BytesIO(prepare_image(_png(4000, 100))))
    assert max(out.size) == 1600 and out.format == "JPEG"
