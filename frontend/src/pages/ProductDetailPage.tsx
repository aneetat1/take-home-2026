import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getProduct } from "../api/products";
import { PriceDisplay } from "../components/PriceDisplay";
import type { Product, Variant } from "../types/product";

type DetailState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; product: Product };

export function ProductDetailPage() {
  const { productId = "" } = useParams();
  const [state, setState] = useState<DetailState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getProduct(productId, controller.signal)
      .then((product) => {
        setState(product ? { status: "ready", product } : { status: "not-found" });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Unable to load product",
        });
      });
    return () => controller.abort();
  }, [productId]);

  if (state.status === "loading") return <DetailLoading />;
  if (state.status === "not-found") {
    return <DetailMessage title="Product not found" message="This product is no longer in the catalog." />;
  }
  if (state.status === "error") {
    return <DetailMessage title="We couldn’t load this product" message={state.message} />;
  }
  return <ProductDetail product={state.product} />;
}

function ProductDetail({ product }: { product: Product }) {
  const [activeImage, setActiveImage] = useState(product.image_urls[0] ?? null);
  const [selectedVariantIndex, setSelectedVariantIndex] = useState(0);
  const selectedVariant = product.variants[selectedVariantIndex] ?? null;

  useEffect(() => {
    setActiveImage(product.image_urls[0] ?? null);
    setSelectedVariantIndex(0);
  }, [product]);

  const optionDimensions = useMemo(
    () => variantDimensions(product.variants),
    [product.variants],
  );

  function chooseVariant(index: number) {
    setSelectedVariantIndex(index);
  }

  return (
    <main className="detail">
      <Link className="detail__back" to="/">← Back to catalog</Link>
      <div className="detail__layout">
        <ProductGallery
          name={product.name}
          images={product.image_urls}
          activeImage={activeImage}
          onSelect={setActiveImage}
        />
        <section className="detail__info">
          <p className="detail__brand">{product.brand}</p>
          <h1>{product.name}</h1>
          <PriceDisplay price={selectedVariant?.price ?? product.price} />
          <p className="detail__description">{product.description}</p>

          {product.colors.length > 0 && (
            <DetailSection title="Colors">
              <div className="tag-list">
                {product.colors.map((color) => <span key={color}>{color}</span>)}
              </div>
            </DetailSection>
          )}

          {product.variants.length > 0 && (
            <DetailSection title="Available configurations">
              <div className="variant-list" role="listbox" aria-label="Product configurations">
                {product.variants.map((variant, index) => (
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === selectedVariantIndex}
                    className="variant-choice"
                    key={variantKey(variant, index)}
                    onClick={() => chooseVariant(index)}
                  >
                    <span>{variantLabel(variant)}</span>
                    <small>{availabilityLabel(variant.available)}</small>
                  </button>
                ))}
              </div>
              <p className="variant-summary">
                {product.variants.length} evidenced{" "}
                {product.variants.length === 1
                  ? "configuration"
                  : "configurations"}
                {optionDimensions.length > 0 && ` across ${optionDimensions.join(", ")}`}
              </p>
            </DetailSection>
          )}

          {product.key_features.length > 0 && (
            <DetailSection title="Product details">
              <ul className="feature-list">
                {product.key_features.map((feature) => <li key={feature}>{feature}</li>)}
              </ul>
            </DetailSection>
          )}

          {product.video_url && (
            <DetailSection title="Product video">
              <video className="detail__video" controls preload="metadata">
                <source src={product.video_url} />
                Your browser does not support embedded video.
              </video>
            </DetailSection>
          )}
        </section>
      </div>
    </main>
  );
}

interface ProductGalleryProps {
  name: string;
  images: string[];
  activeImage: string | null;
  onSelect: (image: string) => void;
}

function ProductGallery({ name, images, activeImage, onSelect }: ProductGalleryProps) {
  if (!activeImage) {
    return <div className="detail-gallery__empty">No product image available</div>;
  }
  return (
    <section className="detail-gallery" aria-label="Product images">
      <div className="detail-gallery__active">
        <img src={activeImage} alt={name} />
      </div>
      {images.length > 1 && (
        <div className="detail-gallery__thumbnails">
          {images.map((image, index) => (
            <button
              type="button"
              className={image === activeImage ? "thumbnail thumbnail--active" : "thumbnail"}
              aria-label={`View image ${index + 1} of ${images.length}`}
              aria-pressed={image === activeImage}
              key={image}
              onClick={() => onSelect(image)}
            >
              <img src={image} alt="" loading={index === 0 ? "eager" : "lazy"} />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="detail-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function DetailMessage({ title, message }: { title: string; message: string }) {
  return (
    <main className="detail detail-message">
      <h1>{title}</h1>
      <p>{message}</p>
      <Link className="detail__back" to="/">← Back to catalog</Link>
    </main>
  );
}

function DetailLoading() {
  return <main className="detail detail-message" aria-busy="true">Loading product…</main>;
}

function variantLabel(variant: Variant): string {
  return variant.options.map((option) => `${option.name}: ${option.value}`).join(" · ");
}

function variantKey(variant: Variant, index: number): string {
  return variant.sku ?? variant.gtin ?? `${variantLabel(variant)}-${index}`;
}

function availabilityLabel(available: boolean | null): string {
  if (available === true) return "Available";
  if (available === false) return "Unavailable";
  return "Availability unknown";
}

function variantDimensions(variants: Variant[]): string[] {
  const dimensions = new Map<string, string>();
  for (const variant of variants) {
    for (const option of variant.options) {
      dimensions.set(option.name.toLocaleLowerCase(), option.name);
    }
  }
  return [...dimensions.values()];
}
