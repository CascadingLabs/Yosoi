"""Tests for DebugManager."""

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


def test_save_debug_html_creates_file(debug_manager, tmp_path):
    debug_manager.save_debug_html('https://example.com/page', '<h1>Hello</h1>')
    debug_dir = tmp_path / 'debug'
    files = list(debug_dir.iterdir())
    assert len(files) == 1
    assert files[0].suffix == '.html'
    content = files[0].read_text()
    assert 'https://example.com/page' in content


def test_save_debug_selectors_creates_json(debug_manager, tmp_path):
    import json

    selectors = {'title': {'primary': 'h1'}}
    debug_manager.save_debug_selectors('https://example.com/page', selectors)
    debug_dir = tmp_path / 'debug'
    json_files = [f for f in debug_dir.iterdir() if f.suffix == '.json']
    assert len(json_files) == 1
    data = json.loads(json_files[0].read_text())
    assert data['url'] == 'https://example.com/page'
    assert data['selectors'] == selectors


def test_get_safe_filename(debug_manager):
    filename = debug_manager._get_safe_filename('https://example.com/blog/post', 'html')
    assert 'example.com' in filename
    assert filename.endswith('.html')
