import { useCallback, useEffect, useState } from "react";

import { getProducts } from "../api/products";
import { ProductCard } from "../components/ProductCard";
import type { ProductSummary } from "../types/product";

type CatalogState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; products: ProductSummary[] };

export function CatalogPage() {
  const [state, setState] = useState<CatalogState>({ status: "loading" });
  const [requestNumber, setRequestNumber] = useState(0);

  const retry = useCallback(() => setRequestNumber((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getProducts(controller.signal)
      .then((products) => setState({ status: "ready", products }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const message = error instanceof Error ? error.message : "Unable to load products";
        setState({ status: "error", message });
      });
    return () => controller.abort();
  }, [requestNumber]);

  return (
    <main className="catalog">
      <header className="catalog__header">
        <div>
          <p className="catalog__eyebrow">Curated essentials</p>
          <h1>Product catalog</h1>
        </div>
        {state.status === "ready" && state.products.length > 0 && (
          <p className="catalog__count">
            {state.products.length} {state.products.length === 1 ? "product" : "products"}
          </p>
        )}
      </header>

      {state.status === "loading" && <CatalogLoading />}
      {state.status === "error" && (
        <section className="catalog-state" role="alert">
          <h2>We couldn’t load the catalog</h2>
          <p>{state.message}</p>
          <button type="button" onClick={retry}>Try again</button>
        </section>
      )}
      {state.status === "ready" && state.products.length === 0 && (
        <section className="catalog-state">
          <h2>No products yet</h2>
          <p>The catalog is ready for its first products.</p>
        </section>
      )}
      {state.status === "ready" && state.products.length > 0 && (
        <section className="product-grid" aria-label="Products">
          {state.products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </section>
      )}
    </main>
  );
}

function CatalogLoading() {
  return (
    <section className="product-grid" aria-label="Loading products" aria-busy="true">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="product-card product-card--loading" key={index}>
          <div className="skeleton skeleton--image" />
          <div className="product-card__body">
            <div className="skeleton skeleton--short" />
            <div className="skeleton skeleton--title" />
            <div className="skeleton skeleton--price" />
          </div>
        </div>
      ))}
    </section>
  );
}
