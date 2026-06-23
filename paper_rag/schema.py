from __future__ import annotations

from dataclasses import dataclass, field
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

    return CultivarRecord(
        cultivar_name=str(raw.get("cultivar_name") or fallback.cultivar_name).strip(),
        crop=str(raw.get("crop") or fallback.crop or NA).strip(),
        country=str(raw.get("country") or fallback.country or NA).strip(),
        location=str(raw.get("location") or fallback.location or NA).strip(),
        characteristics=characteristics,
        coefficients=coefficients,
    )


def records_to_sample_db(records: List[CultivarRecord]) -> Dict[str, Any]:
    cultivars: Dict[str, Any] = {}
    for record in records:
        cultivars[record.cultivar_name] = {
            "cultivar_name": record.cultivar_name,
            "characteristics": record.characteristics,
            "coefficients": record.coefficients,
        }

    countries = sorted({record.country for record in records if record.country != NA})
    crops = sorted({record.crop for record in records if record.crop != NA})
    return {
        "crop": crops[0] if len(crops) == 1 else NA,
        "country": countries[0] if len(countries) == 1 else NA,
        "cultivars": cultivars,
    }
