import hashlib
import json
import re
from pathlib import Path

from pydantic import ValidationError

from models import CatalogProduct, Product, ProductSummary


DEFAULT_CATALOG_PATH = Path(__file__).parent / "output" / "products" / "products.json"
MAX_SLUG_CHARACTERS = 60


class ProductStoreError(ValueError):
    """Raised when the checked-in product catalog cannot be loaded safely."""


class ProductStore:
    """An immutable, validated in-memory view of the product catalog."""

    def __init__(self, products: list[CatalogProduct]) -> None:
        ids = [product.id for product in products]
        if len(ids) != len(set(ids)):
            raise ProductStoreError("Product catalog contains duplicate IDs")
        self._products = tuple(products)
        self._products_by_id = {product.id: product for product in products}

    @classmethod
    def load(cls, path: Path = DEFAULT_CATALOG_PATH) -> "ProductStore":
        try:
            raw_products = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ProductStoreError(
                f"Product catalog does not exist: {path}"
            ) from error
        except json.JSONDecodeError as error:
            raise ProductStoreError(
                f"Product catalog is not valid JSON: {path}"
            ) from error

        if not isinstance(raw_products, list):
            raise ProductStoreError("Product catalog must contain a JSON array")
        try:
            products = [CatalogProduct.model_validate(value) for value in raw_products]
        except ValidationError as error:
            raise ProductStoreError(
                f"Product catalog failed validation: {error}"
            ) from error
        return cls(products)

    def list_products(self) -> list[ProductSummary]:
        return [
            ProductSummary(
                id=product.id,
                name=product.name,
                price=product.price,
                brand=product.brand,
                category=product.category,
                image_url=product.image_urls[0] if product.image_urls else None,
            )
            for product in self._products
        ]

    def get_product(self, product_id: str) -> CatalogProduct | None:
        return self._products_by_id.get(product_id)

    def __len__(self) -> int:
        return len(self._products)


def stable_product_id(product: Product) -> str:
    """Build a readable deterministic ID from source-backed product identity."""

    slug = re.sub(r"[^a-z0-9]+", "-", product.name.casefold()).strip("-")
    slug = slug[:MAX_SLUG_CHARACTERS].rstrip("-") or "product"
    identity = f"{product.brand.casefold()}\0{product.name.casefold()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def catalog_product(product: Product) -> CatalogProduct:
    values = product.model_dump(exclude={"id"})
    return CatalogProduct(id=stable_product_id(product), **values)
