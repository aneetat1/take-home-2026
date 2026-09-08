import argparse
import asyncio
import logging
from pathlib import Path
from typing import Sequence

from hydrate import DEFAULT_CATEGORY_MODEL, DEFAULT_EXTRACTION_MODEL
from ingestion import ingest_directory, print_batch_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract product data from HTML files")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="process a directory of HTML files")
    ingest.add_argument("--input-dir", type=Path, default=Path("data"))
    ingest.add_argument("--output-dir", type=Path, default=Path("output/products"))
    ingest.add_argument(
        "--manifest",
        type=Path,
        help="optional JSON mapping of HTML filenames to their source URLs",
    )
    ingest.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
    ingest.add_argument("--category-model", default=DEFAULT_CATEGORY_MODEL)
    ingest.add_argument("--concurrency", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    if args.command == "ingest":
        result = asyncio.run(
            ingest_directory(
                input_dir=args.input_dir,
                output_dir=args.output_dir,
                manifest_path=args.manifest,
                extraction_model=args.model,
                category_model=args.category_model,
                concurrency=args.concurrency,
            )
        )
        print_batch_summary(result)
        return 1 if result.failures else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
