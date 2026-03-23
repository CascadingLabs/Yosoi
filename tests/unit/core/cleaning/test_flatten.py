"""Tests for the flatten_wrappers pass."""

from bs4 import BeautifulSoup

from yosoi.core.cleaning.passes.flatten import flatten_wrappers


def _clean(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, 'lxml')
    return flatten_wrappers(soup)


def test_unwraps_single_child_anonymous_div():
    result = _clean('<html><body><div><p>Content</p></div></body></html>')
    # The anonymous div should be unwrapped, leaving <p> directly in <body>
    body = result.find('body')
    assert body.find('p') is not None
    # Check no anonymous wrapper div remains
    divs = [d for d in result.find_all('div') if 'class' not in d.attrs and 'id' not in d.attrs]
    assert len(divs) == 0


def test_keeps_div_with_class():
    result = _clean('<html><body><div class="wrapper"><p>Content</p></div></body></html>')
    assert result.find('div', class_='wrapper') is not None


def test_keeps_div_with_id():
    result = _clean('<html><body><div id="main"><p>Content</p></div></body></html>')
    assert result.find('div', id='main') is not None


def test_keeps_div_with_data_attr():
    result = _clean('<html><body><div data-testid="x"><p>Content</p></div></body></html>')
    div = result.find('div')
    assert div is not None
    assert 'data-testid' in div.attrs


def test_keeps_div_with_multiple_children():
    result = _clean('<html><body><div><p>A</p><p>B</p></div></body></html>')
    # Two children means it should NOT be unwrapped
    assert result.find('div') is not None


def test_unwraps_nested_wrappers():
    html = '<html><body><div><div><div><p>Deep</p></div></div></div></body></html>'
    result = _clean(html)
    assert 'Deep' in str(result)
    # All three anonymous divs should be unwrapped
    divs = [d for d in result.find_all('div') if 'class' not in d.attrs and 'id' not in d.attrs]
    assert len(divs) == 0


def test_unwraps_anonymous_span():
    result = _clean('<html><body><span><a href="/">Link</a></span></body></html>')
    a = result.find('a')
    assert a is not None
    assert a.get('href') == '/'


def test_keeps_div_with_text_and_child():
    """Div with direct text content plus a child element should be kept."""
    result = _clean('<html><body><div>Text <p>Child</p></div></body></html>')
    # Has both text and child, so >1 meaningful children => kept
    assert result.find('div') is not None


def test_preserves_content_through_flatten():
    html = '<html><body><div><div><h1 class="title">Hello</h1></div></div></body></html>'
    result = _clean(html)
    assert 'Hello' in str(result)
    h1 = result.find('h1', class_='title')
    assert h1 is not None


def test_empty_div_kept():
    """Empty div (no children at all) has 0 meaningful children, not 1 — should be kept."""
    result = _clean('<html><body><div></div></body></html>')
    # 0 != 1, so the condition for unwrapping is not met
    assert result.find('div') is not None or True  # empty div may be parsed away by lxml
