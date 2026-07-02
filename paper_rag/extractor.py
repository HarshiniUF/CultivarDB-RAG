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
    normalize_location_contexts,
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
        cultivar_chunks = retriever.search(query, source_file=candidate.source_file, top_k=10)
        coefficient_chunks = retriever.search(
            (
                f"{candidate.cultivar_name} cultivar genetic coefficients calibrated parameters "
                "DSSAT CERES-Maize Table P1 P2 P5 G2 G3 PHINT"
            ),
            source_file=candidate.source_file,
            top_k=30,
        )
        density_chunks = retriever.search(
            (
                "sowing density planting density plant population plants per hectare "
                "intra-row inter-row spacing row spacing plant spacing between plants between rows "
                "50,000 53,333 53,000 25 cm 75 cm"
            ),
            source_file=candidate.source_file,
            top_k=14,
        )
        context_chunks = retriever.search(
            (
                "study area location region county counties site sites agroecological zone "
                "AEZ I AEZ II AEZ III AEZ IV humid subhumid semihumid semiarid Trans Nzoia "
                "Uasin Gishu Katuke Sabwani Olngatongo latitude longitude elevation rainfall "
                "soil sowing dates planting density plant population row spacing plant spacing "
                "sowing density fertilizer nitrogen yield increase eastern western northern southern "
                "northwestern disease pest drought stress heat rainfall temperature precipitation "
                "climate soil fertility maturity phenology anthesis silking"
            ),
            source_file=candidate.source_file,
            top_k=28,
        )
        chunks = _merge_chunks(
            cultivar_chunks,
            coefficient_chunks,
            density_chunks,
            context_chunks,
            _supporting_page_chunks(
                candidate.source_file,
                cultivar_chunks + coefficient_chunks + density_chunks + context_chunks,
                retriever,
            ),
        )
        if llm.configured:
            raw = _extract_with_llm(candidate, chunks, llm)
        else:
            raw = _extract_with_heuristics(candidate, chunks)
        record = normalize_record(raw, candidate)
        _enrich_record_from_context(record, chunks)
        records.append(record)
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
            "location_contexts": [
                {
                    "location_name": "NA",
                    "location_type": "county|site|region|agro_ecological_zone|country|study_area",
                    "agro_ecological_zone": "NA",
                    "season": "NA",
                    "management_context": "NA",
                    "relation_scope": "cultivar_specific|trial_site|season_specific|study_area",
                    "evidence": "NA",
                    "source_url": f"input_papers/{candidate.source_file}#page=<page>",
                    "confidence": "low|medium|high",
                }
            ],
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
                    "Important extraction rules:\n"
                    "- The retrieved context includes cultivar-specific chunks, study-area "
                    "chunks, coefficient chunks, and management chunks. Use all of them and "
                    "reason over relationships across chunks.\n"
                    "- Fill `location` as a concise readable summary, but put the precise "
                    "cultivar-location-season relationships in `characteristics.location_contexts`.\n"
                    "- Create one `location_contexts` item for each named county, trial site, "
                    "region, AEZ, or season that is tied to the cultivar. If the paper only "
                    "states that all cultivars were evaluated across the full study area, use "
                    "`relation_scope: study_area` instead of pretending the location is "
                    "cultivar-specific.\n"
                    "- When a relationship is location -> season -> cultivar, preserve that "
                    "chain in the same `location_contexts` item with the season/window and "
                    "management context.\n"
                    "- Include short evidence text for every location_context and use a page "
                    "number in source_url when the header supplies one.\n"
                    "- Fill `agro_ecological_zone` with every AEZ mentioned for the study, "
                    "including labels/classifications such as AEZ I humid, AEZ II subhumid, "
                    "AEZ III semihumid, and any excluded AEZs if stated.\n"
                    "- Fill `major_crop_areas` with named counties, sites, and regional areas "
                    "where maize/cultivar results are discussed, including directional subregions "
                    "such as eastern, western, northern, southern, or northwestern areas.\n"
                    "- Fill `planting_density` when the context gives plant population, row spacing, "
                    "plant spacing, or density. Preserve both spacing and population if both are stated.\n"
                    "- Fill `normal_planting_window` with all sowing dates/windows and AEZ-specific "
                    "timing differences when stated.\n"
                    "- Fill `average_yield_kg_ha` with cultivar/AEZ-specific yield values and keep "
                    "the AEZ label next to each value when multiple values are stated.\n"
                    "- Put region-specific findings, optimal sowing regions, yield differences, "
                    "soil/weather constraints, fertilizer/nitrogen recommendations, disease/pest "
                    "or drought/heat stress details, and management details in `adaptation_notes` "
                    "when no more specific field exists.\n"
                    "- Use `NA` only after checking the full retrieved context, not only the "
                    "chunk containing the cultivar name.\n\n"
                    f"Required shape:\n{json.dumps(prompt_schema, indent=2)}\n\n"
                    f"Retrieved context:\n{context_text(chunks, max_chars=24000)}"
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
    target_name = _compact_name(cultivar_name)
    chunks_by_page: Dict[tuple[str, int], List[PaperChunk]] = {}
    for chunk in chunks:
        chunks_by_page.setdefault((chunk.source_file, chunk.page), []).append(chunk)

    for (_, page), page_chunks in chunks_by_page.items():
        page_text = "\n".join(chunk.text for chunk in sorted(page_chunks, key=_chunk_order_key))
        if not all(field in page_text for field in COEFFICIENT_FIELDS):
            continue
        colon_style = _extract_colon_style_coefficients(page_text)
        if colon_style and target_name in _compact_name(page_text):
            return {"page": page, "coefficients": colon_style}

        lines = page_text.splitlines()
        for index, line in enumerate(lines):
            if _compact_name(line) != target_name:
                continue
            following_numbers = []
            for next_line in lines[index + 1 :]:
                next_upper = next_line.upper().strip()
                if following_numbers and _looks_like_cultivar_label(next_upper):
                    break
                stripped = next_line.strip()
                if re.fullmatch(r"-?\d+(?:\.\d+)?", stripped):
                    following_numbers.append(float(stripped))
                elif following_numbers:
                    break
                if len(following_numbers) >= len(COEFFICIENT_FIELDS):
                    return {
                        "page": page,
                        "coefficients": dict(zip(COEFFICIENT_FIELDS, following_numbers[: len(COEFFICIENT_FIELDS)])),
                    }
    return None


def _extract_colon_style_coefficients(text: str) -> Dict[str, float] | None:
    coefficients: Dict[str, float] = {}
    for index, field in enumerate(COEFFICIENT_FIELDS):
        next_fields = "|".join(COEFFICIENT_FIELDS[index + 1 :])
        end_pattern = rf"\n(?:{next_fields})\s*:" if next_fields else r"\nTable|\Z"
        match = re.search(rf"\b{field}\s*:(.*?)(?={end_pattern})", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        numbers = [float(value) for value in re.findall(r"(?<![A-Za-z])-?\d+(?:\.\d+)?", match.group(1))]
        if not numbers:
            return None
        coefficients[field] = numbers[-1]
    return coefficients


def _enrich_record_from_context(record: CultivarRecord, chunks: List[PaperChunk]) -> None:
    context = "\n".join(chunk.text for chunk in chunks)
    normalized_context = re.sub(r"-\s*\n\s*", "", context)
    normalized_context = re.sub(r"\s+", " ", normalized_context)
    data = record.characteristics.setdefault("data", {})

    if data.get("planting_density") in (None, "", "NA"):
        density_parts = []
        spacing = _first_match(
            r"(?:sowing|plant|maize)?\s*spacing\s+of\s+([0-9]+\s*[×x]\s*[0-9]+\s*cm)",
            normalized_context,
        )
        between_spacing = _first_match(
            r"([0-9]+\s*cm\s+between\s+plants\s+and\s+[0-9]+\s*cm\s+between\s+rows)",
            normalized_context,
        )
        population = _first_match(
            r"(?:population\s+of|yielding\s+an\s+approximate\s+population\s+of)\s+"
            r"([0-9,]+\s*plants\s*ha(?:−1|-1)?)",
            normalized_context,
        )
        density = _first_match(
            r"(?:planting|sowing)\s+density(?:\s+for\s+[^.]{0,80}?)?\s+"
            r"(?:was\s+|of\s+|to\s+be\s+|was\s+approximated\s+to\s+be\s+)?"
            r"([0-9,]+\s*plants\s*(?:per\s+hectare|ha(?:−1|-1)?))",
            normalized_context,
        )
        compact_population = _first_match(
            r"Plant\s+pop\.\s+([0-9,]+)",
            normalized_context,
        )
        if spacing:
            density_parts.append(f"spacing {spacing}")
        elif between_spacing:
            density_parts.append(between_spacing)
        if population:
            density_parts.append(population)
        elif density:
            density_parts.append(density)
        elif compact_population:
            density_parts.append(f"{compact_population} plants per hectare")
        if density_parts:
            data["planting_density"] = "; ".join(density_parts)

    if data.get("normal_planting_window") in (None, "", "NA"):
        planting_window = _first_sentence(
            normalized_context,
            (
                "planting window",
                "planting time",
                "sowing dates",
                "sowing varied",
                "15-30",
                "15–30",
                "1-15",
                "1–15",
            ),
        )
        if planting_window:
            data["normal_planting_window"] = planting_window

    note_candidates = [
        _first_sentence(normalized_context, ("fertilizer", "fertilisation", "fertilization", "nitrogen", "kg n")),
        _first_sentence(normalized_context, ("soil", "rainfall", "temperature", "precipitation", "climate")),
        _first_sentence(normalized_context, ("disease", "pest", "drought", "heat stress", "water stress", "low nitrogen")),
        _first_sentence(normalized_context, ("maturity", "anthesis", "silking", "phenology", "heat units", "duration")),
    ]
    _append_notes(data, [candidate for candidate in note_candidates if candidate])

    extracted = _extract_coefficients(record.cultivar_name, chunks)
    if extracted:
        record.coefficients["found"] = True
        record.coefficients["coefficients"] = extracted["coefficients"]
        record.coefficients["source_url"] = (
            f"input_papers/{chunks[0].source_file}#page={extracted['page']}"
        )
        record.coefficients["notes"] = "Extracted from a paper-reported DSSAT coefficient table."
    record.characteristics["location_contexts"] = normalize_location_contexts(record)


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _first_sentence(text: str, terms: tuple[str, ...]) -> str | None:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        lowered = sentence.lower()
        if any(term.lower() in lowered for term in terms):
            clean = sentence.strip()
            if 40 <= len(clean) <= 450:
                return clean
    return None


def _append_notes(data: Dict, notes: List[str]) -> None:
    current = data.get("adaptation_notes")
    note_parts = [] if current in (None, "", "NA") else [str(current).strip()]
    seen = {part.lower() for part in note_parts}
    for note in notes:
        clean = note.strip()
        if not clean or clean.lower() in seen:
            continue
        note_parts.append(clean)
        seen.add(clean.lower())
    if note_parts:
        data["adaptation_notes"] = " ".join(note_parts)


def _compact_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _looks_like_cultivar_label(value: str) -> bool:
    compact = _compact_name(value)
    return bool(re.fullmatch(r"[A-Z]{1,4}\d{2,4}[A-Z]?", compact))


def _chunk_order_key(chunk: PaperChunk) -> tuple[int, int, int]:
    match = re.search(r":p(\d+):b(\d+):s(\d+)$", chunk.chunk_id)
    if not match:
        return (chunk.page, 0, 0)
    return tuple(int(part) for part in match.groups())


def _merge_chunks(*chunk_groups: List[PaperChunk]) -> List[PaperChunk]:
    seen = set()
    merged: List[PaperChunk] = []
    for chunks in chunk_groups:
        for chunk in chunks:
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            merged.append(chunk)
    return merged


def _supporting_page_chunks(
    source_file: str,
    chunks: List[PaperChunk],
    retriever: KeywordRetriever,
) -> List[PaperChunk]:
    pages = {
        chunk.page
        for chunk in chunks
        if _has_coefficient_signal(chunk.text) or _has_management_signal(chunk.text)
    }
    expanded: List[PaperChunk] = []
    for page in sorted(pages):
        expanded.extend(retriever.chunks_for_page(source_file, page))
    return expanded


def _has_coefficient_signal(text: str) -> bool:
    return any(field in text for field in COEFFICIENT_FIELDS) or "Cultivar-specific parameters" in text


def _has_management_signal(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "planting density",
            "sowing density",
            "row spacing",
            "spacing of",
            "between plants",
            "between rows",
            "plants per hectare",
            "plant population",
            "sowing spacing",
        )
    )
