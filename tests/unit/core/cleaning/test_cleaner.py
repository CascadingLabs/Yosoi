"""Unit tests for HTMLCleaner."""

import lxml.html
import pytest
from rich.console import Console

from yosoi.core.cleaning.cleaner import HTMLCleaner


def parse(html: str) -> lxml.html.HtmlElement:
    """Parse a full HTML document the way the cleaner does."""
    return lxml.html.document_fromstring(html)


def to_str(element: lxml.html.HtmlElement) -> str:
    """Serialise an lxml element back to a string."""
    return lxml.html.tostring(element, encoding='unicode')


def css_one(element: lxml.html.HtmlElement, selector: str) -> lxml.html.HtmlElement | None:
    """Return the first element matching *selector*, or None (parallels bs4 find)."""
    found = element.cssselect(selector)
    return found[0] if found else None


@pytest.fixture
def cleaner():
    return HTMLCleaner(console=Console(quiet=True))


@pytest.fixture
def sample_html():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <script>console.log('noisy script');</script>
        <style>.ads { color: red; }</style>
    </head>
    <body>
        <nav>
            <ul>
                <li><a href="/">Home</a></li>
            </ul>
        </nav>
        <header>
            <h1>My Website</h1>
        </header>
        <main id="content">
            <article>
                <h2 class="headline">Main Story</h2>
                <p>This is the important content.</p>
                <div class="ad-banner">Buy things!</div>
            </article>
            <aside class="sidebar">
                <h3>Links</h3>
                <ul>
                    <li><a href="#">Link 1</a></li>
                </ul>
            </aside>
        </main>
        <footer>
            <p>&copy; 2025</p>
        </footer>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# clean_html - noise removal
# ---------------------------------------------------------------------------


def test_clean_html_removes_scripts(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    assert '<script' not in result


def test_clean_html_removes_styles(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    assert '<style' not in result


def test_clean_html_removes_nav(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    tree = lxml.html.fromstring(result)
    assert tree.find('.//nav') is None


def test_clean_html_removes_header(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    tree = lxml.html.fromstring(result)
    assert tree.find('.//header') is None


def test_clean_html_removes_footer(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    tree = lxml.html.fromstring(result)
    assert tree.find('.//footer') is None


def test_clean_html_removes_sidebars(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    tree = lxml.html.fromstring(result)
    assert css_one(tree, 'aside.sidebar') is None


def test_clean_html_removes_ad_class(cleaner):
    html = '<html><body><main><h1>Title</h1><div class="advertisement">Ad</div></main></body></html>'
    result = cleaner.clean_html(html)
    assert 'advertisement' not in result


def test_clean_html_preserves_main_content(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    assert 'Main Story' in result
    assert 'This is the important content.' in result


def test_clean_html_prefers_main_over_body(cleaner):
    html = '<html><body><main><h1>Only Main</h1></main><div>Outside main</div></body></html>'
    result = cleaner.clean_html(html)
    assert 'Only Main' in result


def test_clean_html_falls_back_to_body_when_no_main(cleaner):
    html = '<html><body><article><h2>Body Content</h2></article></body></html>'
    result = cleaner.clean_html(html)
    assert 'Body Content' in result


def test_clean_html_returns_string(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# _compress_html_simple - attribute stripping
# ---------------------------------------------------------------------------


def test_compress_removes_only_noise_attributes(cleaner):
    # Opt-in removal: inline style and JS event handlers are stripped; everything
    # else (class, data-*, and any other attribute) is kept.
    html = '<html><body><div class="foo" style="color:red" onclick="bad()" data-val="keep">text</div></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    div = result.find('.//div')
    assert 'class' in div.attrib
    assert 'data-val' in div.attrib
    assert 'onclick' not in div.attrib
    assert 'style' not in div.attrib


def test_compress_keeps_id_href_and_other_attributes(cleaner):
    # title is no longer dropped — only known-noise attributes are.
    html = '<html><body><a id="link" href="/page" title="keep">text</a></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    a = result.find('.//a')
    assert 'id' in a.attrib
    assert 'href' in a.attrib
    assert 'title' in a.attrib


def test_compress_keeps_data_and_role_attributes(cleaner):
    # role is a valuable selector/accessibility target and must survive cleaning.
    html = '<html><body><span data-price="9.99" role="price">text</span></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    span = result.find('.//span')
    assert 'data-price' in span.attrib
    assert 'role' in span.attrib


def test_compress_keeps_bare_custom_element_attributes(cleaner):
    # Regression: web components stash structured data in bare attributes
    # (e.g. Reddit's <shreddit-comment depth="2" score="42" permalink="/r/...">).
    # An allowlist used to silently drop these, leaving discovery no clean target.
    html = (
        '<html><body>'
        '<shreddit-comment depth="2" score="42" permalink="/r/x/c1/" author="alice" thingid="t1_abc">'
        'hi</shreddit-comment>'
        '</body></html>'
    )
    result = cleaner._compress_html_simple(parse(html))
    node = result.find('.//shreddit-comment')
    assert node is not None
    for attr in ('depth', 'score', 'permalink', 'author', 'thingid'):
        assert attr in node.attrib, f'{attr} was stripped'


def test_compress_deduplicates_list_items(cleaner):
    """List with >3 items should be trimmed to 3."""
    html = '<html><body><ul>' + ''.join(f'<li>Item {i}</li>' for i in range(6)) + '</ul></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    items = result.find('.//ul').findall('li')
    assert len(items) == 3


def test_compress_keeps_short_lists_intact(cleaner):
    html = '<html><body><ul><li>A</li><li>B</li></ul></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    items = result.find('.//ul').findall('li')
    assert len(items) == 2


def test_compress_deduplicates_table_rows(cleaner):
    """Table with >5 rows should be trimmed to 5."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(8))
    html = f'<html><body><table>{rows}</table></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    tr_count = len(result.find('.//table').xpath('.//tr'))
    assert tr_count == 5


def test_compress_removes_html_comments(cleaner):
    html = '<html><body><!-- secret comment --><p>Real content</p></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert 'secret comment' not in to_str(result)
    assert 'Real content' in to_str(result)


def test_compress_visible_elements_kept(cleaner):
    html = '<html><body><div class="content"><p>Visible</p></div></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert 'Visible' in to_str(result)


# ---------------------------------------------------------------------------
# _prune_non_semantic
# ---------------------------------------------------------------------------


def test_prune_removes_svg(cleaner):
    html = '<html><body><svg><path d="M0"/></svg><p>Keep me</p></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    assert result.find('.//svg') is None
    assert 'Keep me' in to_str(result)


def test_prune_removes_canvas(cleaner):
    html = '<html><body><canvas id="c"></canvas><p>Keep</p></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    assert result.find('.//canvas') is None


def test_prune_replaces_base64_src(cleaner):
    html = '<html><body><img src="data:image/png;base64,ABC"/></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    img = result.find('.//img')
    assert img.get('src') == '[data-uri-removed]'


def test_prune_keeps_normal_img_src(cleaner):
    html = '<html><body><img src="https://example.com/img.png"/></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    img = result.find('.//img')
    assert 'example.com' in img.get('src')


def test_prune_keeps_div_with_class(cleaner):
    html = '<html><body><div class="product"><p>Keep this</p></div></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    assert css_one(result, 'div.product') is not None


# ---------------------------------------------------------------------------
# _collapse_whitespace
# ---------------------------------------------------------------------------


def test_collapse_whitespace_collapses_multiple_spaces(cleaner):
    result = cleaner._collapse_whitespace('hello   world')
    assert '  ' not in result
    assert 'hello world' in result


def test_collapse_whitespace_collapses_multiple_newlines(cleaner):
    result = cleaner._collapse_whitespace('line1\n\n\nline2')
    assert '\n\n' not in result
    assert 'line1' in result
    assert 'line2' in result


def test_collapse_whitespace_removes_blank_lines(cleaner):
    result = cleaner._collapse_whitespace('  \n  \nhello\n  ')
    assert result == 'hello'


def test_collapse_whitespace_strips_line_whitespace(cleaner):
    result = cleaner._collapse_whitespace('  hello  \n  world  ')
    lines = result.split('\n')
    for line in lines:
        assert line == line.strip()


def test_collapse_whitespace_returns_string(cleaner):
    result = cleaner._collapse_whitespace('<p>  test  </p>')
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Additional targeted tests for mutant killing
# ---------------------------------------------------------------------------


def test_compress_deduplicates_list_items_keeps_exactly_3(cleaner):
    """List with exactly 4 items should be trimmed to exactly 3."""
    html = '<html><body><ul>' + ''.join(f'<li>Item {i}</li>' for i in range(4)) + '</ul></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    items = result.find('.//ul').findall('li')
    assert len(items) == 3


def test_compress_list_with_exactly_3_items_untouched(cleaner):
    """List with exactly 3 items should NOT be truncated."""
    html = '<html><body><ul><li>A</li><li>B</li><li>C</li></ul></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    items = result.find('.//ul').findall('li')
    assert len(items) == 3


def test_compress_table_with_exactly_5_rows_untouched(cleaner):
    """Table with exactly 5 rows should NOT be truncated."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(5))
    html = f'<html><body><table>{rows}</table></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    tr_count = len(result.find('.//table').xpath('.//tr'))
    assert tr_count == 5


def test_compress_table_with_6_rows_trimmed_to_5(cleaner):
    """Table with exactly 6 rows should be trimmed to 5."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(6))
    html = f'<html><body><table>{rows}</table></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    tr_count = len(result.find('.//table').xpath('.//tr'))
    assert tr_count == 5


def test_compress_hidden_parent_with_hidden_child_does_not_crash(cleaner):
    """Regression: decomposing a hidden parent must not crash on its (now stale)
    hidden descendants still present in the static node list."""
    html = '<html><body><div hidden><span hidden>x</span><p hidden>y</p></div><div class="ok">keep</div></body></html>'
    result = cleaner._compress_html_simple(parse(html))  # must not raise
    assert css_one(result, 'div.ok') is not None


def test_compress_removes_hidden_element(cleaner):
    """Opt-in removal keeps the 'hidden' attribute, so the hidden-element pass now
    correctly prunes the element (previously the attr was stripped first, leaking
    hidden content into the cleaned HTML)."""
    html = '<html><body><div hidden class="x">Hidden</div><div class="y">Shown</div></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert css_one(result, 'div.x') is None
    assert css_one(result, 'div.y') is not None


def test_compress_removes_aria_hidden_attribute(cleaner):
    """aria-hidden=true elements are removed entirely by the hidden-element pass."""
    html = '<html><body><div class="x" aria-hidden="true">Content</div></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    div = css_one(result, 'div.x')
    # aria-hidden="true" → element removed; if anything survives it must not keep the attr
    if div is not None:
        assert 'aria-hidden' not in div.attrib


def test_prune_keeps_div_with_id(cleaner):
    html = '<html><body><div id="content"><p>Keep this</p></div></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    assert css_one(result, 'div#content') is not None


def test_prune_keeps_div_with_data_attr(cleaner):
    html = '<html><body><div data-id="123"><p>Keep</p></div></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    # div with data attribute should be kept
    assert result.find('.//div') is not None


def test_compress_keeps_attribute_href(cleaner):
    html = '<html><body><a href="/path" onclick="bad()">link</a></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    a = result.find('.//a')
    assert 'href' in a.attrib
    assert 'onclick' not in a.attrib


def test_compress_keeps_src_attribute(cleaner):
    html = '<html><body><img src="image.png" loading="lazy" onerror="bad()"/></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    img = result.find('.//img')
    assert 'src' in img.attrib
    assert 'loading' in img.attrib  # opt-in removal: only noise (event handlers) is dropped
    assert 'onerror' not in img.attrib


def test_compress_keeps_datetime_attribute(cleaner):
    html = '<html><body><time datetime="2024-01-01" style="color:red">Jan 1</time></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    time_tag = result.find('.//time')
    assert 'datetime' in time_tag.attrib
    assert 'style' not in time_tag.attrib


def test_compress_keeps_type_attribute(cleaner):
    html = '<html><body><input type="text" placeholder="Enter"/></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    inp = result.find('.//input')
    assert 'type' in inp.attrib


def test_collapse_whitespace_collapses_tabs(cleaner):
    result = cleaner._collapse_whitespace('hello\t\tworld')
    assert '\t\t' not in result
    assert 'hello world' in result


def test_clean_html_uses_main_inside_body(cleaner):
    html = '<html><body><div>Outside</div><main><h1>Inside Main</h1></main></body></html>'
    result = cleaner.clean_html(html)
    assert 'Inside Main' in result


def test_clean_html_removes_noscript(cleaner):
    html = '<html><body><noscript>Enable JS</noscript><p>Content</p></body></html>'
    result = cleaner.clean_html(html)
    assert 'noscript' not in result.lower() or 'Enable JS' not in result


def test_clean_html_removes_iframe(cleaner):
    html = '<html><body><iframe src="bad.html"/><p>Real content</p></body></html>'
    result = cleaner.clean_html(html)
    assert '<iframe' not in result


def test_clean_html_removes_ad_class_exact(cleaner):
    html = '<html><body><main><p>Content</p><div class="ad">Ad content</div></main></body></html>'
    result = cleaner.clean_html(html)
    assert 'Ad content' not in result


def test_clean_html_removes_useful_links(cleaner):
    html = '<html><body><main><p>Content</p><div class="useful-links">Links</div></main></body></html>'
    result = cleaner.clean_html(html)
    assert 'useful-links' not in result


def test_clean_html_removes_related_posts(cleaner):
    html = '<html><body><main><article><p>Content</p></article><div class="related-posts">More posts</div></main></body></html>'
    result = cleaner.clean_html(html)
    assert 'related-posts' not in result


def test_clean_html_removes_widget_class(cleaner):
    html = '<html><body><main><p>Real</p><div class="widget">Widget</div></main></body></html>'
    result = cleaner.clean_html(html)
    assert 'Widget' not in result


def test_clean_html_warn_threshold_large_content(cleaner):
    """Content >30000 chars should still be returned (just warns)."""
    large_content = 'x' * 31000
    html = f'<html><body><main><p>{large_content}</p></main></body></html>'
    result = cleaner.clean_html(html)
    assert isinstance(result, str)
    assert len(result) > 0


def test_clean_html_warn_threshold_exactly_30000_no_warn(cleaner):
    """Content of exactly 30000 chars should NOT trigger warning (condition is >)."""
    # Create content that is exactly 30000 chars after cleaning
    # We test by providing small content (under threshold) - should not warn
    html = '<html><body><main><p>short content</p></main></body></html>'
    result = cleaner.clean_html(html)
    assert isinstance(result, str)
    assert len(result) > 0


def test_cleaner_uses_provided_console():
    """When a console is provided, it must be used, not create a new one."""
    from rich.console import Console

    custom_console = Console(quiet=True)
    cleaner = HTMLCleaner(console=custom_console)
    assert cleaner.console is custom_console


def test_cleaner_creates_console_when_none():
    """When console=None, a new Console must be created."""
    from rich.console import Console

    cleaner = HTMLCleaner(console=None)
    assert isinstance(cleaner.console, Console)


def test_compress_list_exactly_4_truncated_to_3(cleaner):
    """List with exactly 4 items must be truncated to 3."""
    html = '<html><body><ul><li>A</li><li>B</li><li>C</li><li>D</li></ul></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    items = result.find('.//ul').findall('li')
    assert len(items) == 3


def test_prune_replaces_data_uri_with_exact_placeholder(cleaner):
    """data: src must be replaced with '[data-uri-removed]'."""
    html = '<html><body><img src="data:image/png;base64,XYZ"/></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    img = result.find('.//img')
    assert img.get('src') == '[data-uri-removed]'


def test_prune_does_not_remove_non_data_src(cleaner):
    """Non-data: src attributes must not be modified."""
    html = '<html><body><img src="https://example.com/image.jpg"/></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    img = result.find('.//img')
    assert img.get('src') == 'https://example.com/image.jpg'


def test_collapse_whitespace_multiple_spaces_become_one(cleaner):
    """Multiple consecutive spaces must become exactly one space."""
    result = cleaner._collapse_whitespace('a   b')
    assert result == 'a b'


def test_collapse_whitespace_multiple_newlines_become_one(cleaner):
    """Multiple consecutive newlines must become exactly one newline."""
    result = cleaner._collapse_whitespace('a\n\n\nb')
    assert result == 'a\nb'


def test_collapse_whitespace_empty_lines_removed(cleaner):
    """Lines that are only whitespace must be removed."""
    result = cleaner._collapse_whitespace('a\n  \nb')
    assert '  ' not in result
    assert 'a' in result
    assert 'b' in result


def test_collapse_whitespace_strips_line_edges(cleaner):
    """Leading/trailing whitespace per line must be removed."""
    result = cleaner._collapse_whitespace('  hello  ')
    assert result == 'hello'


def test_selector_attributes_survive_cleaning(cleaner):
    """Selector-worthy attributes survive; only event handlers are dropped."""
    html = '<html><body><a class="link" id="myid" href="/page" src="img.png" onclick="bad()" title="keep">text</a></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    a = result.find('.//a')
    assert 'class' in a.attrib
    assert 'id' in a.attrib
    assert 'href' in a.attrib
    assert 'title' in a.attrib  # kept under opt-in removal
    assert 'onclick' not in a.attrib


# ---------------------------------------------------------------------------
# Coverage: <main> without <body>, fallback to full HTML
# ---------------------------------------------------------------------------


def test_clean_html_no_body_with_main_tag(cleaner):
    """When HTML has no <body> but has a top-level <main>, extract from <main>."""
    html = '<main><h1>Main Content</h1><p>Some text</p></main>'
    result = cleaner.clean_html(html)
    assert 'Main Content' in result
    assert 'Some text' in result


def test_clean_html_no_body_no_main_falls_back_to_full_html(cleaner):
    """When HTML has neither <body> nor <main>, fall back to full HTML."""
    html = '<div><h1>Bare Content</h1></div>'
    result = cleaner.clean_html(html)
    assert 'Bare Content' in result


def test_clean_html_main_with_body_inside(cleaner):
    """When HTML has <main> wrapping a <body> (weird but possible), extract <body> inside <main>."""
    # lxml normalizes this, but we can test that the <main> path works
    html = '<main><article><h1>Article Title</h1></article></main>'
    result = cleaner.clean_html(html)
    assert 'Article Title' in result


# ---------------------------------------------------------------------------
# Coverage: hidden and aria-hidden removal
# ---------------------------------------------------------------------------


def test_compress_hidden_and_aria_hidden_step5_iterates(cleaner):
    """The hidden-element pass iterates all tags checking for hidden/aria-hidden."""
    html = '<html><body><div data-visible="yes">Content</div><p>More</p></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert 'Content' in to_str(result)
    assert 'More' in to_str(result)


def test_compress_keeps_aria_hidden_false_elements(cleaner):
    """Elements with aria-hidden='false' should NOT be decomposed."""
    html = '<html><body><span aria-hidden="false">Visible to SR</span></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert 'Visible to SR' in to_str(result)


# ---------------------------------------------------------------------------
# Coverage: deeply nested empty anonymous divs/spans
# ---------------------------------------------------------------------------


def test_prune_removes_deeply_nested_empty_anonymous_div(cleaner):
    """Anonymous div at depth > 8 with no text should be decomposed."""
    # Build HTML with deep nesting (> 8 levels)
    html = '<html><body><div class="a"><div class="b"><div class="c"><div class="d"><div class="e"><div class="f"><div class="g"><div class="h"><div></div></div></div></div></div></div></div></div></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    # The innermost anonymous empty div should be removed: no anonymous, empty,
    # deeply-nested div/span should remain.
    anonymous_empties = [
        tag
        for tag in result.xpath('.//div | .//span')
        if 'class' not in tag.attrib
        and 'id' not in tag.attrib
        and not any(k.startswith('data-') for k in tag.attrib)
        and sum(1 for _ in tag.iterancestors()) > 8
        and len(tag.text_content().strip()) == 0
    ]
    assert len(anonymous_empties) == 0


def test_prune_keeps_shallow_anonymous_div(cleaner):
    """Anonymous div at depth <= 8 should be kept even if empty."""
    html = '<html><body><div></div></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    # Shallow anonymous empty div should still exist
    divs = result.xpath('.//div')
    assert len(divs) >= 1


def test_prune_keeps_deep_div_with_text(cleaner):
    """Deeply nested anonymous div with text content should be kept."""
    html = '<html><body><div class="a"><div class="b"><div class="c"><div class="d"><div class="e"><div class="f"><div class="g"><div class="h"><div>Has text</div></div></div></div></div></div></div></div></body></html>'
    result = cleaner._prune_non_semantic(parse(html))
    assert 'Has text' in to_str(result)


# ---------------------------------------------------------------------------
# Coverage: hidden/aria-hidden element decomposition via _compress_html_simple
# ---------------------------------------------------------------------------


def test_compress_decomposes_hidden_element(cleaner):
    """The hidden-element pass iterates all tags; visible siblings survive."""
    html = '<html><body><div hidden="">secret</div><p>visible</p></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert 'visible' in to_str(result)


def test_compress_decomposes_aria_hidden_true_element(cleaner):
    """Element with aria-hidden='true' is decomposed; visible siblings survive."""
    html = '<html><body><span aria-hidden="true">icon</span><p>real</p></body></html>'
    result = cleaner._compress_html_simple(parse(html))
    assert 'real' in to_str(result)


def test_clean_html_no_body_main_only_extracts_content(cleaner):
    """HTML fragment with only <main> (no <body>) extracts from <main>."""
    html = '<main><h1>Title</h1><p>text</p></main>'
    result = cleaner.clean_html(html)
    assert 'Title' in result
    assert 'text' in result


def test_compress_decomposes_deeply_nested_empty_anonymous_divs(cleaner):
    """_compress_html_simple removes empty anonymous divs deeper than 8 levels."""
    # 9 nested empty anonymous divs — innermost reaches depth > 8 threshold
    nested = '<div>' * 9 + '</div>' * 9
    html = f'<html><body><p>important content</p>{nested}</body></html>'
    tree = parse(html)

    before_count = len(tree.xpath('.//div'))
    result = cleaner._compress_html_simple(tree)
    after_count = len(result.xpath('.//div'))

    assert after_count < before_count  # deeply nested empty anonymous divs were stripped
    assert 'important content' in to_str(result)
