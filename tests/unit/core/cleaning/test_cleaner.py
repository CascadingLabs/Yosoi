"""Unit tests for HTMLCleaner."""

import pytest
from bs4 import BeautifulSoup
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
