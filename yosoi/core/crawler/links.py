"""Generic link extraction for crawl expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from urllib.parse import quote, urljoin, urlparse

import lxml.html

from yosoi.core.crawler.frontier import canonicalize_url

_PAGINATION_RE = re.compile(r'\b(next|older|more|load more|page\s+\d+)\b|[>»]', re.IGNORECASE)
_CONTENT_HINT_RE = re.compile(r'\b(article|story|post|news|detail|item|product|profile)\b', re.IGNORECASE)
_PATH_ID_RE = re.compile(
    r'^(?:\d+|[0-9a-f]{8,}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[a-z0-9_-]*\d[a-z0-9_-]*)$',
    re.IGNORECASE,
)
_ONCLICK_CALL_RE = re.compile(r'^\s*(?:return\s+)?(?P<name>[A-Za-z_$][\w$]*)\((?P<args>.*?)\)')
_STRING_ARG_RE = re.compile(r"""(['"])(?P<value>.*?)(?<!\\)\1""")
_FUNCTION_RE = re.compile(
    r'function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<params>[^)]*)\)\s*{(?P<body>.*?)}',
    re.DOTALL,
)
_LOCATION_TEMPLATE_RE = re.compile(
    r"""(?:window\.)?location(?:\.href)?\s*=\s*(['"])(?P<url>(?:https?://|/)[^'"]+)\1""",
    re.DOTALL,
)
_PAYLOAD_ASSIGN_RE = re.compile(r'\bvar\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>.*?);', re.DOTALL)
_ENCODE_CALL_RE = re.compile(r'encodeURIComponent\(\s*(?P<name>[A-Za-z_$][\w$]*)\s*\)')
_QUOTED_RE = re.compile(r"""(['"])(?P<value>.*?)(?<!\\)\1""")


@dataclass(frozen=True, slots=True)
class CrawlLink:
    """A normalized link candidate from a page."""

    url: str
    text: str
    score: float
    is_pagination: bool = False


@dataclass(frozen=True, slots=True)
class _NavigationTemplate:
    url_prefix: str
    payload_prefix: str = ''
    payload_suffix: str = ''

    def build(self, arg: str, *, base_url: str) -> str | None:
        if self.payload_prefix or self.payload_suffix:
            payload = f'{self.payload_prefix}{arg}{self.payload_suffix}'
            return canonicalize_url(urljoin(base_url, f'{self.url_prefix}{quote(payload, safe="")}'))
        return canonicalize_url(urljoin(base_url, f'{self.url_prefix}{quote(arg, safe="")}'))


class LinkExtractor:
    """Extract crawlable links without site-specific selectors."""

    def extract(self, html: str, *, base_url: str, allowed_hosts: set[str] | None = None) -> list[CrawlLink]:
        """Return de-duplicated HTTP(S) links in document order."""
        try:
            root = lxml.html.fromstring(html)
        except (ValueError, TypeError):
            return []

        seen: set[str] = set()
        links: list[CrawlLink] = []
        js_templates = _navigation_function_templates(html)
        for anchor in root.xpath('//a[@href]'):
            href = anchor.get('href')
            if not href:
                continue
            canonical = canonicalize_url(urljoin(base_url, href))
            if canonical is None or canonical in seen:
                continue
            host = urlparse(canonical).hostname
            if allowed_hosts is not None and host not in allowed_hosts:
                continue

            text = ' '.join(anchor.text_content().split())
            is_pagination = self._is_pagination(anchor, text)
            links.append(
                CrawlLink(
                    url=canonical,
                    text=text,
                    score=self._score(canonical, text, is_pagination),
                    is_pagination=is_pagination,
                )
            )
            seen.add(canonical)

        for element in root.xpath('//*[@onclick]'):
            canonical = _onclick_navigation_url(element.get('onclick'), js_templates, base_url=base_url)
            if canonical is None or canonical in seen:
                continue
            host = urlparse(canonical).hostname
            if allowed_hosts is not None and host not in allowed_hosts:
                continue

            text = ' '.join(element.text_content().split())
            is_pagination = self._is_pagination(element, text)
            links.append(
                CrawlLink(
                    url=canonical,
                    text=text,
                    score=self._score(canonical, text, is_pagination),
                    is_pagination=is_pagination,
                )
            )
            seen.add(canonical)
        return links

    def _is_pagination(self, anchor: object, text: str) -> bool:
        label = ''
        if hasattr(anchor, 'get'):
            raw_label = anchor.get('aria-label')  # type: ignore[attr-defined]
            label = raw_label if isinstance(raw_label, str) else ''
        return bool(_PAGINATION_RE.search(f'{text} {label}'))

    def _score(self, url: str, text: str, is_pagination: bool) -> float:
        if is_pagination:
            return 0.95
        parsed = urlparse(url)
        haystack = f'{parsed.path} {text}'
        if _CONTENT_HINT_RE.search(haystack):
            if parsed.path.endswith(('.html', '.htm')):
                return 0.9
            if parsed.query:
                return 0.85
            return 0.8
        return 0.5


def path_similarity(left_url: str, right_url: str) -> float:
    """Return generic URL path-shape similarity in ``[0, 1]``.

    Dynamic-looking path segments collapse to ``{id}`` so pages like
    ``/news/2026/alpha`` and ``/news/2026/beta`` match by route shape, while
    query strings and host names do not create site-specific scoring rules.
    """
    left = _path_signature(left_url)
    right = _path_signature(right_url)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(a='/'.join(left), b='/'.join(right), autojunk=False).ratio()


def best_path_similarity(url: str, references: tuple[str, ...]) -> float:
    """Return the strongest route-shape match against known candidate URLs."""
    if not references:
        return 0.0
    return max(path_similarity(url, reference) for reference in references)


def _navigation_function_templates(html: str) -> dict[str, _NavigationTemplate]:
    templates: dict[str, _NavigationTemplate] = {}
    for match in _FUNCTION_RE.finditer(html):
        body = match.group('body')
        location = _LOCATION_TEMPLATE_RE.search(body)
        if location is None:
            continue
        url_prefix = location.group('url')
        if not _accepts_appended_argument(url_prefix):
            continue
        params = tuple(param.strip() for param in match.group('params').split(',') if param.strip())
        templates[match.group('name')] = _payload_navigation_template(body, url_prefix, params) or _NavigationTemplate(
            url_prefix=url_prefix
        )
    return templates


def _onclick_navigation_url(
    onclick: object,
    templates: dict[str, _NavigationTemplate],
    *,
    base_url: str,
) -> str | None:
    if not isinstance(onclick, str):
        return None
    call = _ONCLICK_CALL_RE.search(onclick)
    if call is None:
        return None
    template = templates.get(call.group('name'))
    if template is None:
        return None
    arg = _first_string_arg(call.group('args'))
    if not arg:
        return None
    return template.build(arg, base_url=base_url)


def _first_string_arg(args: str) -> str | None:
    match = _STRING_ARG_RE.search(args)
    if match is None:
        return None
    return match.group('value')


def _accepts_appended_argument(template: str) -> bool:
    return template.endswith(('=', '/', '-', '_'))


def _payload_navigation_template(
    body: str,
    url_prefix: str,
    params: tuple[str, ...],
) -> _NavigationTemplate | None:
    location_match = _LOCATION_TEMPLATE_RE.search(body)
    location_tail = body[location_match.end() :] if location_match else ''
    payload_name_match = _ENCODE_CALL_RE.search(location_tail)
    if payload_name_match is None:
        return None
    payload_name = payload_name_match.group('name')
    for assignment in _PAYLOAD_ASSIGN_RE.finditer(body):
        if assignment.group('name') != payload_name:
            continue
        expr = assignment.group('expr')
        arg_name = next(
            (param for param in params if re.search(rf'encodeURIComponent\(\s*{re.escape(param)}\s*\)', expr)), None
        )
        if arg_name is None:
            return None
        return _template_from_payload_expression(url_prefix, expr, arg_name)
    return None


def _template_from_payload_expression(url_prefix: str, expr: str, arg_name: str) -> _NavigationTemplate | None:
    arg_call = re.search(rf'encodeURIComponent\(\s*{re.escape(arg_name)}\s*\)', expr)
    if arg_call is None:
        return None
    before = ''.join(match.group('value') for match in _QUOTED_RE.finditer(expr[: arg_call.start()]))
    after_expr = expr[arg_call.end() :]
    after = ''.join(match.group('value') for match in _QUOTED_RE.finditer(after_expr))
    if not before or not after:
        return None
    if 'HASH=' in after and re.search(r'\+\s*[A-Za-z_$][\w$]*\s*\+', after_expr):
        after = after.replace('HASH=', 'HASH=crawl-', 1)
    return _NavigationTemplate(url_prefix=url_prefix, payload_prefix=before, payload_suffix=after)


def _path_signature(url: str) -> tuple[str, ...]:
    parsed = urlparse(url)
    segments = tuple(segment for segment in parsed.path.split('/') if segment)
    return tuple(
        _normalize_path_segment(segment, is_terminal=index == len(segments) - 1)
        for index, segment in enumerate(segments)
    )


def _normalize_path_segment(segment: str, *, is_terminal: bool = False) -> str:
    normalized = segment.strip().lower()
    if not normalized:
        return ''
    if _PATH_ID_RE.match(normalized):
        return '{id}'
    suffix = PurePosixPath(normalized).suffix
    if suffix:
        stem = normalized[: -len(suffix)]
        if _PATH_ID_RE.match(stem):
            return f'{{id}}{suffix}'
        if is_terminal and ('-' in stem or len(stem) >= 16):
            return f'{{slug}}{suffix}'
    if is_terminal and ('-' in normalized or len(normalized) >= 16):
        return '{slug}'
    return normalized
