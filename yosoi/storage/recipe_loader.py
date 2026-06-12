"""Recipe loader — fetch a RecipeBundle from an HTTP URL or local file path.

This is the async entry point for the ``contract=`` URL/path overload in
``ys.scrape()``. It handles:

- HTTP/HTTPS URLs (raw GitHub, any public host)
- Local ``.json`` file paths
- Schema version checking
- Integrity verification (sha256)
- Fail-fast on stale or misaligned recipes

Usage::

    bundle = await load_recipe("https://raw.githubusercontent.com/...")
    bundle = await load_recipe("/path/to/recipe.json")
"""

from __future__ import annotations

import logging
import os

import httpx

from yosoi.models.recipe import RecipeBundle

logger = logging.getLogger(__name__)

# Maximum size we'll accept for a recipe file fetched over HTTP.
# Recipes are small JSON documents — 5 MB is already very generous.
_MAX_RECIPE_BYTES = 5 * 1024 * 1024  # 5 MiB

# Timeout for HTTP fetches.
_HTTP_TIMEOUT = 30.0


def is_recipe_source(source: str) -> bool:
    """Return True when ``source`` looks like a recipe URL or JSON file path.

    Used by ``scrape()`` to decide whether to go through the recipe path
    instead of the normal ``resolve_contract()`` path.

    Matches:
    - Any ``http://`` or ``https://`` URL
    - Any local path ending in ``.json`` that exists on disk
    """
    if source.startswith('http://') or source.startswith('https://'):
        return True
    return source.endswith('.json') and os.path.isfile(source)


async def load_recipe(source: str) -> RecipeBundle:
    """Load, validate, and return a RecipeBundle from a URL or local path.

    Performs in order:
    1. Fetch content (HTTP GET or file read)
    2. Parse JSON into RecipeBundle
    3. Schema version check
    4. Integrity check (recipe_id sha256)
    5. Alignment check (contract fields vs selector coverage) — warns, does not fail
    6. Fail-fast if no selectors are present at all

    Args:
        source: An ``https://`` URL or a local ``.json`` file path.

    Returns:
        Validated RecipeBundle ready for use.

    Raises:
        ValueError: On schema mismatch, integrity failure, or empty selectors.
        FileNotFoundError: When a local path does not exist.
        httpx.HTTPError: On network failure fetching a URL.
    """
    raw = await _fetch_raw(source)
    return _parse_and_validate(raw, source)


async def _fetch_raw(source: str) -> str:
    """Fetch raw JSON text from a URL or local path."""
    if source.startswith('http://') or source.startswith('https://'):
        return await _fetch_http(source)
    return _read_local(source)


async def _fetch_http(url: str) -> str:
    """Fetch a recipe from an HTTP/HTTPS URL."""
    logger.info('Fetching recipe from %s', url)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={'Accept': 'application/json, text/plain, */*'},
        )
        response.raise_for_status()

        content_length = int(response.headers.get('content-length', 0))
        if content_length and content_length > _MAX_RECIPE_BYTES:
            raise ValueError(
                f'Recipe at {url!r} is too large '
                f'({content_length} bytes > {_MAX_RECIPE_BYTES} byte limit). '
                'Recipes should be small JSON documents.'
            )

        raw = response.text
        if len(raw.encode()) > _MAX_RECIPE_BYTES:
            raise ValueError(f'Recipe at {url!r} exceeds the {_MAX_RECIPE_BYTES} byte size limit.')

    logger.info('Fetched recipe from %s (%d chars)', url, len(raw))
    return raw


def _read_local(path: str) -> str:
    """Read a recipe from a local file path."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Recipe file not found: {path!r}')
    logger.info('Reading recipe from local file %s', path)
    with open(path, encoding='utf-8') as f:
        return f.read()


def _parse_and_validate(raw: str, source: str) -> RecipeBundle:
    """Parse JSON and run all validation checks. Fail-fast on any failure."""
    try:
        bundle = RecipeBundle.model_validate_json(raw)
    except Exception as exc:
        raise ValueError(
            f'Failed to parse recipe from {source!r}.\nIs this a valid Yosoi recipe JSON file?\nDetail: {exc}'
        ) from exc

    # 1. Schema version
    try:
        bundle.verify_schema()
    except ValueError as exc:
        raise ValueError(f'Recipe from {source!r}: {exc}') from exc

    # 2. Integrity
    try:
        bundle.verify_integrity()
    except ValueError as exc:
        raise ValueError(f'Recipe from {source!r}: {exc}') from exc

    # 3. Must have at least one domain's selectors
    if not bundle.selectors:
        raise ValueError(
            f'Recipe from {source!r} contains no selector snapshots. '
            'A recipe must include pre-discovered selectors to enable zero-LLM replay. '
            'Re-mint the recipe with `yosoi recipe mint` after running discovery.'
        )

    # 4. Alignment — warn but do not fail
    warnings = bundle.verify_alignment()
    for w in warnings:
        logger.warning('Recipe alignment warning (%s): %s', source, w)

    logger.info(
        'Recipe loaded: contract=%s domains=%s fields=%d',
        bundle.contract.name,
        list(bundle.selectors.keys()),
        len(bundle.contract.fields),
    )
    return bundle
