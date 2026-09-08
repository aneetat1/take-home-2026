import extraction
from extraction import extract_page_evidence


def test_extracts_title_metadata_and_canonical_url() -> None:
    html = """
        <html>
          <head>
            <title>  Example   Product </title>
            <meta name="description" content=" A useful product. ">
            <meta property="og:image" content="first.jpg">
            <meta property="og:image" content="second.jpg">
            <link rel="canonical alternate" href="https://example.com/product">
          </head>
        </html>
    """

    evidence = extract_page_evidence(html)

    assert evidence.title == "Example Product"
    assert [(entry.name, entry.content) for entry in evidence.metadata] == [
        ("description", "A useful product."),
        ("og:image", "first.jpg"),
        ("og:image", "second.jpg"),
        ("canonical", "https://example.com/product"),
    ]


def test_preserves_json_ld_objects_arrays_and_graphs() -> None:
    html = """
        <script type="application/ld+json">
          {"@context": "https://schema.org", "@graph": [{"@type": "Product"}]}
        </script>
        <script type="application/ld+json; charset=utf-8">
          [{"@type": "BreadcrumbList"}, {"@type": "Organization"}]
        </script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.json_ld == [
        {
            "@context": "https://schema.org",
            "@graph": [{"@type": "Product"}],
        },
        [{"@type": "BreadcrumbList"}, {"@type": "Organization"}],
    ]


def test_json_ld_media_type_is_case_insensitive() -> None:
    html = """
        <script type="Application/LD+JSON; charset=UTF-8">
          {"@type": "Product"}
        </script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.json_ld == [{"@type": "Product"}]


def test_skips_malformed_json_ld_without_losing_valid_blocks() -> None:
    html = """
        <script type="application/ld+json">{"broken": }</script>
        <script type="application/ld+json">{"@type": "Product"}</script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.json_ld == [{"@type": "Product"}]


def test_extracts_standalone_and_assigned_json_without_executing_scripts() -> None:
    html = """
        <script type="application/json">{"price": 25, "currency": "USD"}</script>
        <script>
          window.PAGE_STATE = {"sizes": ["Small", "Large"]};
          const settings = [{"available": true}];
          dangerousFunction();
        </script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.embedded_json == [
        {"price": 25, "currency": "USD"},
        {"sizes": ["Small", "Large"]},
        [{"available": True}],
    ]


def test_skips_malformed_assignment_without_losing_later_valid_data() -> None:
    html = """
        <script>
          window.BROKEN = {"price": };
          window.VALID = {"price": 40};
        </script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.embedded_json == [{"price": 40}]


def test_deduplicates_identical_structured_values() -> None:
    html = """
        <script type="application/json">{"product": {"name": "Example"}}</script>
        <script>window.STATE = {"product": {"name": "Example"}};</script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.embedded_json == [{"product": {"name": "Example"}}]


def test_ignores_assignment_like_text_in_javascript_strings_and_comments() -> None:
    html = r'''
        <script>
          const message = 'window.FAKE = {"price": 10}';
          // window.COMMENTED = {"price": 20};
          /* window.ALSO_COMMENTED = {"price": 30}; */
          window.REAL = {"price": 40};
        </script>
    '''

    evidence = extract_page_evidence(html)

    assert evidence.embedded_json == [{"price": 40}]


def test_visible_text_excludes_non_rendered_content() -> None:
    html = """
        <head><title>Browser title</title></head>
        <main>
          <h1>Example Product</h1>
          <p>A   useful\n description.</p>
          <p hidden>Hidden attribute</p>
          <p aria-hidden="TRUE">Hidden from accessibility tree</p>
          <input type="HIDDEN" value="Hidden input">
          <svg><title>Decorative icon</title></svg>
          <script>window.STATE = {"secret": "script text"};</script>
          <style>.product { color: red; }</style>
          <template>Template text</template>
          <noscript>JavaScript fallback</noscript>
        </main>
    """

    evidence = extract_page_evidence(html)

    assert evidence.title == "Browser title"
    assert evidence.visible_text == "Example Product\nA useful description."


def test_handles_a_minimal_page() -> None:
    evidence = extract_page_evidence("<p>Hello</p>")

    assert evidence.title is None
    assert evidence.metadata == []
    assert evidence.json_ld == []
    assert evidence.embedded_json == []
    assert evidence.image_candidates == []
    assert evidence.video_candidates == []
    assert evidence.visible_text == "Hello"


def test_collects_markup_images_and_resolves_relative_urls() -> None:
    html = """
        <picture>
          <source srcset="/large.webp 1600w, /large-2x.webp 2x">
          <img
            src="/small.jpg"
            data-src="/lazy.jpg"
            data-zoom-image="/zoom.jpg"
            srcset="/medium.jpg 800w, https://cdn.example.com/full.jpg 2400w"
            width="400"
            height="500"
            alt="  Blue   chair  "
          >
        </picture>
    """

    evidence = extract_page_evidence(html, "https://shop.example.com/products/chair")

    assert [candidate.url for candidate in evidence.image_candidates] == [
        "https://shop.example.com/large.webp",
        "https://shop.example.com/large-2x.webp",
        "https://shop.example.com/small.jpg",
        "https://shop.example.com/lazy.jpg",
        "https://shop.example.com/zoom.jpg",
        "https://shop.example.com/medium.jpg",
        "https://cdn.example.com/full.jpg",
    ]
    assert evidence.image_candidates[0].width == 1600
    assert evidence.image_candidates[1].density == 2
    assert evidence.image_candidates[-1].width == 2400
    assert evidence.image_candidates[2].height == 500
    assert evidence.image_candidates[2].alt_text == "Blue chair"


def test_collects_metadata_media_and_removes_duplicate_urls() -> None:
    html = """
        <meta property="og:image" content="https://cdn.example.com/product.jpg">
        <meta property="twitter:image" content="https://cdn.example.com/product.jpg">
        <meta property="og:video" content="https://cdn.example.com/product.mp4">
        <img src="https://cdn.example.com/product.jpg">
    """

    evidence = extract_page_evidence(html)

    assert [candidate.url for candidate in evidence.image_candidates] == [
        "https://cdn.example.com/product.jpg"
    ]
    assert [candidate.url for candidate in evidence.video_candidates] == [
        "https://cdn.example.com/product.mp4"
    ]


def test_uses_document_base_url_when_source_url_is_not_supplied() -> None:
    html = """
        <base href="https://cdn.example.com/catalog/">
        <img src="product.jpg">
    """

    evidence = extract_page_evidence(html)

    assert evidence.image_candidates[0].url == (
        "https://cdn.example.com/catalog/product.jpg"
    )


def test_duplicate_media_keeps_later_resolution_evidence() -> None:
    html = """
        <img
          src="https://cdn.example.com/product.jpg"
          width="400"
          height="500"
        >
        <script type="application/ld+json">
          {"image": {
            "url": "https://cdn.example.com/product.jpg",
            "width": 2400,
            "height": 3000
          }}
        </script>
    """

    evidence = extract_page_evidence(html)

    assert len(evidence.image_candidates) == 1
    assert evidence.image_candidates[0].width == 2400
    assert evidence.image_candidates[0].height == 3000


def test_collects_video_sources_and_poster() -> None:
    html = """
        <video poster="/poster.jpg" src="/primary.mp4">
          <source src="/fallback.webm" type="video/webm">
        </video>
    """

    evidence = extract_page_evidence(html, "https://example.com/products/lamp")

    assert [candidate.url for candidate in evidence.image_candidates] == [
        "https://example.com/poster.jpg"
    ]
    assert [candidate.url for candidate in evidence.video_candidates] == [
        "https://example.com/primary.mp4",
        "https://example.com/fallback.webm",
    ]
    assert all(
        candidate.poster_url == "https://example.com/poster.jpg"
        for candidate in evidence.video_candidates
    )


def test_collects_images_from_structured_data() -> None:
    html = """
        <script type="application/ld+json">
          {
            "@type": "Product",
            "image": [
              "https://cdn.example.com/front.jpg",
              {"url": "/side.jpg", "width": 2000, "height": 2500}
            ]
          }
        </script>
        <script type="application/json">
          {"product": {"thumbnailUrl": "https://cdn.example.com/thumb.jpg"}}
        </script>
    """

    evidence = extract_page_evidence(html, "https://example.com/item")

    assert [candidate.url for candidate in evidence.image_candidates] == [
        "https://cdn.example.com/front.jpg",
        "https://example.com/side.jpg",
        "https://cdn.example.com/thumb.jpg",
    ]
    assert evidence.image_candidates[1].width == 2000
    assert evidence.image_candidates[1].height == 2500


def test_collects_video_objects_from_structured_data() -> None:
    html = """
        <script type="application/ld+json">
          {
            "@type": "VideoObject",
            "thumbnailUrl": "/poster.jpg",
            "contentUrl": "/demo.mp4",
            "embedUrl": "https://video.example.com/embed/123"
          }
        </script>
    """

    evidence = extract_page_evidence(html, "https://example.com/product")

    assert [candidate.url for candidate in evidence.video_candidates] == [
        "https://example.com/demo.mp4",
        "https://video.example.com/embed/123",
    ]
    assert all(
        candidate.poster_url == "https://example.com/poster.jpg"
        for candidate in evidence.video_candidates
    )


def test_collects_nested_mixed_media_renditions() -> None:
    html = """
        <script type="application/json">
          {"mediaObjects": [
            {
              "type": "image",
              "sources": {
                "thumbnail": {"url": "https://cdn.example.com/small.jpg"},
                "full": {"url": "https://cdn.example.com/full.jpg"}
              }
            },
            {
              "type": "video",
              "file": {"url": "https://cdn.example.com/demo.mp4"}
            }
          ]}
        </script>
    """

    evidence = extract_page_evidence(html)

    assert [candidate.url for candidate in evidence.image_candidates] == [
        "https://cdn.example.com/small.jpg",
        "https://cdn.example.com/full.jpg",
    ]
    assert [candidate.url for candidate in evidence.video_candidates] == [
        "https://cdn.example.com/demo.mp4"
    ]


def test_does_not_treat_unrelated_content_urls_as_video() -> None:
    html = """
        <script type="application/json">
          {"article": {"contentUrl": "https://example.com/story"}}
        </script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.video_candidates == []


def test_rejects_non_http_media_urls() -> None:
    html = """
        <img src="data:image/png;base64,abc">
        <img src="javascript:alert('x')">
        <img src="asset_identifier_123">
        <img src="//cdn.example.com/protocol-relative.jpg">
    """

    without_base = extract_page_evidence(html)
    with_base = extract_page_evidence(html, "https://example.com/product")

    assert [candidate.url for candidate in without_base.image_candidates] == [
        "https://cdn.example.com/protocol-relative.jpg"
    ]
    assert [candidate.url for candidate in with_base.image_candidates] == [
        "https://cdn.example.com/protocol-relative.jpg"
    ]


def test_structured_media_collection_obeys_candidate_limit(monkeypatch) -> None:
    monkeypatch.setattr(extraction, "MAX_MEDIA_CANDIDATES", 2)
    html = """
        <script type="application/json">
          {"images": [
            "https://cdn.example.com/one.jpg",
            "https://cdn.example.com/two.jpg",
            "https://cdn.example.com/three.jpg"
          ]}
        </script>
    """

    evidence = extract_page_evidence(html)

    assert [candidate.url for candidate in evidence.image_candidates] == [
        "https://cdn.example.com/one.jpg",
        "https://cdn.example.com/two.jpg",
    ]


def test_structured_media_collection_obeys_depth_limit(monkeypatch) -> None:
    monkeypatch.setattr(extraction, "MAX_STRUCTURED_MEDIA_DEPTH", 2)
    html = """
        <script type="application/json">
          {"images": {"large": {"asset": {"url": "https://example.com/deep.jpg"}}}}
        </script>
    """

    evidence = extract_page_evidence(html)

    assert evidence.image_candidates == []
