import type { Price } from "../types/product";

interface PriceDisplayProps {
  price: Price;
}

function formatPrice(value: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
  }).format(value);
}

export function PriceDisplay({ price }: PriceDisplayProps) {
  const hasDiscount =
    price.compare_at_price !== null && price.compare_at_price > price.price;

  return (
    <p className="price" aria-label={hasDiscount ? "Sale price" : "Price"}>
      <span className={hasDiscount ? "price__current price__current--sale" : "price__current"}>
        {formatPrice(price.price, price.currency)}
      </span>
      {hasDiscount && (
        <del className="price__original">
          {formatPrice(price.compare_at_price!, price.currency)}
        </del>
      )}
    </p>
  );
}
