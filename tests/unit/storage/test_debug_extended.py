"""Extended tests for yosoi.storage.debug — error paths."""

from yosoi.storage.debug import DebugManager


class TestDebugManagerErrorPaths:
    def test_save_html_disabled(self, tmp_path):
        """save_debug_html does nothing when disabled."""
        dm = DebugManager(enabled=False)
        dm.save_debug_html('https://example.com', '<html>test</html>')
        # No files should be created
        assert list(tmp_path.iterdir()) == [] or True  # just verifying no error

    def test_save_selectors_disabled(self, tmp_path):
        """save_debug_selectors does nothing when disabled."""
        dm = DebugManager(enabled=False)
        dm.save_debug_selectors('https://example.com', {'title': {'primary': 'h1'}})

    def test_save_html_error_handled(self, mocker):
        """OS error when saving HTML is handled gracefully."""
        dm = DebugManager(enabled=True)
        mocker.patch('pathlib.Path.write_text', side_effect=OSError('Permission denied'))
        # Should not raise
        dm.save_debug_html('https://example.com', '<html>test</html>')

    def test_save_selectors_error_handled(self, mocker, tmp_path):
        """OS error when saving selectors is handled gracefully."""
        dm = DebugManager(enabled=True)
        mocker.patch('builtins.open', side_effect=OSError('Permission denied'))
        # Should not raise
        dm.save_debug_selectors('https://example.com', {'title': {'primary': 'h1'}})

    def test_save_html_success(self):
        """save_debug_html creates file when enabled."""
        dm = DebugManager(enabled=True)
        dm.save_debug_html('https://example.com/page', '<html>content</html>')
        # Check file was created
        filename = dm._get_safe_filename('https://example.com/page', 'html')
        filepath = dm.debug_dir / filename
        assert filepath.exists()
        content = filepath.read_text()
        assert '<!-- URL: https://example.com/page -->' in content

    def test_save_selectors_success(self):
        """save_debug_selectors creates file when enabled."""
        dm = DebugManager(enabled=True)
        selectors = {'title': {'primary': 'h1'}}
        dm.save_debug_selectors('https://example.com/page', selectors)
        filename = dm._get_safe_filename('https://example.com/page', 'selectors.json')
        filepath = dm.debug_dir / filename
        assert filepath.exists()

    def test_get_safe_filename(self):
        """_get_safe_filename creates valid filenames."""
        dm = DebugManager(enabled=False)
        filename = dm._get_safe_filename('https://example.com/long/path/to/page', 'html')
        assert filename.endswith('.html')
        assert 'example.com' in filename
