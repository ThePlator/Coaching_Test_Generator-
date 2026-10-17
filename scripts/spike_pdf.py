"""M0 Spike B — does Hindi render correctly in an exported PDF?

Renders a small bilingual question paper (HTML + Jinja2 → WeasyPrint) using the
bundled Noto fonts, then:
  1. lists the fonts embedded in the PDF (NotoSansDevanagari must be there), and
  2. saves a PNG of page 1 so you can check the conjuncts by eye.

Usage:
    .venv/bin/python scripts/spike_pdf.py

Open scripts/spike_out/spike.pdf (or spike_page1.png) and check that these
are joined correctly with no boxes (tofu) or detached matras:
    क्ष  त्र  ज्ञ  श्र  द्ध  प्र  कृ  र्म  ट्ठ  हृदय  संविधान  अनुच्छेद
"""

from __future__ import annotations

import sys
from pathlib import Path

from jinja2 import Template

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
OUT_DIR = ROOT / "scripts" / "spike_out"

HTML = Template("""<!doctype html>
<html lang="hi"><head><meta charset="utf-8">
<style>
@font-face { font-family: "Noto Sans"; src: url("{{ fonts }}/NotoSans-Regular.ttf"); font-weight: 400; }
@font-face { font-family: "Noto Sans"; src: url("{{ fonts }}/NotoSans-Bold.ttf"); font-weight: 700; }
@font-face { font-family: "Noto Sans Devanagari"; src: url("{{ fonts }}/NotoSansDevanagari-Regular.ttf"); font-weight: 400; }
@font-face { font-family: "Noto Sans Devanagari"; src: url("{{ fonts }}/NotoSansDevanagari-Bold.ttf"); font-weight: 700; }
@page { size: A4; margin: 16mm 14mm;
        @bottom-center { content: "Page " counter(page) " / " counter(pages); font: 9pt "Noto Sans"; } }
body { font-family: "Noto Sans", "Noto Sans Devanagari", sans-serif; font-size: 11pt; line-height: 1.5; }
header { text-align: center; border-bottom: 1.5px solid #000; padding-bottom: 6px; margin-bottom: 10px; }
header h1 { margin: 0; font-size: 16pt; }
header .meta { display: flex; justify-content: space-between; font-size: 10pt; margin-top: 4px; }
.q { break-inside: avoid; margin: 0 0 12px; }
.q .hi { margin-top: 2px; }
.opts { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 18px; margin: 4px 0 0 22px; }
.stress { margin-top: 18px; padding: 8px; border: 1px dashed #888; font-size: 14pt; }
</style></head><body>
<header>
  <h1>{{ institute }} · {{ institute_hi }}</h1>
  <div>{{ title }}</div>
  <div class="meta"><span>Date / दिनांक: 18-10-2026</span><span>Time / समय: 30 min</span><span>Max Marks / पूर्णांक: {{ questions|length }}</span></div>
  <div class="meta"><span>Name / नाम: ____________________</span><span>Roll No. / अनुक्रमांक: ________</span></div>
</header>
{% for q in questions %}
<div class="q">
  <div><b>{{ loop.index }}.</b> {{ q.en }}</div>
  <div class="hi">&nbsp;&nbsp;&nbsp;&nbsp;{{ q.hi }}</div>
  <div class="opts">
    {% for e, h in q.opts %}<div>({{ "abcd"[loop.index0] }}/{{ "कखगघ"[loop.index0] }}) {{ e }} / {{ h }}</div>{% endfor %}
  </div>
</div>
{% endfor %}
<div class="stress">
  Conjunct check: क्ष त्र ज्ञ श्र द्ध प्र कृ र्म ट्ठ ह्न ह्य द्व श्व स्त्र — हृदय, संविधान, अनुच्छेद, प्रत्यक्षीकरण, उत्प्रेषण, अधिकार-पृच्छा, क्षत्रिय, श्रद्धा, द्वितीय
</div>
</body></html>""")

QUESTIONS = [
    {
        "en": "Which Article of the Constitution abolishes untouchability?",
        "hi": "संविधान का कौन-सा अनुच्छेद अस्पृश्यता का अंत करता है?",
        "opts": [("Article 14", "अनुच्छेद 14"), ("Article 17", "अनुच्छेद 17"),
                 ("Article 21", "अनुच्छेद 21"), ("Article 32", "अनुच्छेद 32")],
    },
    {
        "en": "Who called Article 32 the heart and soul of the Constitution?",
        "hi": "अनुच्छेद 32 को संविधान का हृदय और आत्मा किसने कहा था?",
        "opts": [("Jawaharlal Nehru", "जवाहरलाल नेहरू"), ("Dr. B. R. Ambedkar", "डॉ. भीमराव अंबेडकर"),
                 ("Sardar Patel", "सरदार पटेल"), ("Dr. Rajendra Prasad", "डॉ. राजेन्द्र प्रसाद")],
    },
    {
        "en": "Which writ literally means 'to have the body'?",
        "hi": "किस रिट का शाब्दिक अर्थ 'शरीर को प्रस्तुत करना' है?",
        "opts": [("Mandamus", "परमादेश"), ("Certiorari", "उत्प्रेषण"),
                 ("Habeas corpus", "बंदी प्रत्यक्षीकरण"), ("Quo warranto", "अधिकार-पृच्छा")],
    },
]


def main() -> None:
    try:
        from weasyprint import HTML as WeasyHTML
    except Exception as e:  # missing Pango/GTK on Windows etc.
        print(f"WeasyPrint not available: {e!r}")
        print("Fallback (LLD §13): render the same HTML with Playwright Chromium page.pdf().")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = HTML.render(
        fonts=FONTS.as_uri(),
        institute="Sharma Coaching Centre",
        institute_hi="शर्मा कोचिंग सेंटर",
        title="Polity — Fundamental Rights · राजव्यवस्था — मौलिक अधिकार",
        questions=QUESTIONS,
    )
    (OUT_DIR / "spike.html").write_text(html, encoding="utf-8")
    pdf_path = OUT_DIR / "spike.pdf"
    WeasyHTML(string=html, base_url=str(ROOT)).write_pdf(pdf_path)
    print(f"PDF: {pdf_path.relative_to(ROOT)}")

    # 1. Embedded fonts
    from pypdf import PdfReader

    fonts: set[str] = set()
    for page in PdfReader(pdf_path).pages:
        res = page.get("/Resources") or {}
        for f in (res.get("/Font") or {}).values():
            fonts.add(str(f.get_object().get("/BaseFont")))
    print("Embedded fonts:", ", ".join(sorted(fonts)) or "(none)")
    ok = any("Devanagari" in f for f in fonts)
    print("NotoSansDevanagari embedded:", "YES" if ok else "NO  ← problem")

    # 2. PNG preview of page 1
    try:
        import pypdfium2 as pdfium

        page = pdfium.PdfDocument(str(pdf_path))[0]
        png = OUT_DIR / "spike_page1.png"
        page.render(scale=2).to_pil().save(png)
        print(f"Preview: {png.relative_to(ROOT)}")
    except Exception as e:
        print(f"(PNG preview skipped: {e!r})")

    print("\nNow open the PDF/PNG and check the 'Conjunct check' box by eye.")


if __name__ == "__main__":
    main()
