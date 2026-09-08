import json

import pytest

import evidence
from evidence import (
    image_url_by_reference,
    prepare_product_evidence,
    video_url_by_reference,
)
from models import (
    ImageCandidate,
    MetadataEntry,
    PageEvidence,
    VideoCandidate,
)


def make_page(**overrides) -> PageEvidence:
    values = {
        "title": "Example Product",
        "metadata": [],
        "json_ld": [],
        "embedded_json": [],
        "image_candidates": [],
        "video_candidates": [],
        "visible_text": "",
    }
    values.update(overrides)
    return PageEvidence(**values)


def test_prioritizes_product_json_ld() -> None:
    page = make_page(
        json_ld=[
            {"@type": "Organization", "name": "Example Store"},
            {"@type": "Product", "name": "Example Chair", "sku": "CHAIR-1"},
        ]
    )

    prepared = prepare_product_evidence(page)

    assert prepared.structured_data[0]["@type"] == "Product"
    assert prepared.structured_data[1]["@type"] == "Organization"


def test_recognizes_full_schema_type_urls() -> None:
    page = make_page(
        json_ld=[
            {"@type": "Organization", "name": "Example Store"},
            {
                "@type": "https://schema.org/Product/",
                "name": "Example Chair",
            },
        ]
    )

    prepared = prepare_product_evidence(page)

    assert prepared.structured_data[0]["name"] == "Example Chair"


def test_deduplicates_metadata_without_losing_repeated_names() -> None:
    page = make_page(
        metadata=[
            MetadataEntry(name="og:image", content="https://example.com/one.jpg"),
            MetadataEntry(name="og:image", content="https://example.com/one.jpg"),
            MetadataEntry(name="og:image", content="https://example.com/two.jpg"),
        ]
    )

    prepared = prepare_product_evidence(page)

    assert [(entry.name, entry.content) for entry in prepared.metadata] == [
        ("og:image", "https://example.com/one.jpg"),
        ("og:image", "https://example.com/two.jpg"),
    ]


def test_preserves_parent_keys_for_nested_product_records() -> None:
    page = make_page(
        embedded_json=[
            {
                "page": {
                    "product": {
                        "name": "Example Chair",
                        "brand": "Example",
                        "price": 125,
                        "currency": "USD",
                    }
                }
            }
        ]
    )

    prepared = prepare_product_evidence(page)

    assert any(
        record.get("page", {}).get("product", {}).get("name")
        == "Example Chair"
        for record in prepared.structured_data
        if isinstance(record, dict)
    )


def test_keeps_sparse_record_when_parent_key_supplies_product_context() -> None:
    page = make_page(
        embedded_json=[{"product": {"name": "Example Chair", "sku": "CHAIR-1"}}]
    )

    prepared = prepare_product_evidence(page)

    assert {"product": {"name": "Example Chair", "sku": "CHAIR-1"}} in (
        prepared.structured_data
    )


def test_removes_duplicate_structured_records() -> None:
    product = {
        "@type": "Product",
        "name": "Example Chair",
        "sku": "CHAIR-1",
    }
    page = make_page(json_ld=[product, product])

    prepared = prepare_product_evidence(page)

    assert prepared.structured_data == [product]


def test_bounds_strings_and_collections(monkeypatch) -> None:
    monkeypatch.setattr(evidence, "MAX_STRING_CHARACTERS", 20)
    monkeypatch.setattr(evidence, "MAX_LIST_ITEMS", 3)
    page = make_page(
        json_ld=[
            {
                "@type": "Product",
                "description": "x" * 100,
                "variants": list(range(10)),
            }
        ]
    )

    prepared = prepare_product_evidence(page)
    product = prepared.structured_data[0]

    assert len(product["description"]) == 20
    assert product["description"].endswith("…")
    assert product["variants"] == [0, 1, 2]


def test_serialized_output_stays_within_requested_budget() -> None:
    page = make_page(
        metadata=[MetadataEntry(name="description", content="m" * 10_000)],
        json_ld=[
            {
                "@type": "Product",
                "name": "Example Chair",
                "description": "d" * 10_000,
                "variants": [{"sku": f"SKU-{index}"} for index in range(200)],
            }
        ],
        visible_text="v" * 30_000,
        image_candidates=[
            ImageCandidate(url=f"https://example.com/{index}.jpg", source="test")
            for index in range(100)
        ],
    )

    prepared = prepare_product_evidence(page, max_characters=5_000)

    assert len(prepared.model_dump_json()) <= 5_000


def test_assigns_stable_media_references_and_preserves_exact_urls() -> None:
    page = make_page(
        image_candidates=[
            ImageCandidate(
                url="https://example.com/front.jpg?width=2400",
                source="img:srcset",
            ),
            ImageCandidate(url="https://example.com/back.jpg", source="json:image"),
        ],
        video_candidates=[
            VideoCandidate(url="https://example.com/demo.mp4", source="video:src")
        ],
    )

    first = prepare_product_evidence(page)
    second = prepare_product_evidence(page)

    assert [item.reference for item in first.image_candidates] == [
        "IMG_0001",
        "IMG_0002",
    ]
    assert [item.reference for item in second.image_candidates] == [
        "IMG_0001",
        "IMG_0002",
    ]
    assert image_url_by_reference(first) == {
        "IMG_0001": "https://example.com/front.jpg?width=2400",
        "IMG_0002": "https://example.com/back.jpg",
    }
    assert video_url_by_reference(first) == {
        "VID_0001": "https://example.com/demo.mp4"
    }
    assert all(item.reference is None for item in page.image_candidates)


def test_distillation_only_uses_values_from_the_source() -> None:
    page = make_page(
        embedded_json=[
            {
                "product": {
                    "name": "Source Name",
                    "brand": "Source Brand",
                    "price": 25,
                    "currency": "USD",
                }
            }
        ]
    )

    serialized = prepare_product_evidence(page).model_dump_json()

    for value in ("Source Name", "Source Brand", "USD"):
        assert value in serialized
    assert "Example Retailer" not in serialized


def test_handles_empty_and_minimal_pages() -> None:
    empty = prepare_product_evidence(make_page(title=None))
    minimal = prepare_product_evidence(
        make_page(title="Small item", visible_text="Small item\n$5.00")
    )

    assert empty.title is None
    assert empty.structured_data == []
    assert empty.image_candidates == []
    assert minimal.title == "Small item"
    assert minimal.visible_text == "Small item\n$5.00"


def test_rejects_unusably_small_budget() -> None:
    with pytest.raises(ValueError, match="at least"):
        prepare_product_evidence(make_page(), max_characters=100)


def test_product_evidence_can_be_serialized_as_json() -> None:
    prepared = prepare_product_evidence(make_page())

    assert json.loads(prepared.model_dump_json())["title"] == "Example Product"
