import { Route, Routes } from "react-router-dom";

import { CatalogPage } from "./pages/CatalogPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CatalogPage />} />
      <Route path="/products/:productId" element={<div aria-label="Product detail" />} />
    </Routes>
  );
}
