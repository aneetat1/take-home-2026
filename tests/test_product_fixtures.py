import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from evidence import prepare_product_evidence
from extraction import extract_page_evidence
from models import Product, VALID_CATEGORIES


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PRODUCT_DIR = PROJECT_ROOT / "output" / "products"
PRODUCT_FILES = sorted(
    path for path in PRODUCT_DIR.glob("*.json") if path.name != "products.json"
)


@pytest.fixture(scope="module")
def products() -> dict[str, Product]:
    return {
        path.stem: Product.model_validate_json(path.read_text(encoding="utf-8"))
        for path in PRODUCT_FILES
    }


def test_one_valid_product_fixture_exists_for_each_snapshot(
    products: dict[str, Product],
) -> None:
    snapshot_names = {path.stem for path in DATA_DIR.glob("*.html")}

    assert set(products) == snapshot_names


def test_combined_fixture_matches_individual_products(
    products: dict[str, Product],
) -> None:
    combined_values = json.loads(
        (PRODUCT_DIR / "products.json").read_text(encoding="utf-8")
    )
    combined = [Product.model_validate(value) for value in combined_values]

    assert combined == list(products.values())


@pytest.mark.parametrize("path", PRODUCT_FILES, ids=lambda path: path.stem)
def test_product_fixture_has_valid_required_fields_and_options(path: Path) -> None:
    product = Product.model_validate_json(path.read_text(encoding="utf-8"))

    assert product.name.strip()
    assert product.brand.strip()
    assert product.description.strip()
    assert product.category.name in VALID_CATEGORIES
    for variant in product.variants:
        option_names = [option.name.strip().casefold() for option in variant.options]
        assert len(option_names) == len(set(option_names))
        assert all(option.value.strip() for option in variant.options)


@pytest.mark.parametrize("path", PRODUCT_FILES, ids=lambda path: path.stem)
def test_selected_media_came_from_the_snapshot(path: Path) -> None:
    product = Product.model_validate_json(path.read_text(encoding="utf-8"))
    html = (DATA_DIR / f"{path.stem}.html").read_text(encoding="utf-8")
    evidence = prepare_product_evidence(extract_page_evidence(html))
    image_candidates = {candidate.url for candidate in evidence.image_candidates}
    video_candidates = {candidate.url for candidate in evidence.video_candidates}

    selected_images = {
        *product.image_urls,
        *(url for variant in product.variants for url in variant.image_urls),
    }
    assert selected_images <= image_candidates
    if product.video_url is not None:
        assert product.video_url in video_candidates


@pytest.mark.parametrize("path", PRODUCT_FILES, ids=lambda path: path.stem)
def test_fixture_media_uses_absolute_http_urls(path: Path) -> None:
    product = Product.model_validate_json(path.read_text(encoding="utf-8"))
    urls = [
        *product.image_urls,
        *(url for variant in product.variants for url in variant.image_urls),
    ]
    if product.video_url is not None:
        urls.append(product.video_url)

    assert all(urlparse(url).scheme in {"http", "https"} for url in urls)


@pytest.mark.parametrize("path", PRODUCT_FILES, ids=lambda path: path.stem)
def test_variant_values_and_identifiers_are_present_in_source_html(path: Path) -> None:
    product = Product.model_validate_json(path.read_text(encoding="utf-8"))
    html = (DATA_DIR / f"{path.stem}.html").read_text(encoding="utf-8")

    for variant in product.variants:
        assert all(option.value in html for option in variant.options)
        if variant.sku is not None:
            assert variant.sku in html
        if variant.gtin is not None:
            assert variant.gtin in html
