from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class PaperChunk:
    text: str
    source_file: str
    page: int
    chunk_type: str
    chunk_id: str


def load_pdf_chunks(pdf_path: Path, chunk_size: int = 1400, overlap: int = 180) -> List[PaperChunk]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to read PDFs. Install dependencies with "
            "`python -m pip install -r paper_rag/requirements.txt`."
        ) from exc

    chunks: List[PaperChunk] = []
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            page_text = page.get_text("text") or ""
            for block_index, (kind, text) in enumerate(_segment_page(page_text)):
                for split_index, split_text in enumerate(_split_text(text, chunk_size, overlap, kind)):
                    clean = split_text.strip()
                    if not clean:
                        continue
                    chunks.append(
                        PaperChunk(
                            text=clean,
                            source_file=pdf_path.name,
                            page=page_index,
                            chunk_type=kind,
                            chunk_id=f"{pdf_path.name}:p{page_index}:b{block_index}:s{split_index}",
                        )
                    )
    return chunks


def load_many(paths: Iterable[Path]) -> List[PaperChunk]:
    all_chunks: List[PaperChunk] = []
    for path in paths:
        all_chunks.extend(load_pdf_chunks(path))
    return all_chunks


def _segment_page(text: str) -> List[tuple[str, str]]:
    blocks: List[tuple[str, str]] = []
    current: List[str] = []
    current_kind = "prose"

    for line in text.splitlines():
        kind = "table" if _looks_like_table_line(line) else "prose"
        if current and kind != current_kind:
            blocks.append((current_kind, "\n".join(current)))
            current = []
        current_kind = kind
        current.append(line)

    if current:
        blocks.append((current_kind, "\n".join(current)))
    return blocks


def _looks_like_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    tokens = stripped.split()
    numeric_tokens = sum(_is_number(token) for token in tokens)
    coefficient_labels = {"P1", "P2", "P5", "G2", "G3", "PHINT"}
    has_coefficients = any(token.strip("()[],:;") in coefficient_labels for token in tokens)
    return "|" in stripped or "\t" in stripped or (len(tokens) >= 5 and numeric_tokens >= 3) or has_coefficients


def _split_text(text: str, chunk_size: int, overlap: int, kind: str) -> List[str]:
    if kind == "table" or len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        boundary = text.rfind("\n", start, end)
        if boundary <= start + chunk_size // 2:
            boundary = end
        chunks.append(text[start:boundary])
        if boundary == len(text):
            break
        start = max(boundary - overlap, start + 1)
    return chunks


def _is_number(value: str) -> bool:
    try:
        float(value.strip("()[],:;"))
        return True
    except ValueError:
        return False
