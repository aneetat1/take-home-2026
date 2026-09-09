import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogPage } from "./CatalogPage";

const products = [
  {
    id: "example-chair-123",
    name: "Example Chair",
    brand: "Example",
    category: { name: "Furniture > Chairs" },
    image_url: "https://example.com/chair.jpg",
    price: { price: 80, currency: "USD", compare_at_price: 100 },
  },
];

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
}

function renderCatalog() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<CatalogPage />} />
        <Route path="/products/:productId" element={<h1>Product details</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CatalogPage", () => {
  it("renders product data and sale pricing", async () => {
    mockFetch(products);
    renderCatalog();

    expect(await screen.findByRole("heading", { name: "Example Chair" })).toBeVisible();
    expect(screen.getByText("Example")).toBeVisible();
    expect(screen.getByText("$80.00")).toBeVisible();
    expect(screen.getByText("$100.00").tagName).toBe("DEL");
    expect(screen.getByRole("img", { name: "Example Chair" })).toHaveAttribute(
      "src",
      "https://example.com/chair.jpg",
    );
  });

  it("navigates to the product detail route", async () => {
    mockFetch(products);
    const user = userEvent.setup();
    renderCatalog();

    await user.click(await screen.findByRole("link", { name: /Example Chair/ }));

    expect(screen.getByRole("heading", { name: "Product details" })).toBeVisible();
  });

  it("shows a loading state while the request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    renderCatalog();

    expect(screen.getByLabelText("Loading products")).toHaveAttribute("aria-busy", "true");
  });

  it("shows an error state and can retry", async () => {
    mockFetch({}, 503);
    const user = userEvent.setup();
    renderCatalog();

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load products (503)");
    mockFetch(products);
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Example Chair" })).toBeVisible();
  });

  it("shows an empty catalog state", async () => {
    mockFetch([]);
    renderCatalog();

    expect(await screen.findByRole("heading", { name: "No products yet" })).toBeVisible();
  });
});
