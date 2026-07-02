from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .cultivar_discovery import discover_cultivars
from .extractor import extract_records
from .llm_client import OpenAICompatibleClient, load_dotenv
from .pdf_loader import load_many
from .retriever import KeywordRetriever
from .schema import records_to_sample_db, records_to_web_index, write_individual_outputs


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "Paper_Rag" / "Json_Outputs" / "paper_based_cultivar_db.json"


def main() -> None:
    args = parse_args()
    load_dotenv(REPO_ROOT / "paper_rag" / ".env")

    papers = resolve_papers(args.papers)
    chunks = load_many(papers)
    llm = OpenAICompatibleClient()
    candidates = discover_cultivars(chunks, llm)
    retriever = KeywordRetriever(chunks)
    records = extract_records(candidates, retriever, llm)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_type": "paper_based_rag",
        "input_papers": [str(path) for path in papers],
        "llm_configured": llm.configured,
        "records": [record.to_dict() for record in records],
        "sample_db": records_to_sample_db(records),
        "web_index": records_to_web_index(records),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    individual_dir = args.individual_output_dir or args.output.parent / "Individual_Papers"
    individual_outputs = write_individual_outputs(
        records,
        individual_dir,
        source_files=[path.name for path in papers],
    )
    print(f"Wrote {len(records)} records to {args.output}")
    print(f"Wrote {len(individual_outputs)} individual paper JSON files to {individual_dir}")
    if not llm.configured:
        print("OPENAI_API_KEY was not set; output used heuristic discovery/extraction only.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build paper_based_cultivar_db.json from paper PDFs. "
            "The only required input is the paper path."
        )
    )
    parser.add_argument(
        "papers",
        nargs="+",
        type=Path,
        help="One or more PDF papers, or a directory containing PDFs.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--individual-output-dir",
        type=Path,
        default=None,
        help="Directory for one JSON file per input paper. Defaults to <output_dir>/Individual_Papers.",
    )
    return parser.parse_args()


def resolve_papers(inputs: List[Path]) -> List[Path]:
    papers: List[Path] = []
    for input_path in inputs:
        path = input_path if input_path.is_absolute() else (Path.cwd() / input_path)
        if path.is_dir():
            papers.extend(sorted(path.glob("*.pdf")))
        elif path.suffix.lower() == ".pdf" and path.exists():
            papers.append(path)
        else:
            raise FileNotFoundError(f"Paper not found or not a PDF: {input_path}")
    if not papers:
        raise FileNotFoundError("No PDF papers were found.")
    return papers


if __name__ == "__main__":
    main()
