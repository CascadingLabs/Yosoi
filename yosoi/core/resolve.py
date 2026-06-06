"""Pure replay function — the primary artifact (CAS-119).

``resolve(spec, html, cache)`` is the single source of truth for replay.
Every frontend (CLI, API, future MCP shim) is a thin reader of this function.

Design contract:
  - Pure: deterministic, no global state, all inputs explicit.
  - Cache is a VALUE passed in by the caller; no daemon, no magic directory.
  - Cache hit → records, zero LLM calls.
  - Cache miss → typed ``NeedsDiscovery``, never silent LLM escalation.
  - Cache keyed by ``(domain, contract_fingerprint)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yosoi.models.needs_discovery import NeedsDiscovery
from yosoi.models.selectors import SelectorLevel

if TYPE_CHECKING:
    from yosoi.models.spec import ContractSpec
    from yosoi.storage.atoms import AtomStore

# Cache value type: (domain, fingerprint) → {field_name: {primary, fallback, tertiary}}
SelectorMap = dict[str, dict[str, Any]]
ContractCache = dict[tuple[str, str], SelectorMap]

# What resolve() returns
ResolveResult = list[dict[str, Any]] | NeedsDiscovery


def resolve(
    spec: ContractSpec,
    html: str,
    cache: ContractCache,
    domain: str,
    *,
    max_level: SelectorLevel = SelectorLevel.CSS,
    url: str | None = None,
    atom_store: AtomStore | None = None,
) -> ResolveResult:
    """Replay cached selectors against ``html`` and return records or a cache-miss signal.

    Args:
        spec: Canonical ContractSpec describing what to extract.
        html: Pre-fetched (and optionally pre-cleaned) HTML to extract from.
        cache: Content-addressed selector cache, keyed by ``(domain, fingerprint)``.
        domain: Domain name — first part of the cache key (e.g. ``'example.com'``).
        max_level: Maximum selector strategy level. Defaults to CSS.
        url: Source URL used for relative-URL resolution in coercions. Defaults to domain.
        atom_store: Optional field-atom index (P3). When atom reads are enabled
            (``YOSOI_ATOM_READS``), a legacy-cache miss is retried against this index
            before falling back to discovery.

    Returns:
        ``list[dict]`` of extracted records on a cache hit, or a :class:`NeedsDiscovery`
        instance on a cache miss. Never raises on a miss — caller decides what to do next.
    """
    fingerprint = spec.fingerprint
    selectors = cache.get((domain, fingerprint))

    if selectors is None:
        # P3: behind YOSOI_ATOM_READS, try the field-atom index before discovery. A full,
        # unambiguous, same-shape resolution extracts directly; anything less falls through.
        atom_records = _try_atom_reads(spec, html, domain, url, atom_store, max_level)
        if atom_records is not None:
            return atom_records
        contract = spec.to_contract()
        return NeedsDiscovery(
            domain=domain,
            contract_fingerprint=fingerprint,
            fields=sorted(contract.discovery_field_names()),
        )

    return _extract_from_html(spec, html, selectors, domain, max_level=max_level, url=url)


def _try_atom_reads(
    spec: ContractSpec,
    html: str,
    domain: str,
    url: str | None,
    atom_store: AtomStore | None,
    max_level: SelectorLevel,
) -> list[dict[str, Any]] | None:
    """Attempt to serve a contract entirely from the field-atom index (P3, flag-gated).

    Returns extracted records when every field resolves unambiguously on this page's
    shape, else None (caller falls back to discovery). Fail-closed: any error or partial
    resolution yields None, never a half-built selector set.
    """
    from yosoi.core.atom_read import (
        allowed_sources,
        atom_reads_enabled,
        resolve_via_atoms,
        selector_map_from_atoms,
    )

    if not atom_reads_enabled():
        return None
    try:
        from yosoi.generalization.capture import observe_html
        from yosoi.generalization.fingerprint import page_shape_fp
        from yosoi.storage.atoms import DEFAULT_STORE_PATH, AtomStore

        store = atom_store if atom_store is not None else AtomStore(DEFAULT_STORE_PATH)
        if len(store) == 0:
            return None
        page_shape = page_shape_fp(observe_html(url or domain, html, row_selector=''))
        requested = [(name, fspec.yosoi_type) for name, fspec in spec.fields.items()]
        if not requested:
            return None
        resolution = resolve_via_atoms(page_shape, requested, store, allowed=allowed_sources())
        if not resolution.fully_resolved:
            return None
        selectors = selector_map_from_atoms(resolution.hits)
        return _extract_from_html(spec, html, selectors, domain, max_level=max_level, url=url)
    except Exception:  # noqa: BLE001 — atom reads must fail closed to legacy discovery
        return None


def _extract_from_html(
    spec: ContractSpec,
    html: str,
    selectors: SelectorMap,
    domain: str,
    *,
    max_level: SelectorLevel = SelectorLevel.CSS,
    url: str | None = None,
) -> list[dict[str, Any]]:
    """Extract and validate records from HTML using cached selectors.

    Separated from ``resolve()`` so it can be called independently when the
    pipeline already has the HTML (avoid a second fetch).
    """
    from rich.console import Console

    from yosoi.core.cleaning import HTMLCleaner
    from yosoi.core.extraction import ContentExtractor

    contract = spec.to_contract()
    quiet_console = Console(quiet=True)
    cleaner = HTMLCleaner(console=quiet_console)
    cleaned = cleaner.clean_html(html)

    extractor = ContentExtractor(console=quiet_console, contract=contract)
    raw = extractor.extract_content_with_html(
        url or domain,
        cleaned,
        selectors,
        max_level=max_level,
    )

    if raw is None:
        return []

    source_url = url or domain
    items: list[dict[str, Any]] = raw if isinstance(raw, list) else [raw]
    validated: list[dict[str, Any]] = []
    for item in items:
        try:
            obj = contract.model_validate(item, context={'source_url': source_url})
            validated.append(obj.model_dump())
        except Exception:  # noqa: BLE001, PERF203
            validated.append(item)
    return validated


def build_cache_from_selectors(
    domain: str,
    fingerprint: str,
    selectors: SelectorMap,
) -> ContractCache:
    """Construct a single-entry ContractCache from an already-loaded selector map.

    Convenience helper for callers that load selectors from SelectorStorage and
    want to pass them into ``resolve()`` without building the dict themselves.
    """
    return {(domain, fingerprint): selectors}
