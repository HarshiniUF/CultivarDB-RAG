# Approach 2: Paper-Based RAG Cultivar Extraction — Pipeline Documentation

This document explains the workflow for building a **second, independent** cultivar database — `Paper_Rag/Json_Outputs/paper_based_cultivar_db.json` — by extracting data directly from the research PDFs in `input_papers/` using Retrieval-Augmented Generation (RAG), instead of live web search or the LLM's general knowledge.

This module does **not** modify or depend on Approach 1 (`Approach1-Readme.md`). It is a standalone pipeline. If the two are ever combined, this output is structured so the merge is a straightforward key match — that merge step itself is not part of this module.

---

## Why a Second Approach

Approach 1's Step 2 (live web search) is blocked by paywalls for most commercial hybrids, and its `characteristics` block is filled from the LLM's general knowledge with source URLs that are often fabricated (e.g. `kalro.org/maize-hybrid-dkc-910-fact-sheet`) — not verifiable.

The PDFs already sitting in `input_papers/` are real, peer-reviewed DSSAT calibration studies covering East Africa (Kenya, Ethiopia, Tanzania, Uganda, Rwanda) and already contain **real, published genotype coefficients** (P1, P2, P5, G2, G3, PHINT) for named cultivars such as H614, KH600-23A, SC627, BH-660, BH540, Melkassa I, Situka, MH-16, Katumani, H513, H511. Approach 2 extracts directly from these papers, so every fact is traceable to an exact PDF + page number.

---

## Scope: Corpus-Driven, Not Query-Driven

Approach 1 asks the LLM "what are the top 10–15 cultivars grown in zone X?" and then tries to find data for each. Approach 2 works the other way around: it reads each paper and asks **"what cultivars does this paper actually discuss?"** — only cultivars the corpus genuinely covers get extracted. Nothing is guessed for gaps in the corpus.

---

## Files Involved

| File | Role |
|---|---|
| `paper_rag/requirements.txt` | Dependencies: `PyMuPDF`, `python-dotenv` |
| `paper_rag/.env.example` | Template for `OPENAI_API_KEY` / `OPENAI_API_BASE` (NaviGator) — copy to `.env` and fill in real values |
| `paper_rag/schema.py` | Dataclass-based validation/normalization for every record; also builds `location_contexts`, web indexes, and per-paper output JSON |
| `paper_rag/pdf_loader.py` | Converts each PDF into page-level chunks; table-like blocks are kept atomic (never split mid-table) |
| `paper_rag/retriever.py` | Dependency-free keyword retriever scoped to the input paper |
| `paper_rag/cultivar_discovery.py` | One LLM call per PDF: lists every named cultivar the paper discusses, plus crop/country/location |
| `paper_rag/extractor.py` | For each (paper, cultivar): retrieves relevant chunks, asks the LLM to extract characteristics + coefficients, validates against `schema.py` |
| `paper_rag/run_pipeline.py` | Orchestrates all steps end-to-end and writes the final output JSON |
| `Paper_Rag/Json_Outputs/paper_based_cultivar_db.json` | Output, written under the JSON output folder |

---

## Configuration

```
OUTPUT_FILE   = "Paper_Rag/Json_Outputs/paper_based_cultivar_db.json"
```
Credentials (`.env`, not committed):
```
OPENAI_API_KEY=...
OPENAI_API_BASE=...        # NaviGator endpoint
LLM_MODEL=gpt-4o
```

## How to Run

```bash
pip install -r paper_rag/requirements.txt
cp paper_rag/.env.example paper_rag/.env        # optional, then fill in real credentials
python -m paper_rag.run_pipeline input_papers/s42106-025-00341-7.pdf
```
Output is written to `Paper_Rag/Json_Outputs/paper_based_cultivar_db.json`.

The only required pipeline input is the paper. You can pass a single PDF, multiple
PDFs, or a directory of PDFs:

```bash
python -m paper_rag.run_pipeline input_papers/
```

---

## Pipeline Steps

### Step 1 — Index the Corpus

**What it does:** Converts every PDF in `input_papers/` into searchable chunks and indexes them with a paper-scoped keyword retriever.

**How it works:**
1. `pdf_loader.py` runs each PDF through PyMuPDF, producing text per page.
2. Each page is segmented into `table` and `prose` runs. A table-like coefficient block is kept as **one atomic chunk** — splitting it would separate a cultivar's name from its P1/P2/P5/G2/G3/PHINT values.
3. Long prose runs are further split (~1000 characters, 150 overlap) for retrieval granularity; tables are never split further regardless of size.
4. Chunks are searched by `KeywordRetriever`, a dependency-free retriever tagged with `source_file` and `page` metadata.

---

### Step 2 — Discover Cultivars Per Paper

**What it does:** Reads each paper and asks the LLM which named cultivars it actually discusses.

**How it works:**
1. For each PDF, the LLM is given that paper's chunks and asked: *"List every named maize cultivar/hybrid/variety mentioned, with its crop, country, and the specific location/site studied."*
2. This produces a worklist of `(paper, cultivar, country, location)` tuples — e.g. `(Kipkulei 2024, "H614", "Kenya", "Trans Nzoia County")`.

**Succeeds when:** The paper names at least one cultivar explicitly. Current validation found one input paper with no named cultivar records; it still gets a zero-record individual JSON file.
**This step defines scope** — no cultivar/zone outside what the corpus actually discusses is ever queried.

---

### Step 3 — Extract Per (Paper, Cultivar)

**What it does:** For each discovered cultivar, pulls the relevant chunks from that specific paper and extracts structured data.

**How it works:**
1. Retrieve multiple evidence streams filtered to that paper's `source_file`: cultivar-specific chunks, DSSAT coefficient chunks, planting-density/management chunks, and broad study-area/location chunks.
2. Expand support pages when a page has coefficient or management signals, so table rows and nearby explanatory text stay together.
3. Pass the retrieved chunks + cultivar name to the LLM with a strict extraction prompt:
   - Extract the **same characteristics fields** the existing LLM-pipeline cultivar agent produces: `maturity_class`, `relative_maturity`, `days_to_maturity`, `average_yield_kg_ha`, `plant_height_cm`, `growth_habit`, `disease_resistance`, `stress_tolerance` (`drought`/`heat`), `growing_degree_days`, `agro_ecological_zone`, `adaptation_notes`, `normal_planting_window`, `planting_density`, `harvest_time`, `season_suitability`, `major_crop_areas`.
   - **Any field not explicitly supported by the paper is set to `"NA"`** — never guessed. This is the core fix over Approach 1's hallucinated-source problem.
   - Extract calibrated DSSAT coefficients (`P1`, `P2`, `P5`, `G2`, `G3`, `PHINT`) only when the paper provides them, with `found: true/false`.
   - Extract `characteristics.location_contexts`, one object per supported cultivar-location-season-management relationship. If the paper only supports a paper-wide relationship, the record is marked with `relation_scope: study_area`.
   - Every extracted fact is tagged with the source PDF filename and page number.
4. Run deterministic enrichment after the LLM call for repeated paper patterns such as coefficient tables, planting density, planting windows, and fallback location contexts.

**Example output for one record:**
```json
{
  "cultivar_name": "SC627",
  "crop": "MZ",
  "country": "Malawi",
  "location": "Medium-altitude agroecological zone",
  "characteristics": {
    "data": {
      "maturity_class": "medium",
      "relative_maturity": "NA",
      "days_to_maturity": "NA",
      "average_yield_kg_ha": "NA",
      "plant_height_cm": "NA",
      "growth_habit": "NA",
      "disease_resistance": ["Maize Streak Virus", "Gray Leaf Spot", "Turcicum leaf blight"],
      "stress_tolerance": {"drought": "NA", "heat": "NA"},
      "growing_degree_days": "NA",
      "agro_ecological_zone": "Medium altitude",
      "adaptation_notes": "Moderately tolerant to low nitrogen",
      "normal_planting_window": "NA",
      "planting_density": "NA",
      "harvest_time": "NA",
      "season_suitability": "NA",
      "major_crop_areas": "NA"
    },
    "source": "1-s2.0-S0167198714000944-main.pdf",
    "source_url": "input_papers/1-s2.0-S0167198714000944-main.pdf#page=3",
    "confidence": "high",
    "location_contexts": [
      {
        "location_name": "Chitedze Research Station, Lilongwe",
        "location_type": "site",
        "agro_ecological_zone": "mid-altitude agro-ecological zone",
        "season": "2007–2008 to 2011–2012",
        "management_context": "Conventional tillage and conservation agriculture treatments",
        "relation_scope": "study_area",
        "evidence": "The study describes SC627 at Chitedze in the mid-altitude zone.",
        "source_url": "input_papers/1-s2.0-S0167198714000944-main.pdf#page=2",
        "confidence": "high"
      }
    ]
  },
  "coefficients": {
    "found": true,
    "source": "RAG: 1-s2.0-S0167198714000944-main.pdf",
    "source_url": "input_papers/1-s2.0-S0167198714000944-main.pdf#page=6",
    "coefficients": {"P1": 230.0, "P2": 0.6, "P5": 940.0, "G2": 430.0, "G3": 6.0, "PHINT": 38.9},
    "notes": "Calibrated coefficients from DSSAT CERES-Maize, conservation agriculture study"
  }
}
```

---

### Step 4 — Validate

Each LLM-extracted record is normalized through `schema.py`. Missing fields are filled with `"NA"` or empty lists, coefficient values are coerced to numeric values, and every record is guaranteed to have a `location_contexts` array.

---

### Step 5 — Aggregate & Write

All validated records are collected into a single output file:

```json
{
  "generated_at": "2026-06-19T00:00:00",
  "source_type": "paper_based_rag",
  "input_papers": ["input_papers/example.pdf"],
  "llm_configured": true,
  "records": [ /* one entry per (paper, cultivar) — see Step 3 example */ ],
  "sample_db": { /* sampleDB.json-compatible cultivar map */ },
  "web_index": {
    "by_crop": {},
    "by_country": {},
    "by_location": {},
    "by_cultivar": {}
  }
}
```

The same run writes per-paper JSON files to:

```text
Paper_Rag/Json_Outputs/Individual_Papers/
```

The individual-output folder is cleaned before every write so stale files do not stay mixed with the latest run.

---

## Source Label Reference

| `source` value | Meaning |
|---|---|
| `"RAG: <pdf filename>"` | Coefficients/characteristics extracted from a specific page of a local research PDF |
| `"NA"` (in any characteristics field) | The paper does not report this field — never filled by guessing |

## Field Compatibility With Approach 1

`characteristics.data` and `coefficients.coefficients` use the **exact same key names** as `sampleDB.json`. `cultivar_name`, `crop`, and `country` also map directly to Approach 1's per-zone dictionary keys. The additional fields `location`, `characteristics.location_contexts`, and `web_index` are designed for the web app use case: a user can filter by crop/location/cultivar and still see the evidence chain back to the paper.

---

## Known Limitations

- **Corpus coverage:** Only cultivars actually discussed in `input_papers/` are extracted — growing the corpus (adding more PDFs) is the only way to cover more cultivars.
- **NA fields:** Characteristics not reported in the source paper stay `"NA"`, even if generally well known — this module intentionally does not fall back to general LLM knowledge.
- **No `.CUL` dependency:** Unlike Approach 1, this module does not use DSSAT `.CUL` files at all (no local-file lookup, no analog-matching fallback) — coefficients are only ever real, paper-reported values or absent (`found: false`).
- **Relationship confidence:** when a paper states that all cultivars were evaluated across the same study area, the pipeline records that relationship as `study_area`; it does not invent cultivar-specific county assignments that the paper does not support.

---

## Dependencies

```
PyMuPDF, python-dotenv
```

LLM: NaviGator/OpenAI-compatible API — configured via `paper_rag/.env` as `OPENAI_API_KEY` + `OPENAI_API_BASE`, same convention as Approach 1. If no key is configured, the pipeline still runs with heuristic cultivar discovery and table-pattern coefficient extraction, marking the output as `llm_configured: false`.
