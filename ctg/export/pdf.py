"""Student paper and answer key: Jinja2 HTML → PDF (LLD §13).

WeasyPrint shapes text with HarfBuzz (via Pango), so Devanagari conjuncts and
matras render correctly. If it can't be loaded (e.g. no GTK on Windows), we try
Playwright Chromium, and failing that raise ExportError so the UI can offer the
HTML to print from a browser.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from ctg.config import ROOT
from ctg.models import Chunk, LocalizedQ, OutputMode, PaperMeta, Question, Test

log = logging.getLogger("ctg.export")

TEMPLATES = Path(__file__).resolve().parent / "templates"
FONTS = ROOT / "assets" / "fonts"
LABELS = {"en": "abcd", "hi": "कखगघ"}
WIDE_OPTION_CHARS = 38           # longer options → one option per line
_BLANK = re.compile(r"_{3,}")


class ExportError(Exception):
    """PDF could not be produced."""


def _blank(text: str) -> Markup:
    """Escape, then draw '____' blanks as an underline box."""
    return Markup(_BLANK.sub('<span class="blank"></span>', str(escape(text))))


_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(enabled_extensions=("html", "j2"), default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["blank"] = _blank


def default_instructions(marks_per_q: float, negative: float = 0.0) -> tuple[str, str]:
    m = fmt_num(marks_per_q)
    en = f"All questions are compulsory. Each question carries {m} mark{'s' if marks_per_q != 1 else ''}."
    hi = f"सभी प्रश्न अनिवार्य हैं। प्रत्येक प्रश्न {m} अंक का है।"
    if negative:
        en += f" {fmt_num(negative)} mark will be deducted for each wrong answer."
        hi += f" प्रत्येक गलत उत्तर पर {fmt_num(negative)} अंक काटा जाएगा।"
    return en, hi


def fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


# -- view models -------------------------------------------------------------


@dataclass
class _Loc:
    lang: str
    stem: str
    answer_text: str
    explanation: str


@dataclass
class _Opt:
    label: str
    text: str


@dataclass
class _QView:
    number: int
    qtype: str
    marks: str
    locs: list[_Loc]
    options: list[_Opt]
    wide: bool
    answer_label: str
    source_quote: str
    heading: str | None


def _langs(mode: OutputMode) -> list[str]:
    return ["en", "hi"] if mode == "bilingual" else [mode]


def _label(i: int, langs: list[str]) -> str:
    return "/".join(LABELS[lang][i] for lang in langs)


def _view(n: int, q: Question, mode: OutputMode, chunks: dict[str, Chunk]) -> _QView:
    langs = [lang for lang in _langs(mode) if getattr(q, lang) is not None]
    locs: list[LocalizedQ] = [getattr(q, lang) for lang in langs]
    n_opts = max((len(loc.options) for loc in locs), default=0)
    options = []
    for i in range(min(n_opts, 4)):
        text = " / ".join(loc.options[i] for loc in locs if i < len(loc.options))
        options.append(_Opt(_label(i, langs), text))
    has_idx = q.answer_index is not None and 0 <= q.answer_index < n_opts
    chunk = chunks.get(q.chunk_id)
    return _QView(
        number=n,
        qtype=q.qtype,
        marks=fmt_num(q.marks),
        locs=[_Loc(lang, loc.stem, loc.answer_text, loc.explanation) for lang, loc in zip(langs, locs)],
        options=options,
        wide=any(len(o.text) > WIDE_OPTION_CHARS for o in options),
        answer_label=_label(q.answer_index, langs) if has_idx else "",
        source_quote=q.source_quote,
        heading=chunk.heading if chunk else None,
    )


def _context(test: Test, meta: PaperMeta, chunks: dict[str, Chunk], show_name_line: bool) -> dict:
    mode = test.config.mode

    def t(en: str, hi: str) -> str:
        return {"en": en, "hi": hi}.get(mode, f"{en} / {hi}")

    questions = [_view(i, q, mode, chunks) for i, q in enumerate(test.questions, 1)]
    total = sum(q.marks for q in test.questions)
    return {
        "meta": meta,
        "mode": mode,
        "t": t,
        "questions": questions,
        "total_marks": fmt_num(total),
        "set_label": test.set_label,
        "footer_set": f"Set {test.set_label}" if test.set_label else "",
        "fonts_url": FONTS.as_uri(),
        "show_name_line": show_name_line,
    }


# -- public API --------------------------------------------------------------


def paper_html(test: Test, meta: PaperMeta) -> str:
    return _env.get_template("paper.html.j2").render(_context(test, meta, {}, show_name_line=True))


def key_html(test: Test, meta: PaperMeta, chunks: dict[str, Chunk]) -> str:
    return _env.get_template("key.html.j2").render(_context(test, meta, chunks, show_name_line=False))


def render_paper(test: Test, meta: PaperMeta) -> bytes:
    return html_to_pdf(paper_html(test, meta))


def render_key(test: Test, meta: PaperMeta, chunks: dict[str, Chunk]) -> bytes:
    return html_to_pdf(key_html(test, meta, chunks))


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as e:          # OSError: Pango/GTK libraries missing
        log.info("weasyprint unavailable: %s", type(e).__name__)
        return _chromium_pdf(html)
    try:
        return HTML(string=html, base_url=str(FONTS)).write_pdf()
    except Exception as e:
        log.exception("weasyprint failed")
        raise ExportError("PDF creation failed") from e


def _chromium_pdf(html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ExportError("No PDF engine available (install WeasyPrint or Playwright)") from e
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            pdf = page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            browser.close()
            return pdf
    except Exception as e:
        raise ExportError("PDF creation failed") from e


def slugify(text: str, max_len: int = 40) -> str:
    """ASCII-ish file-system-safe slug; keeps Devanagari letters if that's all there is."""
    t = unicodedata.normalize("NFKD", text)
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", t.encode("ascii", "ignore").decode()).strip("-").lower()
    if ascii_part:
        return ascii_part[:max_len].strip("-")
    # \w misses Devanagari matras (Mc/Mn), so match the Devanagari block directly.
    deva = "-".join(re.findall(r"[ऀ-ॿ]+", text))
    return deva[:max_len].strip("-") or "test"


def save(outputs_dir: Path, meta: PaperMeta, files: dict[str, bytes]) -> Path:
    """Write files under outputs/<YYYY-MM-DD>_<slug>/ and return that folder."""
    folder = outputs_dir / f"{meta.date.isoformat()}_{slugify(meta.title)}"
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    log.info("saved %d file(s) to %s", len(files), folder.name)
    return folder
