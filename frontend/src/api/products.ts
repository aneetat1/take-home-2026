import type { Product, ProductSummary } from "../types/product";

export async function getProducts(signal?: AbortSignal): Promise<ProductSummary[]> {
  const response = await fetch("/api/products", { signal });
  if (!response.ok) {
    throw new Error(`Unable to load products (${response.status})`);
  }
  return response.json() as Promise<ProductSummary[]>;
}

export async function getProduct(
  productId: string,
  signal?: AbortSignal,
): Promise<Product | null> {
  const response = await fetch(`/api/products/${encodeURIComponent(productId)}`, {
    signal,
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Unable to load product (${response.status})`);
  }
  return response.json() as Promise<Product>;
}
