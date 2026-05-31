"""Content-addressed storage + a per-domain lookup index for ``ys.File`` downloads.

Downloaded bytes are stored under their sha256 (``<domain>/<sha256>.<ext>``) so identical
re-downloads collapse to a single file (dedup). A per-domain ``index.json`` is the
canonical lookup table the bytes feed:

- ``blobs``: ``sha256 -> {name, domain, content_type, ext, size_bytes, source_urls,
  first_seen, last_seen, seen_count}`` — "what is this hash, where did it come from".
- ``fields``: ``field -> {last_sha256, last_seen, history[]}`` — the drift source: a
  download is "changed" when a field's bytes differ from the last time we saw it.

This is intentionally a small JSON index, not a database. Concurrency: the read-modify-write
on ``index.json`` is last-writer-wins under concurrent same-domain workers.
FUTURE: guard with the pipeline's per-domain ``write_lock``; add a global cross-site rollup.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from yosoi.models.replay import utc_now
from yosoi.utils.files import atomic_write_json

_INDEX_NAME = 'index.json'

# content-type (sans parameters) → file extension for the content-addressed filename.
_EXT_BY_CONTENT_TYPE = {
    'text/csv': 'csv',
    'application/csv': 'csv',
    'application/json': 'json',
    'text/json': 'json',
    'application/pdf': 'pdf',
    'text/plain': 'txt',
    'text/html': 'html',
    'application/xml': 'xml',
    'text/xml': 'xml',
    'application/zip': 'zip',
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/gif': 'gif',
    'audio/mpeg': 'mp3',
    'video/mp4': 'mp4',
    'application/mp4': 'mp4',
    'audio/wav': 'wav',
}


def infer_extension(content_type: str | None, allowed_types: tuple[str, ...] = ()) -> str:
    """Pick a filename extension from the declared content-type, then the allowlist.

    Falls back to the first allowlist entry that looks like a bare name (not a MIME),
    then to ``'bin'``.
    """
    ct = (content_type or '').split(';')[0].strip().lower()
    if ct in _EXT_BY_CONTENT_TYPE:
        return _EXT_BY_CONTENT_TYPE[ct]
    for name in allowed_types:
        if '/' not in name:  # a friendly name / extension, not an explicit MIME
            return name
    return 'bin'


def _load_index(index_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(index_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault('blobs', {})
    data.setdefault('fields', {})
    return data


def _update_index(
    qdir: Path,
    *,
    field: str,
    domain: str,
    sha256: str,
    name: str,
    content_type: str | None,
    ext: str,
    size_bytes: int,
    source_url: str | None,
) -> bool:
    """Upsert the blob + field entries; return whether the field's bytes changed."""
    index_path = qdir / _INDEX_NAME
    data = _load_index(index_path)
    now = utc_now().isoformat()

    blob = data['blobs'].get(sha256)
    if blob is None:
        data['blobs'][sha256] = {
            'name': name,
            'domain': domain,
            'content_type': content_type,
            'ext': ext,
            'size_bytes': size_bytes,
            'source_urls': [source_url] if source_url else [],
            'first_seen': now,
            'last_seen': now,
            'seen_count': 1,
        }
    else:
        blob['last_seen'] = now
        blob['seen_count'] = int(blob.get('seen_count', 0)) + 1
        if source_url and source_url not in blob.get('source_urls', []):
            blob.setdefault('source_urls', []).append(source_url)

    field_entry = data['fields'].get(field)
    changed = field_entry is None or field_entry.get('last_sha256') != sha256
    if field_entry is None:
        data['fields'][field] = {'last_sha256': sha256, 'last_seen': now, 'history': [sha256]}
    else:
        field_entry['last_sha256'] = sha256
        field_entry['last_seen'] = now
        history = field_entry.setdefault('history', [])
        if not history or history[-1] != sha256:
            history.append(sha256)

    atomic_write_json(index_path, data, ensure_ascii=False)
    return changed


def commit_download(
    *,
    qdir: Path,
    field: str,
    src_path: Path,
    sha256: str,
    content_type: str | None,
    size_bytes: int,
    source_url: str | None,
    allowed_types: tuple[str, ...],
) -> tuple[Path, bool]:
    """Move a freshly-downloaded file to its content-addressed path and update the index.

    Stores at ``<qdir>/<sha256>.<ext>``. If that blob already exists, the freshly
    downloaded ``src_path`` is dropped (dedup). Returns ``(content_addressed_path, changed)``
    where ``changed`` is True when this field's bytes differ from the last recorded download.
    """
    ext = infer_extension(content_type, allowed_types)
    cas_path = qdir / f'{sha256}.{ext}'
    original_name = src_path.name
    if cas_path.exists():
        if src_path != cas_path:
            src_path.unlink(missing_ok=True)  # identical bytes already stored — drop the dup
    else:
        os.replace(src_path, cas_path)  # same dir → atomic move

    changed = _update_index(
        qdir,
        field=field,
        domain=qdir.name,
        sha256=sha256,
        name=original_name,
        content_type=content_type,
        ext=ext,
        size_bytes=size_bytes,
        source_url=source_url,
    )
    return cas_path, changed


__all__ = ['commit_download', 'infer_extension']
