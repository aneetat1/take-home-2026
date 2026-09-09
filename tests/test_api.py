import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import create_app
from models import CatalogProduct, Category, Price, Product
from product_store import (
    DEFAULT_CATALOG_PATH,
    ProductStore,
    ProductStoreError,
    catalog_product,
    stable_product_id,
)


def make_product(name: str = "Example Lamp") -> Product:
    return Product(
        name=name,
        price=Price(price=125, currency="USD"),
        description="A compact table lamp.",
        key_features=["Fabric shade"],
        image_urls=["https://example.com/lamp.jpg"],
        category=Category(name="Home & Garden > Lighting > Lamps"),
        brand="Example",
        colors=["Blue"],
        variants=[],
    )


def write_catalog(path: Path, products: list[Product]) -> list[CatalogProduct]:
    records = [catalog_product(product) for product in products]
    path.write_text(
        json.dumps([record.model_dump(mode="json") for record in records])
    )
    return records


def test_stable_product_ids_are_deterministic_and_readable() -> None:
    product = make_product("A Lamp & Shade")

    first = stable_product_id(product)

    assert first == stable_product_id(product)
    assert first.startswith("a-lamp-shade-")
    assert first != stable_product_id(make_product("A Different Lamp"))


def test_store_rejects_invalid_product_data(tmp_path: Path) -> None:
    catalog = tmp_path / "products.json"
    catalog.write_text('[{"id": "broken", "name": "Incomplete"}]')

    with pytest.raises(ProductStoreError, match="failed validation"):
        ProductStore.load(catalog)


def test_store_rejects_duplicate_ids() -> None:
    product = catalog_product(make_product())

    with pytest.raises(ProductStoreError, match="duplicate IDs"):
        ProductStore([product, product])


def test_checked_in_catalog_has_stable_ids() -> None:
    store = ProductStore.load(DEFAULT_CATALOG_PATH)
    summaries = store.list_products()

    assert len(summaries) == 5
    for summary in summaries:
        product = store.get_product(summary.id)
        assert product is not None
        assert product.id == stable_product_id(product)


def test_api_lists_product_summaries_and_returns_details(tmp_path: Path) -> None:
    catalog = tmp_path / "products.json"
    records = write_catalog(catalog, [make_product(), make_product("Floor Lamp")])

    with TestClient(create_app(catalog)) as client:
        response = client.get("/api/products")
        detail = client.get(f"/api/products/{records[0].id}")

    assert response.status_code == 200
    summaries = response.json()
    assert [item["id"] for item in summaries] == [record.id for record in records]
    assert summaries[0]["image_url"] == "https://example.com/lamp.jpg"
    assert "description" not in summaries[0]
    assert detail.status_code == 200
    assert detail.json() == records[0].model_dump(mode="json")


def test_api_returns_404_for_unknown_product(tmp_path: Path) -> None:
    catalog = tmp_path / "products.json"
    write_catalog(catalog, [make_product()])

    with TestClient(create_app(catalog)) as client:
        response = client.get("/api/products/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


def test_health_reports_loaded_product_count(tmp_path: Path) -> None:
    catalog = tmp_path / "products.json"
    write_catalog(catalog, [make_product(), make_product("Floor Lamp")])

    with TestClient(create_app(catalog)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "products": 2}


def test_invalid_catalog_fails_during_application_startup(tmp_path: Path) -> None:
    catalog = tmp_path / "products.json"
    catalog.write_text("not JSON")

    with pytest.raises(ProductStoreError, match="not valid JSON"):
        with TestClient(create_app(catalog)):
            pass
