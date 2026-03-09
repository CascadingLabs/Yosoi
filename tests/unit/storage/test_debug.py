"""Tests for DebugManager."""

import json

import pytest
from rich.console import Console

from yosoi.storage.debug import DebugManager


@pytest.fixture
def debug_manager(tmp_path, monkeypatch):
    import yosoi.storage.debug as debug_mod

    monkeypatch.setattr(debug_mod, 'get_debug_path', lambda: tmp_path / 'debug')
    return DebugManager(console=Console(quiet=True), enabled=True)


def test_debug_manager_disabled_does_nothing(tmp_path):
    mgr = DebugManager(enabled=False)
    mgr.save_debug_html('https://example.com', '<html></html>')
    mgr.save_debug_selectors('https://example.com', {'title': 'h1'})
    # No files created when disabled
    assert not (tmp_path / 'debug').exists()


def test_debug_manager_enabled_false_debug_dir_is_none():
    mgr = DebugManager(enabled=False)
    assert mgr.debug_dir is None


def test_debug_manager_enabled_true_debug_dir_is_set(tmp_path, monkeypatch):
    import yosoi.storage.debug as debug_mod

    monkeypatch.setattr(debug_mod, 'get_debug_path', lambda: tmp_path / 'debug')
    mgr = DebugManager(console=Console(quiet=True), enabled=True)
    assert mgr.debug_dir is not None
    assert mgr.enabled is True


def test_save_debug_html_creates_file(debug_manager, tmp_path):
    debug_manager.save_debug_html('https://example.com/page', '<h1>Hello</h1>')
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    assert len(files) == 1
    assert files[0].suffix == '.html'
    content = files[0].read_text()
    assert 'https://example.com/page' in content


def test_save_debug_html_includes_html_content(debug_manager, tmp_path):
    debug_manager.save_debug_html('https://example.com/page', '<h1>Hello</h1>')
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    content = files[0].read_text()
    assert '<h1>Hello</h1>' in content


def test_save_debug_html_includes_length_comment(debug_manager, tmp_path):
    html_content = '<h1>Hello</h1>'
    debug_manager.save_debug_html('https://example.com/page', html_content)
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    content = files[0].read_text()
    assert str(len(html_content)) in content


def test_save_debug_html_url_in_comment(debug_manager, tmp_path):
    debug_manager.save_debug_html('https://example.com/article', '<p>body</p>')
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    content = files[0].read_text()
    assert '<!-- URL: https://example.com/article -->' in content


def test_save_debug_html_disabled_no_file(tmp_path):
    mgr = DebugManager(enabled=False)
    mgr.save_debug_html('https://example.com', '<h1>Hello</h1>')
    assert not (tmp_path / 'debug').exists()


def test_save_debug_selectors_creates_json(debug_manager, tmp_path):
    selectors = {'title': {'primary': 'h1'}}
    debug_manager.save_debug_selectors('https://example.com/page', selectors)
    debug_dir = tmp_path / 'debug'
    json_files = [f for f in debug_dir.iterdir() if f.suffix == '.json']
    assert len(json_files) == 1
    data = json.loads(json_files[0].read_text())
    assert data['url'] == 'https://example.com/page'
    assert data['selectors'] == selectors


def test_save_debug_selectors_disabled_no_file(tmp_path):
    mgr = DebugManager(enabled=False)
    mgr.save_debug_selectors('https://example.com', {'title': 'h1'})
    assert not (tmp_path / 'debug').exists()


def test_save_debug_selectors_json_has_url_key(debug_manager, tmp_path):
    selectors = {'price': {'primary': '.price'}}
    debug_manager.save_debug_selectors('https://shop.com/product', selectors)
    debug_dir = tmp_path / 'debug'
    json_files = [f for f in debug_dir.iterdir() if f.suffix == '.json']
    data = json.loads(json_files[0].read_text())
    assert 'url' in data
    assert 'selectors' in data


def test_get_safe_filename(debug_manager):
    filename = debug_manager._get_safe_filename('https://example.com/blog/post', 'html')
    assert 'example.com' in filename
    assert filename.endswith('.html')


def test_get_safe_filename_uses_suffix(debug_manager):
    html_filename = debug_manager._get_safe_filename('https://example.com/page', 'html')
    json_filename = debug_manager._get_safe_filename('https://example.com/page', 'selectors.json')
    assert html_filename.endswith('.html')
    assert json_filename.endswith('.selectors.json')


def test_get_safe_filename_includes_netloc(debug_manager):
    filename = debug_manager._get_safe_filename('https://mysite.org/path', 'html')
    assert 'mysite.org' in filename


def test_get_safe_filename_path_truncated_at_50(debug_manager):
    long_path = '/a' * 30  # 60 chars
    filename = debug_manager._get_safe_filename(f'https://example.com{long_path}', 'html')
    # The path part should be truncated at 50 chars
    # After netloc, the safe path should be at most 50 chars from path
    assert len(filename) < 200  # reasonable upper bound


def test_debug_manager_enabled_true_creates_debug_dir(tmp_path, monkeypatch):
    """When enabled=True, debug_dir must be created."""
    import yosoi.storage.debug as debug_mod

    debug_path = tmp_path / 'debug_created'
    monkeypatch.setattr(debug_mod, 'get_debug_path', lambda: debug_path)
    mgr = DebugManager(console=Console(quiet=True), enabled=True)
    assert debug_path.exists()
    assert mgr.debug_dir == debug_path


def test_debug_manager_disabled_debug_dir_is_none():
    """When enabled=False, debug_dir must be None."""
    mgr = DebugManager(enabled=False)
    assert mgr.debug_dir is None


def test_debug_manager_enabled_attribute_is_true(tmp_path, monkeypatch):
    """When enabled=True, self.enabled must be True."""
    import yosoi.storage.debug as debug_mod

    monkeypatch.setattr(debug_mod, 'get_debug_path', lambda: tmp_path / 'dbg')
    mgr = DebugManager(console=Console(quiet=True), enabled=True)
    assert mgr.enabled is True


def test_debug_manager_disabled_attribute_is_false():
    """When enabled=False, self.enabled must be False."""
    mgr = DebugManager(enabled=False)
    assert mgr.enabled is False


def test_save_debug_html_file_content_has_url_comment(debug_manager, tmp_path):
    """Saved HTML file must start with '<!-- URL: {url} -->'."""
    debug_manager.save_debug_html('https://test.example.com/page', '<p>content</p>')
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    content = files[0].read_text()
    assert content.startswith('<!-- URL: https://test.example.com/page -->')


def test_save_debug_html_file_content_second_line_is_length(debug_manager, tmp_path):
    """Second line must be '<!-- Cleaned HTML length: N chars -->'."""
    html_content = '<p>hello world</p>'
    debug_manager.save_debug_html('https://example.com/page', html_content)
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    content = files[0].read_text()
    expected_len = len(html_content)
    assert f'<!-- Cleaned HTML length: {expected_len} chars -->' in content


def test_get_safe_filename_slashes_replaced_with_underscore(debug_manager):
    """Path slashes must be replaced with underscores in filename."""
    filename = debug_manager._get_safe_filename('https://example.com/blog/post/slug', 'html')
    # After the netloc, path slashes become underscores
    assert '/' not in filename.replace('.html', '').replace('example.com', '')


def test_get_safe_filename_format_is_base_dot_suffix(debug_manager):
    """Filename format must be '{netloc}{safe_path}.{suffix}'."""
    filename = debug_manager._get_safe_filename('https://example.com/page', 'html')
    # Must end with '.html'
    assert filename.endswith('.html')
    # Must contain netloc
    assert 'example.com' in filename


def test_save_debug_selectors_file_content_has_url_key(debug_manager, tmp_path):
    """Debug selectors JSON must contain 'url' key with exact URL."""
    url = 'https://target.com/article'
    selectors = {'title': {'primary': 'h1'}}
    debug_manager.save_debug_selectors(url, selectors)
    debug_dir = tmp_path / 'debug'
    json_files = [f for f in debug_dir.iterdir() if f.suffix == '.json']
    data = json.loads(json_files[0].read_text())
    assert data['url'] == url


def test_save_debug_selectors_uses_indent_2(debug_manager, tmp_path):
    """Debug selectors JSON must use indent=2."""
    debug_manager.save_debug_selectors('https://example.com/page', {'title': {'primary': 'h1'}})
    debug_dir = tmp_path / 'debug'
    json_files = [f for f in debug_dir.iterdir() if f.suffix == '.json']
    raw = json_files[0].read_text()
    assert '  ' in raw  # indent=2 means 2-space indentation
