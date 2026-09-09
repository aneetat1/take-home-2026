import { Link } from "react-router-dom";

import type { ProductSummary } from "../types/product";
import { PriceDisplay } from "./PriceDisplay";

interface ProductCardProps {
  product: ProductSummary;
}

export function ProductCard({ product }: ProductCardProps) {
  return (
    <article className="product-card">
      <Link className="product-card__link" to={`/products/${product.id}`}>
        <div className="product-card__media">
          {product.image_url ? (
            <img
              className="product-card__image"
              src={product.image_url}
              alt={product.name}
              loading="lazy"
            />
          ) : (
            <div className="product-card__image-placeholder" aria-hidden="true">
              No image
            </div>
          )}
        </div>
        <div className="product-card__body">
          <p className="product-card__brand">{product.brand}</p>
          <h2 className="product-card__name">{product.name}</h2>
          <PriceDisplay price={product.price} />
        </div>
      </Link>
    </article>
  );
}
