from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from models import CatalogProduct, ProductSummary
from product_store import DEFAULT_CATALOG_PATH, ProductStore


def create_app(catalog_path: Path = DEFAULT_CATALOG_PATH) -> FastAPI:
    """Create the API and load its validated catalog during startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.product_store = ProductStore.load(catalog_path)
        yield

    app = FastAPI(title="Channel3 Product Catalog API", lifespan=lifespan)

    @app.get("/api/health")
    def health(request: Request) -> dict[str, int | str]:
        store = _store(request)
        return {"status": "ok", "products": len(store)}

    @app.get("/api/products", response_model=list[ProductSummary])
    def list_products(request: Request) -> list[ProductSummary]:
        return _store(request).list_products()

    @app.get("/api/products/{product_id}", response_model=CatalogProduct)
    def get_product(product_id: str, request: Request) -> CatalogProduct:
        product = _store(request).get_product(product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return product

    return app


def _store(request: Request) -> ProductStore:
    return request.app.state.product_store


app = create_app()
