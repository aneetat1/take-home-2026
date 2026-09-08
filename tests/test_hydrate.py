import asyncio
import json
from collections.abc import Callable

import pytest

import ai
import hydrate
from hydrate import (
    ProductHydrationError,
    find_category_candidates,
    hydrate_product,
)
from models import (
    CategorySelection,
    ExtractedCategory,
    Price,
    ProductDraft,
    VariantDraft,
    VariantDraftCollection,
    VariantOption,
)


LAMP_CATEGORY = "Home & Garden > Lighting > Lamps"


def make_draft(**overrides) -> ProductDraft:
    values = {
        "name": "Example Floor Lamp",
        "price": Price(price=125, currency="USD"),
        "description": "A tall floor lamp.",
        "key_features": ["Metal shade"],
        "image_ids": ["IMG_0001"],
        "video_id": None,
        "brand": "Example",
        "colors": ["White"],
        "variants": [],
        "category": ExtractedCategory(
            search_terms=["floor lamp", "lighting"],
            proposed_name=LAMP_CATEGORY,
        ),
    }
    values.update(overrides)
    return ProductDraft(**values)


def product_html() -> str:
    return """
        <html>
          <head><title>Example Floor Lamp</title></head>
          <body>
            <h1>Example Floor Lamp</h1>
            <img src="/images/lamp-full.jpg" alt="Example Floor Lamp">
          </body>
        </html>
    """


def install_ai_responses(
    monkeypatch,
    draft: ProductDraft | dict,
    selection: CategorySelection | dict | None = None,
) -> list[tuple[list[dict[str, str]], type]]:
    calls: list[tuple[list[dict[str, str]], type]] = []

    async def fake_responses(model, input, text_format=None, **kwargs):
        calls.append((input, text_format))
        if text_format is ProductDraft:
            return draft
        if text_format is CategorySelection:
            return selection or CategorySelection(name=LAMP_CATEGORY)
        raise AssertionError(f"Unexpected response schema: {text_format}")

    monkeypatch.setattr(ai, "responses", fake_responses)
    return calls


def run(coroutine: Callable):
    return asyncio.run(coroutine)


def test_passes_prepared_evidence_to_extraction_model(monkeypatch) -> None:
    calls = install_ai_responses(monkeypatch, make_draft())

    product = run(
        hydrate_product(product_html(), "https://shop.example.com/products/lamp")
    )

    evidence_payload = json.loads(calls[0][0][1]["content"])
    assert evidence_payload["title"] == "Example Floor Lamp"
    assert evidence_payload["image_candidates"][0]["reference"] == "IMG_0001"
    assert product.name == "Example Floor Lamp"


def test_resolves_media_references_to_exact_urls(monkeypatch) -> None:
    draft = make_draft(video_id="VID_0001")
    calls = []

    async def fake_responses(model, input, text_format=None, **kwargs):
        calls.append(text_format)
        if text_format is ProductDraft:
            return draft
        return CategorySelection(name=LAMP_CATEGORY)

    monkeypatch.setattr(ai, "responses", fake_responses)
    html = """
        <title>Example Floor Lamp</title>
        <img src="/images/lamp.jpg?width=2400">
        <video src="/videos/lamp.mp4"></video>
    """

    product = run(hydrate_product(html, "https://shop.example.com/products/lamp"))

    assert product.image_urls == [
        "https://shop.example.com/images/lamp.jpg?width=2400"
    ]
    assert product.video_url == "https://shop.example.com/videos/lamp.mp4"


def test_discards_unknown_media_references(monkeypatch) -> None:
    install_ai_responses(monkeypatch, make_draft(image_ids=["IMG_9999"]))

    product = run(hydrate_product(product_html(), "https://shop.example.com/product"))

    assert product.image_urls == []


def test_discards_unknown_video_reference(monkeypatch) -> None:
    install_ai_responses(monkeypatch, make_draft(video_id="VID_NOT_EVIDENCED"))

    product = run(hydrate_product(product_html(), "https://shop.example.com/product"))

    assert product.video_url is None


def test_category_selection_must_come_from_shortlist(monkeypatch) -> None:
    install_ai_responses(
        monkeypatch,
        make_draft(),
        CategorySelection(name="Invented > Category"),
    )

    with pytest.raises(ProductHydrationError, match="outside the supplied shortlist"):
        run(hydrate_product(product_html(), "https://shop.example.com/product"))


def test_rejects_malformed_category_response(monkeypatch) -> None:
    install_ai_responses(monkeypatch, make_draft(), selection={"category": "lamp"})

    with pytest.raises(ProductHydrationError, match="valid selection"):
        run(hydrate_product(product_html(), "https://shop.example.com/product"))


def test_final_category_validator_rejects_invalid_taxonomy_value(monkeypatch) -> None:
    invalid_category = "Invented > Category"
    install_ai_responses(
        monkeypatch,
        make_draft(),
        CategorySelection(name=invalid_category),
    )
    monkeypatch.setattr(
        hydrate,
        "find_category_candidates",
        lambda *args, **kwargs: [invalid_category],
    )

    with pytest.raises(ProductHydrationError, match="not in the Google"):
        run(hydrate_product(product_html(), "https://shop.example.com/product"))


def test_preserves_evidenced_variant_configurations(monkeypatch) -> None:
    variants = [
        VariantDraft(
            options=[
                VariantOption(name="Color", value="Navy"),
                VariantOption(name="Size", value="Large"),
            ],
            sku="CHAIR-NAVY-L",
            gtin=None,
            price=None,
            available=True,
            image_ids=["IMG_0001"],
        )
    ]
    install_ai_responses(monkeypatch, make_draft(variants=variants))

    product = run(
        hydrate_product(product_html(), "https://shop.example.com/products/lamp")
    )

    assert len(product.variants) == 1
    assert [(option.name, option.value) for option in product.variants[0].options] == [
        ("Color", "Navy"),
        ("Size", "Large"),
    ]
    assert product.variants[0].sku == "CHAIR-NAVY-L"


def test_preserves_multiple_variants_and_resolves_variant_images(monkeypatch) -> None:
    variants = [
        VariantDraft(
            options=[VariantOption(name="Color", value="Navy")],
            sku="CHAIR-NAVY",
            gtin=None,
            price=None,
            available=True,
            image_ids=["IMG_0001"],
        ),
        VariantDraft(
            options=[VariantOption(name="Color", value="Black")],
            sku="CHAIR-BLACK",
            gtin=None,
            price=None,
            available=False,
            image_ids=["IMG_0002"],
        ),
    ]
    install_ai_responses(monkeypatch, make_draft(variants=variants))
    html = """
        <img src="/images/navy.jpg">
        <img src="/images/black.jpg">
    """

    product = run(hydrate_product(html, "https://shop.example.com/products/chair"))

    assert [variant.sku for variant in product.variants] == [
        "CHAIR-NAVY",
        "CHAIR-BLACK",
    ]
    assert [variant.image_urls for variant in product.variants] == [
        ["https://shop.example.com/images/navy.jpg"],
        ["https://shop.example.com/images/black.jpg"],
    ]
    assert [variant.available for variant in product.variants] == [True, False]


def test_uses_focused_pass_when_explicit_variant_collection_is_larger(
    monkeypatch,
) -> None:
    initial_variant = VariantDraft(
        options=[VariantOption(name="Size", value="Small")],
        sku="SHIRT-S",
        gtin=None,
        price=None,
        available=True,
        image_ids=[],
    )
    complete_variants = [
        initial_variant,
        VariantDraft(
            options=[VariantOption(name="Size", value="Large")],
            sku="SHIRT-L",
            gtin=None,
            price=None,
            available=False,
            image_ids=[],
        ),
    ]
    schemas = []

    async def fake_responses(model, input, text_format=None, **kwargs):
        schemas.append(text_format)
        if text_format is ProductDraft:
            return make_draft(variants=[initial_variant])
        if text_format is VariantDraftCollection:
            return VariantDraftCollection(variants=complete_variants)
        return CategorySelection(name=LAMP_CATEGORY)

    monkeypatch.setattr(ai, "responses", fake_responses)
    html = """
        <script type="application/json">
          {"product": {
            "name": "Example Shirt",
            "skus": [
              {"sku": "SHIRT-S", "size": "Small"},
              {"sku": "SHIRT-L", "size": "Large"}
            ]
          }}
        </script>
    """

    product = run(hydrate_product(html))

    assert [variant.sku for variant in product.variants] == ["SHIRT-S", "SHIRT-L"]
    assert schemas == [ProductDraft, VariantDraftCollection, CategorySelection]


def test_discards_unknown_variant_media_reference(monkeypatch) -> None:
    variant = VariantDraft(
        options=[VariantOption(name="Color", value="Navy")],
        sku="CHAIR-NAVY",
        gtin=None,
        price=None,
        available=True,
        image_ids=["IMG_9999"],
    )
    install_ai_responses(monkeypatch, make_draft(variants=[variant]))

    product = run(hydrate_product(product_html(), "https://shop.example.com/product"))

    assert product.variants[0].image_urls == []


def test_rejects_malformed_extraction_response(monkeypatch) -> None:
    install_ai_responses(monkeypatch, {"name": "Incomplete"})

    with pytest.raises(ProductHydrationError, match="valid product draft"):
        run(hydrate_product(product_html(), "https://shop.example.com/product"))


def test_finds_exact_and_related_taxonomy_candidates() -> None:
    category = ExtractedCategory(
        search_terms=["floor lamp", "lighting"],
        proposed_name=LAMP_CATEGORY,
    )

    candidates = find_category_candidates(
        category,
        product_name="Example Floor Lamp",
        limit=10,
    )

    assert candidates[0] == LAMP_CATEGORY
    assert len(candidates) <= 10
    assert all("lamp" in candidate.casefold() for candidate in candidates[:2])


def test_returns_no_category_candidates_without_lexical_evidence() -> None:
    candidates = find_category_candidates(
        ExtractedCategory(search_terms=[], proposed_name=None),
        product_name="",
    )

    assert candidates == []


def test_tests_do_not_require_an_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    install_ai_responses(monkeypatch, make_draft())

    product = run(
        hydrate_product(product_html(), "https://shop.example.com/products/lamp")
    )

    assert product.category.name == LAMP_CATEGORY
