from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Dict, List


NA = "NA"


CHARACTERISTIC_FIELDS = {
    "maturity_class": NA,
    "relative_maturity": NA,
    "days_to_maturity": NA,
    "average_yield_kg_ha": NA,
    "plant_height_cm": NA,
    "growth_habit": NA,
    "disease_resistance": [],
    "stress_tolerance": {"drought": NA, "heat": NA},
    "growing_degree_days": NA,
    "agro_ecological_zone": NA,
    "adaptation_notes": NA,
    "normal_planting_window": NA,
    "planting_density": NA,
    "harvest_time": NA,
    "season_suitability": NA,
    "major_crop_areas": NA,
}


COEFFICIENT_FIELDS = ("P1", "P2", "P5", "G2", "G3", "PHINT")


@dataclass
class CultivarCandidate:
    cultivar_name: str
    crop: str = NA
    country: str = NA
    location: str = NA
    source_file: str = ""


@dataclass
class CultivarRecord:
    cultivar_name: str
    crop: str = NA
    country: str = NA
    location: str = NA
    characteristics: Dict[str, Any] = field(default_factory=dict)
    coefficients: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cultivar_name": self.cultivar_name,
            "crop": self.crop,
            "country": self.country,
            "location": self.location,
            "characteristics": self.characteristics,
            "coefficients": self.coefficients,
        }


def default_characteristics(source_file: str, page: int | None = None) -> Dict[str, Any]:
    data = {}
    for key, value in CHARACTERISTIC_FIELDS.items():
        if isinstance(value, dict):
            data[key] = dict(value)
        elif isinstance(value, list):
            data[key] = list(value)
        else:
            data[key] = value

    page_suffix = f"#page={page}" if page else ""
    return {
        "data": data,
        "location_contexts": [],
        "source": source_file,
        "source_url": f"input_papers/{source_file}{page_suffix}",
        "confidence": "low",
    }


def default_coefficients(source_file: str, page: int | None = None) -> Dict[str, Any]:
    page_suffix = f"#page={page}" if page else ""
    return {
        "found": False,
        "source": f"RAG: {source_file}",
        "source_url": f"input_papers/{source_file}{page_suffix}",
        "coefficients": {},
        "notes": "No paper-reported DSSAT coefficients were extracted.",
    }


def normalize_record(raw: Dict[str, Any], fallback: CultivarCandidate) -> CultivarRecord:
    characteristics = raw.get("characteristics") or default_characteristics(fallback.source_file)
    characteristics.setdefault("data", {})
    characteristics.setdefault("location_contexts", [])
    for key, default_value in CHARACTERISTIC_FIELDS.items():
        if key not in characteristics["data"]:
            if isinstance(default_value, dict):
                characteristics["data"][key] = dict(default_value)
            elif isinstance(default_value, list):
                characteristics["data"][key] = list(default_value)
            else:
                characteristics["data"][key] = default_value
    characteristics.setdefault("source", fallback.source_file)
    characteristics.setdefault("source_url", f"input_papers/{fallback.source_file}")
    characteristics.setdefault("confidence", "low")

    coefficients = raw.get("coefficients") or default_coefficients(fallback.source_file)
    coefficients.setdefault("found", bool(coefficients.get("coefficients")))
    coefficients.setdefault("source", f"RAG: {fallback.source_file}")
    coefficients.setdefault("source_url", f"input_papers/{fallback.source_file}")
    coefficients.setdefault("coefficients", {})
    coefficients.setdefault("notes", "")

    clean_coefficients = {}
    for key in COEFFICIENT_FIELDS:
        value = coefficients["coefficients"].get(key)
        if value in (None, "", NA):
            continue
        try:
            clean_coefficients[key] = float(value)
        except (TypeError, ValueError):
            continue
    coefficients["coefficients"] = clean_coefficients
    coefficients["found"] = bool(clean_coefficients)

    record = CultivarRecord(
        cultivar_name=str(raw.get("cultivar_name") or fallback.cultivar_name).strip(),
        crop=str(raw.get("crop") or fallback.crop or NA).strip(),
        country=str(raw.get("country") or fallback.country or NA).strip(),
        location=str(raw.get("location") or fallback.location or NA).strip(),
        characteristics=characteristics,
        coefficients=coefficients,
    )
    record.characteristics["location_contexts"] = normalize_location_contexts(record)
    return record


def normalize_location_contexts(record: CultivarRecord) -> List[Dict[str, Any]]:
    raw_contexts = record.characteristics.get("location_contexts")
    contexts = raw_contexts if isinstance(raw_contexts, list) else []
    normalized = []
    seen = set()
    for context in contexts:
        if not isinstance(context, dict):
            continue
        location_name = str(context.get("location_name") or context.get("location") or "").strip()
        if not location_name or location_name == NA:
            continue
        normalized_context = _location_context(
            location_name=location_name,
            location_type=context.get("location_type"),
            agro_ecological_zone=context.get("agro_ecological_zone"),
            season=context.get("season"),
            management_context=context.get("management_context"),
            relation_scope=context.get("relation_scope"),
            evidence=context.get("evidence"),
            source_url=context.get("source_url") or record.characteristics.get("source_url"),
            confidence=context.get("confidence") or record.characteristics.get("confidence"),
        )
        key = _context_key(normalized_context)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(normalized_context)

    if normalized:
        return normalized

    data = record.characteristics.get("data", {})
    fallback_locations = _split_locations(record.location)
    if not fallback_locations:
        fallback_locations = _split_locations(data.get("major_crop_areas"))
    if not fallback_locations and record.country != NA:
        fallback_locations = [record.country]

    return [
        _location_context(
            location_name=location,
            location_type=_infer_location_type(location),
            agro_ecological_zone=data.get("agro_ecological_zone"),
            season=data.get("normal_planting_window") or data.get("season_suitability"),
            management_context=data.get("planting_density"),
            relation_scope="study_area" if record.location and "," in record.location else "cultivar_or_paper",
            evidence="Derived from normalized paper-level location fields.",
            source_url=record.characteristics.get("source_url"),
            confidence=record.characteristics.get("confidence"),
        )
        for location in fallback_locations
    ]


def records_to_sample_db(records: List[CultivarRecord], generated_at: str | None = None) -> Dict[str, Any]:
    zones: Dict[str, Dict[str, Any]] = {}
    cultivar_zones: Dict[str, set[str]] = {}

    for record in records:
        for zone_name in _record_zone_names(record):
            zones.setdefault(zone_name, {})
            cultivar_zones.setdefault(record.cultivar_name, set()).add(zone_name)
            cultivar_record = _sample_cultivar_record(record)
            existing = zones[zone_name].get(record.cultivar_name)
            zones[zone_name][record.cultivar_name] = (
                _merge_sample_cultivar_records(existing, cultivar_record)
                if existing
                else cultivar_record
            )

    countries = sorted({record.country for record in records if record.country != NA})
    crops = sorted({record.crop for record in records if record.crop != NA})
    return {
        "crop": _single_or_joined(crops),
        "country": _single_or_joined(countries),
        "generated_at": generated_at or NA,
        "total_zones": len(zones),
        "processed": len(zones),
        "summary": {
            "total_cultivars_identified": {
                cultivar: sorted(zone_names)
                for cultivar, zone_names in sorted(cultivar_zones.items())
            }
        },
        "zones": {
            zone_name: dict(sorted(cultivars.items()))
            for zone_name, cultivars in sorted(zones.items())
        },
    }


def records_to_web_index(records: List[CultivarRecord]) -> Dict[str, Any]:
    """Create UI-friendly indexes for crop/location/cultivar filtering."""
    by_crop: Dict[str, List[Dict[str, Any]]] = {}
    by_country: Dict[str, List[Dict[str, Any]]] = {}
    by_location: Dict[str, List[Dict[str, Any]]] = {}
    by_cultivar: Dict[str, Dict[str, Any]] = {}

    for index, record in enumerate(records):
        record_id = _record_id(record, index)
        summary = {
            "record_id": record_id,
            "cultivar_name": record.cultivar_name,
            "crop": record.crop,
            "country": record.country,
            "location": record.location,
            "source_url": record.characteristics.get("source_url"),
            "coefficient_source_url": record.coefficients.get("source_url"),
            "has_coefficients": bool(record.coefficients.get("found")),
        }
        by_cultivar[record_id] = {
            **summary,
            "location_contexts": record.characteristics.get("location_contexts", []),
            "characteristics": record.characteristics,
            "coefficients": record.coefficients,
        }
        _append_index(by_crop, record.crop, summary)
        _append_index(by_country, record.country, summary)
        for context in record.characteristics.get("location_contexts", []):
            location = context.get("location_name")
            if location and location != NA:
                _append_index(
                    by_location,
                    location,
                    {
                        **summary,
                        "location_context": context,
                    },
                )

    return {
        "by_crop": _sort_index(by_crop),
        "by_country": _sort_index(by_country),
        "by_location": _sort_index(by_location),
        "by_cultivar": dict(sorted(by_cultivar.items())),
    }


def write_individual_outputs(
    records: List[CultivarRecord],
    output_dir: Path,
    source_files: List[str] | None = None,
) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_output in output_dir.glob("*.json"):
        stale_output.unlink()

    grouped: Dict[str, List[CultivarRecord]] = {}
    for record in records:
        source = str(record.characteristics.get("source") or "unknown_source")
        grouped.setdefault(source, []).append(record)
    for source_file in source_files or []:
        grouped.setdefault(Path(source_file).name, [])

    written = []
    for source_file, paper_records in sorted(grouped.items()):
        output_path = output_dir / f"{Path(source_file).stem}.json"
        payload = {
            "source_file": source_file,
            "record_count": len(paper_records),
            "records": [record.to_dict() for record in paper_records],
            "sample_db": records_to_sample_db(paper_records),
            "web_index": records_to_web_index(paper_records),
        }
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(output_path)
    return written


def _location_context(
    *,
    location_name: Any = NA,
    location_type: Any = NA,
    agro_ecological_zone: Any = NA,
    season: Any = NA,
    management_context: Any = NA,
    relation_scope: Any = NA,
    evidence: Any = NA,
    source_url: Any = NA,
    confidence: Any = "low",
) -> Dict[str, Any]:
    return {
        "location_name": _clean_value(location_name),
        "location_type": _clean_value(location_type) or _infer_location_type(_clean_value(location_name)),
        "agro_ecological_zone": _clean_value(agro_ecological_zone),
        "season": _clean_value(season),
        "management_context": _clean_value(management_context),
        "relation_scope": _clean_value(relation_scope),
        "evidence": _clean_value(evidence),
        "source_url": _clean_value(source_url),
        "confidence": _clean_value(confidence) or "low",
    }


def _single_or_joined(values: List[str]) -> str:
    if not values:
        return NA
    return values[0] if len(values) == 1 else ", ".join(values)


def _record_zone_names(record: CultivarRecord) -> List[str]:
    zones = []
    for context in record.characteristics.get("location_contexts", []):
        if not isinstance(context, dict):
            continue
        for key in ("agro_ecological_zone", "location_name"):
            value = _clean_value(context.get(key))
            if value != NA:
                zones.append(value)
                break
    data = record.characteristics.get("data", {})
    if not zones:
        for value in (data.get("agro_ecological_zone"), record.location, data.get("major_crop_areas")):
            clean = _clean_value(value)
            if clean != NA:
                zones.append(clean)
                break
    if not zones:
        zones.append("Unspecified")

    unique_zones = []
    seen = set()
    for zone in zones:
        clean = zone.strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            unique_zones.append(clean)
    return unique_zones


def _sample_cultivar_record(record: CultivarRecord) -> Dict[str, Any]:
    characteristics = {
        "data": _sample_characteristics_data(record.characteristics.get("data", {})),
        "source": record.characteristics.get("source", NA),
        "source_url": record.characteristics.get("source_url", NA),
        "confidence": record.characteristics.get("confidence", "low"),
    }
    coefficients = {
        "found": bool(record.coefficients.get("found")),
        "source": record.coefficients.get("source", f"RAG: {characteristics['source']}"),
        "source_url": record.coefficients.get("source_url"),
        "coefficients": {
            field: record.coefficients.get("coefficients", {}).get(field)
            for field in COEFFICIENT_FIELDS
            if field in record.coefficients.get("coefficients", {})
        },
        "notes": record.coefficients.get("notes", ""),
    }
    return {"characteristics": characteristics, "coefficients": coefficients}


def _sample_characteristics_data(data: Dict[str, Any]) -> Dict[str, Any]:
    sample_data = {}
    for key, default_value in CHARACTERISTIC_FIELDS.items():
        value = data.get(key, default_value)
        if isinstance(default_value, dict):
            clean_value = value if isinstance(value, dict) else {}
            sample_data[key] = {
                nested_key: clean_value.get(nested_key, nested_default)
                for nested_key, nested_default in default_value.items()
            }
        elif isinstance(default_value, list):
            sample_data[key] = value if isinstance(value, list) else ([] if value in (None, "", NA) else [value])
        else:
            sample_data[key] = value if value not in (None, "") else NA
    return sample_data


def _merge_sample_cultivar_records(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = json.loads(json.dumps(existing))
    existing_data = merged["characteristics"]["data"]
    incoming_data = incoming["characteristics"]["data"]
    for key, incoming_value in incoming_data.items():
        existing_value = existing_data.get(key)
        if key == "disease_resistance":
            existing_data[key] = _merge_lists(existing_value or [], incoming_value or [])
        elif key == "stress_tolerance":
            existing_data[key] = {
                stress_key: _prefer_value(existing_value.get(stress_key), incoming_value.get(stress_key))
                for stress_key in CHARACTERISTIC_FIELDS["stress_tolerance"]
            }
        else:
            existing_data[key] = _prefer_value(existing_value, incoming_value)

    if not merged["coefficients"].get("found") and incoming["coefficients"].get("found"):
        merged["coefficients"] = incoming["coefficients"]
    elif merged["coefficients"].get("found") and incoming["coefficients"].get("found"):
        merged["coefficients"]["notes"] = _merge_notes(
            merged["coefficients"].get("notes", ""),
            incoming["coefficients"].get("notes", ""),
        )

    merged["characteristics"]["source"] = _merge_sources(
        merged["characteristics"].get("source"),
        incoming["characteristics"].get("source"),
    )
    merged["characteristics"]["source_url"] = _merge_sources(
        merged["characteristics"].get("source_url"),
        incoming["characteristics"].get("source_url"),
    )
    return merged


def _prefer_value(existing: Any, incoming: Any) -> Any:
    if existing in (None, "", NA) and incoming not in (None, "", NA):
        return incoming
    return existing if existing not in (None, "") else NA


def _merge_lists(existing: List[Any], incoming: List[Any]) -> List[Any]:
    merged = []
    seen = set()
    for value in [*existing, *incoming]:
        key = str(value).lower()
        if value and key not in seen:
            seen.add(key)
            merged.append(value)
    return merged


def _merge_sources(existing: Any, incoming: Any) -> Any:
    values = []
    for source in (existing, incoming):
        if isinstance(source, list):
            values.extend(source)
        elif source not in (None, "", NA):
            values.append(source)
    merged = _merge_lists([], values)
    if not merged:
        return NA
    return merged[0] if len(merged) == 1 else merged


def _merge_notes(existing: str, incoming: str) -> str:
    return " ".join(_merge_lists([], [existing, incoming]))


def _split_locations(value: Any) -> List[str]:
    if not value or value == NA:
        return []
    parts = re.split(r",|;|\band\b", str(value))
    locations = []
    seen = set()
    for part in parts:
        location = part.strip(" .")
        if not location or location == NA:
            continue
        key = location.lower()
        if key in seen:
            continue
        seen.add(key)
        locations.append(location)
    return locations


def _infer_location_type(location: str) -> str:
    lowered = location.lower()
    if "county" in lowered:
        return "county"
    if "aez" in lowered or "zone" in lowered:
        return "agro_ecological_zone"
    if any(term in lowered for term in ("site", "farm", "station", "center", "centre")):
        return "site"
    if any(term in lowered for term in ("region", "western", "eastern", "northern", "southern")):
        return "region"
    return "study_area"


def _append_index(index: Dict[str, List[Dict[str, Any]]], key: str, item: Dict[str, Any]) -> None:
    if not key or key == NA:
        return
    index.setdefault(key, []).append(item)


def _sort_index(index: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        key: sorted(value, key=lambda item: (item["cultivar_name"], item["record_id"]))
        for key, value in sorted(index.items())
    }


def _record_id(record: CultivarRecord, index: int) -> str:
    source = str(record.characteristics.get("source") or "paper")
    base = f"{Path(source).stem}-{record.cultivar_name}-{index + 1}"
    return re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()


def _context_key(context: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(context.get("location_name", "")).lower(),
        str(context.get("agro_ecological_zone", "")).lower(),
        str(context.get("season", "")).lower(),
    )


def _clean_value(value: Any) -> str:
    if value in (None, ""):
        return NA
    return str(value).strip()
