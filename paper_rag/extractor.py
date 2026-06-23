from __future__ import annotations

import json
import re
from typing import Dict, List

from .llm_client import OpenAICompatibleClient
from .pdf_loader import PaperChunk
from .retriever import KeywordRetriever, context_text
from .schema import (
    COEFFICIENT_FIELDS,
    CultivarCandidate,
    CultivarRecord,
    default_characteristics,
    default_coefficients,
    normalize_record,
)


def extract_records(
    candidates: List[CultivarCandidate],
    retriever: KeywordRetriever,
    llm: OpenAICompatibleClient,
) -> List[CultivarRecord]:
    records = []
    for candidate in candidates:
        query = (
            f"{candidate.cultivar_name} cultivar variety hybrid DSSAT CERES "
            "P1 P2 P5 G2 G3 PHINT maturity yield disease drought"
        )
        chunks = retriever.search(query, source_file=candidate.source_file, top_k=10)
        if llm.configured:
            raw = _extract_with_llm(candidate, chunks, llm)
        else:
            raw = _extract_with_heuristics(candidate, chunks)
        records.append(normalize_record(raw, candidate))
    return records


def _extract_with_llm(
    candidate: CultivarCandidate,
    chunks: List[PaperChunk],
    llm: OpenAICompatibleClient,
) -> Dict:
    prompt_schema = {
        "cultivar_name": candidate.cultivar_name,
        "crop": candidate.crop,
        "country": candidate.country,
        "location": candidate.location,
        "characteristics": {
            "data": {
                "maturity_class": "NA",
                "relative_maturity": "NA",
                "days_to_maturity": "NA",
                "average_yield_kg_ha": "NA",
                "plant_height_cm": "NA",
                "growth_habit": "NA",
                "disease_resistance": [],
                "stress_tolerance": {"drought": "NA", "heat": "NA"},
                "growing_degree_days": "NA",
                "agro_ecological_zone": "NA",
                "adaptation_notes": "NA",
                "normal_planting_window": "NA",
                "planting_density": "NA",
                "harvest_time": "NA",
                "season_suitability": "NA",
                "major_crop_areas": "NA",
            },
            "source": candidate.source_file,
            "source_url": f"input_papers/{candidate.source_file}#page=<page>",
            "confidence": "low|medium|high",
        },
        "coefficients": {
            "found": False,
            "source": f"RAG: {candidate.source_file}",
            "source_url": f"input_papers/{candidate.source_file}#page=<page>",
            "coefficients": {"P1": None, "P2": None, "P5": None, "G2": None, "G3": None, "PHINT": None},
            "notes": "",
        },
    }
    return llm.chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You extract structured cultivar records from retrieved paper chunks. "
                    "Use only the provided context. Never guess missing fields; write NA. "
                    "Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Extract the record for cultivar `{candidate.cultivar_name}` from "
                    f"`{candidate.source_file}`. Preserve the JSON shape below. Coefficients "
                    "must be paper-reported DSSAT genotype coefficients only. Include page "
                    "numbers in source_url when supported by the context headers.\n\n"
                    f"Required shape:\n{json.dumps(prompt_schema, indent=2)}\n\n"
                    f"Retrieved context:\n{context_text(chunks)}"
                ),
            },
        ]
    )


def _extract_with_heuristics(candidate: CultivarCandidate, chunks: List[PaperChunk]) -> Dict:
    page = chunks[0].page if chunks else None
    characteristics = default_characteristics(candidate.source_file, page)
    coefficients = default_coefficients(candidate.source_file, page)
    extracted = _extract_coefficients(candidate.cultivar_name, chunks)
    if extracted:
        coefficients["found"] = True
        coefficients["coefficients"] = extracted["coefficients"]
        coefficients["source_url"] = f"input_papers/{candidate.source_file}#page={extracted['page']}"
        coefficients["notes"] = "Extracted by table-pattern matching; verify against the source paper."

    return {
        "cultivar_name": candidate.cultivar_name,
        "crop": candidate.crop,
        "country": candidate.country,
        "location": candidate.location,
        "characteristics": characteristics,
        "coefficients": coefficients,
    }


def _extract_coefficients(cultivar_name: str, chunks: List[PaperChunk]) -> Dict | None:
    name_terms = [term for term in re.split(r"[\s-]+", cultivar_name.upper()) if term]
    for chunk in chunks:
        lines = chunk.text.splitlines()
        for index, line in enumerate(lines):
            upper = line.upper()
            if not all(term in upper for term in name_terms):
                continue
            window = " ".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
            numbers = [float(value) for value in re.findall(r"(?<![A-Za-z])-?\d+(?:\.\d+)?", window)]
            if len(numbers) < len(COEFFICIENT_FIELDS):
                continue
            # Prefer the final six numbers because cultivar names often contain digits.
            values = numbers[-len(COEFFICIENT_FIELDS) :]
            return {
                "page": chunk.page,
                "coefficients": dict(zip(COEFFICIENT_FIELDS, values)),
            }
    return None
