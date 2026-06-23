from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List

from .llm_client import OpenAICompatibleClient
from .pdf_loader import PaperChunk
from .retriever import context_text
from .schema import CultivarCandidate, NA


COUNTRIES = (
    "Kenya",
    "Ethiopia",
    "Tanzania",
    "Uganda",
    "Rwanda",
    "Malawi",
    "Zambia",
    "Zimbabwe",
    "South Africa",
)

COMMON_NON_CULTIVARS = {
    "DSSAT",
    "CERES",
    "MAIZE",
    "CROP",
    "TABLE",
    "FIGURE",
    "YIELD",
    "MODEL",
    "ANOVA",
    "PHINT",
}


def discover_cultivars(chunks: Iterable[PaperChunk], llm: OpenAICompatibleClient) -> List[CultivarCandidate]:
    chunks_by_source: Dict[str, List[PaperChunk]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_source[chunk.source_file].append(chunk)

    candidates: List[CultivarCandidate] = []
    for source_file, source_chunks in chunks_by_source.items():
        if llm.configured:
            candidates.extend(_discover_with_llm(source_file, source_chunks, llm))
        else:
            candidates.extend(_discover_with_heuristics(source_file, source_chunks))

    return _dedupe(candidates)


def _discover_with_llm(
    source_file: str,
    chunks: List[PaperChunk],
    llm: OpenAICompatibleClient,
) -> List[CultivarCandidate]:
    paper_context = context_text(chunks[:18], max_chars=18000)
    response = llm.chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You extract cultivar worklists from agricultural research papers. "
                    "Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "From the paper context below, list every named crop cultivar, hybrid, "
                    "or variety actually discussed. Do not infer names. Return JSON with a "
                    "`cultivars` array. Each item must have cultivar_name, crop, country, "
                    "and location. Use MZ for maize crop when applicable and NA when the "
                    "paper does not state a value.\n\n"
                    f"Paper: {source_file}\n\n{paper_context}"
                ),
            },
        ]
    )
    return [
        CultivarCandidate(
            cultivar_name=str(item.get("cultivar_name", "")).strip(),
            crop=str(item.get("crop") or NA).strip(),
            country=str(item.get("country") or NA).strip(),
            location=str(item.get("location") or NA).strip(),
            source_file=source_file,
        )
        for item in response.get("cultivars", [])
        if str(item.get("cultivar_name", "")).strip()
    ]


def _discover_with_heuristics(source_file: str, chunks: List[PaperChunk]) -> List[CultivarCandidate]:
    joined = "\n".join(chunk.text for chunk in chunks[:30])
    country = next((name for name in COUNTRIES if re.search(rf"\b{name}\b", joined, re.I)), NA)
    crop = "MZ" if re.search(r"\b(maize|zea mays)\b", joined, re.I) else NA

    names = set()
    patterns = [
        r"\bH\s?\d{3}\b",
        r"\bBH\s?-?\s?\d{3}\b",
        r"\bKH\s?\d{3}-?\d{2}[A-Z]?\b",
        r"\bSC\s?-?\s?\d{3}\b",
        r"\bDKC\s?-?\s?\d{2,4}(?:-\d+)?\b",
        r"\bMelkassa\s+[IVX0-9]+\b",
        r"\bKatumani\b",
        r"\bSituka\b",
        r"\bMH\s?-?\s?\d{2}\b",
    ]
    for pattern in patterns:
        names.update(match.group(0).strip() for match in re.finditer(pattern, joined, re.I))

    return [
        CultivarCandidate(_normalize_name(name), crop=crop, country=country, location=NA, source_file=source_file)
        for name in names
        if name.upper() not in COMMON_NON_CULTIVARS
    ]


def _dedupe(candidates: List[CultivarCandidate]) -> List[CultivarCandidate]:
    seen = set()
    unique = []
    for candidate in candidates:
        name = _normalize_name(candidate.cultivar_name)
        key = (candidate.source_file, name.upper())
        if not name or key in seen:
            continue
        seen.add(key)
        candidate.cultivar_name = name
        unique.append(candidate)
    return unique


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace(" - ", "-").strip())
