"""Chunk normalized text at ~800 tokens with 120 overlap, keeping the source
line interval and a deterministic ordinal (ADR 3)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\S+")


@dataclass
class TextChunk:
    ordinal: int
    text: str
    line_start: int   # 1-based, inclusive
    line_end: int     # 1-based, inclusive


def _token_count(line: str) -> int:
    return len(_TOKEN.findall(line))


def chunk_text(text: str, target_tokens: int = 800, overlap_tokens: int = 120) -> list[TextChunk]:
    if overlap_tokens >= target_tokens:
        raise ValueError("overlap must be smaller than the chunk size")
    lines = text.split("\n")
    counts = [_token_count(ln) for ln in lines]
    chunks: list[TextChunk] = []
    start = 0
    ordinal = 0
    n = len(lines)
    while start < n:
        total = 0
        end = start
        while end < n and (total + counts[end] <= target_tokens or end == start):
            total += counts[end]
            end += 1
        body = "\n".join(lines[start:end]).strip()
        if body:
            chunks.append(TextChunk(ordinal=ordinal, text=body,
                                    line_start=start + 1, line_end=end))
            ordinal += 1
        if end >= n:
            break
        # Step back far enough to overlap ~overlap_tokens, deterministically.
        back = 0
        cursor = end
        while cursor > start + 1 and back < overlap_tokens:
            cursor -= 1
            back += counts[cursor]
        start = cursor if cursor > start else end
    return chunks
