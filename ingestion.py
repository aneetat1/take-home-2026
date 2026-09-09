import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import ai
from hydrate import DEFAULT_CATEGORY_MODEL, DEFAULT_EXTRACTION_MODEL, hydrate_product
from models import Product
from product_store import catalog_product


Hydrator = Callable[..., Awaitable[Product]]


@dataclass(frozen=True)
class IngestionResult:
    """The product or error produced for one input file."""

    source_file: Path
    product: Product | None
    error: str | None
    usage_records: tuple[ai.UsageRecord, ...]

    @property
    def usage(self) -> ai.UsageSummary:
        return ai.summarize_usage(list(self.usage_records))


@dataclass(frozen=True)
class BatchResult:
    """All outcomes and cumulative usage from one ingestion run."""

    results: tuple[IngestionResult, ...]
    combined_output: Path

    @property
    def successes(self) -> tuple[IngestionResult, ...]:
        return tuple(result for result in self.results if result.product is not None)

    @property
    def failures(self) -> tuple[IngestionResult, ...]:
        return tuple(result for result in self.results if result.error is not None)

    @property
    def usage(self) -> ai.UsageSummary:
        records = [
            record for result in self.results for record in result.usage_records
        ]
        return ai.summarize_usage(records)

    @property
    def successful_usage(self) -> ai.UsageSummary:
        """Usage from products that completed successfully."""

        records = [
            record
            for result in self.successes
            for record in result.usage_records
        ]
        return ai.summarize_usage(records)


def discover_html_files(input_dir: Path) -> list[Path]:
    """Find HTML inputs in a stable order."""

    if not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    files = sorted(
        (path for path in input_dir.iterdir() if path.suffix.casefold() == ".html"),
        key=lambda path: path.name.casefold(),
    )
    stems = [path.stem.casefold() for path in files]
    if len(stems) != len(set(stems)):
        raise ValueError("HTML input filenames must have unique stems")
    return files


def load_source_manifest(path: Path | None) -> dict[str, str]:
    """Load optional filename-to-source-URL metadata."""

    if path is None:
        return {}
    if not path.is_file():
        raise ValueError(f"Source manifest does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Source manifest is not valid JSON: {path}") from error
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(url, str)
        for name, url in value.items()
    ):
        raise ValueError("Source manifest must map filenames to URL strings")
    return value


async def ingest_directory(
    *,
    input_dir: Path,
    output_dir: Path,
    manifest_path: Path | None = None,
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
    category_model: str = DEFAULT_CATEGORY_MODEL,
    concurrency: int = 2,
    hydrator: Hydrator = hydrate_product,
) -> BatchResult:
    """Hydrate every HTML file while keeping failures and usage isolated."""

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    files = discover_html_files(input_dir)
    source_urls = load_source_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        (output_dir / f"{path.stem}.json").unlink(missing_ok=True)
    semaphore = asyncio.Semaphore(concurrency)

    async def process(path: Path) -> IngestionResult:
        with ai.capture_usage() as usage:
            try:
                async with semaphore:
                    product = await hydrator(
                        path.read_text(encoding="utf-8"),
                        source_urls.get(path.name),
                        extraction_model=extraction_model,
                        category_model=category_model,
                    )
                _write_json_atomic(
                    output_dir / f"{path.stem}.json",
                    catalog_product(product).model_dump(mode="json"),
                )
                return IngestionResult(
                    source_file=path,
                    product=product,
                    error=None,
                    usage_records=tuple(usage.records),
                )
            except Exception as error:
                return IngestionResult(
                    source_file=path,
                    product=None,
                    error=f"{type(error).__name__}: {error}",
                    usage_records=tuple(usage.records),
                )

    results = tuple(await asyncio.gather(*(process(path) for path in files)))
    combined_output = output_dir / "products.json"
    _write_json_atomic(
        combined_output,
        [
            catalog_product(result.product).model_dump(mode="json")
            for result in results
            if result.product is not None
        ],
    )
    return BatchResult(results=results, combined_output=combined_output)


def _write_json_atomic(path: Path, value: object) -> None:
    """Replace a JSON file only after its complete contents reach disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(value, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def print_batch_summary(result: BatchResult) -> None:
    """Print product outcomes and cumulative token and cost totals."""

    for item in result.results:
        status = "ok" if item.product is not None else f"failed ({item.error})"
        print(f"{item.source_file.name}: {status}; {_format_usage(item.usage)}")

    summary = result.usage
    print(
        f"Batch: {len(result.successes)} succeeded, {len(result.failures)} failed; "
        f"{_format_usage(summary)}"
    )
    for model, totals in summary.by_model.items():
        print(f"  {model}: {_format_usage(totals)}")

    successful_usage = result.successful_usage
    if result.successes and successful_usage.estimated_cost is not None:
        average = successful_usage.estimated_cost / len(result.successes)
        print(
            f"Average per successful product: ${average:.6f}; "
            f"1M products: ${average * 1_000_000:,.2f}; "
            f"10M products: ${average * 10_000_000:,.2f}"
        )
    elif result.successes:
        print(
            "Cost projection unavailable because a successful product used a model "
            "with unknown pricing"
        )


def _format_usage(usage: ai.UsageTotals) -> str:
    cost = (
        f"${usage.estimated_cost:.6f}"
        if usage.estimated_cost is not None
        else "unknown cost"
    )
    return (
        f"calls={usage.calls}, input={usage.input_tokens}, "
        f"output={usage.output_tokens}, reasoning={usage.reasoning_tokens}, "
        f"cost={cost}"
    )
