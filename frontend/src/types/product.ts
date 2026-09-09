export interface Price {
  price: number;
  currency: string;
  compare_at_price: number | null;
}

export interface Category {
  name: string;
}

export interface ProductSummary {
  id: string;
  name: string;
  price: Price;
  brand: string;
  category: Category;
  image_url: string | null;
}

export interface VariantOption {
  name: string;
  value: string;
}

export interface Variant {
  options: VariantOption[];
  sku: string | null;
  gtin: string | null;
  price: Price | null;
  available: boolean | null;
  image_urls: string[];
}

export interface Product {
  id: string;
  name: string;
  price: Price;
  description: string;
  key_features: string[];
  image_urls: string[];
  video_url: string | null;
  category: Category;
  brand: string;
  colors: string[];
  variants: Variant[];
}
