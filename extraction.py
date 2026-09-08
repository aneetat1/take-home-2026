import json
import re
from typing import Any

from bs4 import BeautifulSoup

from models import MetadataEntry, PageEvidence


MAX_SCRIPT_CHARACTERS = 2_000_000
MAX_EMBEDDED_JSON_VALUES = 100

JSON_ASSIGNMENT_PATTERN = re.compile(
    r"(?:(?:var|let|const)\s+)?"
    r"(?:window\.)?[A-Za-z_$][\w$]*"
    r"(?:\.[A-Za-z_$][\w$]*)*\s*=\s*"
)


def extract_page_evidence(html: str) -> PageEvidence:
    """Collect page evidence without making assumptions about a site's layout."""

    soup = BeautifulSoup(html, "lxml")

    return PageEvidence(
        title=_extract_title(soup),
        metadata=_extract_metadata(soup),
        json_ld=_extract_json_ld(soup),
        embedded_json=_extract_embedded_json(soup),
        visible_text=_extract_visible_text(soup),
    )


def _extract_title(soup: BeautifulSoup) -> str | None:
    if soup.title is None:
        return None

    title = _normalize_text(soup.title.get_text(" ", strip=True))
    return title or None


def _extract_metadata(soup: BeautifulSoup) -> list[MetadataEntry]:
    entries: list[MetadataEntry] = []

    for element in soup.find_all("meta"):
        name = next(
            (
                element.get(attribute)
                for attribute in ("property", "name", "itemprop", "http-equiv")
                if element.get(attribute)
            ),
            None,
        )
        content = element.get("content")
        if not isinstance(name, str) or not isinstance(content, str):
            continue

        normalized_name = _normalize_text(name)
        normalized_content = _normalize_text(content)
        if normalized_name and normalized_content:
            entries.append(
                MetadataEntry(name=normalized_name, content=normalized_content)
            )

    for element in soup.find_all("link", rel=True, href=True):
        relationships = element.get("rel", [])
        if isinstance(relationships, str):
            relationships = relationships.split()
        if "canonical" not in {relationship.casefold() for relationship in relationships}:
            continue

        href = element.get("href")
        if isinstance(href, str) and href.strip():
            entries.append(MetadataEntry(name="canonical", content=href.strip()))

    return entries


def _extract_json_ld(soup: BeautifulSoup) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()

    for script in soup.find_all("script"):
        media_type = _script_media_type(script.get("type"))
        if media_type != "application/ld+json":
            continue

        value = _decode_json(script.string or script.get_text())
        if value is not None:
            _append_unique(values, seen, value)

    return values


def _extract_embedded_json(soup: BeautifulSoup) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()

    for script in soup.find_all("script"):
        if len(values) >= MAX_EMBEDDED_JSON_VALUES:
            break

        media_type = _script_media_type(script.get("type"))
        if media_type == "application/ld+json":
            continue

        content = script.string or script.get_text()
        if not content or len(content) > MAX_SCRIPT_CHARACTERS:
            continue

        whole_value = _decode_json(content)
        if whole_value is not None:
            _append_unique(values, seen, whole_value)
            continue

        for value in _decode_json_assignments(content):
            _append_unique(values, seen, value)
            if len(values) >= MAX_EMBEDDED_JSON_VALUES:
                break

    return values


def _decode_json_assignments(script: str) -> list[Any]:
    values: list[Any] = []
    decoder = json.JSONDecoder()
    code_mask = _mask_javascript_strings_and_comments(script)

    for match in JSON_ASSIGNMENT_PATTERN.finditer(code_mask):
        remainder = script[match.end() :].lstrip()
        if not remainder.startswith(("{", "[")):
            continue

        try:
            value, _ = decoder.raw_decode(remainder)
        except (json.JSONDecodeError, RecursionError):
            continue
        values.append(value)

    return values


def _mask_javascript_strings_and_comments(script: str) -> str:
    """Hide strings and comments while preserving positions in JavaScript source."""

    masked = list(script)
    index = 0

    while index < len(script):
        character = script[index]

        if character in ("'", '"', "`"):
            quote = character
            masked[index] = " "
            index += 1
            while index < len(script):
                masked[index] = "\n" if script[index] == "\n" else " "
                if script[index] == "\\":
                    index += 1
                    if index < len(script):
                        masked[index] = "\n" if script[index] == "\n" else " "
                elif script[index] == quote:
                    index += 1
                    break
                index += 1
            continue

        if script.startswith("//", index):
            while index < len(script) and script[index] != "\n":
                masked[index] = " "
                index += 1
            continue

        if script.startswith("/*", index):
            while index < len(script):
                if script.startswith("*/", index):
                    masked[index] = masked[index + 1] = " "
                    index += 2
                    break
                masked[index] = "\n" if script[index] == "\n" else " "
                index += 1
            continue

        index += 1

    return "".join(masked)


def _extract_visible_text(soup: BeautifulSoup) -> str:
    # These elements contain code or fallback markup rather than rendered page text.
    for element in soup.find_all(
        ("head", "script", "style", "template", "noscript", "svg")
    ):
        element.decompose()

    # Standard HTML visibility markers can be handled without knowing site CSS.
    for element in soup.find_all(hidden=True):
        element.decompose()
    for element in soup.find_all(attrs={"aria-hidden": re.compile(r"^true$", re.I)}):
        element.decompose()
    for element in soup.find_all("input", attrs={"type": re.compile(r"^hidden$", re.I)}):
        element.decompose()

    lines = (
        normalized
        for text in soup.stripped_strings
        if (normalized := _normalize_text(text))
    )
    return "\n".join(lines)


def _script_media_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.partition(";")[0].strip().casefold()


def _decode_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        return None


def _append_unique(values: list[Any], seen: set[str], value: Any) -> None:
    fingerprint = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if fingerprint not in seen:
        seen.add(fingerprint)
        values.append(value)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())
