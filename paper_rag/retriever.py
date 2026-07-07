from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Sequence

from .pdf_loader import PaperChunk


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")


class KeywordRetriever:
    """Small dependency-free retriever for paper-scoped RAG context."""

    def __init__(self, chunks: Sequence[PaperChunk]):
        self._chunks = list(chunks)
        self._chunk_tokens = [Counter(_tokens(chunk.text)) for chunk in self._chunks]
        document_frequency = Counter()
        for token_counts in self._chunk_tokens:
            document_frequency.update(token_counts.keys())
        total = max(len(self._chunks), 1)
        self._idf = {
            token: math.log((1 + total) / (1 + frequency)) + 1.0
            for token, frequency in document_frequency.items()
        }

    def search(
        self,
        query: str,
        *,
        source_file: str | None = None,
        top_k: int = 8,
    ) -> List[PaperChunk]:
        query_tokens = Counter(_tokens(query))
        scored = []
        for chunk, token_counts in zip(self._chunks, self._chunk_tokens):
            if source_file and chunk.source_file != source_file:
                continue
            score = 0.0
            for token, query_count in query_tokens.items():
                score += query_count * token_counts.get(token, 0) * self._idf.get(token, 1.0)
            if "P1" in chunk.text and "PHINT" in chunk.text:
                score += 4.0
            if chunk.chunk_type == "table":
                score += 1.5
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (item[0], -item[1].page), reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def chunks_for_page(self, source_file: str, page: int) -> List[PaperChunk]:
        return [
            chunk
            for chunk in self._chunks
            if chunk.source_file == source_file and chunk.page == page
        ]


def context_text(chunks: Iterable[PaperChunk], max_chars: int = 14000) -> str:
    parts = []
    used = 0
    for chunk in chunks:
        header = f"[source={chunk.source_file} page={chunk.page} type={chunk.chunk_type}]"
        part = f"{header}\n{chunk.text.strip()}"
        if used + len(part) > max_chars:
            break
        parts.append(part)
        used += len(part)
    return "\n\n---\n\n".join(parts)


def _tokens(text: str) -> List[str]:
    return [token.upper() for token in TOKEN_RE.findall(text)]
