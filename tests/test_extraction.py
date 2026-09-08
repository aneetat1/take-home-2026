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
    assert evidence.visible_text == "Hello"
