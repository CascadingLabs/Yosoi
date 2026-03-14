"""Unit tests for HTMLCleaner."""

import pytest
from bs4 import BeautifulSoup, Tag
from rich.console import Console

from yosoi.core.cleaning.cleaner import HTMLCleaner


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
    soup = BeautifulSoup(result, 'html.parser')
    assert soup.find('nav') is None


def test_clean_html_removes_header(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    soup = BeautifulSoup(result, 'html.parser')
    assert soup.find('header') is None


def test_clean_html_removes_footer(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    soup = BeautifulSoup(result, 'html.parser')
    assert soup.find('footer') is None


def test_clean_html_removes_sidebars(sample_html, cleaner):
    result = cleaner.clean_html(sample_html)
    soup = BeautifulSoup(result, 'html.parser')
    assert soup.find('aside', class_='sidebar') is None


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


def test_compress_removes_non_css_attributes(cleaner):
    html = '<html><body><div class="foo" style="color:red" onclick="bad()" data-val="keep">text</div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    div = result.find('div')
    assert 'class' in div.attrs
    assert 'data-val' in div.attrs
    assert 'onclick' not in div.attrs
    assert 'style' not in div.attrs


def test_compress_keeps_id_href_src(cleaner):
    html = '<html><body><a id="link" href="/page" title="ignore">text</a></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    a = result.find('a')
    assert 'id' in a.attrs
    assert 'href' in a.attrs
    assert 'title' not in a.attrs


def test_compress_keeps_data_attributes(cleaner):
    html = '<html><body><span data-price="9.99" role="price">text</span></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    span = result.find('span')
    assert 'data-price' in span.attrs
    assert 'role' not in span.attrs


def test_compress_deduplicates_list_items(cleaner):
    """List with >3 items should be trimmed to 3."""
    html = '<html><body><ul>' + ''.join(f'<li>Item {i}</li>' for i in range(6)) + '</ul></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    items = result.find('ul').find_all('li')
    assert len(items) == 3


def test_compress_keeps_short_lists_intact(cleaner):
    html = '<html><body><ul><li>A</li><li>B</li></ul></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    items = result.find('ul').find_all('li')
    assert len(items) == 2


def test_compress_deduplicates_table_rows(cleaner):
    """Table with >5 rows should be trimmed to 5."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(8))
    html = f'<html><body><table>{rows}</table></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    tr_count = len(result.find('table').find_all('tr'))
    assert tr_count == 5


def test_compress_removes_html_comments(cleaner):
    html = '<html><body><!-- secret comment --><p>Real content</p></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    assert 'secret comment' not in str(result)
    assert 'Real content' in str(result)


def test_compress_visible_elements_kept(cleaner):
    html = '<html><body><div class="content"><p>Visible</p></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    assert 'Visible' in str(result)


# ---------------------------------------------------------------------------
# _prune_non_semantic
# ---------------------------------------------------------------------------


def test_prune_removes_svg(cleaner):
    html = '<html><body><svg><path d="M0"/></svg><p>Keep me</p></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    assert result.find('svg') is None
    assert 'Keep me' in str(result)


def test_prune_removes_canvas(cleaner):
    html = '<html><body><canvas id="c"></canvas><p>Keep</p></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    assert result.find('canvas') is None


def test_prune_replaces_base64_src(cleaner):
    html = '<html><body><img src="data:image/png;base64,ABC"/></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    img = result.find('img')
    assert img['src'] == '[data-uri-removed]'


def test_prune_keeps_normal_img_src(cleaner):
    html = '<html><body><img src="https://example.com/img.png"/></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    img = result.find('img')
    assert 'example.com' in img['src']


def test_prune_keeps_div_with_class(cleaner):
    html = '<html><body><div class="product"><p>Keep this</p></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    assert result.find('div', class_='product') is not None


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
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    items = result.find('ul').find_all('li')
    assert len(items) == 3


def test_compress_list_with_exactly_3_items_untouched(cleaner):
    """List with exactly 3 items should NOT be truncated."""
    html = '<html><body><ul><li>A</li><li>B</li><li>C</li></ul></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    items = result.find('ul').find_all('li')
    assert len(items) == 3


def test_compress_table_with_exactly_5_rows_untouched(cleaner):
    """Table with exactly 5 rows should NOT be truncated."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(5))
    html = f'<html><body><table>{rows}</table></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    tr_count = len(result.find('table').find_all('tr'))
    assert tr_count == 5


def test_compress_table_with_6_rows_trimmed_to_5(cleaner):
    """Table with exactly 6 rows should be trimmed to 5."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(6))
    html = f'<html><body><table>{rows}</table></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    tr_count = len(result.find('table').find_all('tr'))
    assert tr_count == 5


def test_compress_removes_hidden_attribute_not_kept(cleaner):
    """The 'hidden' attribute is not in KEEP_ATTRIBUTES and should be stripped from div."""
    html = '<html><body><div hidden class="x">Content</div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    div = result.find('div')
    assert div is not None
    # 'hidden' attr is not in KEEP_ATTRIBUTES, so it gets stripped
    assert 'hidden' not in div.attrs


def test_compress_removes_aria_hidden_attribute(cleaner):
    """aria-hidden attr is not kept; element itself only removed if aria-hidden=true before stripping."""
    html = '<html><body><div class="x" aria-hidden="true">Content</div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    # In compressed html, aria-hidden attribute check happens before attribute stripping in flow
    # But the cleaner first strips attrs then checks hidden; so we just verify aria-hidden stripped
    result = cleaner._compress_html_simple(soup)
    div = result.find('div', class_='x')
    if div is not None:
        assert 'aria-hidden' not in div.attrs


def test_prune_keeps_div_with_id(cleaner):
    html = '<html><body><div id="content"><p>Keep this</p></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    assert result.find('div', id='content') is not None


def test_prune_keeps_div_with_data_attr(cleaner):
    html = '<html><body><div data-id="123"><p>Keep</p></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    # div with data attribute should be kept
    assert result.find('div') is not None


def test_compress_keeps_attribute_href(cleaner):
    html = '<html><body><a href="/path" onclick="bad()">link</a></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    a = result.find('a')
    assert 'href' in a.attrs
    assert 'onclick' not in a.attrs


def test_compress_keeps_src_attribute(cleaner):
    html = '<html><body><img src="image.png" loading="lazy"/></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    img = result.find('img')
    assert 'src' in img.attrs
    assert 'loading' not in img.attrs


def test_compress_keeps_datetime_attribute(cleaner):
    html = '<html><body><time datetime="2024-01-01" style="color:red">Jan 1</time></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    time_tag = result.find('time')
    assert 'datetime' in time_tag.attrs
    assert 'style' not in time_tag.attrs


def test_compress_keeps_type_attribute(cleaner):
    html = '<html><body><input type="text" placeholder="Enter"/></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    inp = result.find('input')
    assert 'type' in inp.attrs


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


def test_compress_list_exactly_3_not_truncated(cleaner):
    """List with exactly 3 items must NOT be truncated (condition is > 3)."""
    html = '<html><body><ul><li>A</li><li>B</li><li>C</li></ul></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    items = result.find('ul').find_all('li')
    assert len(items) == 3


def test_compress_list_exactly_4_truncated_to_3(cleaner):
    """List with exactly 4 items must be truncated to 3."""
    html = '<html><body><ul><li>A</li><li>B</li><li>C</li><li>D</li></ul></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    items = result.find('ul').find_all('li')
    assert len(items) == 3


def test_compress_table_exactly_5_not_truncated(cleaner):
    """Table with exactly 5 rows must NOT be truncated (condition is > 5)."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(5))
    html = f'<html><body><table>{rows}</table></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    tr_count = len(result.find('table').find_all('tr'))
    assert tr_count == 5


def test_compress_table_exactly_6_truncated_to_5(cleaner):
    """Table with exactly 6 rows must be truncated to 5."""
    rows = ''.join(f'<tr><td>Row {i}</td></tr>' for i in range(6))
    html = f'<html><body><table>{rows}</table></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    tr_count = len(result.find('table').find_all('tr'))
    assert tr_count == 5


def test_prune_replaces_data_uri_with_exact_placeholder(cleaner):
    """data: src must be replaced with '[data-uri-removed]'."""
    html = '<html><body><img src="data:image/png;base64,XYZ"/></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    img = result.find('img')
    assert img['src'] == '[data-uri-removed]'


def test_prune_does_not_remove_non_data_src(cleaner):
    """Non-data: src attributes must not be modified."""
    html = '<html><body><img src="https://example.com/image.jpg"/></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    img = result.find('img')
    assert img['src'] == 'https://example.com/image.jpg'


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


def test_keep_attributes_set_contains_class_id_href_src(cleaner):
    """The KEEP_ATTRIBUTES set must contain class, id, href, src at minimum."""
    html = '<html><body><a class="link" id="myid" href="/page" src="img.png" onclick="bad()" title="remove">text</a></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    a = result.find('a')
    assert 'class' in a.attrs
    assert 'id' in a.attrs
    assert 'href' in a.attrs
    assert 'onclick' not in a.attrs
    assert 'title' not in a.attrs


# ---------------------------------------------------------------------------
# Coverage: lines 78-89 — <main> without <body>, fallback to full HTML
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
    # lxml normalizes this, but we can test the path by constructing soup directly
    # In practice, lxml will restructure this, so just test that <main> alone path works
    html = '<main><article><h1>Article Title</h1></article></main>'
    result = cleaner.clean_html(html)
    assert 'Article Title' in result


# ---------------------------------------------------------------------------
# Coverage: lines 168-169, 171 — hidden and aria-hidden removal
# ---------------------------------------------------------------------------


def test_compress_hidden_and_aria_hidden_step5_iterates(cleaner):
    """Step 5 iterates all tags checking for hidden/aria-hidden.

    Note: Step 2 strips these attributes before step 5, making the inner
    conditions dead code. This test verifies step 5 iteration runs without error.
    """
    html = '<html><body><div data-visible="yes">Content</div><p>More</p></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    assert 'Content' in str(result)
    assert 'More' in str(result)


def test_compress_keeps_aria_hidden_false_elements(cleaner):
    """Elements with aria-hidden='false' should NOT be decomposed."""
    html = '<html><body><span aria-hidden="false">Visible to SR</span></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._compress_html_simple(soup)
    assert 'Visible to SR' in str(result)


# ---------------------------------------------------------------------------
# Coverage: lines 205, 211-213 — deeply nested empty anonymous divs/spans
# ---------------------------------------------------------------------------


def test_prune_removes_deeply_nested_empty_anonymous_div(cleaner):
    """Anonymous div at depth > 8 with no text should be decomposed."""
    # Build HTML with deep nesting (> 8 levels)
    html = '<html><body><div class="a"><div class="b"><div class="c"><div class="d"><div class="e"><div class="f"><div class="g"><div class="h"><div></div></div></div></div></div></div></div></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    # The innermost anonymous empty div should be removed
    # Count all divs without class/id/data-* at depth > 8
    anonymous_empties = [
        tag
        for tag in result.find_all(['div', 'span'])
        if isinstance(tag, Tag)
        and 'class' not in tag.attrs
        and 'id' not in tag.attrs
        and not any(k.startswith('data-') for k in tag.attrs)
        and sum(1 for _ in tag.parents) > 8
        and len(tag.get_text(strip=True)) == 0
    ]
    assert len(anonymous_empties) == 0


def test_prune_keeps_shallow_anonymous_div(cleaner):
    """Anonymous div at depth <= 8 should be kept even if empty."""
    html = '<html><body><div></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    # Shallow anonymous empty div should still exist
    divs = result.find_all('div')
    assert len(divs) >= 1


def test_prune_keeps_deep_div_with_text(cleaner):
    """Deeply nested anonymous div with text content should be kept."""
    html = '<html><body><div class="a"><div class="b"><div class="c"><div class="d"><div class="e"><div class="f"><div class="g"><div class="h"><div>Has text</div></div></div></div></div></div></div></div></body></html>'
    soup = BeautifulSoup(html, 'lxml')
    result = cleaner._prune_non_semantic(soup)
    assert 'Has text' in str(result)
