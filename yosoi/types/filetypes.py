"""File-type allowlist registry, content sniffing, and parse transforms for ``ys.File``.

The allowlist is the cheap, high-value safety layer behind ``ys.File(allowed_types=…)``:
a download is only trusted when its bytes match a type the caller explicitly named.
Matching uses the server-declared ``Content-Type`` *and* magic-byte signatures, so an
executable disguised as a document — or an HTML "sign in to download" interstitial served
as ``text/html`` — is rejected even though it never appears in the allowlist.

There is **no permissive default**: an empty effective allowlist matches nothing
(see :func:`matches_allowed_types`). Callers enforce default-deny on top of that.
"""

from __future__ import annotations

import csv as _csv
import io
import json as _json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

# Structured parse formats shipped today. Stdlib only — no docling / RAG / embeddings / OCR.
# The format is inferred from the download's content-type (see ``parse_download``); it is
# NOT a user knob — the field's declared type decides whether parsing happens at all.
PARSE_FORMATS: tuple[str, ...] = ('csv', 'json')


@dataclass(frozen=True)
class FileTypeSpec:
    """How to recognise one allowed file type.

    Attributes:
        accept_content_types: Server ``Content-Type`` values (sans parameters) that
            count as this type. Kept deliberately narrow so mislabeled HTML is rejected.
        magic: ``(offset, signature)`` byte patterns; any match confirms the type
            regardless of the declared content-type. Empty for text formats.
        text_like: True for text formats (csv/json/…) that have no magic bytes — only
            these may fall back to a "looks like UTF-8 text" check when the server sends
            no content-type at all.
    """

    accept_content_types: frozenset[str] = field(default_factory=frozenset)
    magic: tuple[tuple[int, bytes], ...] = ()
    text_like: bool = False


# Built-in friendly-name → spec table. Binary types lean on magic bytes (so
# ``application/octet-stream`` is safe to accept); text types lean on a narrow
# content-type set so a ``text/html`` interstitial can't slip through.
_OCTET = 'application/octet-stream'
_TYPES: dict[str, FileTypeSpec] = {
    'csv': FileTypeSpec(frozenset({'text/csv', 'application/csv', 'text/plain'}), (), text_like=True),
    'json': FileTypeSpec(frozenset({'application/json', 'text/json'}), (), text_like=True),
    'txt': FileTypeSpec(frozenset({'text/plain'}), (), text_like=True),
    'xml': FileTypeSpec(frozenset({'application/xml', 'text/xml'}), (), text_like=True),
    'pdf': FileTypeSpec(frozenset({'application/pdf', _OCTET}), ((0, b'%PDF-'),)),
    'png': FileTypeSpec(frozenset({'image/png', _OCTET}), ((0, b'\x89PNG\r\n\x1a\n'),)),
    'jpg': FileTypeSpec(frozenset({'image/jpeg', _OCTET}), ((0, b'\xff\xd8\xff'),)),
    'jpeg': FileTypeSpec(frozenset({'image/jpeg', _OCTET}), ((0, b'\xff\xd8\xff'),)),
    'gif': FileTypeSpec(frozenset({'image/gif', _OCTET}), ((0, b'GIF87a'), (0, b'GIF89a'))),
    'zip': FileTypeSpec(frozenset({'application/zip', _OCTET}), ((0, b'PK\x03\x04'), (0, b'PK\x05\x06'))),
    'mp3': FileTypeSpec(
        frozenset({'audio/mpeg', _OCTET}),
        ((0, b'ID3'), (0, b'\xff\xfb'), (0, b'\xff\xf3'), (0, b'\xff\xf2')),
    ),
    'mp4': FileTypeSpec(frozenset({'video/mp4', 'application/mp4', _OCTET}), ((4, b'ftyp'),)),
    'wav': FileTypeSpec(frozenset({'audio/wav', 'audio/x-wav', _OCTET}), ((0, b'RIFF'),)),
}

# Aliases so a few common synonyms resolve to a canonical key.
_ALIASES = {'jpeg': 'jpg', 'text': 'txt', 'mpeg3': 'mp3', 'm4a': 'mp4'}


def _canonical(name: str) -> str:
    """Normalise one allowlist entry to a canonical key, or raise on an unknown type.

    Accepts friendly names (``mp4``), bare extensions (``.mp4``), and explicit MIME
    strings (``video/mp4`` or vendor types like ``application/vnd.ms-excel``).
    """
    n = name.strip().lower().lstrip('.')
    if not n:
        raise ValueError('allowed_types entries must be non-empty')
    n = _ALIASES.get(n, n)
    if n in _TYPES:
        return n
    if '/' in n:  # explicit MIME — accept verbatim (power-user escape hatch)
        return n
    raise ValueError(
        f'unknown file type {name!r}; use a known name ({", ".join(sorted(_TYPES))}), '
        'a bare extension, or an explicit MIME type'
    )


def _spec_for(canonical: str) -> FileTypeSpec:
    spec = _TYPES.get(canonical)
    if spec is not None:
        return spec
    # Explicit MIME entry: trust the declared content-type only.
    return FileTypeSpec(frozenset({canonical}), (), text_like=canonical.startswith('text/'))


def normalize_allowed_types(names: Iterable[str] | None) -> tuple[str, ...]:
    """Validate + canonicalise an ``allowed_types`` list (deduped, order-stable).

    Raises ``ValueError`` on an unrecognised type name so a typo fails at
    contract-definition time rather than silently allowing nothing.
    """
    if names is None:
        return ()
    if isinstance(names, str):  # guard against ys.File(allowed_types='csv')
        names = [names]
    out: list[str] = []
    for name in names:
        canon = _canonical(name)
        if canon not in out:
            out.append(canon)
    return tuple(out)


def _looks_like_text(head: bytes) -> bool:
    """Heuristic: decodable as UTF-8 and contains no NUL byte (i.e. not binary)."""
    if b'\x00' in head:
        return False
    try:
        head.decode('utf-8')
    except UnicodeDecodeError:
        # A truncated multi-byte sequence at the buffer edge is still "text".
        try:
            head[: max(0, len(head) - 3)].decode('utf-8')
        except UnicodeDecodeError:
            return False
    return True


def matches_allowed_types(
    allowed: tuple[str, ...],
    declared_content_type: str | None,
    head_bytes: bytes,
) -> bool:
    """True iff the download matches at least one allowed type.

    Default-deny: an empty ``allowed`` returns False (nothing matches).
    """
    if not allowed:
        return False
    ct = (declared_content_type or '').split(';')[0].strip().lower()
    for canonical in allowed:
        spec = _spec_for(canonical)
        for offset, sig in spec.magic:
            if head_bytes[offset : offset + len(sig)] == sig:
                return True
        if ct and ct in spec.accept_content_types:
            return True
        # No content-type from the server + a text format → accept real text only.
        if not ct and spec.text_like and _looks_like_text(head_bytes):
            return True
    return False


# --- parse transforms ------------------------------------------------------
#
# These back the 'parsed' output view (a ys.File field annotated list/dict/Model). The
# format (csv vs json) is chosen from the download's content-type — NOT a user knob — so
# the field's declared *type* stays the single signal for "I want structured data". The
# resulting python structure is then validated/coerced against the annotation by the
# contract's TypeAdapter oracle (Contract.coerce_field), which is how a list[MyRow] field
# gets per-row, semantically-typed rows for free. Pluggable seam for xlsx/zip later.

ParseFn = Callable[[bytes, str | None], Any]


def _parse_csv(data: bytes, _content_type: str | None) -> list[dict[str, str]]:
    text = data.decode('utf-8-sig', errors='replace')
    return list(_csv.DictReader(io.StringIO(text)))


def _parse_json(data: bytes, _content_type: str | None) -> Any:
    return _json.loads(data.decode('utf-8'))


_PARSERS: dict[str, ParseFn] = {'csv': _parse_csv, 'json': _parse_json}


def _format_for_content_type(content_type: str | None) -> str:
    """Pick a parse format (csv/json) from the server-declared content-type."""
    ct = (content_type or '').split(';')[0].strip().lower()
    if 'json' in ct:
        return 'json'
    # csv, text/plain, octet-stream, or no content-type → treat as delimited text.
    return 'csv'


def parse_download(data: bytes, content_type: str | None) -> Any:
    """Parse downloaded bytes into a python structure, format chosen by content-type.

    JSON content-types → parsed object; everything else → CSV rows (``list[dict]``).
    The caller (contract validation) then coerces this into the field's declared type.
    """
    fmt = _format_for_content_type(content_type)
    return _PARSERS[fmt](data, content_type)


def known_type_names() -> tuple[str, ...]:
    """Sorted built-in friendly type names (for error messages / docs)."""
    return tuple(sorted(_TYPES))


__all__ = [
    'PARSE_FORMATS',
    'FileTypeSpec',
    'known_type_names',
    'matches_allowed_types',
    'normalize_allowed_types',
    'parse_download',
]
