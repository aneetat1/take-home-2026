import json
import re
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from models import ImageCandidate, MetadataEntry, PageEvidence, VideoCandidate


MAX_SCRIPT_CHARACTERS = 2_000_000
MAX_EMBEDDED_JSON_VALUES = 100
MAX_STRUCTURED_MEDIA_NODES = 50_000
MAX_STRUCTURED_MEDIA_DEPTH = 30
MAX_MEDIA_CANDIDATES = 2_000

IMAGE_ATTRIBUTES = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-image",
    "data-image-url",
    "data-zoom-image",
    "data-large-image",
)
SRCSET_ATTRIBUTES = ("srcset", "data-srcset", "data-lazy-srcset")
IMAGE_KEYS = {
    "image",
    "images",
    "imageurl",
    "imageurls",
    "thumbnail",
    "thumbnailurl",
    "thumbnailurls",
    "primaryimage",
    "primaryimageurl",
}
VIDEO_KEYS = {
    "video",
    "videos",
    "videourl",
    "videourls",
    "contenturl",
    "embedurl",
}
POSTER_KEYS = {"poster", "posterurl", "thumbnail", "thumbnailurl"}
URL_KEYS = {"url", "src", "href", "contenturl", "embedurl"}
VIDEO_EXTENSIONS = {".mp4", ".m3u8", ".mov", ".webm", ".m4v", ".avi"}

ImageAdder = Callable[..., str | None]
VideoAdder = Callable[..., None]

JSON_ASSIGNMENT_PATTERN = re.compile(
    r"(?:(?:var|let|const)\s+)?"
    r"(?:window\.)?[A-Za-z_$][\w$]*"
    r"(?:\.[A-Za-z_$][\w$]*)*\s*=\s*"
)


def extract_page_evidence(html: str, source_url: str | None = None) -> PageEvidence:
    """Collect page evidence without making assumptions about a site's layout."""

    soup = BeautifulSoup(html, "lxml")
    metadata = _extract_metadata(soup)
    json_ld = _extract_json_ld(soup)
    embedded_json = _extract_embedded_json(soup)
    base_url = _find_base_url(soup, metadata, source_url)
    image_candidates, video_candidates = _extract_media_candidates(
        soup,
        metadata,
        json_ld,
        embedded_json,
        base_url,
    )

    return PageEvidence(
        title=_extract_title(soup),
        metadata=metadata,
        json_ld=json_ld,
        embedded_json=embedded_json,
        image_candidates=image_candidates,
        video_candidates=video_candidates,
        visible_text=_extract_visible_text(soup),
    )


def _extract_media_candidates(
    soup: BeautifulSoup,
    metadata: list[MetadataEntry],
    json_ld: list[Any],
    embedded_json: list[Any],
    source_url: str | None,
) -> tuple[list[ImageCandidate], list[VideoCandidate]]:
    images: list[ImageCandidate] = []
    videos: list[VideoCandidate] = []
    image_indexes: dict[str, int] = {}
    video_indexes: dict[str, int] = {}

    def add_image(
        value: Any,
        source: str,
        *,
        width: int | None = None,
        height: int | None = None,
        density: float | None = None,
        alt_text: str | None = None,
    ) -> str | None:
        url = _normalize_media_url(value, source_url)
        if url is None:
            return None
        if url in image_indexes:
            existing = images[image_indexes[url]]
            existing.width = _larger_value(existing.width, width)
            existing.height = _larger_value(existing.height, height)
            existing.density = _larger_value(existing.density, density)
            existing.alt_text = existing.alt_text or _optional_text(alt_text)
        elif len(images) < MAX_MEDIA_CANDIDATES:
            image_indexes[url] = len(images)
            images.append(
                ImageCandidate(
                    url=url,
                    source=source,
                    width=width,
                    height=height,
                    density=density,
                    alt_text=_optional_text(alt_text),
                )
            )
        return url

    def add_video(
        value: Any,
        source: str,
        *,
        poster_url: str | None = None,
    ) -> None:
        url = _normalize_media_url(value, source_url)
        if url is None:
            return
        if url in video_indexes:
            existing = videos[video_indexes[url]]
            existing.poster_url = existing.poster_url or poster_url
        elif len(videos) < MAX_MEDIA_CANDIDATES:
            video_indexes[url] = len(videos)
            videos.append(VideoCandidate(url=url, source=source, poster_url=poster_url))

    for element in soup.find_all(("img", "source")):
        if not isinstance(element, Tag):
            continue
        if element.name == "source" and element.find_parent("picture") is None:
            continue
        alt_text = element.get("alt") if element.name == "img" else None
        width = _positive_int(element.get("width"))
        height = _positive_int(element.get("height"))
        attributes = IMAGE_ATTRIBUTES if element.name == "img" else ()
        for attribute in attributes:
            add_image(
                element.get(attribute),
                f"{element.name}:{attribute}",
                width=width,
                height=height,
                alt_text=alt_text if isinstance(alt_text, str) else None,
            )
        for attribute in SRCSET_ATTRIBUTES:
            value = element.get(attribute)
            if not isinstance(value, str):
                continue
            for url, candidate_width, density in _parse_srcset(value):
                add_image(
                    url,
                    f"{element.name}:{attribute}",
                    width=candidate_width,
                    density=density,
                    alt_text=alt_text if isinstance(alt_text, str) else None,
                )

    for element in soup.find_all("video"):
        if not isinstance(element, Tag):
            continue
        poster_url = add_image(element.get("poster"), "video:poster")
        add_video(element.get("src"), "video:src", poster_url=poster_url)
        for source in element.find_all("source", src=True):
            add_video(source.get("src"), "video:source", poster_url=poster_url)

    for entry in metadata:
        key = _semantic_key(entry.name)
        if "image" in key:
            add_image(entry.content, f"metadata:{entry.name}")
        elif "video" in key:
            add_video(entry.content, f"metadata:{entry.name}")

    for value in json_ld:
        _collect_structured_media(value, "json_ld", add_image, add_video)
    for value in embedded_json:
        _collect_structured_media(value, "embedded_json", add_image, add_video)

    return images, videos


def _collect_structured_media(
    value: Any,
    source: str,
    add_image: ImageAdder,
    add_video: VideoAdder,
) -> None:
    """Walk structured data using media field names rather than site-specific paths."""

    visited = 0

    def walk(
        node: Any,
        context: str | None = None,
        depth: int = 0,
        width: int | None = None,
        height: int | None = None,
        poster_url: str | None = None,
    ) -> None:
        nonlocal visited
        if depth > MAX_STRUCTURED_MEDIA_DEPTH or visited >= MAX_STRUCTURED_MEDIA_NODES:
            return
        visited += 1

        if isinstance(node, list):
            for item in node:
                walk(item, context, depth + 1, width, height, poster_url)
            return
        if not isinstance(node, dict):
            if context == "image":
                add_image(
                    node,
                    f"{source}:image",
                    width=width,
                    height=height,
                )
            elif context == "video":
                add_video(node, f"{source}:video", poster_url=poster_url)
            elif context == "media":
                if _looks_like_video_url(node):
                    add_video(node, f"{source}:video", poster_url=poster_url)
                else:
                    add_image(
                        node,
                        f"{source}:image",
                        width=width,
                        height=height,
                    )
            return

        object_width = _positive_int(node.get("width")) or width
        object_height = _positive_int(node.get("height")) or height
        object_type = str(node.get("@type", "")).casefold()
        declared_type = str(node.get("type", "")).casefold()
        is_video_object = "videoobject" in object_type
        object_context = context
        if context == "media":
            if "video" in declared_type:
                object_context = "video"
            elif "image" in declared_type:
                object_context = "image"
        object_poster_url = poster_url
        if is_video_object:
            for key, child in node.items():
                if _semantic_key(str(key)) in POSTER_KEYS:
                    object_poster_url = _first_media_url(child)
                    if object_poster_url is not None:
                        object_poster_url = add_image(
                            object_poster_url, f"{source}:video-poster"
                        )
                        break

        for key, child in node.items():
            normalized_key = _semantic_key(str(key))
            child_context = None
            if _is_image_key(normalized_key):
                child_context = "image"
            elif _is_video_key(normalized_key) and (
                normalized_key not in {"contenturl", "embedurl"} or is_video_object
            ):
                child_context = "video"
            elif _is_media_key(normalized_key):
                child_context = "media"
            elif object_context is not None and normalized_key in URL_KEYS:
                child_context = object_context
            elif object_context is not None and isinstance(child, (dict, list)):
                # Media containers often group renditions under names such as
                # "portrait" or "large" before reaching a conventional URL key.
                child_context = object_context
            walk(
                child,
                child_context,
                depth + 1,
                object_width,
                object_height,
                object_poster_url,
            )

    walk(value)


def _find_base_url(
    soup: BeautifulSoup,
    metadata: list[MetadataEntry],
    source_url: str | None,
) -> str | None:
    if source_url:
        return source_url

    base = soup.find("base", href=True)
    if isinstance(base, Tag):
        href = base.get("href")
        if isinstance(href, str) and _normalize_media_url(href, None):
            return href

    for entry in metadata:
        if entry.name.casefold() == "canonical" and _normalize_media_url(
            entry.content, None
        ):
            return entry.content
    return None


def _first_media_url(value: Any) -> Any | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            candidate = _first_media_url(item)
            if candidate is not None:
                return candidate
    if isinstance(value, dict):
        for key, child in value.items():
            if _semantic_key(str(key)) in URL_KEYS:
                return child
    return None


def _parse_srcset(value: str) -> list[tuple[str, int | None, float | None]]:
    candidates: list[tuple[str, int | None, float | None]] = []
    for item in value.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        width = None
        density = None
        if len(parts) > 1:
            descriptor = parts[-1].casefold()
            try:
                if descriptor.endswith("w"):
                    width = int(descriptor[:-1])
                elif descriptor.endswith("x"):
                    density = float(descriptor[:-1])
            except ValueError:
                pass
        candidates.append((parts[0], width, density))
    return candidates


def _normalize_media_url(value: Any, source_url: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw_url = value.strip()
    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"
    elif not urlparse(raw_url).scheme and not _looks_like_relative_url(raw_url):
        return None
    url = urljoin(source_url, raw_url) if source_url else raw_url
    parsed = urlparse(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _looks_like_relative_url(value: str) -> bool:
    if value.startswith(("/", "./", "../")) or "/" in value:
        return True
    path = value.partition("?")[0].partition("#")[0]
    return bool(re.search(r"\.[a-z0-9]{2,5}$", path, re.I))


def _semantic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _is_image_key(key: str) -> bool:
    return (
        key in IMAGE_KEYS
        or key.endswith(("image", "images", "imageurl", "imageurls"))
        or key.startswith("image")
    )


def _is_video_key(key: str) -> bool:
    return (
        key in VIDEO_KEYS
        or key.endswith(("video", "videos", "videourl", "videourls"))
        or key.startswith("video")
    )


def _is_media_key(key: str) -> bool:
    return key.startswith("media") or key.endswith(
        ("media", "mediaobject", "mediaobjects")
    )


def _looks_like_video_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    path = urlparse(value).path.casefold()
    return any(path.endswith(extension) for extension in VIDEO_EXTENSIONS)


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _larger_value[T: int | float](first: T | None, second: T | None) -> T | None:
    values = [value for value in (first, second) if value is not None]
    return max(values, default=None)


def _optional_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _normalize_text(value)
    return normalized or None


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
