from pathlib import Path

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
