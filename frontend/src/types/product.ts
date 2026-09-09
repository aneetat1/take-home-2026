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
