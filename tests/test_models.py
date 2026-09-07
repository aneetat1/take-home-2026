import pytest
from pydantic import ValidationError

from models import Category, Price, Product, Variant, VariantOption


def make_variant(**overrides) -> Variant:
    values = {
        "options": [
            VariantOption(name="Color", value="Navy"),
            VariantOption(name="Size", value="Large"),
        ],
        "sku": "SHIRT-NAVY-L",
        "gtin": "00123456789012",
        "price": None,
        "available": None,
        "image_urls": [],
    }
    values.update(overrides)
    return Variant(**values)


def test_variant_represents_multiple_options() -> None:
    variant = make_variant()

    assert [(option.name, option.value) for option in variant.options] == [
        ("Color", "Navy"),
        ("Size", "Large"),
    ]
    assert variant.available is None


def test_product_can_have_no_variants() -> None:
    product = Product(
        name="Desk Lamp",
        price=Price(price=50, currency="usd"),
        description="A compact desk lamp.",
        key_features=[],
        image_urls=[],
        video_url=None,
        category=Category(name="Home & Garden > Lighting > Lamps"),
        brand="Example",
        colors=[],
        variants=[],
    )

    assert product.variants == []
    assert product.price.currency == "USD"


@pytest.mark.parametrize(
    ("name", "value"),
    [("", "Large"), ("   ", "Large"), ("Size", ""), ("Size", "   ")],
)
def test_variant_option_rejects_blank_text(name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        VariantOption(name=name, value=value)


def test_variant_rejects_duplicate_option_names() -> None:
    with pytest.raises(ValidationError, match="cannot repeat an option name"):
        make_variant(
            options=[
                VariantOption(name="Size", value="Medium"),
                VariantOption(name=" size ", value="Large"),
            ]
        )


def test_variant_requires_at_least_one_option() -> None:
    with pytest.raises(ValidationError):
        make_variant(options=[])


def test_blank_optional_identifiers_become_none() -> None:
    variant = make_variant(sku="  ", gtin=" ")

    assert variant.sku is None
    assert variant.gtin is None


@pytest.mark.parametrize("field", ["price", "compare_at_price"])
def test_price_rejects_negative_values(field: str) -> None:
    values = {"price": 10, "currency": "USD", "compare_at_price": 20}
    values[field] = -1

    with pytest.raises(ValidationError):
        Price(**values)


def test_compare_at_price_cannot_be_lower_than_price() -> None:
    with pytest.raises(ValidationError, match="cannot be lower"):
        Price(price=20, compare_at_price=10, currency="USD")


def test_invalid_category_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not a valid category"):
        Category(name="Invented > Category")
