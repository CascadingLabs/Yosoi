"""Live-tab execution of ``ys.File`` download specs.

Runs inside the browser fetcher's open-tab phase (see ``voiddriver._do_fetch``): for
each :class:`DownloadSpec` it either re-clicks the trigger and captures the resulting
download (``retrigger``) or fetches a resolved URL through the page's authenticated
context (``refetch``). Every download is verified against the spec's ``allowed_types``
(magic bytes + declared content-type) and fails fast on any mismatch — the offending
bytes are purged. The value returned is the view chosen by the field's declared type
(``DownloadRecord`` / path / bytes / text / parsed structure) via ``spec.output``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from yosoi.models.download import DownloadRecord, DownloadResult, DownloadSpec
from yosoi.storage.download_store import commit_download
from yosoi.types.filetypes import matches_allowed_types, parse_download
from yosoi.utils.exceptions import DownloadError
from yosoi.utils.files import init_yosoi

logger = logging.getLogger(__name__)

# Bytes inspected for magic-byte sniffing (head of the file).
_HEAD_BYTES = 4096
# Default per-file cap when a spec sets none. Kept modest on purpose: a scrape rarely
# needs a huge file, and N concurrent workers x a large cap is easy disk exhaustion.
_DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB
# Smallest accepted download — rejects a 0-byte/placeholder file even within an allowed type.
_MIN_BYTES = 1


def quarantine_dir(domain: str, base_dir: str | None = None) -> Path:
    """Return a per-domain quarantine dir (mode 0700).

    Defaults to ``.yosoi/downloads/<domain>/``. Pass *base_dir* to redirect downloads
    elsewhere (e.g. a scratch volume); a ``<domain>`` subdir is still created under it.
    """
    base = Path(base_dir).expanduser() if base_dir else init_yosoi('downloads')
    base.mkdir(parents=True, exist_ok=True)
    safe = ''.join(c if (c.isalnum() or c in '.-_') else '_' for c in domain) or 'unknown'
    target = base / safe
    target.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):  # best effort on platforms without chmod
        os.chmod(target, 0o700)
    return target


async def _resolve_href(tab: Any, selector: str) -> str | None:
    """Read the absolute href of the element matched by *selector* on the live tab."""
    expr = (
        f'(() => {{ const el = document.querySelector({json.dumps(selector)}); '
        'return el ? (el.href || el.getAttribute("href")) : null; })()'
    )
    try:
        result = await tab.eval_js(expr)
    except Exception as exc:  # noqa: BLE001 - eval failures become a fail-fast below
        logger.debug('href resolution failed for %r: %s', selector, exc)
        return None
    return result if isinstance(result, str) and result else None


async def _capture(tab: Any, spec: DownloadSpec, qdir: Path) -> Any:
    """Perform the actual download, returning a voidcrawl ``DownloadOutcome``."""
    # capture_download is exported at runtime but missing from voidcrawl's published
    # .pyi stub (only safe_url is declared) — VoidCrawl stub gap, see CAS-105 notes.
    from voidcrawl import capture_download, safe_url  # type: ignore[attr-defined]

    max_bytes = spec.max_bytes or _DEFAULT_MAX_BYTES

    if spec.mode == 'retrigger':
        if not spec.trigger:
            raise DownloadError(spec.field, 'retrigger mode requires a trigger selector')
        async with capture_download(tab, str(qdir), max_bytes=max_bytes) as dl:
            await tab.click_element(spec.trigger)
        return dl.value

    # refetch: resolve a URL, then download it through the page's browser context.
    url = spec.url or (await _resolve_href(tab, spec.href) if spec.href else None)
    if not url:
        raise DownloadError(spec.field, 'refetch mode could not resolve a URL to download')
    if safe_url(url) is None:
        raise DownloadError(spec.field, f'unsafe download URL scheme: {url!r}')
    # FUTURE (CAS-108): full SSRF defense — DNS-resolve + reject RFC1918/link-local/
    # metadata IPs + per-redirect re-validation. Alpha relies on safe_url + the
    # allowed_types content gate; refetch is opt-in and off by default.
    return await tab.download(url, str(qdir), max_bytes=max_bytes)


def _read_download_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _purge_download(path: Path) -> None:
    path.unlink(missing_ok=True)


def _commit_verified_download(
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
    return commit_download(
        qdir=qdir,
        field=field,
        src_path=src_path,
        sha256=sha256,
        content_type=content_type,
        size_bytes=size_bytes,
        source_url=source_url,
        allowed_types=allowed_types,
    )


async def run_download(tab: Any, spec: DownloadSpec, qdir: Path) -> DownloadResult:
    """Execute one download spec and return its verified result (fail-fast on any error)."""
    if not spec.allowed_types:
        raise DownloadError(
            spec.field,
            'no allowed_types in effect (default-deny) — set ys.File(allowed_types=[...]) '
            'or a run-wide allowlist before enabling downloads',
        )
    try:
        outcome = await _capture(tab, spec, qdir)
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(spec.field, f'download did not complete: {exc}') from exc

    path = Path(outcome.path)
    try:
        data = _read_download_bytes(path)
    except OSError as exc:
        raise DownloadError(spec.field, f'downloaded file unreadable: {exc}') from exc

    if len(data) < _MIN_BYTES:
        _purge_download(path)
        raise DownloadError(spec.field, f'downloaded file is empty ({len(data)} bytes)')

    declared_ct = getattr(outcome, 'content_type', None)
    if not matches_allowed_types(spec.allowed_types, declared_ct, data[:_HEAD_BYTES]):
        _purge_download(path)  # purge — bytes aren't trusted
        raise DownloadError(
            spec.field,
            f'content does not match allowed_types {list(spec.allowed_types)} '
            f'(declared content-type={declared_ct!r}, {len(data)} bytes)',
        )

    # Content-address the verified bytes (dedup) + record provenance / drift in the per-domain
    # index. `changed` is True when this field's bytes differ from the last recorded download.
    sha256 = hashlib.sha256(data).hexdigest()
    size_bytes = int(getattr(outcome, 'bytes', len(data)))
    cas_path, changed = _commit_verified_download(
        qdir=qdir,
        field=spec.field,
        src_path=path,
        sha256=sha256,
        content_type=declared_ct,
        size_bytes=size_bytes,
        source_url=spec.url or spec.href,
        allowed_types=spec.allowed_types,
    )
    record = DownloadRecord(
        path=str(cas_path),
        sha256=sha256,
        size_bytes=size_bytes,
        content_type=declared_ct,
        requested_url=spec.url or spec.href or spec.trigger,
    )
    # The field's declared type (resolved into spec.output) decides the value view.
    # A DownloadRecord is always available on the result for provenance regardless.
    value = _project_value(spec, data, declared_ct, record)
    return DownloadResult(record=record, value=value, changed=changed)


def _project_value(spec: DownloadSpec, data: bytes, content_type: str | None, record: DownloadRecord) -> Any:
    """Resolve the field value for a download according to ``spec.output``.

    'parsed' yields a generic python structure (csv rows / json object); the contract's
    TypeAdapter then coerces it into the field's declared type (e.g. list[MyRow]).
    """
    if spec.output == 'record':
        return record
    if spec.output == 'path':
        return Path(record.path)
    if spec.output == 'bytes':
        return data
    if spec.output == 'text':
        return data.decode('utf-8', errors='replace')
    # 'parsed'
    try:
        return parse_download(data, content_type)
    except Exception as exc:
        raise DownloadError(spec.field, f'could not parse download as structured data: {exc}') from exc


async def execute_downloads(
    tab: Any,
    specs: dict[str, DownloadSpec] | None,
    domain: str,
    base_dir: str | None = None,
) -> dict[str, DownloadResult]:
    """Run every download spec sequentially on the live *tab*; return per-field results.

    *base_dir* overrides the quarantine root (defaults to ``.yosoi/downloads/``).
    """
    if not specs:
        return {}
    qdir = quarantine_dir(domain, base_dir)
    results: dict[str, DownloadResult] = {}
    for field, spec in specs.items():
        results[field] = await run_download(tab, spec, qdir)
    return results


__all__ = ['execute_downloads', 'quarantine_dir', 'run_download']
