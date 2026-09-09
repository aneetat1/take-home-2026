import type { ProductSummary } from "../types/product";

export async function getProducts(signal?: AbortSignal): Promise<ProductSummary[]> {
  const response = await fetch("/api/products", { signal });
  if (!response.ok) {
    throw new Error(`Unable to load products (${response.status})`);
  }
  return response.json() as Promise<ProductSummary[]>;
}
