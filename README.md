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
`Paper_Rag/Json_Outputs/paper_based_cultivar_db.json` by default. It contains:

- `records`: one structured entry per paper/cultivar.
- `sample_db`: a `sampleDB.json`-compatible cultivar map.
- `web_index`: crop, country, cultivar, and location indexes for UI filtering.
- `characteristics.location_contexts`: per-cultivar location/season/management
  relationships with evidence and source pages.

The pipeline also writes one JSON file per input paper to
`Paper_Rag/Json_Outputs/Individual_Papers/`, including zero-record papers.
