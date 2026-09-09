import json
import math
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import ImageCandidate, MetadataEntry, PageEvidence, ProductEvidence


DEFAULT_MAX_CHARACTERS = 100_000
MIN_MAX_CHARACTERS = 500
MAX_METADATA_ENTRIES = 50
MAX_METADATA_CONTENT_CHARACTERS = 2_000
MAX_VISIBLE_TEXT_CHARACTERS = 20_000
MAX_STRUCTURED_RECORDS = 50
MAX_STRUCTURED_DEPTH = 12
MAX_STRUCTURED_NODES = 5_000
MAX_DICTIONARY_ITEMS = 100
MAX_LIST_ITEMS = 100
MAX_STRING_CHARACTERS = 4_000
MAX_IMAGE_CANDIDATES = 500
MAX_VIDEO_CANDIDATES = 50
RENDITION_QUERY_PARAMETERS = {
    "dpr",
    "fit",
    "fm",
    "format",
    "h",
    "hei",
    "height",
    "q",
    "quality",
    "resmode",
    "w",
    "wid",
    "width",
}

HIGH_VALUE_SCHEMA_TYPES = {
    "product",
    "productgroup",
    "offer",
    "aggregateoffer",
    "videoobject",
}
HIGH_VALUE_METADATA_NAMES = {
    "description",
    "ogdescription",
    "ogimage",
    "ogpriceamount",
    "ogpricecurrency",
    "ogtitle",
    "productpriceamount",
    "productpricecurrency",
    "twitterdescription",
    "twitterimage",
    "twittertitle",
}
RELEVANT_FIELD_PARTS = {
    "availability",
    "answer",
    "barcode",
    "brand",
    "color",
    "choice",
    "currency",
    "description",
    "ean",
    "feature",
    "fit",
    "gtin",
    "image",
    "inventory",
    "item",
    "material",
    "media",
    "name",
    "offer",
    "option",
    "price",
    "product",
    "propert",
    "question",
    "selection",
    "size",
    "sku",
    "stock",
    "style",
    "title",
    "upc",
    "variant",
    "video",
}
CONTEXT_FIELD_KEYS = {"id", "label", "stringvalue", "type", "value"}


def prepare_product_evidence(
    page: PageEvidence,
    *,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> ProductEvidence:
    """Prepare deterministic, source-backed evidence within a serialized size limit."""

    if max_characters < MIN_MAX_CHARACTERS:
        raise ValueError(f"max_characters must be at least {MIN_MAX_CHARACTERS}")

    prepared = ProductEvidence(
        title=_truncate_text(page.title, MAX_STRING_CHARACTERS),
        metadata=[],
        structured_data=[],
        visible_text="",
        image_candidates=[],
        video_candidates=[],
    )
    if _serialized_length(prepared) > max_characters:
        prepared.title = None

    metadata_limit = max(MIN_MAX_CHARACTERS, int(max_characters * 0.10))
    visible_text_limit = max(MIN_MAX_CHARACTERS, int(max_characters * 0.30))
    structured_data_limit = max(MIN_MAX_CHARACTERS, int(max_characters * 0.70))

    for entry in _prioritize_metadata(page):
        candidate = entry.model_copy(
            update={
                "content": _truncate_text(
                    entry.content, MAX_METADATA_CONTENT_CHARACTERS
                )
            }
        )
        if not _append_within_budget(
            prepared, "metadata", candidate, metadata_limit
        ):
            continue

    prepared.visible_text = _fit_text(
        prepared,
        page.visible_text,
        min(MAX_VISIBLE_TEXT_CHARACTERS, len(page.visible_text)),
        visible_text_limit,
    )

    for value in _prioritized_structured_records(page):
        if not _append_within_budget(
            prepared, "structured_data", value, structured_data_limit
        ):
            continue

    preferred_images = _collapse_image_renditions(page.image_candidates)
    referenced_images = [
        candidate.model_copy(update={"reference": f"IMG_{index:04d}"})
        for index, candidate in enumerate(
            preferred_images[:MAX_IMAGE_CANDIDATES], start=1
        )
    ]
    referenced_videos = [
        candidate.model_copy(update={"reference": f"VID_{index:04d}"})
        for index, candidate in enumerate(
            page.video_candidates[:MAX_VIDEO_CANDIDATES], start=1
        )
    ]

    # Include a few images before reserving room for videos, then fill any
    # remaining budget with the rest of the image evidence.
    for referenced in referenced_images[:10]:
        _append_within_budget(
            prepared, "image_candidates", referenced, max_characters
        )
    for referenced in referenced_videos:
        if not _append_within_budget(
            prepared, "video_candidates", referenced, max_characters
        ):
            break
    for referenced in referenced_images[10:]:
        if not _append_within_budget(
            prepared, "image_candidates", referenced, max_characters
        ):
            break

    return prepared


def image_url_by_reference(evidence: ProductEvidence) -> dict[str, str]:
    """Return the exact image URLs associated with stable evidence references."""

    return {
        candidate.reference: candidate.url
        for candidate in evidence.image_candidates
        if candidate.reference is not None
    }


def video_url_by_reference(evidence: ProductEvidence) -> dict[str, str]:
    """Return the exact video URLs associated with stable evidence references."""

    return {
        candidate.reference: candidate.url
        for candidate in evidence.video_candidates
        if candidate.reference is not None
    }


def _collapse_image_renditions(
    candidates: list[ImageCandidate],
) -> list[ImageCandidate]:
    """Keep the largest URL when candidates differ only by render settings."""

    selected: list[ImageCandidate] = []
    indexes: dict[str, int] = {}
    for candidate in candidates:
        identity = _image_identity(candidate.url)
        if identity not in indexes:
            indexes[identity] = len(selected)
            selected.append(candidate)
            continue

        index = indexes[identity]
        if _image_resolution_score(candidate) > _image_resolution_score(
            selected[index]
        ):
            selected[index] = candidate
    return selected


def _image_identity(url: str) -> str:
    parsed = urlsplit(url)
    identity_query = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name.casefold() not in RENDITION_QUERY_PARAMETERS
    ]
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path,
            urlencode(sorted(identity_query)),
            "",
        )
    )


def _image_resolution_score(candidate: ImageCandidate) -> tuple[float, int]:
    query_items = parse_qsl(urlsplit(candidate.url).query)
    query = {name.casefold(): value for name, value in query_items}
    rendition_parameter_count = sum(
        name.casefold() in RENDITION_QUERY_PARAMETERS for name, _ in query_items
    )
    if rendition_parameter_count == 0:
        # A URL without resize instructions is the page's original rendition.
        return math.inf, 0
    declared_width = candidate.width or _positive_number(
        query.get("width") or query.get("wid") or query.get("w")
    )
    density = candidate.density or _positive_number(query.get("dpr")) or 1
    return declared_width * density, -rendition_parameter_count


def _positive_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _prioritize_metadata(page: PageEvidence) -> list[MetadataEntry]:
    indexed = list(enumerate(page.metadata))
    indexed.sort(
        key=lambda pair: (
            _semantic_key(pair[1].name) not in HIGH_VALUE_METADATA_NAMES,
            pair[0],
        )
    )
    unique: list[MetadataEntry] = []
    seen: set[tuple[str, str]] = set()
    for _, entry in indexed:
        fingerprint = (entry.name, entry.content)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(entry)
        if len(unique) >= MAX_METADATA_ENTRIES:
            break
    return unique


def _prioritized_structured_records(page: PageEvidence) -> list[Any]:
    ranked: list[tuple[int, int, Any]] = []
    order = 0

    for value in page.json_ld:
        priority = 100 if _contains_high_value_schema_type(value) else 50
        compacted = _compact_value(value)
        if compacted is not None:
            ranked.append((priority, order, compacted))
            order += 1

    for value in page.embedded_json:
        for score, path, record in _find_relevant_records(value):
            compacted = _compact_value(record)
            if compacted is None:
                continue
            wrapped = _wrap_with_parent_keys(path[-2:], compacted)
            ranked.append((score, order, wrapped))
            order += 1

    ranked.sort(key=lambda item: (-item[0], item[1]))
    unique: list[Any] = []
    seen: set[str] = set()
    for _, _, value in ranked:
        fingerprint = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(value)
        if len(unique) >= MAX_STRUCTURED_RECORDS:
            break
    return unique


def _find_relevant_records(
    value: Any,
) -> list[tuple[int, tuple[str, ...], dict[str, Any]]]:
    records: list[tuple[int, tuple[str, ...], dict[str, Any]]] = []
    visited = 0

    def walk(node: Any, path: tuple[str, ...], depth: int) -> None:
        nonlocal visited
        if depth > MAX_STRUCTURED_DEPTH or visited >= MAX_STRUCTURED_NODES:
            return
        visited += 1

        if isinstance(node, list):
            for item in node[:MAX_LIST_ITEMS]:
                walk(item, path, depth + 1)
            return
        if not isinstance(node, dict):
            return

        path_score = _field_score(_semantic_key(path[-1])) if path else 0
        score = _record_score(node) + min(path_score, 2)
        if score >= 3:
            records.append((score, path, node))

        prioritized_items = sorted(
            node.items(),
            key=lambda item: -_field_score(_semantic_key(str(item[0]))),
        )
        for key, child in prioritized_items[:MAX_DICTIONARY_ITEMS]:
            walk(child, path + (str(key),), depth + 1)

    walk(value, (), 0)
    return records


def _record_score(value: dict[str, Any]) -> int:
    score = 0
    schema_types = _schema_types(value.get("@type"))
    if schema_types & HIGH_VALUE_SCHEMA_TYPES:
        score += 10

    matched_parts: set[str] = set()
    for key in value:
        normalized = _semantic_key(str(key))
        matched_parts.update(
            part for part in RELEVANT_FIELD_PARTS if part in normalized
        )
    score += min(len(matched_parts), 8)
    return score


def _field_score(key: str) -> int:
    return sum(1 for part in RELEVANT_FIELD_PARTS if part in key)


def _contains_high_value_schema_type(value: Any) -> bool:
    remaining_nodes = MAX_STRUCTURED_NODES

    def contains(node: Any, depth: int) -> bool:
        nonlocal remaining_nodes
        if depth > MAX_STRUCTURED_DEPTH or remaining_nodes <= 0:
            return False
        remaining_nodes -= 1

        if isinstance(node, list):
            return any(contains(item, depth + 1) for item in node[:MAX_LIST_ITEMS])
        if not isinstance(node, dict):
            return False
        if _schema_types(node.get("@type")) & HIGH_VALUE_SCHEMA_TYPES:
            return True
        return any(contains(child, depth + 1) for child in node.values())

    return contains(value, 0)


def _schema_types(value: Any) -> set[str]:
    if isinstance(value, str):
        return {_normalize_schema_type(value)}
    if isinstance(value, list):
        return {
            _normalize_schema_type(item) for item in value if isinstance(item, str)
        }
    return set()


def _normalize_schema_type(value: str) -> str:
    return _semantic_key(re.split(r"[/#:]", value.rstrip("/#"))[-1])


def _compact_value(value: Any) -> Any | None:
    remaining_nodes = MAX_STRUCTURED_NODES

    def compact(node: Any, depth: int) -> Any | None:
        nonlocal remaining_nodes
        if depth > MAX_STRUCTURED_DEPTH or remaining_nodes <= 0:
            return None
        remaining_nodes -= 1

        if isinstance(node, str):
            return _truncate_text(node, MAX_STRING_CHARACTERS)
        if node is None or isinstance(node, (bool, int, float)):
            return node
        if isinstance(node, list):
            values = [compact(item, depth + 1) for item in node[:MAX_LIST_ITEMS]]
            return [item for item in values if item is not None]
        if isinstance(node, dict):
            items = sorted(
                node.items(),
                key=lambda item: -_field_score(_semantic_key(str(item[0]))),
            )
            if _record_score(node) >= 3:
                relevant_items = [
                    item
                    for item in items
                    if _field_score(_semantic_key(str(item[0]))) > 0
                    or _semantic_key(str(item[0])) in CONTEXT_FIELD_KEYS
                    or item[0] == "@type"
                ]
                if relevant_items:
                    items = relevant_items
            result: dict[str, Any] = {}
            for key, child in items[:MAX_DICTIONARY_ITEMS]:
                compacted = compact(child, depth + 1)
                if compacted is not None:
                    result[str(key)] = compacted
            return result
        return None

    return compact(value, 0)


def _wrap_with_parent_keys(path: tuple[str, ...], value: Any) -> Any:
    wrapped = value
    for key in reversed(path):
        wrapped = {key: wrapped}
    return wrapped


def _append_within_budget(
    evidence: ProductEvidence,
    field_name: str,
    value: Any,
    max_characters: int,
) -> bool:
    collection = getattr(evidence, field_name)
    collection.append(value)
    if _serialized_length(evidence) <= max_characters:
        return True
    collection.pop()
    return False


def _fit_text(
    evidence: ProductEvidence,
    value: str,
    maximum: int,
    max_characters: int,
) -> str:
    low = 0
    high = maximum
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = _truncate_text(value, middle)
        evidence.visible_text = candidate
        if _serialized_length(evidence) <= max_characters:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _truncate_text(value: str | None, maximum: int) -> str | None:
    if value is None or len(value) <= maximum:
        return value
    if maximum <= 1:
        return value[:maximum]
    return f"{value[: maximum - 1]}…"


def _serialized_length(evidence: ProductEvidence) -> int:
    return len(evidence.model_dump_json())


def _semantic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())
