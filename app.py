"""Coaching Test Generator — Streamlit UI (LLD §12).

Run:  streamlit run app.py
Only UI code lives here; everything else is in the `ctg` package.
"""

from __future__ import annotations

import re
from datetime import date

import streamlit as st

from ctg.config import InstituteProfile, Settings, load_institute, save_institute, setup_logging
from ctg.export.pdf import ExportError, default_instructions, key_html, paper_html, render_key, render_paper, save, slugify
from ctg.ingest import IngestError, SourceInput
from ctg.llm import LLMError, LLMTimeout, LLMUnavailable, ModelMissing, NoVisionModel, OllamaClient
from ctg.models import QTYPE_LABELS, REASON_LABELS, LocalizedQ, PaperMeta, Question, TestConfig
from ctg.pipeline import Progress, generate, prepare, regenerate_one
from ctg.session import SessionLog
from ctg.validate import check_question

st.set_page_config(page_title="Coaching Test Generator", page_icon="📝", layout="centered")

LANG_OPTIONS = {"bilingual": "Bilingual · द्विभाषी", "hi": "Hindi · हिंदी", "en": "English"}
DIFFICULTY_OPTIONS = {"easy": "Easy · आसान", "medium": "Medium · मध्यम", "hard": "Hard · कठिन"}
WARNING_LABELS = {
    "answer_not_in_quote": "Answer is not word-for-word in the source line — please check.",
    "long_stem": "Long question — consider shortening.",
    "ocr_source": "Read from a photo — check spellings.",
}
ERROR_MESSAGES = {
    LLMUnavailable: "Gemma is not running. Open a terminal and run `ollama serve`, then try again.",
    ModelMissing: "Model not installed. Run `ollama pull gemma3:4b` (one-time, ~3 GB).",
    NoVisionModel: "Photo reading needs a vision model such as gemma3:4b.",
    LLMTimeout: "The model took too long. Try fewer questions or a shorter chapter.",
}
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+\-.!|~$])")


# -- resources & state -------------------------------------------------------


@st.cache_resource
def get_settings() -> Settings:
    s = Settings()
    setup_logging(s)
    return s


@st.cache_resource
def get_llm() -> OllamaClient:
    llm = OllamaClient(get_settings())
    llm.warm_up()                         # load the model once so the first test isn't cold
    return llm


def init_state() -> None:
    defaults = {
        "doc": None, "chunks_list": None, "chunks": {}, "test": None, "report": None,
        "pending_cfg": None, "editing": None, "pdfs": None, "health": None, "notice": None,
        "session": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
    st.session_state.setdefault("reviewed_cb", False)


def md(text: str) -> str:
    """Escape Markdown so question text (e.g. '____') shows as typed."""
    return _MD_SPECIAL.sub(r"\\\1", text)


def log() -> SessionLog:
    """Session log for the first-user numbers; a throwaway one if no chapter was loaded yet."""
    return st.session_state.session or SessionLog()


def friendly(e: Exception) -> str:
    for cls, msg in ERROR_MESSAGES.items():
        if isinstance(e, cls):
            return msg
    return str(e) or "Something went wrong."


def invalidate_review() -> None:
    """Any change after review means the teacher must look again before export."""
    st.session_state.reviewed_cb = False
    st.session_state.pdfs = None


# -- sidebar -----------------------------------------------------------------


def sidebar(settings: Settings, llm: OllamaClient) -> InstituteProfile:
    profile = load_institute(settings.institute_file)
    with st.sidebar:
        st.subheader("Model")
        if st.session_state.health is None or st.button("Check again", width="stretch"):
            st.session_state.health = llm.health()
        h = st.session_state.health
        if h.ok and h.vision:
            st.success(f"🟢 {settings.model} — {h.message}")
        elif h.ok:
            st.warning(f"🟡 {settings.model} — {h.message}")
        elif h.server_up:
            st.warning(f"🟡 {h.message}")
        else:
            st.error(f"🔴 {h.message}")

        st.subheader("Institute · संस्थान")
        with st.form("institute"):
            name = st.text_input("Name (English)", profile.name)
            name_hi = st.text_input("नाम (हिंदी)", profile.name_hi or "")
            time_min = st.number_input("Default time (min)", 5, 300, profile.default_time_min, step=5)
            marks = st.number_input("Default marks per question", 0.25, 10.0,
                                    float(profile.default_marks_per_q), step=0.25)
            negative = st.number_input("Negative marking per wrong answer", 0.0, 5.0,
                                       float(profile.negative_marking), step=0.25)
            if st.form_submit_button("Save", width="stretch"):
                profile = InstituteProfile(name=name.strip() or profile.name, name_hi=name_hi.strip() or None,
                                           default_time_min=int(time_min), default_marks_per_q=marks,
                                           negative_marking=negative)
                save_institute(profile, settings.institute_file)
                st.toast("Saved")
        st.caption("Runs fully on this laptop. Your chapters never leave it.")
    return profile


# -- step 1: chapter -----------------------------------------------------------


def step_chapter(settings: Settings, llm: OllamaClient) -> None:
    st.header("1 · Chapter · अध्याय")
    title = st.text_input("Chapter / test title", placeholder="e.g. Polity — Fundamental Rights")
    tab_pdf, tab_photo, tab_text = st.tabs(["PDF", "Photos · फोटो", "Paste text"])
    src: SourceInput | None = None
    with tab_pdf:
        f = st.file_uploader("Chapter PDF", type=["pdf"], key="pdf_file")
        if f and st.button("Read PDF", type="primary", key="read_pdf"):
            src = SourceInput(kind="pdf", title=title or f.name.rsplit(".", 1)[0], data=f.getvalue())
    with tab_photo:
        st.caption("One page per photo, flat, in good light.")
        files = st.file_uploader("Book page photos", type=["jpg", "jpeg", "png", "webp"],
                                 accept_multiple_files=True, key="photo_files")
        if files and st.button("Read photos", type="primary", key="read_photos"):
            src = SourceInput(kind="images", title=title or "Chapter", images=[x.getvalue() for x in files])
    with tab_text:
        text = st.text_area("Paste the chapter or your notes", height=220, key="paste_text")
        if text.strip() and st.button("Use this text", type="primary", key="read_text"):
            src = SourceInput(kind="text", title=title or "Notes", text=text)

    if src is not None:
        st.session_state.session = SessionLog.start(src.kind)
        bar = st.progress(0.0, text="Reading the chapter…")

        def on_progress(p: Progress) -> None:
            bar.progress(min(1.0, p.current / max(p.total, 1)), text=p.message)

        try:
            doc, chunks = prepare(src, llm, settings, on_progress)
        except (IngestError, LLMError) as e:
            bar.empty()
            st.error(friendly(e))
        else:
            bar.empty()
            st.session_state.update(doc=doc, chunks_list=chunks, chunks={c.id: c for c in chunks},
                                    test=None, report=None, editing=None)
            log().chapter_ready(len(doc.pages), len(doc.ocr_pages), len(chunks))
            invalidate_review()

    doc = st.session_state.doc
    if doc:
        ocr = f", {len(doc.ocr_pages)} read from images" if doc.ocr_pages else ""
        st.success(f"**{md(doc.title)}** — {len(doc.pages)} page(s){ocr}, "
                   f"{len(st.session_state.chunks_list)} part(s), {len(doc.text):,} characters")
        with st.expander("Preview extracted text"):
            st.text(doc.text[:5000] + ("\n…" if len(doc.text) > 5000 else ""))


# -- step 2: settings & generate -------------------------------------------------


def step_settings(settings: Settings, llm: OllamaClient) -> None:
    if not st.session_state.doc:
        return
    st.header("2 · Settings · सेटिंग्स")
    running = st.session_state.pending_cfg is not None
    n = st.slider("Number of questions", 5, 50, 10, disabled=running)
    qtypes = st.multiselect("Question types", list(QTYPE_LABELS), default=["mcq"],
                            format_func=QTYPE_LABELS.get, disabled=running)
    c1, c2 = st.columns(2)
    difficulty = c1.radio("Difficulty", list(DIFFICULTY_OPTIONS), index=1,
                          format_func=DIFFICULTY_OPTIONS.get, disabled=running)
    mode = c2.radio("Language", list(LANG_OPTIONS), format_func=LANG_OPTIONS.get, disabled=running)
    if n > 15:
        st.caption("⏱️ More than 15 questions can take several minutes on a laptop.")

    def request() -> None:
        st.session_state.pending_cfg = TestConfig(num_questions=n, qtypes=qtypes or ["mcq"],
                                                  difficulty=difficulty, mode=mode)

    st.button("Generate test · टेस्ट बनाएं", type="primary", disabled=running or not qtypes,
              on_click=request, width="stretch")

    if running:
        cfg: TestConfig = st.session_state.pending_cfg
        bar = st.progress(0.0, text="Starting…")

        def on_progress(p: Progress) -> None:
            bar.progress(min(1.0, p.current / max(p.total, 1)), text=f"{p.message} · kept {p.kept}")

        try:
            result = generate(st.session_state.doc, st.session_state.chunks_list, cfg, llm, settings, on_progress)
        except LLMError as e:
            st.session_state.notice = ("error", friendly(e))
        else:
            marks = load_institute(settings.institute_file).default_marks_per_q
            for q in result.test.questions:
                q.marks = marks
            st.session_state.update(test=result.test, report=result.report, chunks=result.chunks, editing=None)
            log().generated(result.report, cfg)
            invalidate_review()
        finally:
            st.session_state.pending_cfg = None
        st.rerun()


# -- step 3: review ----------------------------------------------------------------


def show_question(i: int, q: Question, mode: str) -> None:
    c = st.session_state.chunks.get(q.chunk_id)
    badge = {"edited": " · ✏️ edited", "regenerated": " · 🔄 new"}.get(q.status, "")
    st.markdown(f"**Q{i}** · {QTYPE_LABELS.get(q.qtype, q.qtype)} · {q.difficulty}{badge}")
    langs = [lang for lang in ("en", "hi") if getattr(q, lang) is not None and (mode == "bilingual" or lang == mode)]
    for lang in langs:
        loc: LocalizedQ = getattr(q, lang)
        st.markdown(md(loc.stem))
        for j, opt in enumerate(loc.options):
            tick = "✅" if j == q.answer_index else "▫️"
            st.markdown(f"{tick} ({'abcd'[j] if lang == 'en' else 'कखगघ'[j]}) {md(opt)}")
        if not loc.options:
            st.markdown(f"✅ **{md(loc.answer_text)}**")
        if loc.explanation:
            st.caption(f"💡 {md(loc.explanation)}")
    heading = f" — {md(c.heading)}" if c and c.heading else ""
    st.caption(f"📖 Source{heading}: “{md(q.source_quote)}”")
    for w in q.warnings:
        st.warning(WARNING_LABELS.get(w, REASON_LABELS.get(w, w)), icon="⚠️")


def edit_form(q: Question, mode: str) -> None:
    langs = ["en", "hi"] if mode == "bilingual" else [mode]
    with st.form(f"edit_{q.id}"):
        new: dict[str, dict] = {}
        n_opts = len((q.en or q.hi).options) if (q.en or q.hi) else 0
        for lang in langs:
            loc: LocalizedQ = getattr(q, lang) or LocalizedQ(stem="", answer_text="")
            st.markdown("**English**" if lang == "en" else "**हिंदी**")
            stem = st.text_area("Question", loc.stem, key=f"{q.id}_{lang}_stem", height=80)
            opts = [st.text_input(f"Option {'abcd'[j] if lang == 'en' else 'कखगघ'[j]}",
                                  loc.options[j] if j < len(loc.options) else "", key=f"{q.id}_{lang}_o{j}")
                    for j in range(n_opts)]
            answer = "" if n_opts else st.text_input("Answer", loc.answer_text, key=f"{q.id}_{lang}_ans")
            expl = st.text_input("Explanation", loc.explanation, key=f"{q.id}_{lang}_expl")
            new[lang] = {"stem": stem, "options": opts, "answer_text": answer, "explanation": expl}
        idx = q.answer_index or 0
        if n_opts:
            idx = st.radio("Correct option", range(n_opts), index=min(idx, n_opts - 1), horizontal=True,
                           format_func=lambda j: "abcd"[j], key=f"{q.id}_idx")
        quote = st.text_area("Source line", q.source_quote, key=f"{q.id}_quote", height=68)
        save_col, cancel_col = st.columns(2)
        if save_col.form_submit_button("Save", type="primary", width="stretch"):
            for lang, v in new.items():
                opts = [o.strip() for o in v["options"]]
                setattr(q, lang, LocalizedQ(stem=v["stem"].strip(), options=opts,
                                            answer_text=opts[idx] if opts else v["answer_text"].strip(),
                                            explanation=v["explanation"].strip()))
            q.answer_index = idx if n_opts else None
            q.source_quote = quote.strip()
            if q.status == "ok":
                log().edited += 1
            q.status = "edited"
            # Re-check; failures become warnings only — the teacher has the final say.
            res = check_question(q, st.session_state.chunks[q.chunk_id], st.session_state.test.config,
                                 get_settings().quote_match_threshold)
            q.warnings = res.warnings + res.reasons
            st.session_state.editing = None
            invalidate_review()
            st.rerun()
        if cancel_col.form_submit_button("Cancel", width="stretch"):
            st.session_state.editing = None
            st.rerun()


def step_review(settings: Settings, llm: OllamaClient) -> None:
    test = st.session_state.test
    if test is None:
        return
    st.header("3 · Review · जाँचें")
    report = st.session_state.report
    if report:
        (st.success if report.kept >= report.requested else st.warning)(
            f"{report.summary()} · {report.seconds:.0f}s")
    if not test.questions:
        st.error("No questions passed the checks. Try a longer chapter, fewer questions, or easy difficulty.")
        return

    mode = test.config.mode
    for i, q in enumerate(list(test.questions), 1):
        with st.container(border=True):
            if st.session_state.editing == q.id:
                edit_form(q, mode)
                continue
            show_question(i, q, mode)
            b1, b2, b3 = st.columns(3)
            if b1.button("✏️ Edit", key=f"edit_{q.id}", width="stretch"):
                st.session_state.editing = q.id
                st.rerun()
            if b2.button("🗑️ Delete", key=f"del_{q.id}", width="stretch"):
                test.questions = [x for x in test.questions if x.id != q.id]
                log().deleted += 1
                invalidate_review()
                st.rerun()
            if b3.button("🔄 Regenerate", key=f"regen_{q.id}", width="stretch"):
                with st.spinner("Writing a new question…"):
                    try:
                        new = regenerate_one(test, q.id, st.session_state.chunks, llm, settings)
                    except LLMError as e:
                        new = None
                        st.session_state.notice = ("error", friendly(e))
                if new is None:
                    log().regenerate_failed += 1
                    st.session_state.notice = st.session_state.notice or (
                        "warning", f"Could not write a better question for Q{i}; kept the old one.")
                else:
                    test.questions = [new if x.id == q.id else x for x in test.questions]
                    log().regenerated += 1
                    invalidate_review()
                st.rerun()

    st.checkbox(f"I have reviewed all {len(test.questions)} questions · मैंने सभी प्रश्न जाँच लिए हैं",
                key="reviewed_cb")


# -- step 4: export ----------------------------------------------------------------


def step_export(settings: Settings, profile: InstituteProfile) -> None:
    test = st.session_state.test
    if test is None or not test.questions:
        return
    st.header("4 · Print · प्रिंट")
    if not st.session_state.reviewed_cb:
        st.info("Tick “I have reviewed all questions” above to create the PDFs.")
        return

    doc = st.session_state.doc
    with st.form("export"):
        title = st.text_input("Title on paper", doc.title if doc else "Practice Test")
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("Date", date.today())
        time_min = c2.number_input("Time (min)", 5, 300, profile.default_time_min, step=5)
        marks = c3.number_input("Marks / question", 0.25, 10.0, float(profile.default_marks_per_q), step=0.25)
        submitted = st.form_submit_button("Create PDFs · PDF बनाएं", type="primary", width="stretch")

    if submitted:
        for q in test.questions:
            q.marks = marks
        en, hi = default_instructions(marks, profile.negative_marking)
        meta = PaperMeta(institute=profile.name, institute_hi=profile.name_hi, title=title.strip() or "Practice Test",
                         date=day, time_min=int(time_min), marks_per_q=marks, instructions_en=en, instructions_hi=hi)
        slug = slugify(meta.title)
        with st.spinner("Creating PDFs…"):
            try:
                files = {f"{slug}_paper.pdf": render_paper(test, meta),
                         f"{slug}_answer_key.pdf": render_key(test, meta, st.session_state.chunks)}
                mime = "application/pdf"
            except ExportError:
                files = {f"{slug}_paper.html": paper_html(test, meta).encode(),
                         f"{slug}_answer_key.html": key_html(test, meta, st.session_state.chunks).encode()}
                mime = "text/html"
            folder = save(settings.outputs_dir, meta, files)
            st.session_state.pdfs = {"files": files, "folder": str(folder), "mime": mime}
            if st.session_state.session:
                st.session_state.session.exported(test.questions)
                st.session_state.session.save(folder)

    pdfs = st.session_state.pdfs
    if pdfs:
        if pdfs["mime"] == "text/html":
            st.warning("PDF creation failed on this computer. Download the HTML files, open them in a browser "
                       "and print (Ctrl+P → Save as PDF).")
        else:
            st.success(f"Saved to `{pdfs['folder']}`")
        cols = st.columns(len(pdfs["files"]))
        for col, (name, data) in zip(cols, pdfs["files"].items()):
            label = "📄 Student paper" if "_paper" in name else "🔑 Answer key"
            col.download_button(label, data, file_name=name, mime=pdfs["mime"], width="stretch")
        if st.session_state.session:
            with st.expander("Session numbers (for your first-user notes)"):
                st.markdown("\n".join(f"- {line}" for line in st.session_state.session.summary_lines()))
                st.caption(f"Also saved as session.json in `{pdfs['folder']}`. Counts only — no chapter text.")


# -- main ------------------------------------------------------------------------------


def main() -> None:
    init_state()
    settings = get_settings()
    llm = get_llm()
    profile = sidebar(settings, llm)

    st.title("📝 Coaching Test Generator")
    st.caption("Chapter in → printable test out, in Hindi, English or both. · प्रश्न पत्र")

    notice = st.session_state.notice
    if notice:
        getattr(st, notice[0])(notice[1])
        st.session_state.notice = None

    step_chapter(settings, llm)
    step_settings(settings, llm)
    step_review(settings, llm)
    step_export(settings, profile)


main()
