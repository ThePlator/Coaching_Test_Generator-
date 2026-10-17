# Coaching Test Generator — Low-Level Design (LLD)

| | |
|---|---|
| **Status** | Draft v1 — 17 Oct 2026 |
| **Depends on** | [HLD](HLD.md), Coaching Test Generator — PRD |
| **Language / runtime** | Python 3.11+, Ollama ≥ 0.5 (structured outputs) |

---

## 1. Repository layout

```
coaching-test-generator/
├── app.py                      # Streamlit entry point (UI only, no business logic)
├── ctg/                        # core package
│   ├── __init__.py
│   ├── config.py               # Settings (env + institute.toml)
│   ├── models.py               # Pydantic domain models
│   ├── llm.py                  # LLMClient protocol, OllamaClient, FakeLLMClient
│   ├── ingest.py               # PDF / image / text → SourceDocument
│   ├── chunker.py              # SourceDocument → list[Chunk] + quotas
│   ├── prompts.py              # prompt builders + few-shot examples
│   ├── schema.py               # JSON schema for model output, per mode
│   ├── generator.py            # Chunk → candidate Questions (LLM call)
│   ├── validate.py             # all code-side checks, dedupe
│   ├── pipeline.py             # orchestration, retry-once-then-drop, progress
│   ├── presets.py              # exam style presets (P1)
│   ├── shuffle.py              # Set A / Set B (P1)
│   ├── bank.py                 # SQLite question bank (P1)
│   ├── export/
│   │   ├── pdf.py              # Jinja2 + WeasyPrint renderer
│   │   ├── text.py             # WhatsApp text quiz (P2)
│   │   └── templates/
│   │       ├── base.css
│   │       ├── paper.html.j2
│   │       └── key.html.j2
│   └── textutil.py             # normalisation, script detection, fuzzy helpers
├── assets/fonts/               # NotoSans-*.ttf, NotoSansDevanagari-*.ttf (OFL)
├── config/institute.example.toml
├── samples/                    # shareable sample chapter(s) only
├── tests/
│   ├── fixtures/               # canned LLM JSON, sample chunks
│   ├── test_textutil.py
│   ├── test_chunker.py
│   ├── test_validate.py
│   ├── test_pipeline.py
│   ├── test_shuffle.py
│   └── test_export.py
├── scripts/setup.sh, setup.ps1, bench.py
├── requirements.txt
├── LICENSE                     # MIT
└── README.md
```

**Dependency rule:** `app.py → ctg.pipeline → (ingest, chunker, generator, validate) → llm`. Only `llm.py` talks to Ollama, and only `app.py` imports Streamlit.

## 2. Configuration (`ctg/config.py`)

```python
class Settings(BaseSettings):            # pydantic-settings, env prefix CTG_
    ollama_host: str = "http://localhost:11434"
    model: str = "gemma3:4b"             # must be vision-capable for photos
    text_model: str | None = None        # optional faster text-only model
    num_ctx: int = 4096
    temperature: float = 0.4
    request_timeout_s: int = 180
    keep_alive: str = "30m"              # keep model warm between calls
    chunk_target_chars: int = 1500
    chunk_max_chars: int = 2200
    overgen_factor: float = 1.3
    max_questions_per_call: int = 5
    quote_match_threshold: int = 90      # rapidfuzz partial_ratio
    dedupe_threshold: int = 90           # rapidfuzz token_sort_ratio
    outputs_dir: Path = Path("outputs")
    bank_path: Path = Path("data/bank.db")
    institute_file: Path = Path("config/institute.toml")

class InstituteProfile(BaseModel):
    name: str = "My Coaching Centre"
    name_hi: str | None = None
    default_time_min: int = 30
    default_marks_per_q: float = 1.0
    negative_marking: float = 0.0
```

## 3. Domain models (`ctg/models.py`)

```python
Lang          = Literal["en", "hi"]
OutputMode    = Literal["en", "hi", "bilingual"]
QType         = Literal["mcq", "true_false", "fill_blank", "short_answer"]
Difficulty    = Literal["easy", "medium", "hard"]
ExamPreset    = Literal["generic", "bihar_board", "bpsc", "ssc", "railway"]
QStatus       = Literal["ok", "edited", "regenerated"]

class SourceDocument(BaseModel):
    title: str
    text: str                       # NFC-normalised full text
    pages: list[str]                # per page / per image text
    ocr_pages: list[int] = []       # page indexes that went through vision OCR
    script: Literal["en", "hi", "mixed"]

class Chunk(BaseModel):
    id: str                         # "c03"
    index: int
    text: str
    heading: str | None
    script: Literal["en", "hi", "mixed"]
    quota: int = 0                  # questions assigned (before over-generation)

class LocalizedQ(BaseModel):        # one language version of a question
    stem: str
    options: list[str] = []         # MCQ: 4, T/F: 2, others: []
    answer_text: str                # text of correct option / blank / model answer
    explanation: str

class Question(BaseModel):
    id: str                         # uuid4 hex[:8]
    chunk_id: str
    qtype: QType
    difficulty: Difficulty
    answer_index: int | None        # MCQ/TF only; shared across languages
    en: LocalizedQ | None
    hi: LocalizedQ | None
    source_quote: str               # verbatim from chunk (chunk's language)
    status: QStatus = "ok"
    warnings: list[str] = []        # soft flags shown in review UI
    marks: float = 1.0

class TestConfig(BaseModel):
    num_questions: conint(ge=5, le=50) = 10
    qtypes: list[QType] = ["mcq"]
    difficulty: Difficulty = "medium"
    mode: OutputMode = "bilingual"
    preset: ExamPreset = "generic"
    allow_aota: bool = False        # "all/none of the above"

class PaperMeta(BaseModel):
    institute: str
    title: str                      # e.g. "Polity — Chapter 3: Fundamental Rights"
    date: date
    time_min: int
    marks_per_q: float
    instructions_en: str
    instructions_hi: str

class Test(BaseModel):
    config: TestConfig
    meta: PaperMeta | None
    questions: list[Question]
    set_label: str | None = None    # "A" / "B"

class GenerationReport(BaseModel):
    requested: int
    generated: int                  # candidates produced by LLM
    kept: int
    retried: int
    dropped: int
    drop_reasons: Counter[str]      # e.g. {"quote_not_found": 3, "duplicate": 1}
    seconds: float
```

Invariants (checked in `validate.py` and by Pydantic `model_validator`):

- `mode == "en"` ⇒ `en` is set and `hi is None`. `"hi"` is the mirror case. `"bilingual"` ⇒ both are set.
- `qtype == "mcq"` ⇒ `len(options) == 4` in every language version, and `answer_index ∈ [0,3]`.
- `qtype == "true_false"` ⇒ `options == ["True","False"]` / `["सही","गलत"]`, and `answer_index ∈ {0,1}`.
- `qtype ∈ {fill_blank, short_answer}` ⇒ `options == []` and `answer_index is None`.
- `answer_text == options[answer_index]` whenever options exist.

## 4. LLM client (`ctg/llm.py`)

```python
class LLMClient(Protocol):
    def chat_json(self, system: str, user: str, schema: dict,
                  images: list[bytes] | None = None) -> dict: ...
    def chat_text(self, system: str, user: str,
                  images: list[bytes] | None = None) -> str: ...
    def health(self) -> HealthStatus: ...   # server up? model pulled? vision?
```

**`OllamaClient`**

- `POST {host}/api/chat` with `stream=false`, `format=<json schema>` for `chat_json`, `keep_alive`, and `options={temperature, num_ctx, num_predict: 2048, top_p: 0.9}`.
- Images are base64 JPEGs in `messages[-1].images`.
- `health()` calls `GET /api/tags` to check the model is present and `POST /api/show` to check its capabilities include `vision`.
- Errors map to `LLMUnavailable` (connection refused), `ModelMissing`, `LLMTimeout` and `LLMBadOutput` (JSON parse failure even with `format`).
- Transport errors get one silent retry. `LLMBadOutput` is passed up to the pipeline as a failed batch.

**`FakeLLMClient`** returns canned fixtures keyed by prompt hash or a queue. It is used by all pipeline tests.

## 5. Ingestion (`ctg/ingest.py`)

```python
def from_pdf(data: bytes, llm: LLMClient, on_progress) -> SourceDocument
def from_images(files: list[bytes], llm: LLMClient, on_progress) -> SourceDocument
def from_text(text: str, title: str = "Pasted notes") -> SourceDocument
```

**PDF algorithm**

1. Read each page with `pypdf.PdfReader(...).pages[i].extract_text()`.
2. If a page has fewer than 80 non-space characters, or more than 30% of its characters are replacement or garbage glyphs (common with legacy Hindi fonts such as Kruti Dev), mark it as **scanned**.
3. Render scanned pages with `pypdfium2` at 170 DPI, then send them to `ocr_image()`.
4. Remove repeated headers and footers: drop any line that appears on 60% or more of the pages, and drop lines that are only page numbers.
5. Join words hyphenated across line breaks (`-\n`), collapse whitespace, apply `unicodedata.normalize("NFC")`.

**Images (`ocr_image`)**

- Fix rotation with `ImageOps.exif_transpose`, convert to RGB, shrink so the long edge is at most 1600 px, save as JPEG q=85.
- Call `llm.chat_text(OCR_SYSTEM, OCR_USER, images=[jpeg])`. The prompt says: *"Transcribe all text on this book page exactly as printed. Keep Hindi in Devanagari. Keep headings on their own lines. Output plain text only, no commentary."*
- If the OCR result has fewer than 40 characters, raise `IngestError("photo unreadable")` and ask the user for a clearer photo.

**Script detection** (`textutil.detect_script`) uses the share of Devanagari letters (U+0900–U+097F) among all letters: ≥ 0.6 → `hi`, ≤ 0.1 → `en`, otherwise `mixed`.

**Limits:** PDF ≤ 30 pages and ≤ 20 MB; images ≤ 10 per upload. Larger inputs are rejected with a message.

## 6. Chunker (`ctg/chunker.py`)

```python
def chunk(doc: SourceDocument, target=1500, max_=2200) -> list[Chunk]
def allocate(chunks: list[Chunk], n: int) -> list[Chunk]   # sets .quota
```

**Splitting**

1. Split into blocks on blank lines.
2. Treat a block as a **heading** if it is a single line under 80 characters with no sentence-ending punctuation (`.`, `?`, `।`), or if it matches a numbered-heading regex (`^\d+(\.\d+)*\s`).
3. Greedily add blocks to the current chunk. Start a new chunk when a heading is found and the current chunk is at least 40% of `target`, or when adding the block would go over `max_`.
4. Split a single block longer than `max_` at sentence boundaries (`(?<=[.?!।])\s+`).
5. Merge a final chunk under 300 characters into the chunk before it.

**Quota allocation (largest remainder)**

```
weights_i = len(chunk_i.text)
if n >= len(chunks):
    raw_i = n * w_i / Σw ; quota_i = floor(raw_i)
    give remaining (n - Σquota) to chunks with largest (raw_i - quota_i)
else:  # fewer questions than chunks → spread evenly
    pick n chunks at stride len(chunks)/n, quota = 1 each
```

**Question-type mix:** requested types are assigned round-robin over the whole test (for example, MCQ+TF with N=10 gives 5+5). The type list for each chunk travels with its quota.

## 7. Prompts (`ctg/prompts.py`)

### 7.1 System prompt (generation)

```
You are an expert question-paper setter for Indian competitive and board exams.
You write questions ONLY from the CHAPTER EXTRACT given by the user.

RULES
1. Use only facts stated in the extract. Never add outside facts, dates or names.
2. MCQ: exactly 4 options, exactly one correct. Wrong options must be plausible
   but clearly wrong according to the extract.
3. source_quote: copy, word for word, the one sentence from the extract that
   proves the answer. Do not translate or paraphrase it.
4. {aota_rule}   # "Never use 'All of the above' / 'None of the above'." unless allowed
5. Hindi must be natural standard exam Hindi in Devanagari (as in BPSC/SSC papers),
   not word-by-word translation.
6. Explanation: one line, refers to the extract.
7. Do not repeat or rephrase any question listed under AVOID.
Return JSON only, matching the schema.
```

### 7.2 User prompt template

```
EXAM STYLE: {preset_style_text}
DIFFICULTY: {difficulty} — {difficulty_hint}
LANGUAGE: {mode_instruction}
QUESTION TYPES: {type_plan}            # e.g. "2 mcq, 1 true_false"
COUNT: {k}

EXAMPLE (format and Hindi tone only — do not reuse its content):
{few_shot_json}

AVOID (already asked):
- {stem_1}
- ...

CHAPTER EXTRACT (language: {chunk_script}):
"""
{chunk_text}
"""
```

- `difficulty_hint`: easy = direct recall of one stated fact; medium = needs understanding of one or two sentences; hard = combines facts from different sentences in the extract.
- `mode_instruction` for bilingual: *"Write every question in BOTH English (en) and Hindi (hi). Both versions must have the same options in the same order and the same answer_index."*
- The few-shot example is a single short bilingual MCQ. There is one per preset, written by hand in exam-style Hindi.

### 7.3 Retry prompt add-on

```
Your previous questions failed these checks:
- Q2: source_quote not found in extract
- Q4: options are not distinct
Write {m} NEW questions that pass all rules.
```

### 7.4 Presets (`ctg/presets.py`, P1)

| Preset | Style text (summary) |
|---|---|
| `generic` | Clear, neutral school-test language. |
| `bihar_board` | BSEB matric/inter style. Simple direct stems such as "निम्नलिखित में से कौन…". |
| `bpsc` | Statement-based stems ("Consider the following statements…"), formal Hindi. |
| `ssc` | Short one-line factual stems with crisp options. |
| `railway` | RRB NTPC/Group D style. Very short stems, single-fact recall. |

## 8. Output schema sent to Ollama (`ctg/schema.py`)

`build_schema(mode, k) -> dict` builds a JSON Schema like the one below. Language blocks are **required** for the chosen mode, so constrained decoding cannot leave them out.

```json
{
  "type": "object",
  "properties": {
    "questions": {
      "type": "array", "minItems": 1, "maxItems": 5,
      "items": {
        "type": "object",
        "properties": {
          "qtype":        {"enum": ["mcq","true_false","fill_blank","short_answer"]},
          "answer_index": {"type": ["integer","null"], "minimum": 0, "maximum": 3},
          "en": {"$ref": "#/$defs/loc"},
          "hi": {"$ref": "#/$defs/loc"},
          "source_quote": {"type": "string", "minLength": 15}
        },
        "required": ["qtype","answer_index","source_quote","en","hi"]
      }
    }
  },
  "required": ["questions"],
  "$defs": {
    "loc": {
      "type": "object",
      "properties": {
        "stem": {"type":"string"}, "options": {"type":"array","items":{"type":"string"}},
        "answer_text": {"type":"string"}, "explanation": {"type":"string"}
      },
      "required": ["stem","options","answer_text","explanation"]
    }
  }
}
```

The response is parsed into `LLMBatch` (a Pydantic model) and mapped to `Question`, filling in `id`, `chunk_id` and `difficulty`.

## 9. Generator (`ctg/generator.py`)

```python
def generate_for_chunk(llm, chunk: Chunk, plan: list[QType], cfg: TestConfig,
                       avoid: list[str], feedback: list[str] | None = None
                       ) -> list[Question]
```

- Splits `plan` into batches of at most `max_questions_per_call` and makes one call per batch.
- Sends `avoid` stems so the model doesn't repeat questions, capped at the last 15 stems to keep the prompt short.
- Returns candidates without validating them. Validation is a separate step.
- If a batch raises `LLMBadOutput`, it returns `[]` and the pipeline treats the whole batch as failed.

## 10. Validator (`ctg/validate.py`)

```python
@dataclass
class CheckResult:
    ok: bool
    reasons: list[str]      # hard failures → retry/drop
    warnings: list[str]     # soft → shown in review UI

def check_question(q: Question, chunk: Chunk, cfg: TestConfig) -> CheckResult
def dedupe(questions: list[Question], existing: list[Question] = []) -> tuple[list, list]
```

### 10.1 Normalisation (`textutil.norm`)

1. NFC.
2. Lowercase (has no effect on Devanagari).
3. Remove ZWJ/ZWNJ (U+200C/D) and soft hyphens.
4. Map `।` and `॥` to `.`, and map curly quotes to straight quotes.
5. Remove all punctuation except Devanagari matras and nukta.
6. Collapse whitespace.

### 10.2 Hard checks (any failure ⇒ question fails)

| Code | Check |
|---|---|
| `schema` | Pydantic invariants from §3 |
| `quote_short` | `len(norm(source_quote)) < 15` |
| `quote_not_found` | `norm(quote) not in norm(chunk)` **and** `fuzz.partial_ratio(norm(quote), norm(chunk)) < 90` |
| `options_count` | MCQ options ≠ 4 in any language version |
| `options_dup` | Any two `norm(option)` are equal, or have `fuzz.ratio ≥ 95` |
| `answer_mismatch` | `answer_text` ≠ `options[answer_index]` after normalisation (for each language) |
| `aota` | An option matches the forbidden list (`all of the above`, `none of the above`, `both a and b`, `उपरोक्त सभी`, `इनमें से कोई नहीं`, `उपर्युक्त सभी`) while `allow_aota=False` |
| `bilingual_mismatch` | Bilingual mode: option counts differ between `en` and `hi`, or a type mismatch (answer index is shared by construction, so only structure can differ) |
| `blank_missing` | `fill_blank` stem has no `____` (3 or more underscores) |
| `empty_text` | Any stem, option or answer is blank |
| `wrong_script` | The `hi` stem is less than 50% Devanagari, or the `en` stem is more than 20% Devanagari |

### 10.3 Soft warnings (kept, flagged with ⚠ in review)

- `answer_not_in_quote`: for a same-language chunk, `fuzz.partial_ratio(answer_text, quote) < 70`.
- `long_stem`: stem over 300 characters.
- `ocr_source`: the chunk came from an OCR'd page (the teacher should double-check spellings).

### 10.4 Dedupe

The key is `norm(en.stem)`, or `norm(hi.stem)` for Hindi-only mode. Walk the list in order. Drop a question if `fuzz.token_sort_ratio(key, kept_key) ≥ 90` for any kept question **or** any question in `existing`. Its drop reason is `duplicate`. (`token_set_ratio` was rejected: it scores stems that differ in one key word, e.g. "…Right to Equality?" vs "…Right to Freedom?", as duplicates.) Dedupe runs after each chunk (against all questions kept so far) and once more at the end.

## 11. Pipeline (`ctg/pipeline.py`)

```python
@dataclass
class Progress:
    stage: Literal["extract","ocr","chunk","generate","check","done"]
    current: int; total: int; kept: int; message: str

def run(source: SourceInput, cfg: TestConfig, llm: LLMClient, settings: Settings,
        on_progress: Callable[[Progress], None]) -> tuple[Test, GenerationReport]

def regenerate_one(test: Test, qid: str, chunks: dict[str, Chunk], llm, settings
                   ) -> Question | None
```

### 11.1 `run` algorithm

```
doc     = ingest(source)                                  # §5
chunks  = allocate(chunk(doc), cfg.num_questions)         # §6
kept    = []
for c in chunks where c.quota > 0:
    plan  = type_plan_for(c)  ;  k = ceil(c.quota * overgen_factor)
    cands = generate_for_chunk(llm, c, plan[:k], cfg, avoid=stems(kept))
    good, bad = partition(cands, check_question)
    good, dups = dedupe(good, existing=kept)
    if bad or len(good) < c.quota:                       # retry ONCE per chunk
        m     = c.quota - len(good)
        cands2 = generate_for_chunk(..., plan[:m], feedback=reasons(bad))
        good2, bad2 = partition(cands2, check_question)
        good2, dups2 = dedupe(good2, existing=kept + good)
        good += good2 ; report.dropped += len(bad2) + len(dups2)
    kept += good[:c.quota]                                # trim over-generation
    on_progress(...)
if len(kept) < cfg.num_questions:
    top-up pass: one extra call on the largest chunks that still have
    unused material (bounded: max 2 calls), validated the same way
kept = dedupe(kept)[0][:cfg.num_questions]
return Test(cfg, None, kept), report
```

- **Bounded cost:** at most `2 × batches + 2` LLM calls. The "retry once, then drop" rule from the PRD applies per chunk.
- **Fault isolation:** an exception in one chunk is logged, counted as `chunk_error`, and the run continues with the next chunk.
- The result can have fewer questions than requested. The UI then shows *"Kept 12 of 15 — 3 dropped (2 source not found, 1 duplicate)"*.

### 11.2 `regenerate_one`

- Uses the same chunk, type and difficulty, with `avoid` set to all current stems.
- Makes up to 2 attempts and validates and dedupes each one.
- On success, returns a question with `status="regenerated"`. Otherwise returns `None`, and the UI keeps the old question and shows a toast.

## 12. Streamlit UI (`app.py`)

### 12.1 Session state

| Key | Type | Purpose |
|---|---|---|
| `doc` | `SourceDocument \| None` | Extracted chapter |
| `chunks` | `dict[str, Chunk]` | Needed for regenerating a question and for the source line |
| `test` | `Test \| None` | Current questions |
| `report` | `GenerationReport \| None` | Kept/dropped banner |
| `reviewed` | `bool` | Export is enabled only after the review section has been rendered and the teacher ticks "I have reviewed all questions" |
| `health` | `HealthStatus` | Shown in the sidebar |

### 12.2 Layout

```
Sidebar:  Institute profile (name, name_hi, default time/marks) · Model status ●
          (green: ready / red: "Start Ollama" / amber: "Model not pulled: run ollama pull gemma3:4b")

1  Chapter        [Tabs: PDF | Photo(s) | Paste text]  → "Extracted 4 pages, 6 chunks" + preview expander
2  Settings       Questions [slider 5–50, default 10] · Types [multiselect] · Difficulty [radio]
                  Language [radio: Hindi | English | Bilingual] · Exam style [select] (P1)
                  [Generate]  → st.progress + status text per chunk
3  Review         Banner: Kept X of Y.  For each question: card with
                  stem (en/hi), options with ✓ on answer, explanation, source line, ⚠ warnings
                  [Edit] → inline form (stems, options, answer radio, explanation)
                  [Delete]  [Regenerate]
                  ☐ I have reviewed all questions
4  Export         Title · Date · Time (min) · Marks/question · Sets: [A only | A+B] (P1)
                  [Create PDFs] → download buttons: Student paper, Answer key (per set)
                  [Save to question bank] (P1)
```

- Generation runs on the main script thread inside `st.status`, and `on_progress` updates the progress bar. Settings widgets are disabled during a run (`st.session_state.running`).
- An edit sets `status="edited"` and runs `check_question` again. Hard failures show as a red warning but **do not block** the edit, because the teacher has the final say.
- The UI sets `client.toolbarMode="minimal"` and `browser.gatherUsageStats=false` in `.streamlit/config.toml` so no network calls are made.

## 13. Export (`ctg/export/pdf.py`)

```python
def render_paper(test: Test, meta: PaperMeta) -> bytes
def render_key(test: Test, meta: PaperMeta, chunks: dict[str, Chunk]) -> bytes
def save(outputs_dir, meta, files: dict[str, bytes]) -> Path
```

- **Engine:** Jinja2, then `weasyprint.HTML(string=..., base_url=assets).write_pdf()`. WeasyPrint shapes text with HarfBuzz through Pango, so Devanagari conjuncts and matras render correctly. Fonts are loaded with local `@font-face` (`NotoSans`, `NotoSansDevanagari`), and `font-family: "Noto Sans", "Noto Sans Devanagari"` lets each script fall back per glyph.
- **Page setup:** A4, `@page { margin: 16mm 14mm; @bottom-center { content: "Page " counter(page) " / " counter(pages) } }`.
- **Paper header:** institute name (en/hi), test title, date, time, maximum marks (`N × marks_per_q`), set label, and a "Name / Roll no." line. Instructions are in the chosen language(s).
- **Question rendering:**
  - Numbers are `1.` … `N.`.
  - Option labels are `(a)–(d)` for English, `(क)–(घ)` for Hindi, and `(a)/(क)` in bilingual mode.
  - In bilingual mode the English stem comes first and the Hindi stem goes on the next line in the same block. Options sit in a 2-column grid, each `en / hi`.
  - `break-inside: avoid` on each question.
  - True/False shows "True / False (सही / गलत)". Fill-blank shows the stem with its blank. Short answer adds 3 ruled lines.
- **Answer key:** a table with Q#, answer label + text, explanation and **source line** (the `source_quote` in italics, with the chunk heading if there is one). It uses the same header and adds "ANSWER KEY — Set A".
- **Files:** `outputs/2026-10-18_polity-ch3/paper_A.pdf`, `key_A.pdf`, …

**Fallback:** if WeasyPrint cannot be imported (missing GTK on Windows), `pdf.py` tries `playwright` Chromium `page.pdf()` with the same HTML. If neither works, the app offers the HTML file for the teacher to print from a browser.

## 14. Set shuffler (`ctg/shuffle.py`, P1)

```python
def make_set(test: Test, label: str, seed: int) -> Test
```

- `rng = random.Random(f"{seed}-{label}")`. Set A is the original order. Set B gets a new order.
- Questions are shuffled with `rng.shuffle`.
- MCQ options get a permutation `p` that is applied **the same way to the `en` and `hi` options**, then `answer_index = p.index(old_answer_index)`. True/False options are never shuffled.
- Property tests check that, for every question, the answer text is unchanged across sets and the bilingual answer letters still match.

## 15. Question bank (`ctg/bank.py`, P1)

```sql
CREATE TABLE chapter (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT,
  content_hash TEXT UNIQUE NOT NULL,          -- sha256 of normalised text
  created_at TEXT NOT NULL
);
CREATE TABLE question (
  id TEXT PRIMARY KEY, chapter_id INTEGER NOT NULL REFERENCES chapter(id),
  qtype TEXT NOT NULL, difficulty TEXT NOT NULL,
  payload_json TEXT NOT NULL,                 -- Question.model_dump_json()
  times_used INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX idx_q_chapter ON question(chapter_id, qtype, difficulty);
```

- Chapter text itself is **not** stored, only its hash and the questions. This avoids keeping copyrighted material.
- API: `save_test(test, title, subject)`, `list_chapters()`, `load(chapter_id, filters) -> list[Question]`, `mark_used(qids)`.
- When the same chapter (same hash) is uploaded again, the UI offers "Use N saved questions".

## 16. Error handling

| Error | Where raised | User-facing message |
|---|---|---|
| `LLMUnavailable` | llm | "Gemma is not running. Open a terminal and run `ollama serve`." |
| `ModelMissing` | llm.health | "Model not installed. Run `ollama pull gemma3:4b` (one-time, ~3 GB)." |
| `NoVisionModel` | ingest | "Photo reading needs a vision model such as gemma3:4b." |
| `LLMTimeout` | llm | Chunk skipped, counted in report. "Some parts took too long; try fewer questions." |
| `IngestError` | ingest | "Could not read this file/photo. Try a clearer photo or paste the text." |
| `TooLarge` | ingest | "Please upload up to 30 pages / 10 photos at a time." |
| `ExportError` | export | "PDF creation failed; download the HTML version and print from your browser." |

**Logging:** `logs/ctg.log`, rotating, INFO level. Logs hold counts, timings and failure **codes** only, never chapter text or question content (privacy).

## 17. Performance budget (default: 10 bilingual MCQs, CPU laptop)

| Step | Calls | Notes |
|---|---|---|
| Model warm-up | 1 | Fired on app start with `keep_alive=30m` so the first run isn't cold |
| Extract (text PDF) | 0 | Under 1 s |
| OCR (per photo) | 1 / page | Slowest path. Advise text PDFs or pasted text where possible. |
| Generate | ⌈13 / 5⌉ ≈ 3–4 | ~5 questions per call. Bilingual output roughly doubles the tokens. |
| Retry | 0–3 | Only for chunks with failures |
| Check, dedupe, export | 0 | Under 2 s total |

`scripts/bench.py` runs the sample chapter end to end and prints seconds per call and tokens per second, so the default question count can be set to fit the 5-minute goal on the first user's laptop. If the run is too slow: lower the default to 10 questions, use `text_model` (e.g. `gemma3:1b`) for text-only inputs, and cap `num_predict`.

## 18. Testing

| Test | What it covers |
|---|---|
| `test_textutil` | NFC, ZWJ removal, danda mapping, script detection on en/hi/mixed samples |
| `test_chunker` | Heading splits, max-size split at `।`, tiny-tail merge, quota sums to N, N < chunks |
| `test_validate` | One fixture per hard-check code (pass and fail), Hindi quote fuzzy match, AOTA list, dedupe threshold |
| `test_pipeline` | `FakeLLMClient`: happy path, retry-then-pass, retry-then-drop, bad JSON batch, chunk exception isolation, report counts |
| `test_shuffle` | Property test (hypothesis): answer text is the same across sets and en/hi answer letters match |
| `test_export` | Renders a Hindi fixture with conjuncts (क्ष, त्र, ज्ञ, श्र, द्ध) and matras; checks that the PDF embeds NotoSansDevanagari (pypdf font list) and saves a PNG snapshot for a manual look |
| Manual / first user | 10-question bilingual test on the teacher's chapter. Record time, keep/edit/wrong per question, and the answers to the pricing questions. |

## 19. Requirements (`requirements.txt`)

```
streamlit>=1.38
pydantic>=2.7
pydantic-settings>=2.3
ollama>=0.4            # or httpx
pypdf>=4.2
pypdfium2>=4.30
Pillow>=10.3
rapidfuzz>=3.9
Jinja2>=3.1
weasyprint>=62
pytest>=8 ; extra == "dev"
hypothesis>=6 ; extra == "dev"
```

## 20. Traceability (PRD → design)

| PRD item | Design section |
|---|---|
| F1 upload PDF / text / photo | §5 |
| F2 count, types, difficulty | §3 `TestConfig`, §6 type plan, §7 |
| F3 language | §3 `OutputMode`, §7.2, §8 |
| F4 options, answer, explanation, source | §3 `Question`, §8 |
| F5 review, edit, delete, regenerate | §11.2, §12 |
| F6 two PDFs | §13 |
| F7 exam presets | §7.4 |
| F8 Set A / B | §14 |
| F9 question bank | §15 |
| F10 Word / WhatsApp | `export/text.py` (P2, not designed further) |
| Quality rules 1–5 | §7.1 |
| Code checks | §10 |
| Human in the loop | §12.1 `reviewed` gate, source line in the key §13 |
| Risks | HLD §11, §16, §17 |
