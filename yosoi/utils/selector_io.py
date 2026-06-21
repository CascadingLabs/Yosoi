"""Selector save/load utilities.

Provides helpers to fetch a standalone selector snapshot file from a local
path, https:// URL, or gh: shorthand — without a bundled contract.

This is the counterpart to contract_io.py. Together they let you mix and
match contracts and selectors from different sources:

    # Your contract, someone else's selectors
    items = await ys.scrape(
        url,
        contract=MyLocalContract,
        selectors="gh:someone/selectors/shopify.json",
    )

    # Someone else's contract, your own selectors (discovered fresh or local)
    items = await ys.scrape(
        url,
        contract="gh:someone/contracts/product.json",
        selectors="selectors/my_shopify_selectors.json",
    )

A standalone selector file is a plain SnapshotMap JSON:

    {
        "url": "https://example.com/product/1",
        "domain": "example.com",
        "snapshots": {
            "name": {"primary": "h1.product-title", "discovered_at": "..."},
            "price": {"primary": ".price", "discovered_at": "..."}
        }
    }

Or a dict of domain -> SnapshotMap (multi-domain, matching the recipe format):

    {
        "example.com": { ...SnapshotMap... },
        "shop.example.com": { ...SnapshotMap... }
    }
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from yosoi.models.snapshot import SnapshotMap

logger = logging.getLogger(__name__)

_MAX_SELECTOR_BYTES = 5 * 1024 * 1024  # 5 MiB
_HTTP_TIMEOUT = 30.0


def is_selector_source(source: str) -> bool:
    """Return True when source looks like a selector JSON file or URL.

    Matches:
    - Any http:// or https:// URL
    - Any gh:owner/repo/path[@ref] shorthand
    - Any local path ending in .json that exists on disk
    """
    from yosoi.storage.recipe_loader import GH_PREFIX

    if source.startswith(('http://', 'https://', GH_PREFIX)):
        return True
    return source.endswith('.json') and os.path.isfile(source)


async def load_selectors(source: str) -> dict[str, SnapshotMap]:
    """Load selector snapshots from a local .json path, https:// URL, or gh: ref.

    Accepts two JSON shapes:
    - A single SnapshotMap (for one domain): {"url": ..., "domain": ..., "snapshots": {...}}
    - A dict of domain -> SnapshotMap (for multiple domains)

    Args:
        source: A local .json path, https:// URL, or gh:owner/repo/path@ref.

    Returns:
        Dict mapping domain strings to SnapshotMap instances.

    Raises:
        ValueError: On plaintext http://, bad JSON, or an invalid selector file.
        FileNotFoundError: When a local path does not exist.
        httpx.HTTPError: On network failure fetching a URL.

    Example::

        selectors = await load_selectors("gh:someone/selectors/shopify.json")
        items = await ys.scrape(url, contract=MyContract, selectors=selectors)
    """
    raw = await _fetch_selector_raw(source)
    return _parse_selectors(raw, source)


async def _fetch_selector_raw(source: str) -> str:
    """Resolve the ref and fetch raw JSON text."""
    from yosoi.storage.recipe_loader import resolve_recipe_ref

    resolved = resolve_recipe_ref(source)
    if resolved.startswith('http://'):
        raise ValueError(
            f'Refusing to fetch selectors over plaintext http: {resolved!r}. Use https://, a gh: ref, or a local path.'
        )
    if resolved.startswith('https://'):
        return await _fetch_selector_http(resolved)
    return _read_selector_local(resolved)


async def _fetch_selector_http(url: str) -> str:
    """Fetch a selector JSON file from an HTTPS URL."""
    import httpx

    logger.info('Fetching selectors from %s', url)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, headers={'Accept': 'application/json, text/plain, */*'})
        response.raise_for_status()

        content_length = int(response.headers.get('content-length', 0))
        if content_length and content_length > _MAX_SELECTOR_BYTES:
            raise ValueError(
                f'Selector file at {url!r} is too large ({content_length} bytes > {_MAX_SELECTOR_BYTES} byte limit).'
            )

        raw = response.text
        if len(raw.encode()) > _MAX_SELECTOR_BYTES:
            raise ValueError(f'Selector file at {url!r} exceeds the {_MAX_SELECTOR_BYTES} byte size limit.')

    logger.info('Fetched selectors from %s (%d chars)', url, len(raw))
    return raw


def _read_selector_local(path: str) -> str:
    """Read a selector JSON file from a local path."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Selector file not found: {path!r}')
    logger.info('Reading selectors from local file %s', path)
    with open(path, encoding='utf-8') as f:
        return f.read()


def _parse_selectors(raw: str, source: str) -> dict[str, SnapshotMap]:
    """Parse raw JSON into a domain -> SnapshotMap dict.

    Handles two shapes:
    1. Single SnapshotMap: {"url": ..., "domain": ..., "snapshots": {...}}
    2. Multi-domain dict: {"example.com": {...SnapshotMap...}, ...}
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Failed to parse selector file from {source!r}: invalid JSON.\nDetail: {exc}') from exc

    if not isinstance(data, dict):
        raise ValueError(f'Selector file from {source!r} must be a JSON object, got {type(data).__name__}.')

    # Shape 1: single SnapshotMap — has "snapshots" key at top level
    if 'snapshots' in data:
        try:
            snap_map = SnapshotMap.model_validate(data)
        except Exception as exc:
            raise ValueError(
                f'Selector file from {source!r} looks like a single SnapshotMap but failed to parse: {exc}'
            ) from exc
        return {snap_map.domain: snap_map}

    # Shape 2: multi-domain dict — each value is a SnapshotMap
    result: dict[str, SnapshotMap] = {}
    errors: list[str] = []
    for domain, value in data.items():
        if not isinstance(value, dict):
            errors.append(f'  {domain!r}: expected object, got {type(value).__name__}')
            continue
        try:
            result[domain] = SnapshotMap.model_validate(value)
        except (ValueError, TypeError) as exc:
            errors.append(f'  {domain!r}: {exc}')

    if errors:
        raise ValueError(f'Selector file from {source!r} has invalid entries:\n' + '\n'.join(errors))

    if not result:
        raise ValueError(
            f'Selector file from {source!r} contains no selector snapshots. '
            "A selector file must contain at least one domain's snapshots."
        )

    return result


def save_selectors(
    snapshots: dict[str, SnapshotMap],
    path: str | Path,
) -> Path:
    """Save selector snapshots to a JSON file.

    Writes a multi-domain selector file that can be shared and loaded with
    load_selectors() or passed directly to ys.scrape(selectors=...).

    Args:
        snapshots: Dict mapping domain strings to SnapshotMap instances,
            as returned by SelectorStorage.load_snapshots().
        path: Destination file path. Should end in .json.

    Returns:
        The resolved Path that was written.

    Example::

        # After running discovery on a domain, export the selectors:
        storage = SelectorStorage()
        snaps = await storage.load_snapshots("example.com")
        ys.save_selectors({"example.com": snaps_map}, "selectors/example.json")

        # Someone else can load and use them:
        items = await ys.scrape(url, contract=MyContract,
                                selectors="selectors/example.json")
    """
    from yosoi.utils.files import atomic_write_text

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    payload = {domain: snap_map.model_dump(mode='json') for domain, snap_map in snapshots.items()}
    atomic_write_text(dest, json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info('Saved selectors for %d domain(s) to %s', len(snapshots), dest)
    return dest
