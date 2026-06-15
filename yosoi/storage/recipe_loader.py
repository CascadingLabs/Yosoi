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
- Domain-coverage check against the URLs about to be scraped — warns, does not fail
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


class StaleRecipeError(ValueError):
    """A preloaded recipe's selectors no longer match the live page.

    Raised by the cache layer (``PipelineCacheMixin._evaluate_cached_verdicts``)
    when a domain's selectors came from a recipe (``selector_source ==
    'preloaded'``) and per-field verification — the SAME ``CacheVerdict.STALE``
    check the on-disk cache already uses — found drift.

    This is deliberately a DIFFERENT outcome from the on-disk-cache case: a
    stale local cache silently re-discovers (the user paid for discovery once,
    can pay again). A stale RECIPE re-discovering silently would defeat the
    entire point of sharing it — the consumer thinks they're getting zero-LLM
    replay and instead gets a surprise LLM bill, or a confusing failure if no
    model is configured. Surfacing it as a distinct, named error lets the
    consumer act on it directly: get a newer recipe, or opt into re-discovery
    explicitly.
    """

    def __init__(self, source: str, stale_fields: set[str], domain: str) -> None:
        """Build the message naming the recipe, domain, and drifted fields."""
        self.source = source
        self.stale_fields = stale_fields
        self.domain = domain
        super().__init__(
            f'Recipe {source!r} is stale for {domain}: selector(s) '
            f'{", ".join(sorted(stale_fields))} no longer match this page '
            f'(the site likely changed since the recipe was minted). '
            f'Check for a newer version of this recipe, or pass model=... '
            f'to allow Yosoi to re-discover these field(s).'
        )


async def load_recipe(
    source: str,
    target_urls: list[str] | None = None,
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
    9. Domain-coverage check against ``target_urls`` — warns, does not fail

    Args:
        source: An ``https://`` URL, a ``gh:owner/repo/path@ref`` shorthand, or a
            local ``.json`` file path.
        target_urls: The URL(s) this recipe is about to be used to scrape. When
            given, each target's domain is checked against the bundle's covered
            domains (with the same one-label subdomain fallback
            ``SelectorStorage._preloaded_for_domain`` uses) and a warning is
            logged for any uncovered domain — BEFORE any fetch happens. Without
            this, an uncovered domain just falls through to normal discovery (if
            a model is configured) with no signal that the recipe was a no-op
            for that URL.
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

    if target_urls:
        _warn_uncovered_domains(bundle, target_urls, source)

    return bundle


def _recipe_covers_domain(covered: set[str], domain: str) -> bool:
    """Return True when *domain* is covered, with the same fallback as the storage layer.

    Mirrors ``SelectorStorage._preloaded_for_domain``'s one-label subdomain
    fallback (``www.example.com`` -> ``example.com``).
    """
    if domain in covered:
        return True
    parts = domain.split('.', 1)
    return len(parts) == 2 and parts[1] in covered


def _warn_uncovered_domains(bundle: RecipeBundle, target_urls: list[str], source: str) -> None:
    """Log a warning for every target URL whose domain this recipe doesn't cover."""
    from yosoi.utils.urls import extract_domain

    covered = set(bundle.selectors.keys())
    uncovered = sorted({d for url in target_urls if not _recipe_covers_domain(covered, d := extract_domain(url))})
    if uncovered:
        logger.warning(
            'Recipe %r covers domain(s) %s but %d target URL(s) are on uncovered domain(s): %s. '
            'Those URLs will NOT use this recipe — they fall through to normal '
            '(LLM) discovery if a model is configured, or fail if not.',
            source,
            ', '.join(sorted(covered)) or '(none)',
            len(uncovered),
            ', '.join(uncovered),
        )


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
