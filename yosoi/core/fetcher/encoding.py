"""Charset resolution for raw HTTP response bytes.

The HTTP ``Content-Type: charset=`` header is only one of the ways the web declares
an encoding, and it is frequently absent or wrong. Decoding on the header alone turns
every other non-UTF-8 page into mojibake with no error to signal it, so this module
walks the declarations in HTML5 priority order and only falls back to lossy decoding
once every honest candidate has failed.
"""

from __future__ import annotations

import codecs
import re
from collections.abc import Mapping
from typing import Final, Protocol

# HTML5 prescans the first 1024 bytes for a meta declaration; be a little more generous
# because real pages push the meta tag past a long comment or conditional block.
_META_PRESCAN_BYTES: Final = 4096

_META_CHARSET_RE: Final = re.compile(rb"""<meta[^>]*?charset\s*=\s*["']?\s*([a-zA-Z0-9_.:+-]+)""", re.IGNORECASE)

# Longest BOM first: the UTF-32 BOMs start with the UTF-16 BOM bytes.
_BOMS: Final = (
    (codecs.BOM_UTF32_LE, 'utf-32-le'),
    (codecs.BOM_UTF32_BE, 'utf-32-be'),
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF16_LE, 'utf-16-le'),
    (codecs.BOM_UTF16_BE, 'utf-16-be'),
)


def charset_from_content_type(content_type: str | None) -> str | None:
    """Return the ``charset`` parameter of a ``Content-Type`` header, if present."""
    if not content_type:
        return None
    for part in content_type.split(';')[1:]:
        key, _, value = part.partition('=')
        if key.strip().lower() == 'charset':
            cleaned = value.strip().strip('"\'')
            return cleaned or None
    return None


def charset_from_meta(content: bytes) -> str | None:
    """Return the encoding declared by an HTML ``<meta charset>`` tag, if present.

    Covers both HTML5 ``<meta charset=...>`` and the legacy
    ``<meta http-equiv="Content-Type" content="...; charset=...">`` form, since the
    regex matches the ``charset=`` token in either attribute.
    """
    match = _META_CHARSET_RE.search(content[:_META_PRESCAN_BYTES])
    if match is None:
        return None
    try:
        return match.group(1).decode('ascii')
    except UnicodeDecodeError:
        return None


def decode_html(content: bytes, *, declared: str | None = None) -> tuple[str, str]:
    """Decode response bytes to text, returning ``(text, encoding_used)``.

    Candidates are tried in order and the first one that decodes *strictly* wins:
    BOM, the HTTP header, the HTML ``<meta charset>`` declaration, UTF-8, then
    byte-level detection. A lossy UTF-8 decode is the last resort, so replacement
    characters now mean "genuinely undecodable bytes" rather than "wrong guess".
    """
    if not content:
        return '', 'utf-8'

    bom_encoding = _bom_encoding(content)
    if bom_encoding is not None:
        text = _strict_decode(content, bom_encoding)
        if text is not None:
            return text, bom_encoding

    for candidate in (declared, charset_from_meta(content), 'utf-8', _detect_encoding(content)):
        if candidate is None:
            continue
        text = _strict_decode(content, candidate)
        if text is not None:
            return text, candidate

    return content.decode('utf-8', errors='replace'), 'utf-8'


class _BytesResponse(Protocol):
    """The slice of an httpx-style response that charset resolution needs."""

    @property
    def content(self) -> bytes: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


def decode_response(response: _BytesResponse) -> str:
    """Decode an httpx-style response body with full charset resolution."""
    declared = charset_from_content_type(response.headers.get('content-type'))
    return decode_html(response.content, declared=declared)[0]


def _bom_encoding(content: bytes) -> str | None:
    for bom, encoding in _BOMS:
        if content.startswith(bom):
            return encoding
    return None


def _strict_decode(content: bytes, encoding: str) -> str | None:
    """Decode with ``errors='strict'``, returning ``None`` when the codec rejects the bytes."""
    try:
        return content.decode(encoding, errors='strict')
    except (LookupError, UnicodeDecodeError, ValueError):
        return None


def _detect_encoding(content: bytes) -> str | None:
    """Best-effort byte-level detection for pages that declare nothing."""
    from charset_normalizer import from_bytes

    best = from_bytes(content).best()
    return None if best is None else best.encoding
