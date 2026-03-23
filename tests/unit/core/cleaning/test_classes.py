"""Tests for the strip_utility_classes pass."""

from bs4 import BeautifulSoup

from yosoi.core.cleaning.passes.classes import _is_utility_class, strip_utility_classes


def _clean(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, 'lxml')
    return strip_utility_classes(soup)


class TestIsUtilityClass:
    def test_tailwind_margin(self):
        assert _is_utility_class('mt-4') is True
        assert _is_utility_class('mb-2') is True
        assert _is_utility_class('mx-auto') is False  # 'auto' doesn't start with digit

    def test_tailwind_padding(self):
        assert _is_utility_class('p-4') is True
        assert _is_utility_class('px-2') is True

    def test_tailwind_width_height(self):
        assert _is_utility_class('w-4') is True
        assert _is_utility_class('h-10') is True

    def test_tailwind_flex(self):
        assert _is_utility_class('flex') is True
        assert _is_utility_class('flex-col') is True

    def test_tailwind_bg(self):
        assert _is_utility_class('bg-white') is True
        assert _is_utility_class('bg-gray-100') is True

    def test_tailwind_text_color(self):
        assert _is_utility_class('text-white') is True
        assert _is_utility_class('text-gray') is True

    def test_tailwind_text_size(self):
        assert _is_utility_class('text-sm') is True
        assert _is_utility_class('text-2xl') is True

    def test_tailwind_rounded(self):
        assert _is_utility_class('rounded-lg') is True
        assert _is_utility_class('rounded') is True

    def test_tailwind_position(self):
        assert _is_utility_class('absolute') is True
        assert _is_utility_class('relative') is True

    def test_semantic_class_kept(self):
        assert _is_utility_class('product-card') is False
        assert _is_utility_class('price') is False
        assert _is_utility_class('article-title') is False

    def test_semantic_word_in_utility_pattern(self):
        """A class like 'product-container' should be kept even if it starts with a pattern."""
        assert _is_utility_class('product-container') is False

    def test_non_matching_class_kept(self):
        """Classes that don't match utility patterns should be kept."""
        assert _is_utility_class('hero-banner') is False
        assert _is_utility_class('main-content') is False

    def test_bootstrap_spacing(self):
        assert _is_utility_class('mt-3') is True
        assert _is_utility_class('pb-2') is True


class TestStripUtilityClasses:
    def test_strips_tailwind_classes_from_element(self):
        html = '<html><body><div class="flex items-center p-4 product-card">text</div></body></html>'
        result = _clean(html)
        div = result.find('div')
        classes = div.get('class', [])
        assert 'product-card' in classes
        assert 'flex' not in classes
        assert 'p-4' not in classes

    def test_removes_class_attr_when_all_stripped(self):
        html = '<html><body><div class="flex p-4 mt-2">text</div></body></html>'
        result = _clean(html)
        div = result.find('div')
        assert 'class' not in div.attrs

    def test_preserves_semantic_only_classes(self):
        html = '<html><body><div class="product-card item-list">text</div></body></html>'
        result = _clean(html)
        div = result.find('div')
        classes = div.get('class', [])
        assert 'product-card' in classes
        assert 'item-list' in classes

    def test_does_not_affect_elements_without_class(self):
        html = '<html><body><div id="main">text</div></body></html>'
        result = _clean(html)
        div = result.find('div')
        assert div.get('id') == 'main'

    def test_handles_empty_class_list(self):
        html = '<html><body><div class="">text</div></body></html>'
        result = _clean(html)
        # Should not crash
        assert 'text' in str(result)

    def test_mixed_utility_and_semantic(self):
        html = '<html><body><span class="text-sm font-bold price-tag rounded-lg">$9.99</span></body></html>'
        result = _clean(html)
        span = result.find('span')
        classes = span.get('class', [])
        assert 'price-tag' in classes
        assert 'text-sm' not in classes
        assert 'rounded-lg' not in classes
