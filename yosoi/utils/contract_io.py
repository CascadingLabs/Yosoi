"""Contract save/load utilities.

Provides simple save and load helpers so contracts can be shared as standalone
JSON files — symmetrical to how selector snapshots are saved to .yosoi/selectors/.

A saved contract is a plain ContractSpec JSON file:

    {
        "name": "Product",
        "doc": "E-commerce product page",
        "fields": {
            "name": {"yosoi_type": "title", "description": "Product name"},
            "price": {"yosoi_type": "price", "description": "Product price"}
        }
    }

Loading accepts:
  - A local file path ending in .json
  - An https:// URL
  - A gh:owner/repo/path@ref shorthand (rewritten to raw.githubusercontent.com)

Saving writes the ContractSpec to disk as indented JSON.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.models.contract import Contract

logger = logging.getLogger(__name__)

# Maximum size accepted for a contract file fetched over HTTP.
# Contracts are small JSON — 1 MB is already very generous.
_MAX_CONTRACT_BYTES = 1 * 1024 * 1024  # 1 MiB
_HTTP_TIMEOUT = 30.0


def save_contract(contract: type[Contract], path: str | Path) -> Path:
    """Save a Contract class to a JSON file.

    Serialises the contract to a ContractSpec and writes it as indented JSON.
    The resulting file can be loaded back with load_contract() or passed
    directly to resolve_contract() / ys.scrape(contract=...).

    Args:
        contract: The Contract subclass to save.
        path: Destination file path. Should end in .json.

    Returns:
        The resolved Path that was written.

    Example::

        import yosoi as ys
        from myapp.contracts import Product

        ys.save_contract(Product, "contracts/product.json")

        # Someone else can then use it:
        items = await ys.scrape(url, contract="contracts/product.json")
    """
    from yosoi.utils.files import atomic_write_text

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    spec = contract.to_spec()
    atomic_write_text(dest, spec.model_dump_json(indent=2))
    logger.info('Saved contract %r to %s', contract.__name__, dest)
    return dest


def is_contract_source(source: str) -> bool:
    """Return True when source looks like a contract JSON file or URL.

    Matches:
    - Any http:// or https:// URL (http:// is matched so it routes into
      load_contract which rejects it with an actionable error)
    - Any gh:owner/repo/path[@ref] shorthand
    - Any local path ending in .json that exists on disk

    Note: this does NOT match all .json paths — only ones that exist — so a
    path:ClassName string like 'myfile.py:MyContract' is never misidentified.
    """
    from yosoi.storage.recipe_loader import GH_PREFIX

    if source.startswith(('http://', 'https://', GH_PREFIX)):
        return True
    return source.endswith('.json') and os.path.isfile(source)


async def load_contract(source: str) -> type[Contract]:
    """Load a Contract class from a local .json path, https:// URL, or gh: ref.

    Fetches and parses a ContractSpec JSON file and rehydrates it into a
    working Contract subclass. Performs integrity checks on the parsed spec
    before returning.

    Args:
        source: A local .json path, https:// URL, or gh:owner/repo/path@ref.

    Returns:
        A rehydrated Contract subclass ready for use.

    Raises:
        ValueError: On plaintext http://, bad JSON, or an invalid spec.
        FileNotFoundError: When a local path does not exist.
        httpx.HTTPError: On network failure fetching a URL.

    Example::

        # Load from GitHub
        contract = await load_contract("gh:owner/repo/contracts/product.json")

        # Load local file
        contract = await load_contract("contracts/product.json")

        # Use immediately
        items = await ys.scrape(url, contract=contract)
    """
    raw = await _fetch_contract_raw(source)
    return _parse_contract(raw, source)


async def _fetch_contract_raw(source: str) -> str:
    """Resolve the ref and fetch raw JSON text from an https URL or local path."""
    from yosoi.storage.recipe_loader import resolve_recipe_ref

    resolved = resolve_recipe_ref(source)
    if resolved.startswith('http://'):
        raise ValueError(
            f'Refusing to fetch contract over plaintext http: {resolved!r}. Use https://, a gh: ref, or a local path.'
        )
    if resolved.startswith('https://'):
        return await _fetch_contract_http(resolved)
    return _read_contract_local(resolved)


async def _fetch_contract_http(url: str) -> str:
    """Fetch a contract JSON file from an HTTPS URL."""
    import httpx

    logger.info('Fetching contract from %s', url)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, headers={'Accept': 'application/json, text/plain, */*'})
        response.raise_for_status()

        content_length = int(response.headers.get('content-length', 0))
        if content_length and content_length > _MAX_CONTRACT_BYTES:
            raise ValueError(
                f'Contract at {url!r} is too large ({content_length} bytes > {_MAX_CONTRACT_BYTES} byte limit).'
            )

        raw = response.text
        if len(raw.encode()) > _MAX_CONTRACT_BYTES:
            raise ValueError(f'Contract at {url!r} exceeds the {_MAX_CONTRACT_BYTES} byte size limit.')

    logger.info('Fetched contract from %s (%d chars)', url, len(raw))
    return raw


def _read_contract_local(path: str) -> str:
    """Read a contract JSON file from a local path."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Contract file not found: {path!r}')
    logger.info('Reading contract from local file %s', path)
    with open(path, encoding='utf-8') as f:
        return f.read()


def _parse_contract(raw: str, source: str) -> type[Contract]:
    """Parse a raw JSON string into a rehydrated Contract class."""
    from yosoi.models.spec import ContractSpec

    try:
        spec = ContractSpec.model_validate_json(raw)
    except Exception as exc:
        raise ValueError(
            f'Failed to parse contract from {source!r}.\nIs this a valid Yosoi ContractSpec JSON file?\nDetail: {exc}'
        ) from exc

    try:
        return spec.to_contract()
    except Exception as exc:
        raise ValueError(f'Contract spec from {source!r} could not be rehydrated: {exc}') from exc
