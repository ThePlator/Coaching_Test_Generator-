"""PDF / photo / pasted text → SourceDocument (LLD §5)."""

from __future__ import annotations

import io
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Literal

from ctg.config import Settings
from ctg.llm import LLMClient, NoVisionModel
from ctg.models import SourceDocument
from ctg.prompts import OCR_SYSTEM, OCR_USER
from ctg.textutil import clean_text, detect_script, garbage_ratio, reflow

log = logging.getLogger("ctg.ingest")

ProgressFn = Callable[[str, int, int], None]  # (message, current, total)

MIN_PAGE_CHARS = 80          # fewer non-space chars → treat page as scanned
MAX_GARBAGE = 0.3            # more garbage glyphs → treat page as scanned
MIN_OCR_CHARS = 40
OCR_DPI = 170
IMAGE_LONG_EDGE = 1600
_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}\s*$", re.IGNORECASE)


class IngestError(Exception):
    """Input could not be read."""


class TooLarge(IngestError):
    """Input over the page / file / photo limits."""


@dataclass
class SourceInput:
    kind: Literal["pdf", "images", "text"]
    title: str = "Chapter"
    data: bytes | None = None                      # pdf
    images: list[bytes] = field(default_factory=list)
    text: str | None = None


def ingest(src: SourceInput, llm: LLMClient, settings: Settings,
           on_progress: ProgressFn | None = None) -> SourceDocument:
    if src.kind == "pdf":
        if src.data is None:
            raise IngestError("no PDF data")
        return from_pdf(src.data, llm, settings, title=src.title, on_progress=on_progress)
    if src.kind == "images":
        return from_images(src.images, llm, settings, title=src.title, on_progress=on_progress)
    return from_text(src.text or "", title=src.title)


def from_text(text: str, title: str = "Pasted notes") -> SourceDocument:
    body = reflow(clean_text(text))
    if len(body.strip()) < 100:
        raise IngestError("Please paste at least a few paragraphs of the chapter.")
    return _document(title, [body], ocr_pages=[])


def from_pdf(data: bytes, llm: LLMClient, settings: Settings, title: str = "Chapter",
             on_progress: ProgressFn | None = None) -> SourceDocument:
    if len(data) > settings.max_pdf_mb * 1024 * 1024:
        raise TooLarge(f"Please upload a PDF under {settings.max_pdf_mb} MB.")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        n = len(reader.pages)
    except (PdfReadError, ValueError, OSError) as e:
        raise IngestError("Could not read this PDF.") from e
    if n > settings.max_pdf_pages:
        raise TooLarge(f"Please upload up to {settings.max_pdf_pages} pages at a time.")

    raw: list[str] = []
    scanned: list[int] = []
    for i, page in enumerate(reader.pages):
        try:
            txt = clean_text(page.extract_text() or "")
        except Exception:  # pypdf can fail on odd pages; fall back to OCR
            txt = ""
        if len("".join(txt.split())) < MIN_PAGE_CHARS or garbage_ratio(txt) > MAX_GARBAGE:
            scanned.append(i)
        raw.append(txt)

    if scanned:
        _require_vision(llm)
        images = _render_pdf_pages(data, scanned)
        for j, (i, img) in enumerate(zip(scanned, images), 1):
            if on_progress:
                on_progress(f"Reading scanned page {i + 1}", j, len(scanned))
            raw[i] = clean_text(ocr_image(img, llm))

    pages = [reflow(p) for p in strip_repeated_lines(raw)]
    if not any(p.strip() for p in pages):
        raise IngestError("No text found in this PDF.")
    return _document(title, pages, ocr_pages=scanned)


def from_images(files: list[bytes], llm: LLMClient, settings: Settings, title: str = "Chapter",
                on_progress: ProgressFn | None = None) -> SourceDocument:
    if not files:
        raise IngestError("No photos uploaded.")
    if len(files) > settings.max_images:
        raise TooLarge(f"Please upload up to {settings.max_images} photos at a time.")
    _require_vision(llm)
    pages = []
    for i, f in enumerate(files, 1):
        if on_progress:
            on_progress(f"Reading photo {i}", i, len(files))
        pages.append(clean_text(ocr_image(prepare_image(f), llm)))
    pages = [reflow(p) for p in pages]
    return _document(title, pages, ocr_pages=list(range(len(pages))))


def prepare_image(data: bytes) -> bytes:
    """EXIF-rotate, RGB, shrink long edge to IMAGE_LONG_EDGE, JPEG q=85."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise IngestError("Could not open this photo.") from e
    img.thumbnail((IMAGE_LONG_EDGE, IMAGE_LONG_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def ocr_image(jpeg: bytes, llm: LLMClient) -> str:
    text = llm.chat_text(OCR_SYSTEM, OCR_USER, images=[jpeg]).strip()
    if len(text) < MIN_OCR_CHARS:
        raise IngestError("Could not read this photo. Try a clearer, flat photo in good light.")
    return text


def strip_repeated_lines(pages: list[str], min_share: float = 0.6) -> list[str]:
    """Drop running headers/footers (lines on ≥ min_share of pages) and bare page numbers."""
    if len(pages) >= 3:
        # count each distinct line once per page
        counts = Counter(ln for p in pages for ln in {x.strip() for x in p.splitlines() if x.strip()})
        repeated = {ln for ln, c in counts.items() if c / len(pages) >= min_share}
    else:
        repeated = set()
    out = []
    for p in pages:
        keep = [ln for ln in p.splitlines()
                if ln.strip() not in repeated and not _PAGE_NUMBER.match(ln)]
        out.append("\n".join(keep))
    return out


def _render_pdf_pages(data: bytes, indexes: list[int]) -> list[bytes]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    out = []
    for i in indexes:
        pil = pdf[i].render(scale=OCR_DPI / 72).to_pil()
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="PNG")
        out.append(prepare_image(buf.getvalue()))
    return out


def _require_vision(llm: LLMClient) -> None:
    if not llm.health().vision:
        raise NoVisionModel("Photo reading needs a vision model such as gemma3:4b.")


def _document(title: str, pages: list[str], ocr_pages: list[int]) -> SourceDocument:
    text = "\n\n".join(p for p in pages if p.strip())
    log.info("ingested pages=%d ocr_pages=%d chars=%d", len(pages), len(ocr_pages), len(text))
    return SourceDocument(title=title, text=text, pages=pages, ocr_pages=ocr_pages,
                          script=detect_script(text))
