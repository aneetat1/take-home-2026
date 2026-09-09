from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# Load categories once at module level
CATEGORIES_FILE = Path(__file__).parent / "categories.txt"
VALID_CATEGORIES = set()
if CATEGORIES_FILE.exists():
    with open(CATEGORIES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                VALID_CATEGORIES.add(line)


class Category(BaseModel):
    # A category from Google's Product Taxonomy
    # https://www.google.com/basepages/producttype/taxonomy.en-US.txt
    name: str

    @field_validator("name")
    @classmethod
    def validate_name_exists(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"Category '{v}' is not a valid category in categories.txt")
        return v


class Price(BaseModel):
    price: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    # If a product is on sale, this is the original price
    compare_at_price: float | None = Field(default=None, ge=0)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Currency must be a three-letter code")
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_compare_at_price(self) -> "Price":
        if self.compare_at_price is not None and self.compare_at_price < self.price:
            raise ValueError("Compare-at price cannot be lower than the selling price")
        return self


class VariantOption(BaseModel):
    """One named choice that helps identify a product configuration."""

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)

    @field_validator("name", "value", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Variant option text must be a string")
        return value.strip()


class Variant(BaseModel):
    """A product configuration explicitly supported by the page.

    Options are stored as name/value pairs so the model can represent
    dimensions beyond common choices such as size and color.
    """

    options: list[VariantOption] = Field(min_length=1)
    sku: str | None
    gtin: str | None
    price: Price | None  # Set only when the page associates a variant price
    available: bool | None  # None when the page does not establish availability
    image_urls: list[str]  # Images explicitly associated with this variant

    @field_validator("sku", "gtin", mode="before")
    @classmethod
    def normalize_optional_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Variant identifiers must be strings")
        return value.strip() or None

    @model_validator(mode="after")
    def validate_unique_option_names(self) -> "Variant":
        option_names = [option.name.casefold() for option in self.options]
        if len(option_names) != len(set(option_names)):
            raise ValueError("A variant cannot repeat an option name")
        return self


class MetadataEntry(BaseModel):
    """A named value read from an HTML metadata element."""

    name: str
    content: str


class ImageCandidate(BaseModel):
    """An image URL and any resolution information stated by the page."""

    reference: str | None = None
    url: str
    source: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    density: float | None = Field(default=None, gt=0)
    alt_text: str | None = None


class VideoCandidate(BaseModel):
    """A video URL found in markup, metadata, or structured page data."""

    reference: str | None = None
    url: str
    source: str
    poster_url: str | None = None


class PageEvidence(BaseModel):
    """Content recovered from a product page before AI interpretation."""

    title: str | None
    metadata: list[MetadataEntry]
    json_ld: list[Any]
    embedded_json: list[Any]
    image_candidates: list[ImageCandidate]
    video_candidates: list[VideoCandidate]
    visible_text: str


class ProductEvidence(BaseModel):
    """A bounded set of page evidence prepared for structured AI extraction."""

    title: str | None
    metadata: list[MetadataEntry]
    structured_data: list[Any]
    visible_text: str
    image_candidates: list[ImageCandidate]
    video_candidates: list[VideoCandidate]


class ExtractedCategory(BaseModel):
    """Taxonomy hints extracted from the page for local candidate retrieval."""

    search_terms: list[str]
    proposed_name: str | None


class VariantDraft(BaseModel):
    """A source-supported variant using media references instead of raw URLs."""

    options: list[VariantOption] = Field(min_length=1)
    sku: str | None
    gtin: str | None
    price: Price | None
    available: bool | None
    image_ids: list[str]


class ProductDraft(BaseModel):
    """Structured AI output before taxonomy and media references are resolved."""

    name: str = Field(min_length=1)
    price: Price
    description: str = Field(min_length=1)
    key_features: list[str]
    image_ids: list[str]
    video_id: str | None
    brand: str = Field(min_length=1)
    colors: list[str]
    variants: list[VariantDraft]
    category: ExtractedCategory

    @field_validator("name", "description", "brand", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Required product text must be a string")
        return value.strip()


class VariantDraftCollection(BaseModel):
    """Complete source-supported configurations recovered from product evidence."""

    variants: list[VariantDraft]


class CategorySelection(BaseModel):
    """The exact Google taxonomy category selected from a supplied shortlist."""

    name: str


# This is the final product schema that you need to output.
# You may add additional models as needed.
class Product(BaseModel):
    name: str
    price: Price
    description: str
    key_features: list[str]
    image_urls: list[str]
    video_url: str | None = None
    category: Category
    brand: str
    colors: list[str]
    # Include only option combinations supported by the source data.
    # Do not generate every possible combination of independent option lists.
    variants: list[Variant]


class CatalogProduct(Product):
    """A persisted product with the stable identifier used by the API."""

    id: str = Field(min_length=1)


class ProductSummary(BaseModel):
    """The subset of product data needed to render a catalog card."""

    id: str
    name: str
    price: Price
    brand: str
    category: Category
    image_url: str | None
