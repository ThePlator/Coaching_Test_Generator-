"""SourceDocument → topic-sized chunks, and spreading questions across them (LLD §6)."""

from __future__ import annotations

import math
from itertools import cycle, islice

from ctg.models import Chunk, QType, SourceDocument
from ctg.textutil import SENTENCE_SPLIT, detect_script, is_heading

MIN_TAIL = 300            # a last chunk shorter than this is merged into the previous one
HEADING_BREAK_SHARE = 0.4  # a heading starts a new chunk once the current one is this full


def chunk(doc: SourceDocument, target: int = 1500, max_: int = 2200) -> list[Chunk]:
    ocr = set(doc.ocr_pages)
    pieces: list[tuple[str, int]] = []           # (text, page index)
    for page_no, page in enumerate(doc.pages):
        for block in (b.strip() for b in page.split("\n\n")):
            if block:
                pieces += [(p, page_no) for p in _split_long(block, max_)]

    groups: list[dict] = []
    cur: dict = _new_group()

    def flush() -> None:
        nonlocal cur
        if cur["parts"]:
            groups.append(cur)
        cur = _new_group()

    for text, page_no in pieces:
        heading = is_heading(text)
        if heading and cur["size"] >= HEADING_BREAK_SHARE * target:
            flush()
        elif cur["size"] and cur["size"] + len(text) + 2 > max_:
            flush()
        if heading and not cur["parts"]:
            cur["heading"] = text
        cur["parts"].append(text)
        cur["size"] += len(text) + 2
        cur["pages"].add(page_no)
    flush()

    # Merge a tiny tail (or a heading-only last group) into the previous chunk.
    if len(groups) > 1 and groups[-1]["size"] < MIN_TAIL:
        tail = groups.pop()
        groups[-1]["parts"] += tail["parts"]
        groups[-1]["pages"] |= tail["pages"]

    chunks = []
    for i, g in enumerate(groups):
        text = "\n\n".join(g["parts"])
        chunks.append(Chunk(
            id=f"c{i + 1:02d}", index=i, text=text, heading=g["heading"],
            script=detect_script(text), from_ocr=bool(g["pages"] & ocr),
        ))
    return chunks


def allocate(chunks: list[Chunk], n: int) -> list[Chunk]:
    """Return copies of `chunks` with `quota` set so that quotas sum to n."""
    if not chunks:
        return []
    quotas = [0] * len(chunks)
    if n >= len(chunks):
        weights = [len(c.text) for c in chunks]
        total = sum(weights) or 1
        raw = [n * w / total for w in weights]
        quotas = [math.floor(r) for r in raw]
        leftover = n - sum(quotas)
        by_remainder = sorted(range(len(chunks)), key=lambda i: raw[i] - quotas[i], reverse=True)
        for i in by_remainder[:leftover]:
            quotas[i] += 1
    else:
        step = len(chunks) / n
        for k in range(n):
            quotas[min(len(chunks) - 1, math.floor((k + 0.5) * step))] = 1
    return [c.model_copy(update={"quota": q}) for c, q in zip(chunks, quotas)]


def type_plan(chunks: list[Chunk], qtypes: list[QType]) -> dict[str, list[QType]]:
    """Round-robin question types over the whole test, in chunk order."""
    types = cycle(qtypes)
    return {c.id: list(islice(types, c.quota)) for c in chunks}


def expand_plan(plan: list[QType], k: int, fallback: list[QType] | None = None) -> list[QType]:
    """Repeat `plan` cyclically to length k (used for over-generation and retries)."""
    base = plan or fallback or ["mcq"]
    return list(islice(cycle(base), k))


def _new_group() -> dict:
    return {"parts": [], "size": 0, "pages": set(), "heading": None}


def _split_long(block: str, max_: int) -> list[str]:
    if len(block) <= max_:
        return [block]
    out: list[str] = []
    cur = ""
    for sent in SENTENCE_SPLIT.split(block):
        while len(sent) > max_:                     # one huge "sentence": cut on whitespace
            cut = sent.rfind(" ", 0, max_)
            cut = cut if cut > 0 else max_
            if cur:
                out.append(cur)
                cur = ""
            out.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if cur and len(cur) + 1 + len(sent) > max_:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out
