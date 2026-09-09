import { Route, Routes } from "react-router-dom";

import { CatalogPage } from "./pages/CatalogPage";
import { ProductDetailPage } from "./pages/ProductDetailPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CatalogPage />} />
      <Route path="/products/:productId" element={<ProductDetailPage />} />
    </Routes>
  );
}
