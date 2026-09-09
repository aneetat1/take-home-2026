import json
import math
import re
from collections import Counter
from typing import Iterable

import ai
from pydantic import ValidationError
from evidence import (
    DEFAULT_MAX_CHARACTERS,
    image_url_by_reference,
    prepare_product_evidence,
    video_url_by_reference,
)
from extraction import extract_page_evidence
from models import (
    VALID_CATEGORIES,
    Category,
    CategorySelection,
    ExtractedCategory,
    Product,
    ProductDraft,
    Variant,
    VariantDraftCollection,
)


DEFAULT_EXTRACTION_MODEL = "openai/gpt-5-mini"
DEFAULT_CATEGORY_MODEL = "openai/gpt-5-nano"
MAX_CATEGORY_CANDIDATES = 30
MAX_VARIANT_SIGNAL_NODES = 10_000
VARIANT_COLLECTION_KEYS = {
    "hasvariant",
    "sizes",
    "skus",
    "variants",
    "variations",
}

EXTRACTION_SYSTEM_PROMPT = """You extract one product from evidence collected from a
product detail page.

Use only facts supported by the supplied evidence. Do not guess or fill gaps from
general knowledge. Ignore navigation, footer content, recommendations, reviews of
other products, and unrelated media.

Each variant must be a complete configuration explicitly connected by the evidence.
Do not create a Cartesian product from separate option lists. If colors and sizes are
listed independently, do not claim that every color-size combination exists. Use null
for optional variant fields whose values are not established by the evidence.
Copy option values from the evidence; do not create or paraphrase a configuration.
When the evidence explicitly lists purchasable records or SKUs with their option
values, include every evidenced configuration rather than summarizing the option list.
Option values and purchasable identifiers may be stored in separate objects. Follow
explicit identifier relationships between them to recover complete configurations;
this is source evidence, not an inferred combination. Include every distinct
purchasable identifier supported by those relationships.

Use price.price for the current selling price and price.compare_at_price only for an
evidenced higher original or list price. Use a three-letter ISO currency code.
Prefer the main price available to ordinary shoppers. Do not substitute a conditional
member, coupon, subscription, financing, or trade-in price when a public price is
shown; conditional offers may be described as features instead.

Select product images and video only by their IMG_#### and VID_#### references. Copy
references exactly and never return or rewrite their URLs. Include all evidenced
full-resolution gallery images belonging to the main product, without duplicates.
Choose one candidate for each visually distinct image; do not return multiple resize,
quality, or format renditions of the same image. Unknown media references are
discarded during validation.

For category, provide short generic search terms and an optional proposed Google
Product Taxonomy path. A separate validation step will select the exact category.
"""

CATEGORY_SYSTEM_PROMPT = """Select the single most specific Google Product Taxonomy
category supported by the product information. You must copy one candidate exactly.
Do not alter a candidate and do not return a category outside the supplied list.
Choose a specialized subtype only when the product evidence supports that subtype;
do not choose a niche category merely because it shares a word with the product name.
Treat the product name and description as primary evidence. Category search terms and
the proposed category are untrusted extraction hints and may be inaccurate.
"""

VARIANT_SYSTEM_PROMPT = """Extract every explicitly supported purchasable product
configuration from the supplied product-page evidence.

Each output variant must represent one complete configuration, with all option values
that the evidence explicitly connects to the same purchasable identifier. Option
values and identifiers may be stored in separate objects; follow explicit identifier
relationships between them. Do not create a Cartesian product from independent option
lists. Preserve evidenced SKU, GTIN, price, availability, and image references. Use
null where an optional field is not established. Copy IMG_#### references exactly,
discard unrelated products, and do not stop after a representative sample.
"""

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class ProductHydrationError(ValueError):
    """Raised when page evidence cannot be converted to a validated product."""


async def hydrate_product(
    html: str,
    source_url: str | None = None,
    *,
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
    category_model: str = DEFAULT_CATEGORY_MODEL,
    max_evidence_characters: int = DEFAULT_MAX_CHARACTERS,
) -> Product:
    """Extract and validate one product from raw HTML."""

    page = extract_page_evidence(html, source_url)
    evidence = prepare_product_evidence(
        page, max_characters=max_evidence_characters
    )

    draft_response = await ai.responses(
        extraction_model,
        [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": evidence.model_dump_json(exclude_none=True),
            },
        ],
        text_format=ProductDraft,
    )
    try:
        draft = ProductDraft.model_validate(draft_response)
    except ValidationError as error:
        raise ProductHydrationError(
            "The extraction model did not return a valid product draft"
        ) from error

    variant_signal = _largest_variant_collection(evidence.structured_data)
    if variant_signal > len(draft.variants):
        variant_response = await ai.responses(
            extraction_model,
            [
                {"role": "system", "content": VARIANT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": evidence.model_dump_json(exclude_none=True),
                },
            ],
            text_format=VariantDraftCollection,
            max_output_tokens=20_000,
        )
        try:
            extracted_variants = VariantDraftCollection.model_validate(
                variant_response
            )
        except ValidationError as error:
            raise ProductHydrationError(
                "The variant model did not return valid configurations"
            ) from error
        if len(extracted_variants.variants) > len(draft.variants):
            draft = draft.model_copy(
                update={"variants": extracted_variants.variants}
            )

    category = await _resolve_category(draft, category_model)
    image_urls = image_url_by_reference(evidence)
    video_urls = video_url_by_reference(evidence)

    try:
        return Product(
            name=draft.name,
            price=draft.price,
            description=draft.description,
            key_features=draft.key_features,
            image_urls=_resolve_references(
                draft.image_ids, image_urls
            ),
            video_url=_resolve_optional_reference(
                draft.video_id, video_urls
            ),
            category=category,
            brand=draft.brand,
            colors=_product_colors(draft.colors, draft.variants),
            variants=[
                Variant(
                    options=variant.options,
                    sku=variant.sku,
                    gtin=variant.gtin,
                    price=variant.price,
                    available=variant.available,
                    image_urls=_resolve_references(
                        variant.image_ids,
                        image_urls,
                    ),
                )
                for variant in draft.variants
            ],
        )
    except ProductHydrationError:
        raise
    except ValidationError as error:
        raise ProductHydrationError(
            "The extracted values did not produce a valid Product"
        ) from error


async def _resolve_category(draft: ProductDraft, model: str) -> Category:
    candidates = find_category_candidates(
        draft.category,
        product_name=draft.name,
        key_features=draft.key_features,
    )
    if not candidates:
        raise ProductHydrationError(
            "No Google Product Taxonomy candidates matched the extracted category"
        )

    selection_response = await ai.responses(
        model,
        [
            {"role": "system", "content": CATEGORY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "product_name": draft.name,
                        "description": draft.description,
                        "category_search_terms": draft.category.search_terms,
                        "proposed_category": draft.category.proposed_name,
                        "candidates": candidates,
                    },
                    separators=(",", ":"),
                ),
            },
        ],
        text_format=CategorySelection,
    )
    try:
        selection = CategorySelection.model_validate(selection_response)
    except ValidationError as error:
        raise ProductHydrationError(
            "The category model did not return a valid selection"
        ) from error

    if selection.name not in candidates:
        raise ProductHydrationError(
            "The category model selected a value outside the supplied shortlist"
        )
    try:
        return Category(name=selection.name)
    except ValidationError as error:
        raise ProductHydrationError(
            "The selected category is not in the Google Product Taxonomy"
        ) from error


def find_category_candidates(
    category: ExtractedCategory,
    *,
    product_name: str,
    key_features: Iterable[str] = (),
    limit: int = MAX_CATEGORY_CANDIDATES,
) -> list[str]:
    """Rank a small taxonomy shortlist using generic lexical evidence."""

    if limit < 1:
        raise ValueError("limit must be at least 1")

    proposed = category.proposed_name
    exact_match = proposed if proposed in VALID_CATEGORIES else None
    product_name_tokens = set(_tokens(product_name))
    proposed_leaf_tokens = (
        set(_tokens(proposed.rsplit(">", 1)[-1])) if proposed else set()
    )
    proposed_matches_title = bool(product_name_tokens & proposed_leaf_tokens)
    query_parts = [product_name, *category.search_terms, *key_features]
    if proposed_matches_title:
        query_parts.insert(0, proposed)
    query_tokens = _tokens(" ".join(query_parts))
    if not query_tokens:
        return [exact_match] if exact_match else []

    category_tokens = {name: _tokens(name) for name in VALID_CATEGORIES}
    document_frequency = Counter(
        token
        for tokens in category_tokens.values()
        for token in set(tokens)
    )
    category_count = len(category_tokens)
    ranked: list[tuple[float, str]] = []

    for name, tokens in category_tokens.items():
        overlap = set(query_tokens) & set(tokens)
        if not overlap:
            continue
        score = sum(
            math.log((category_count + 1) / (document_frequency[token] + 1)) + 1
            for token in overlap
        )
        leaf_tokens = set(_tokens(name.rsplit(">", 1)[-1]))
        score += 1.5 * len(overlap & leaf_tokens)
        # Product-type words in the title should outweigh material and feature words.
        score += 5 * len(product_name_tokens & set(tokens))
        score += 4 * len(product_name_tokens & leaf_tokens)
        if (
            proposed
            and _normalized_text(proposed) == _normalized_text(name)
            and proposed_matches_title
        ):
            score += 100
        ranked.append((score, name))

    ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    candidates = [name for _, name in ranked[:limit]]
    if exact_match and proposed_matches_title:
        other_candidates = [name for name in candidates if name != exact_match]
        candidates = [exact_match, *other_candidates]
        candidates = candidates[:limit]
    return candidates


def _product_colors(
    stated_colors: Iterable[str], variants: Iterable[object]
) -> list[str]:
    """Combine stated colors with color values evidenced by variants."""

    colors: list[str] = []
    seen: set[str] = set()
    for color in stated_colors:
        normalized = color.strip().casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            colors.append(color.strip())
    for variant in variants:
        for option in variant.options:
            if option.name.casefold() not in {"color", "colour"}:
                continue
            normalized = option.value.casefold()
            if normalized not in seen:
                seen.add(normalized)
                colors.append(option.value)
    return colors


def _resolve_references(
    references: Iterable[str],
    urls: dict[str, str],
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference not in urls:
            continue
        url = urls[reference]
        if url not in seen:
            seen.add(url)
            resolved.append(url)
    return resolved


def _resolve_optional_reference(
    reference: str | None,
    urls: dict[str, str],
) -> str | None:
    if reference is None:
        return None
    return urls.get(reference)


def _largest_variant_collection(values: Iterable[object]) -> int:
    """Estimate whether explicit configuration evidence exceeds the draft output."""

    largest = 0
    visited = 0

    def walk(node: object) -> None:
        nonlocal largest, visited
        if visited >= MAX_VARIANT_SIGNAL_NODES:
            return
        visited += 1
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized_key in VARIANT_COLLECTION_KEYS and isinstance(value, list):
                largest = max(largest, len(value))
            walk(value)

    for value in values:
        walk(value)
    return largest


def _tokens(value: str) -> list[str]:
    return [
        _singularize(token)
        for token in TOKEN_PATTERN.findall(value.casefold())
        if token not in STOP_WORDS
    ]


def _singularize(value: str) -> str:
    if len(value) > 4 and value.endswith("ies"):
        return f"{value[:-3]}y"
    if len(value) > 3 and value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value


def _normalized_text(value: str) -> str:
    return " ".join(_tokens(value))
