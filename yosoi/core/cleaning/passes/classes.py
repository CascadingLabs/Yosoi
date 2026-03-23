"""Strip utility/styling CSS classes that waste context without aiding selector discovery."""

import re

from bs4 import BeautifulSoup, Tag

# Patterns that match purely presentational utility classes (Tailwind, Bootstrap, etc.)
_UTILITY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'^-?[mp][xytblr]?-\d'),  # m-4, px-2, pt-0, -mt-1
    re.compile(r'^-?gap-'),  # gap-4
    re.compile(r'^-?space-[xy]-'),  # space-x-2
    re.compile(r'^[wh]-\d'),  # w-4, h-10
    re.compile(r'^(min|max)-[wh]-'),  # min-w-0, max-h-screen
    re.compile(r'^(flex|grid|block|inline|hidden|table|contents)$'),
    re.compile(r'^(flex|grid)-'),  # flex-col, grid-cols-3
    re.compile(r'^(justify|items|self|place)-'),  # justify-center, items-start
    re.compile(r'^(order|col-span|row-span)-'),  # order-1, col-span-2
    re.compile(r'^text-(xs|sm|base|lg|xl|\d)'),  # text-sm, text-2xl
    re.compile(r'^(font|leading|tracking)-'),  # font-bold, leading-tight
    re.compile(r'^(bg|from|via|to)-'),  # bg-white, from-blue-500
    re.compile(
        r'^text-(white|black|gray|red|blue|green|yellow|purple|pink|indigo|orange|slate|zinc|neutral|stone|amber|lime|emerald|teal|cyan|sky|violet|fuchsia|rose)'
    ),
    re.compile(r'^(border|ring|outline|shadow)'),  # border-2, ring-1, shadow-md
    re.compile(r'^rounded'),  # rounded-lg, rounded-full
    re.compile(r'^(opacity|transition|duration|ease|delay|animate)-'),
    re.compile(r'^(overflow|object|z|inset|top|right|bottom|left)-'),
    re.compile(r'^(absolute|relative|fixed|sticky|static)$'),
    re.compile(r'^(visible|invisible|collapse)$'),
    re.compile(r'^(cursor|pointer-events|select)-'),
    re.compile(r'^(sr-only|not-sr-only)$'),
    re.compile(r'^(whitespace|break|truncate|line-clamp)-?'),
    re.compile(r'^(float|clear)-'),
    re.compile(r'^(decoration|underline|overline|line-through|no-underline)'),
    re.compile(r'^(uppercase|lowercase|capitalize|normal-case)$'),
    re.compile(r'^(italic|not-italic)$'),
    re.compile(r'^(antialiased|subpixel-antialiased)$'),
    # Bootstrap utility classes
    re.compile(r'^(d|col|row|offset|align)-'),  # d-flex, col-md-6
    re.compile(r'^(ms|me|ps|pe|mt|mb|pt|pb)-\d'),  # Bootstrap spacing
]

# Words that suggest a class is semantically meaningful for selectors
_SEMANTIC_WORDS: frozenset[str] = frozenset(
    {
        'product',
        'price',
        'title',
        'name',
        'card',
        'item',
        'article',
        'content',
        'main',
        'wrapper',
        'container',
        'list',
        'detail',
        'description',
        'summary',
        'review',
        'rating',
        'author',
        'date',
        'image',
        'thumbnail',
        'gallery',
        'link',
        'button',
        'heading',
        'body',
        'post',
        'entry',
        'meta',
        'info',
        'data',
        'result',
        'search',
        'category',
        'tag',
        'label',
        'badge',
        'status',
        'comment',
        'reply',
        'avatar',
        'profile',
        'user',
        'menu',
        'breadcrumb',
        'pagination',
        'tab',
        'modal',
        'dropdown',
        'carousel',
        'slider',
        'banner',
        'hero',
        'feature',
        'section',
        'block',
        'panel',
        'group',
        'row',
        'cell',
        'header',
        'footer',
    }
)


def strip_utility_classes(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove purely presentational CSS classes from all elements.

    Classes that match known utility patterns (Tailwind, Bootstrap spacing/layout)
    are removed unless the class name also contains a semantic keyword that could
    be useful as a selector target.

    Args:
        soup: Parsed HTML tree to modify in-place.

    Returns:
        The same (mutated) soup object.

    """
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        classes = tag.get('class')
        if not classes:
            continue
        if not isinstance(classes, list):
            continue
        filtered = [cls for cls in classes if not _is_utility_class(cls)]
        if filtered:
            tag['class'] = filtered
        else:
            del tag['class']
    return soup


def _is_utility_class(cls: str) -> bool:
    """Return True if a class name is purely presentational."""
    lower = cls.lower()
    # Keep if it contains a semantic word
    for word in _SEMANTIC_WORDS:
        if word in lower:
            return False
    # Strip if it matches a utility pattern
    return any(pattern.match(cls) for pattern in _UTILITY_PATTERNS)
