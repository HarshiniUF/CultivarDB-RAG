from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .schema import COEFFICIENT_FIELDS, CHARACTERISTIC_FIELDS, CultivarRecord, NA


UNIFIED_SCHEMA_FIELDS = [
    "record_id",
    "source_type",
    "source_file",
    "source_url",
    "cultivar_name",
    "cultivar_key",
    "crop",
    "country",
    "primary_location",
    "agro_ecological_zone",
    "maturity_class",
    "relative_maturity",
    "days_to_maturity",
    "average_yield_kg_ha",
    "plant_height_cm",
    "growth_habit",
    "disease_resistance",
    "drought_tolerance",
    "heat_tolerance",
    "growing_degree_days",
    "normal_planting_window",
    "planting_density",
    "harvest_time",
    "season_suitability",
    "major_crop_areas",
    "adaptation_notes",
    "coefficient_found",
    "P1",
    "P2",
    "P5",
    "G2",
    "G3",
    "PHINT",
    "coefficient_source_url",
    "confidence",
    "location_contexts",
]


def records_to_unified_rows(
    records: List[CultivarRecord],
    *,
    source_type: str = "paper_rag",
) -> List[Dict[str, Any]]:
    rows = []
    for index, record in enumerate(records):
        data = record.characteristics.get("data", {})
        coefficients = record.coefficients.get("coefficients", {})
        stress = data.get("stress_tolerance") or {}
        if not isinstance(stress, dict):
            stress = {}
        source_file = str(record.characteristics.get("source") or NA)
        row = {
            "record_id": _record_id(record, index),
            "source_type": source_type,
            "source_file": source_file,
            "source_url": record.characteristics.get("source_url") or NA,
            "cultivar_name": record.cultivar_name,
            "cultivar_key": _cultivar_key(record.cultivar_name),
            "crop": record.crop,
            "country": record.country,
            "primary_location": record.location,
            "agro_ecological_zone": data.get("agro_ecological_zone", NA),
            "maturity_class": data.get("maturity_class", NA),
            "relative_maturity": data.get("relative_maturity", NA),
            "days_to_maturity": data.get("days_to_maturity", NA),
            "average_yield_kg_ha": data.get("average_yield_kg_ha", NA),
            "plant_height_cm": data.get("plant_height_cm", NA),
            "growth_habit": data.get("growth_habit", NA),
            "disease_resistance": _stringify(data.get("disease_resistance", [])),
            "drought_tolerance": stress.get("drought", NA),
            "heat_tolerance": stress.get("heat", NA),
            "growing_degree_days": data.get("growing_degree_days", NA),
            "normal_planting_window": data.get("normal_planting_window", NA),
            "planting_density": data.get("planting_density", NA),
            "harvest_time": data.get("harvest_time", NA),
            "season_suitability": data.get("season_suitability", NA),
            "major_crop_areas": data.get("major_crop_areas", NA),
            "adaptation_notes": data.get("adaptation_notes", NA),
            "coefficient_found": bool(record.coefficients.get("found")),
            "coefficient_source_url": record.coefficients.get("source_url") or NA,
            "confidence": record.characteristics.get("confidence", NA),
            "location_contexts": record.characteristics.get("location_contexts", []),
        }
        for field in COEFFICIENT_FIELDS:
            row[field] = coefficients.get(field, NA)
        rows.append({field: row.get(field, NA) for field in UNIFIED_SCHEMA_FIELDS})
    return rows


def rows_to_agent_index(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    index: Dict[str, Any] = {"by_crop_country": {}, "by_location": {}, "by_cultivar": {}}
    for row in rows:
        summary = {
            "record_id": row["record_id"],
            "cultivar_name": row["cultivar_name"],
            "cultivar_key": row["cultivar_key"],
            "crop": row["crop"],
            "country": row["country"],
            "primary_location": row["primary_location"],
            "agro_ecological_zone": row["agro_ecological_zone"],
            "coefficient_found": row["coefficient_found"],
            "coefficients": {field: row[field] for field in COEFFICIENT_FIELDS if row[field] != NA},
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "coefficient_source_url": row["coefficient_source_url"],
        }
        crop_country_key = _index_key(row["crop"], row["country"])
        index["by_crop_country"].setdefault(crop_country_key, []).append(summary)
        index["by_cultivar"].setdefault(row["cultivar_key"], []).append(summary)
        for location in _row_locations(row):
            index["by_location"].setdefault(_safe_key(location), []).append(summary)

    for group in index.values():
        for key, values in group.items():
            group[key] = sorted(values, key=lambda item: (item["cultivar_name"], item["record_id"]))
    return index


def write_standardized_outputs(records: List[CultivarRecord], output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = records_to_unified_rows(records)
    unified_path = output_dir / "unified_cultivar_records.json"
    schema_path = output_dir / "unified_schema.json"
    agent_index_path = output_dir / "agent_cultivar_lookup.json"
    merged_path = output_dir / "merged_cultivar_database.json"
    csv_path = output_dir / "unified_cultivar_records.csv"

    unified_path.write_text(json.dumps({"schema": UNIFIED_SCHEMA_FIELDS, "records": rows}, indent=2) + "\n")
    schema_path.write_text(
        json.dumps(
            {
                "description": (
                    "Stable combine-ready schema for LLM, paper-RAG, and GARDIAN-derived cultivar records. "
                    "Detailed source-specific fields stay optional under location_contexts."
                ),
                "fields": UNIFIED_SCHEMA_FIELDS,
                "coefficient_fields": list(COEFFICIENT_FIELDS),
                "characteristic_fields": list(CHARACTERISTIC_FIELDS.keys()),
            },
            indent=2,
        )
        + "\n"
    )
    agent_index_path.write_text(json.dumps(rows_to_agent_index(rows), indent=2) + "\n")
    merged_path.write_text(json.dumps(rows_to_merged_database(rows), indent=2) + "\n")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNIFIED_SCHEMA_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _stringify(row.get(key, NA)) for key in UNIFIED_SCHEMA_FIELDS})
    return {
        "unified_json": str(unified_path),
        "unified_csv": str(csv_path),
        "schema": str(schema_path),
        "agent_lookup": str(agent_index_path),
        "merged_database": str(merged_path),
    }


def rows_to_merged_database(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge paper/API/LLM rows into crop-country-cultivar records while keeping sources."""
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = _index_key(row["crop"], row["country"], row["cultivar_key"])
        entry = merged.setdefault(
            key,
            {
                "cultivar_key": row["cultivar_key"],
                "cultivar_names": [],
                "crop": row["crop"],
                "country": row["country"],
                "locations": [],
                "agro_ecological_zones": [],
                "best_coefficients": None,
                "coefficient_sets": [],
                "sources": [],
                "records": [],
            },
        )
        _append_unique(entry["cultivar_names"], row["cultivar_name"])
        _append_unique(entry["locations"], row["primary_location"])
        _append_unique(entry["agro_ecological_zones"], row["agro_ecological_zone"])
        coefficient_set = {field: row[field] for field in COEFFICIENT_FIELDS if row[field] != NA}
        if coefficient_set:
            coefficient_payload = {
                "coefficients": coefficient_set,
                "source_url": row["coefficient_source_url"],
                "record_id": row["record_id"],
            }
            if coefficient_payload not in entry["coefficient_sets"]:
                entry["coefficient_sets"].append(coefficient_payload)
            if entry["best_coefficients"] is None:
                entry["best_coefficients"] = coefficient_payload
        source_payload = {
            "source_type": row["source_type"],
            "source_file": row["source_file"],
            "source_url": row["source_url"],
        }
        if source_payload not in entry["sources"]:
            entry["sources"].append(source_payload)
        entry["records"].append(row["record_id"])
    return {"records": dict(sorted(merged.items()))}


def write_dssat_exports(records: List[CultivarRecord], output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    coefficient_records = []
    seen_coefficients = set()
    for record in records:
        coeffs = record.coefficients.get("coefficients", {})
        if not record.coefficients.get("found") or not all(field in coeffs for field in COEFFICIENT_FIELDS):
            continue
        key = (_cultivar_key(record.cultivar_name), tuple(round(float(coeffs[field]), 6) for field in COEFFICIENT_FIELDS))
        if key in seen_coefficients:
            continue
        seen_coefficients.add(key)
        coefficient_records.append(record)
    cul_path = output_dir / "MZCER_RAG.CUL"
    csv_path = output_dir / "cultivar_coefficients.csv"
    manifest_path = output_dir / "dssat_export_manifest.json"

    cul_lines = [
        "*MAIZE CULTIVARS: extracted from paper RAG outputs",
        "@VAR#  VRNAME.......... EXPNO   ECO#    P1    P2    P5    G2    G3 PHINT",
    ]
    csv_rows = []
    for index, record in enumerate(coefficient_records, start=1):
        coeffs = record.coefficients["coefficients"]
        var_id = f"R{index:04d}"[:5]
        eco_id = f"RG{index:03d}"[:5]
        name = _dssat_name(record.cultivar_name)
        cul_lines.append(
            f"{var_id:<6} {name:<16} {'RAG':<6} {eco_id:<5} "
            f"{coeffs['P1']:>5.1f} {coeffs['P2']:>5.2f} {coeffs['P5']:>5.1f} "
            f"{coeffs['G2']:>5.1f} {coeffs['G3']:>5.2f} {coeffs['PHINT']:>5.1f}"
        )
        csv_rows.append(
            {
                "VAR#": var_id,
                "VRNAME": record.cultivar_name,
                "EXPNO": "RAG",
                "ECO#": eco_id,
                **{field: coeffs[field] for field in COEFFICIENT_FIELDS},
                "source_file": record.characteristics.get("source") or NA,
                "source_url": record.coefficients.get("source_url") or NA,
            }
        )

    cul_path.write_text("\n".join(cul_lines) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["VAR#", "VRNAME", "EXPNO", "ECO#", *COEFFICIENT_FIELDS, "source_file", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    manifest_path.write_text(
        json.dumps(
            {
                "description": "DSSAT-oriented exports generated from paper-reported cultivar coefficients.",
                "cultivar_file": str(cul_path),
                "coefficient_csv": str(csv_path),
                "records_with_complete_coefficients": len(coefficient_records),
                "not_generated": {
                    "ECO": "Ecotype parameters were not generated because they are not consistently reported in the input papers.",
                    "SPE": "Species files were not generated because species-level DSSAT parameters are not cultivar-specific paper outputs.",
                },
                "warning": "Review the .CUL file before DSSAT use; values are only as complete as the source papers.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"cul": str(cul_path), "csv": str(csv_path), "manifest": str(manifest_path)}


def _record_id(record: CultivarRecord, index: int) -> str:
    source = str(record.characteristics.get("source") or "paper")
    base = f"{Path(source).stem}-{record.cultivar_name}-{index + 1}"
    return re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()


def _row_locations(row: Dict[str, Any]) -> Iterable[str]:
    if row.get("primary_location") and row["primary_location"] != NA:
        yield row["primary_location"]
    for context in row.get("location_contexts") or []:
        if isinstance(context, dict):
            location = context.get("location_name")
            if location and location != NA:
                yield str(location)
            aez = context.get("agro_ecological_zone")
            if aez and aez != NA:
                yield str(aez)


def _index_key(*parts: str) -> str:
    return "::".join(_safe_key(part) for part in parts if part and part != NA)


def _safe_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "na"


def _cultivar_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower()) or "na"


def _append_unique(values: List[str], value: Any) -> None:
    if not value or value == NA:
        return
    if value not in values:
        values.append(value)


def _dssat_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9 -]", "", value).upper()[:16]


def _stringify(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value in (None, ""):
        return NA
    return str(value)
