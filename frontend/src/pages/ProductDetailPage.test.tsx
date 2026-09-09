import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductDetailPage } from "./ProductDetailPage";

const product = {
  id: "example-chair-123",
  name: "Example Chair",
  brand: "Example",
  price: { price: 80, currency: "USD", compare_at_price: 100 },
  description: "A comfortable chair for quiet afternoons.",
  key_features: ["Solid oak frame", "Woven seat"],
  image_urls: [
    "https://example.com/front.jpg",
    "https://example.com/detail.jpg",
  ],
  video_url: "https://example.com/chair.mp4",
  category: { name: "Furniture > Chairs" },
  colors: ["Natural", "Black"],
  variants: [
    {
      options: [
        { name: "Color", value: "Natural" },
        { name: "Size", value: "Standard" },
      ],
      sku: "CHAIR-NATURAL",
      gtin: null,
      price: null,
      available: true,
      image_urls: ["https://example.com/front.jpg"],
    },
    {
      options: [
        { name: "Color", value: "Black" },
        { name: "Size", value: "Standard" },
      ],
      sku: "CHAIR-BLACK",
      gtin: null,
      price: null,
      available: false,
      image_urls: ["https://example.com/detail.jpg"],
    },
  ],
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={[`/products/${product.id}`]}>
      <Routes>
        <Route path="/" element={<h1>Catalog route</h1>} />
        <Route path="/products/:productId" element={<ProductDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockResponse(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProductDetailPage", () => {
  it("renders product details, features, variants, and video", async () => {
    mockResponse(product);
    renderDetail();

    expect(await screen.findByRole("heading", { name: product.name })).toBeVisible();
    expect(screen.getByText(product.description)).toBeVisible();
    expect(screen.getByText("Solid oak frame")).toBeVisible();
    expect(screen.getByRole("option", { name: /Color: Natural · Size: Standard/ })).toBeVisible();
    expect(
      screen.getByRole("option", { name: /Color: Black · Size: Standard/ }),
    ).toHaveTextContent("Unavailable");
    expect(document.querySelector("video source")).toHaveAttribute("src", product.video_url);
  });

  it("changes the active gallery image", async () => {
    mockResponse(product);
    const user = userEvent.setup();
    renderDetail();
    const gallery = await screen.findByRole("region", { name: "Product images" });
    const activeImage = within(gallery).getByRole("img", { name: product.name });

    await user.click(within(gallery).getByRole("button", { name: "View image 2 of 2" }));

    expect(activeImage).toHaveAttribute("src", product.image_urls[1]);
  });

  it("selects only an enumerated variant configuration", async () => {
    mockResponse(product);
    const user = userEvent.setup();
    renderDetail();
    const blackVariant = await screen.findByRole("option", { name: /Color: Black/ });

    await user.click(blackVariant);

    expect(blackVariant).toHaveAttribute("aria-selected", "true");
  });

  it("shows a not-found state for an unknown product", async () => {
    mockResponse({ detail: "Product not found" }, 404);
    renderDetail();

    expect(await screen.findByRole("heading", { name: "Product not found" })).toBeVisible();
    expect(screen.getByRole("link", { name: /Back to catalog/ })).toHaveAttribute("href", "/");
  });

  it("returns to the catalog", async () => {
    mockResponse(product);
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("link", { name: /Back to catalog/ }));

    expect(screen.getByRole("heading", { name: "Catalog route" })).toBeVisible();
  });
});
