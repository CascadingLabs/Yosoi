"""Recipe loader — fetch a RecipeBundle from a URL, ``gh:`` ref, or local file path.

This is the async entry point for the ``contract=`` URL/path overload in
``ys.scrape()`` and the hydration backend for ``ReplayPolicy``. It handles:

- HTTPS URLs (raw GitHub, any public host) — plaintext ``http://`` is rejected
- ``gh:owner/repo/path@ref`` shorthand (rewritten to raw.githubusercontent.com)
- Local ``.json`` file paths
- Private-host fetches via an optional bearer token (resolved from a SecretRef
  at the policy edge — never read from env here)
- Schema version checking
- Integrity verification (sha256), plus an optional pinned ``expected_recipe_id``
- Fail-fast on stale or misaligned recipes

Usage::

    bundle = await load_recipe("https://raw.githubusercontent.com/...")
    bundle = await load_recipe("gh:owner/yosoi-recipes/recipes/shop/v1/recipe.json@main")
    bundle = await load_recipe("/path/to/recipe.json")
"""

from __future__ import annotations

import logging
import os

from yosoi.models.recipe import RecipeBundle

logger = logging.getLogger(__name__)

# Maximum size we'll accept for a recipe file fetched over HTTP.
# Recipes are small JSON documents — 5 MB is already very generous.
_MAX_RECIPE_BYTES = 5 * 1024 * 1024  # 5 MiB

# Timeout for HTTP fetches.
_HTTP_TIMEOUT = 30.0

#: GitHub shorthand prefix accepted by :func:`resolve_recipe_ref`.
GH_PREFIX = 'gh:'


def is_recipe_source(source: str) -> bool:
    """Return True when ``source`` looks like a recipe URL, ``gh:`` ref, or JSON file path.

    Used by ``scrape()`` to decide whether to go through the recipe path
    instead of the normal ``resolve_contract()`` path.

    Matches:
    - Any ``http://`` or ``https://`` URL (``http://`` is matched so it routes
      into :func:`load_recipe`, which rejects it with an actionable error —
      better than silently treating it as a contract name)
    - Any ``gh:owner/repo/path[@ref]`` shorthand
    - Any local path ending in ``.json`` that exists on disk
    """
    if source.startswith(('http://', 'https://', GH_PREFIX)):
        return True
    return source.endswith('.json') and os.path.isfile(source)


def resolve_recipe_ref(source: str) -> str:
    """Rewrite a ``gh:owner/repo/path@ref`` shorthand into a raw.githubusercontent URL.

    Pure string manipulation — no IO, no GitHub API — so the MVP install path
    stays a plain https fetch. Non-``gh:`` sources pass through untouched. The
    ``@ref`` segment is split on the LAST ``@`` so paths containing ``@`` keep
    working; a missing ref defaults to ``main``.

    Args:
        source: A recipe ref in any accepted form.

    Returns:
        An ``https://raw.githubusercontent.com/...`` URL for ``gh:`` refs,
        otherwise ``source`` unchanged.

    Raises:
        ValueError: When a ``gh:`` ref is missing owner, repo, or a file path.

    """
    if not source.startswith(GH_PREFIX):
        return source
    body = source[len(GH_PREFIX) :]
    if '@' in body:
        path_part, _, ref = body.rpartition('@')
    else:
        path_part, ref = body, 'main'
    parts = [p for p in path_part.split('/') if p]
    if len(parts) < 3 or not ref:
        raise ValueError(
            f'Malformed gh: recipe ref {source!r}. '
            "Expected 'gh:owner/repo/path/to/recipe.json[@ref]' (ref defaults to 'main')."
        )
    owner, repo, *rest = parts
    return f'https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{"/".join(rest)}'


async def load_recipe(
    source: str,
    *,
    expected_recipe_id: str | None = None,
    token: str | None = None,
) -> RecipeBundle:
    """Load, validate, and return a RecipeBundle from a URL, ``gh:`` ref, or local path.

    Performs in order:
    1. Resolve ``gh:`` shorthand; reject plaintext ``http://``
    2. Fetch content (HTTPS GET or file read)
    3. Parse JSON into RecipeBundle
    4. Schema version check
    5. Integrity check (recipe_id sha256)
    6. Pinned-identity check (``expected_recipe_id``), when supplied
    7. Alignment check (contract fields vs selector coverage) — warns, does not fail
    8. Fail-fast if no selectors are present at all

    Args:
        source: An ``https://`` URL, a ``gh:owner/repo/path@ref`` shorthand, or a
            local ``.json`` file path.
        expected_recipe_id: Optional pinned content hash (``sha256:...``). A
            fetched bundle whose ``recipe_id`` differs fails closed — the
            lockfile-grade guarantee for refs that can move (e.g. ``@main``).
        token: Optional bearer token for private hosts. Pass the *resolved*
            secret (the policy edge owns SecretRef resolution); it is sent only
            on the initial request — httpx drops Authorization on cross-origin
            redirects, so the token cannot leak to a redirect target.

    Returns:
        Validated RecipeBundle ready for use.

    Raises:
        ValueError: On plaintext-http refusal, schema mismatch, integrity
            failure, pinned-id mismatch, or empty selectors.
        FileNotFoundError: When a local path does not exist.
        httpx.HTTPError: On network failure fetching a URL.

    """
    raw = await _fetch_raw(source, token=token)
    bundle = _parse_and_validate(raw, source)
    if expected_recipe_id is not None and bundle.recipe_id != expected_recipe_id:
        raise ValueError(
            f'Recipe from {source!r} has recipe_id {bundle.recipe_id!r} but '
            f'{expected_recipe_id!r} was pinned. The artifact at this ref has changed '
            '(or the pin is stale) — refusing to replay an unexpected recipe.'
        )
    return bundle


async def _fetch_raw(source: str, token: str | None = None) -> str:
    """Resolve the ref and fetch raw JSON text from an https URL or local path."""
    resolved = resolve_recipe_ref(source)
    if resolved.startswith('http://'):
        raise ValueError(
            f'Refusing to fetch recipe over plaintext http: {resolved!r}. '
            'Integrity hashing protects the artifact at rest, not a plaintext fetch '
            'an attacker can rewrite end-to-end (recipe_id travels inside the same '
            'file). Use https://, a gh: ref, or a local path.'
        )
    if resolved.startswith('https://'):
        return await _fetch_http(resolved, token=token)
    return _read_local(resolved)


async def _fetch_http(url: str, token: str | None = None) -> str:
    """Fetch a recipe from an HTTPS URL, optionally authenticating with a bearer token."""
    import httpx  # lazy: keep `import yosoi` (and the policy edge) off the httpx tax

    logger.info('Fetching recipe from %s', url)
    headers = {'Accept': 'application/json, text/plain, */*'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
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
