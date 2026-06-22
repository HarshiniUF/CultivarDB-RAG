# CultivarDB Creation — Pipeline Documentation

This document explains the full workflow for building the `cultivar_db` — the JSON database of DSSAT genotypic coefficients used by the SNX generation pipeline.

---

## Files Involved

| File | Role |
|---|---|
| `generate_dataset_v3.py` | Main entry point — runs per country/crop/zone |
| `agents/standalone_cultivar_helper_agent_v2.py` | Core agent: 3-step fallback chain |
| `Genotype/MZCER048.CUL` (and other `.CUL` files) | DSSAT official coefficient reference |
| `utils/helpers.py` | `get_cultivar_list_by_location()` — reads cultivarDB for SNX |
| `utils/cul_parser.py` | `parse_and_match_cultivar()` — INGENO lookup for SNX |
| `data/cultivar_db/<country>/<crop>/` | Output location for generated JSON files |

---

## Configuration (in `generate_dataset_v3.py`)

```python
COUNTRY   = "Kenya"
CROP_CODE = "MZ"          # MZ=Maize, WH=Wheat, RI=Rice, SG=Sorghum
ZONES     = ["AEZ1", "AEZ2", "AEZ3", ...]   # Agro-Ecological Zones to process
```

## How to Run

```bash
cd /home/harshini/Desktop/FILE_X/FileX_MultiAgent
python generate_dataset_v3.py
```

Output JSON files are saved to `data/cultivar_db/Kenya/MZ/AEZ1.json`, etc.

---

## The 3-Step Fallback Chain

For every cultivar in every zone, the agent tries three steps in order. The first step that succeeds sets the coefficients; later steps are skipped.

---

### Step 1 — Local .CUL File Lookup

**What it does:** Searches DSSAT's official `.CUL` file for an exact or close cultivar name match.

**How it works:**
1. The agent sends the cultivar name (e.g. `DKC 910`) and the full `.CUL` file text to the LLM.
2. The LLM reads the fixed-width table and returns the matching row's `VAR#` (INGENO) and coefficient values.
3. The LLM also tries fuzzy matching — e.g. `DKC910`, `DKC-910`, `DEKALB 910`.

**Example input to LLM:**
```
Cultivar: DKC 910
CUL file contents:
@VAR#  VRNAME.......... EXPNO   ECO#    P1    P2    P5    G2    G3 PHINT
KY0011 H614             .      IB0001 396.9 0.500 623.6 825.0 10.15 75.00
990003 SHORT SEASON     .      IB0001 110.0 0.300 680.0 820.4  6.60 38.90
...
```

**Example output:**
```json
{"found": true, "source": "Local .CUL file", "coefficients": {"P1": 220.0, "P2": 0.52, "P5": 800.0, "G2": 700.0, "G3": 8.5, "PHINT": 38.9}}
```

**Succeeds when:** The cultivar name (or a close variant) exists in the `.CUL` file.  
**Source label:** `"Local .CUL file"`

---

### Step 2 — Web Search + Research Paper Scraping

**What it does:** Searches the web for published DSSAT calibration studies and tries to extract coefficient tables.

**How it works:**
1. Constructs a search query: `"DKC 910 DSSAT CERES-Maize P1 P2 P5 G2 G3 calibration coefficients"`
2. Uses DuckDuckGo (`ddgs`) to get up to 5 result URLs.
3. Filters to open-access domains only (MDPI, frontiersin.org, researchgate.net, cgiar.org, etc.) — paywalled sites (Elsevier, Springer, Wiley) are skipped.
4. Fetches each page with `WebFetch` and extracts text.
5. Sends the page text to the LLM with a prompt asking it to extract P1/P2/P5/G2/G3/PHINT values.

**Succeeds when:** An open-access paper contains a coefficient table for the exact cultivar.  
**Fails in practice when:** The cultivar's calibration data is only in paywalled journals (common for commercial hybrids).  
**Source label:** `"WebFetch: <url>"`

---

### Step 3 — Analog Matching (Generic Archetypes)

**What it does:** When no published data is found, assigns the cultivar to the closest DSSAT generic archetype based on its maturity class.

**How it works:**
1. The LLM is asked about the cultivar's agronomic traits: days-to-maturity, maturity class (early/medium/late), grain type, etc.
2. The maturity class maps to one of three `.CUL` generic rows:

| Maturity Class | INGENO | DSSAT Name | P1 |
|---|---|---|---|
| Early (DTM ≤ 115 days) | 990003 | SHORT SEASON | 110.0 |
| Medium (DTM 115–130 days) | 990002 | MEDIUM SEASON | 200.0 |
| Late (DTM > 130 days) | 990001 | LONG SEASON | 320.0 |

3. The full coefficient row from the `.CUL` file is returned as-is — no estimation, no modification.

**Example:** DKC 910 is a medium-late hybrid → mapped to `990002 MEDIUM SEASON` with `P1=200, P2=0.3, P5=800, G2=700, G3=8.5, PHINT=38.9`.

**Succeeds when:** The cultivar's maturity class can be determined (almost always).  
**Source label:** `"analog: <SHORT|MEDIUM|LONG> SEASON"`

---

### If All 3 Steps Fail

The cultivar is recorded as not found:

```json
{"found": false, "source": "not_found", "source_url": null, "coefficients": {}}
```

This is rare — Step 3 (analog) nearly always succeeds because maturity class information is widely available for commercial hybrids.

---

## Per-Zone Workflow

For each AEZ zone defined in `ZONES`:

1. The agent queries the LLM for the top 10–15 commercially grown cultivars in that zone.
2. For each cultivar, it runs the 3-step fallback chain.
3. All results are collected into one JSON file per zone.

---

## Output JSON Structure

Each zone produces a file like `data/cultivar_db/Kenya/MZ/AEZ1.json`:

```json
{
  "country": "Kenya",
  "crop_code": "MZ",
  "aez_zone": "AEZ1",
  "cultivars": {
    "DKC 910": {
      "cultivar_name": "DKC 910",
      "characteristics": {
        "data": {
          "days_to_maturity": "120-130",
          "maturity_class": "medium",
          "grain_type": "dent",
          "yield_potential_t_ha": 10.0
        }
      },
      "coefficients": {
        "found": true,
        "source": "analog: MEDIUM SEASON",
        "source_url": null,
        "coefficients": {
          "P1": 200.0, "P2": 0.300, "P5": 800.0,
          "G2": 700.0, "G3": 8.50, "PHINT": 38.90
        }
      }
    }
  }
}
```

---

## Source Label Reference

| `source` value | Meaning |
|---|---|
| `"Local .CUL file"` | Exact or fuzzy match found in DSSAT `.CUL` file |
| `"WebFetch: <url>"` | Coefficients extracted from an open-access research paper |
| `"analog: SHORT SEASON"` | Mapped to 990003 generic archetype (early maturity) |
| `"analog: MEDIUM SEASON"` | Mapped to 990002 generic archetype (medium maturity) |
| `"analog: LONG SEASON"` | Mapped to 990001 generic archetype (late maturity) |
| `"not_found"` | All 3 steps failed |

---

## How CultivarDB Is Used in SNX Generation

The SNX pipeline reads cultivarDB through `CultivarAgent`:

1. `get_cultivar_list_by_location(country, location, crop_code)` loads the zone's JSON and returns cultivar names where `coefficients.found == True`.
2. `parse_and_match_cultivar(cultivar_name, crop_code)` re-searches the `.CUL` file to get the official `VAR#` (INGENO) for the matched cultivar.
3. The SNX `*CULTIVARS` section is written as:
   ```
   *CULTIVARS
   @C CR INGENO CNAME
    1 MZ KY0011 H614
   ```
   - `INGENO` comes from the `.CUL` file lookup
   - `CNAME` comes from the cultivarDB (the cultivar name string)

The coefficient values in the DB are **not** written directly into the SNX file — DSSAT reads coefficients at runtime from its own `.CUL` files using the INGENO code.

---

## Summary Progress Output

When the agent finishes a zone, it prints:

```
📊 Summary: 2 local .CUL, 0 web paper, 11 analog, 0 not found
```

---

## Known Limitations

- **Paywalled papers:** Step 2 rarely succeeds for commercial hybrid cultivars (Elsevier/Springer block access). Step 3 compensates.
- **Analog accuracy:** Generic archetype coefficients are not variety-specific. They are suitable placeholders but may not capture variety-specific yield potential.
- **LLM trait knowledge:** Step 3 relies on the LLM knowing the cultivar's maturity class. Very new or obscure local varieties may be misclassified.

---

## Supported Crop Codes

| Code | Crop | CUL File |
|---|---|---|
| MZ | Maize | MZCER048.CUL |
| WH | Wheat | WHCER048.CUL |
| RI | Rice | RICER048.CUL |
| SG | Sorghum | SGCER048.CUL |

---

## Dependencies

```
langchain, duckduckgo-search (ddgs), beautifulsoup4, requests, python-dotenv
```

LLM: NaviGator API (University of Florida) — configured via `.env` as `OPENAI_API_KEY` + `OPENAI_API_BASE`.
