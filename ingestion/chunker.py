from __future__ import annotations

import re

from app.types import ChunkDraft, Paragraph
from retrieval.tokenizer import approximate_token_count


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\.])\s*|\n+")


def chunk_paragraphs(
    paragraphs: list[Paragraph],
    *,
    chunk_size: int = 320,
    overlap: int = 60,
) -> list[ChunkDraft]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")

    units: list[tuple[str, str | None, int | None]] = []
    for paragraph in paragraphs:
        sentences = [part.strip() for part in SENTENCE_BOUNDARY.split(paragraph.text) if part.strip()]
        if not sentences:
            continue
        for sentence in sentences:
            if approximate_token_count(sentence) <= chunk_size:
                units.append((sentence, paragraph.heading, paragraph.page_number))
                continue
            units.extend(_split_long_unit(sentence, paragraph.heading, paragraph.page_number, chunk_size))

    chunks: list[ChunkDraft] = []
    buffer: list[tuple[str, str | None, int | None]] = []
    buffer_tokens = 0
    for unit in units:
        unit_tokens = approximate_token_count(unit[0])
        # A heading is a semantic boundary. Carrying overlap across sections can
        # join unrelated policies (for example leave approval and emergency
        # procurement) into one vector, which then produces misleading
        # citations and extractive answers.
        if buffer and unit[1] != buffer[-1][1]:
            chunks.append(_build_chunk(buffer))
            buffer = []
            buffer_tokens = 0
        if buffer and buffer_tokens + unit_tokens > chunk_size:
            chunks.append(_build_chunk(buffer))
            buffer = _overlap_suffix(buffer, overlap)
            buffer_tokens = sum(approximate_token_count(item[0]) for item in buffer)
            while buffer and buffer_tokens + unit_tokens > chunk_size:
                removed = buffer.pop(0)
                buffer_tokens -= approximate_token_count(removed[0])
        buffer.append(unit)
        buffer_tokens += unit_tokens

    if buffer:
        candidate = _build_chunk(buffer)
        if not chunks or candidate.content != chunks[-1].content:
            chunks.append(candidate)
    return chunks


def _split_long_unit(
    text: str,
    heading: str | None,
    page_number: int | None,
    chunk_size: int,
) -> list[tuple[str, str | None, int | None]]:
    # Character windows are only a fallback for unusually long, punctuation-free text.
    width = max(120, chunk_size * 2)
    return [(text[start : start + width], heading, page_number) for start in range(0, len(text), width)]


def _overlap_suffix(
    units: list[tuple[str, str | None, int | None]], overlap: int
) -> list[tuple[str, str | None, int | None]]:
    if overlap == 0:
        return []
    selected: list[tuple[str, str | None, int | None]] = []
    token_total = 0
    for unit in reversed(units):
        selected.append(unit)
        token_total += approximate_token_count(unit[0])
        if token_total >= overlap:
            break
    return list(reversed(selected))


def _build_chunk(units: list[tuple[str, str | None, int | None]]) -> ChunkDraft:
    content = "\n".join(unit[0] for unit in units).strip()
    heading = next((unit[1] for unit in units if unit[1]), None)
    page_number = next((unit[2] for unit in units if unit[2] is not None), None)
    return ChunkDraft(
        content=content,
        heading=heading,
        page_number=page_number,
        token_count=approximate_token_count(content),
    )
