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

The output is written to `paper_based_cultivar_db.json` by default. It contains
both `records` and a `sample_db` block whose cultivar entries mirror
`sampleDB.json`.
