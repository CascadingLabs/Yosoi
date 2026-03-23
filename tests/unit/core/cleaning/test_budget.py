"""Tests for the enforce_budget pass."""

from yosoi.core.cleaning.passes.budget import enforce_budget, estimate_tokens


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens('') == 0

    def test_short_string(self):
        assert estimate_tokens('hello') == 1

    def test_proportional_to_length(self):
        assert estimate_tokens('x' * 400) == 100

    def test_html_content(self):
        html = '<div class="product"><h1>Title</h1><p>Description here</p></div>'
        tokens = estimate_tokens(html)
        assert tokens == len(html) // 4


class TestEnforceBudget:
    def test_under_budget_unchanged(self):
        html = '<p>Short content</p>'
        result = enforce_budget(html, 1000)
        assert result == html

    def test_zero_budget_disables(self):
        html = '<p>Content</p>' * 100
        result = enforce_budget(html, 0)
        assert result == html

    def test_over_budget_truncates(self):
        # Create content well over budget
        html = (
            '<html><body>'
            + ''.join(f'<div class="item"><p>Paragraph {i} with text</p></div>' for i in range(100))
            + '</body></html>'
        )
        budget = 200
        result = enforce_budget(html, budget)
        assert estimate_tokens(result) <= budget

    def test_strips_attributes_first(self):
        """Strategy 1 strips non-essential attrs before truncating DOM."""
        html = '<html><body><div class="product" data-id="123" href="/page"><p>Content</p></div></body></html>'
        # Use a budget that's tight but could fit if attrs are stripped
        original_tokens = estimate_tokens(html)
        result = enforce_budget(html, original_tokens - 5)
        # Should have stripped attrs like data-id, href
        assert 'data-id' not in result or len(result) < len(html)

    def test_preserves_some_structure(self):
        """Even after truncation, result should be valid-ish HTML."""
        html = '<html><body>' + ''.join(f'<p>Para {i}</p>' for i in range(50)) + '</body></html>'
        result = enforce_budget(html, 100)
        assert '<html>' in result or '<body>' in result

    def test_large_content_fits_budget(self):
        """Large content should be brought within budget."""
        paragraphs = ''.join(f'<div><p>This is paragraph {i} with some reasonable text.</p></div>' for i in range(200))
        html = f'<html><body>{paragraphs}</body></html>'
        budget = 500
        result = enforce_budget(html, budget)
        assert estimate_tokens(result) <= budget

    def test_exact_budget_unchanged(self):
        """Content exactly at budget should not be modified."""
        html = 'x' * 400  # 100 tokens
        result = enforce_budget(html, 100)
        assert result == html
