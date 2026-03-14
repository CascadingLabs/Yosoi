"""Tests for yosoi.types.related_content coercion."""

from yosoi.types.coerce import dispatch


class TestRelatedContent:
    def _coerce(self, value, source_url=None):
        """Helper to dispatch related_content coercion."""
        return dispatch('related_content', value, {}, source_url=source_url)

    def test_list_of_dicts_with_text_and_href(self):
        """Dicts with text and href produce 'text (href)' format."""
        result = self._coerce([{'text': 'Google', 'href': 'https://google.com'}])
        assert result == 'Google (https://google.com)'

    def test_list_of_dicts_text_only(self):
        """Dicts with only text produce just the text."""
        result = self._coerce([{'text': 'Hello', 'href': ''}])
        assert result == 'Hello'

    def test_list_of_dicts_href_only(self):
        """Dicts with only href produce just the href."""
        result = self._coerce([{'text': '', 'href': 'https://foo.com'}])
        assert result == 'https://foo.com'

    def test_list_of_strings(self):
        """List of non-dict items are stringified."""
        result = self._coerce(['item1', 'item2'])
        assert result == 'item1\nitem2'

    def test_mixed_list(self):
        """Mixed dicts and strings work together."""
        result = self._coerce([{'text': 'Link', 'href': 'https://a.com'}, 'plain'])
        assert 'Link (https://a.com)' in result
        assert 'plain' in result

    def test_non_list_value(self):
        """Non-list values are stringified."""
        result = self._coerce('just a string')
        assert result == 'just a string'

    def test_none_value(self):
        """None is passed through by dispatch."""
        result = self._coerce(None)
        assert result is None

    def test_empty_list(self):
        """Empty list returns empty string."""
        result = self._coerce([])
        assert result == ''

    def test_empty_parts_filtered(self):
        """Empty parts (empty text, empty href) are filtered out."""
        result = self._coerce([{'text': '', 'href': ''}, {'text': 'Valid', 'href': 'https://v.com'}])
        assert result == 'Valid (https://v.com)'
