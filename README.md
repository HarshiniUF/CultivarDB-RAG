RAG Pipeline for creation of Cultivar DataBase

## Paper-only pipeline

The implemented pipeline reads one or more PDF papers and writes a sample-compatible
JSON file. The only required input is the paper path:

```bash
python -m pip install -r paper_rag/requirements.txt
cp paper_rag/.env.example paper_rag/.env  # optional, for LLM extraction
python -m paper_rag.run_pipeline input_papers/s42106-025-00341-7.pdf
```

To process every bundled paper:

```bash
python -m paper_rag.run_pipeline input_papers/
```

The combined output is written to
`Paper_Rag/Json_Outputs/paper_based_cultivar_db.json` by default. The file now
matches the `sampleDB.json` layout:

- `crop`
- `country`
- `generated_at`
- `total_zones`
- `processed`
- `summary.total_cultivars_identified`
- `zones.<zone>.<cultivar>.characteristics`
- `zones.<zone>.<cultivar>.coefficients`

By default, the pipeline writes only this combined JSON file.

To support the three planned data sources (LLM baseline, paper RAG, and
GARDIAN/API records), each run also writes combine-ready standardized outputs:

- `Paper_Rag/Json_Outputs/Standardized/unified_cultivar_records.json`
- `Paper_Rag/Json_Outputs/Standardized/unified_cultivar_records.csv`
- `Paper_Rag/Json_Outputs/Standardized/unified_schema.json`
- `Paper_Rag/Json_Outputs/Standardized/agent_cultivar_lookup.json`
- `Paper_Rag/Json_Outputs/Standardized/merged_cultivar_database.json`

Pass `--write-auxiliary-outputs` to generate these helper files. They keep the same top-level columns across sources. Rich paper-specific
details such as `location_contexts` remain available, but optional, so future
LLM and GARDIAN outputs can be merged without changing the schema. The
standardized rows include a normalized `cultivar_key` so aliases such as
`SC-627` and `SC627` can be merged for downstream APIs and field agents.

For DSSAT workflows, records with complete paper-reported coefficients are also
exported to:

- `Paper_Rag/Json_Outputs/DSSAT_Outputs/MZCER_RAG.CUL`
- `Paper_Rag/Json_Outputs/DSSAT_Outputs/cultivar_coefficients.csv`
- `Paper_Rag/Json_Outputs/DSSAT_Outputs/dssat_export_manifest.json`

The pipeline only creates cultivar coefficient exports from reported values; it
does not invent `.ECO` or `.SPE` parameters when papers do not provide them.
