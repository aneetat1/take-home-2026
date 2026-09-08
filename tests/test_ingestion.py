import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai
import ingestion
import main as cli
from ingestion import BatchResult, IngestionResult, ingest_directory
from models import Category, Price, Product


def make_product(name: str) -> Product:
    return Product(
        name=name,
        price=Price(price=25, currency="USD"),
        description="A useful product.",
        key_features=[],
        image_urls=[],
        video_url=None,
        category=Category(name="Home & Garden > Lighting > Lamps"),
        brand="Example",
        colors=[],
        variants=[],
    )


def record_usage(model: str = "openai/gpt-5-mini") -> None:
    ai._log_usage(
        SimpleNamespace(
            model=model,
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                output_tokens_details=SimpleNamespace(reasoning_tokens=20),
            ),
        )
    )


def test_discovers_only_html_files_in_stable_order(tmp_path: Path) -> None:
    (tmp_path / "z.HTML").write_text("z")
    (tmp_path / "A.html").write_text("a")
    (tmp_path / "README.md").write_text("ignore")

    files = ingestion.discover_html_files(tmp_path)

    assert [path.name for path in files] == ["A.html", "z.HTML"]


def test_cli_does_not_assume_a_source_manifest() -> None:
    args = cli.build_parser().parse_args(["ingest"])

    assert args.manifest is None


def test_batch_limits_concurrency_and_writes_valid_outputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for name in ("c.html", "a.html", "b.html"):
        (input_dir / name).write_text(name)

    active = 0
    maximum_active = 0

    async def fake_hydrator(html, source_url, **kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        record_usage()
        active -= 1
        return make_product(html)

    result = asyncio.run(
        ingest_directory(
            input_dir=input_dir,
            output_dir=output_dir,
            concurrency=2,
            hydrator=fake_hydrator,
        )
    )

    assert maximum_active == 2
    assert [item.source_file.name for item in result.results] == [
        "a.html",
        "b.html",
        "c.html",
    ]
    assert len(result.successes) == 3
    assert result.usage.calls == 3
    assert result.usage.by_model["openai/gpt-5-mini"].calls == 3
    for name in ("a", "b", "c"):
        Product.model_validate_json((output_dir / f"{name}.json").read_text())
    combined = json.loads((output_dir / "products.json").read_text())
    assert [product["name"] for product in combined] == [
        "a.html",
        "b.html",
        "c.html",
    ]


def test_one_failure_does_not_discard_successful_products(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "bad.html").write_text("bad")
    (input_dir / "good.html").write_text("good")
    output_dir.mkdir()
    (output_dir / "bad.json").write_text('{"stale": true}')

    async def fake_hydrator(html, source_url, **kwargs):
        record_usage()
        if html == "bad":
            raise ValueError("could not extract")
        return make_product(html)

    result = asyncio.run(
        ingest_directory(
            input_dir=input_dir,
            output_dir=output_dir,
            hydrator=fake_hydrator,
        )
    )

    assert len(result.successes) == 1
    assert len(result.failures) == 1
    assert result.failures[0].source_file.name == "bad.html"
    assert "could not extract" in result.failures[0].error
    assert (output_dir / "good.json").is_file()
    assert not (output_dir / "bad.json").exists()
    assert len(json.loads((output_dir / "products.json").read_text())) == 1
    assert result.usage.calls == 2


def test_manifest_url_is_passed_to_hydrator(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "product.html").write_text("product")
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps({"product.html": "https://example.com/products/one"})
    )
    received_urls = []

    async def fake_hydrator(html, source_url, **kwargs):
        received_urls.append(source_url)
        return make_product(html)

    asyncio.run(
        ingest_directory(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            manifest_path=manifest,
            hydrator=fake_hydrator,
        )
    )

    assert received_urls == ["https://example.com/products/one"]


def test_unknown_manifest_file_uses_no_source_url(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "heldout.html").write_text("heldout")
    manifest = tmp_path / "sources.json"
    manifest.write_text("{}")
    received_urls = []

    async def fake_hydrator(html, source_url, **kwargs):
        received_urls.append(source_url)
        return make_product(html)

    asyncio.run(
        ingest_directory(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            manifest_path=manifest,
            hydrator=fake_hydrator,
        )
    )

    assert received_urls == [None]


def test_atomic_write_preserves_existing_file_on_replace_failure(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "product.json"
    output.write_text("original")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(ingestion.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        ingestion._write_json_atomic(output, {"new": True})

    assert output.read_text() == "original"
    assert list(tmp_path.iterdir()) == [output]


def test_cli_returns_nonzero_when_a_product_fails(monkeypatch, tmp_path: Path) -> None:
    failed = IngestionResult(
        source_file=tmp_path / "bad.html",
        product=None,
        error="ValueError: bad input",
        usage_records=(),
    )

    async def fake_ingest_directory(**kwargs):
        return BatchResult((failed,), tmp_path / "products.json")

    monkeypatch.setattr(cli, "ingest_directory", fake_ingest_directory)

    assert cli.main(["ingest"]) == 1


def test_cli_returns_zero_when_all_products_succeed(monkeypatch, tmp_path: Path) -> None:
    succeeded = IngestionResult(
        source_file=tmp_path / "good.html",
        product=make_product("good"),
        error=None,
        usage_records=(),
    )

    async def fake_ingest_directory(**kwargs):
        return BatchResult((succeeded,), tmp_path / "products.json")

    monkeypatch.setattr(cli, "ingest_directory", fake_ingest_directory)

    assert cli.main(["ingest"]) == 0


def test_cost_projection_uses_only_successful_products(
    tmp_path: Path, capsys
) -> None:
    successful = IngestionResult(
        source_file=tmp_path / "good.html",
        product=make_product("good"),
        error=None,
        usage_records=(ai.UsageRecord("model", 10, 5, 2, 0.25),),
    )
    failed = IngestionResult(
        source_file=tmp_path / "bad.html",
        product=None,
        error="ValueError: bad input",
        usage_records=(ai.UsageRecord("model", 20, 10, 4, 0.75),),
    )

    ingestion.print_batch_summary(
        BatchResult((successful, failed), tmp_path / "products.json")
    )

    output = capsys.readouterr().out
    assert "cost=$1.000000" in output
    assert "Average per successful product: $0.250000" in output
