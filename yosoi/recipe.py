"""Ergonomic public API for flat Yosoi recipe artifacts."""

from __future__ import annotations

import json
import keyword
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from yosoi.models.contract import Contract
from yosoi.models.recipe import Recipe, RecipeA3Act, RecipeA3Node, RecipeA3Scope, RecipeMetadata, RecipeValidation
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap, SnapshotStatus
from yosoi.models.spec import ContractSpec
from yosoi.storage.recipe_store import (
    GH_PREFIX,
    GistPublishResult,
    GitHubPrPublishResult,
    RecipeInstallResult,
    publish_recipe_gist,
    publish_recipe_github,
    publish_recipe_github_pr,
    resolve_recipe_ref,
)
from yosoi.storage.recipe_store import load_recipe as _load_recipe
from yosoi.utils.contracts import resolve_contract
from yosoi.utils.files import atomic_write_text, init_yosoi
from yosoi.utils.urls import extract_domain

if TYPE_CHECKING:
    from yosoi.policy import Policy

SelectorValue = str | dict[str, Any]
SelectorInput = SnapshotMap | Mapping[str, SnapshotMap]
ContractInput = type[Contract] | str | ContractSpec

__all__ = [
    'Metadata',
    'Recipe',
    'RecipeMetadata',
    'RecipePublishResult',
    'RecipeTrust',
    'RecipeValidateResult',
    'RecipeValidation',
    'Trust',
    'Validation',
    'check',
    'compile_contract',
    'gist',
    'install',
    'install_recipe',
    'load',
    'load_recipe',
    'mint',
    'mint_recipe',
    'publish',
    'render_contract_py',
    'run',
    'run_recipe',
    'run_sync',
    'selector_map',
    'validate',
    'validate_recipe',
    'validate_sync',
]


@dataclass(frozen=True)
class RecipeValidateResult:
    """Result of validating a recipe against live fixture URL(s)."""

    recipe: Recipe
    validation: RecipeValidation
    status: str
    source: str | None = None
    path: Path | None = None
    raw_result: Any | None = None


@dataclass(frozen=True)
class RecipePublishResult:
    """One publish destination result from :func:`publish`."""

    backend: str
    url: str
    recipe_id: str
    mode: str | None = None
    path: str | None = None
    raw_url: str | None = None
    html_url: str | None = None
    filename: str | None = None
    branch: str | None = None
    fork_repo: str | None = None
    public: bool | None = None


@dataclass(frozen=True)
class RecipeTrust:
    """Strict allowlist for accepting recipe artifacts from outside the process.

    Empty remote trust is deny-by-default. Add only the dimensions you intend to
    trust: source hosts/GitHub owners, exact recipe ids, and/or contract
    fingerprints. When multiple allowlists are set, all of them must pass.
    """

    allow_local: bool = True
    allowed_hosts: frozenset[str] = frozenset()
    allowed_github_owners: frozenset[str] = frozenset()
    allowed_recipe_ids: frozenset[str] = frozenset()
    allowed_contract_fingerprints: frozenset[str] = frozenset()

    @classmethod
    def local_only(cls) -> RecipeTrust:
        """Trust only local files."""
        return cls(allow_local=True)

    @classmethod
    def github(cls, *owners: str) -> RecipeTrust:
        """Trust recipes fetched from specific GitHub owners/users/orgs."""
        return cls(allowed_github_owners=frozenset(owners))

    @classmethod
    def hosts(cls, *hosts: str) -> RecipeTrust:
        """Trust recipes fetched from exact HTTPS hosts."""
        return cls(allowed_hosts=frozenset(host.lower() for host in hosts))

    def recipe_ids(self, *recipe_ids: str) -> RecipeTrust:
        """Require exact recipe ids in addition to any existing source rules."""
        return _replace_trust(self, allowed_recipe_ids=self.allowed_recipe_ids | frozenset(recipe_ids))

    def contracts(self, *contracts: ContractInput) -> RecipeTrust:
        """Require exact contract fingerprints in addition to any source rules."""
        fingerprints = frozenset(_contract_spec(contract).fingerprint for contract in contracts)
        return _replace_trust(
            self,
            allowed_contract_fingerprints=self.allowed_contract_fingerprints | fingerprints,
        )

    def verify_source(self, source: str) -> None:
        """Raise before network/file IO when a source is outside this trust boundary."""
        if _is_local_source(source):
            if not self.allow_local:
                raise PermissionError(f'Recipe source {source!r} is local, but local recipes are not trusted.')
            return
        self._verify_remote_source(source)

    def verify_artifact(self, recipe: Recipe) -> None:
        """Raise when verified recipe contents are outside this trust boundary."""
        if self.allowed_recipe_ids and recipe.recipe_id not in self.allowed_recipe_ids:
            raise PermissionError(f'Recipe id {recipe.recipe_id!r} is not in the trusted recipe id allowlist.')
        if self.allowed_contract_fingerprints and recipe.contract.fingerprint not in self.allowed_contract_fingerprints:
            raise PermissionError(
                f'Recipe contract fingerprint {recipe.contract.fingerprint!r} is not in the trusted contract allowlist.'
            )

    def verify(self, source: str, recipe: Recipe) -> None:
        """Raise when a source/recipe pair is outside this trust boundary."""
        self.verify_source(source)
        self.verify_artifact(recipe)

    def _verify_remote_source(self, source: str) -> None:
        owner = _github_owner(source)
        host = urlparse(resolve_recipe_ref(source)).netloc.lower()
        has_source_allowlist = bool(self.allowed_hosts or self.allowed_github_owners)
        if not has_source_allowlist:
            raise PermissionError(
                f'Recipe source {source!r} is remote and no trusted remote origin/user was configured.'
            )
        if self.allowed_github_owners and owner not in self.allowed_github_owners:
            raise PermissionError(f'Recipe GitHub owner {owner!r} is not trusted.')
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise PermissionError(f'Recipe host {host!r} is not trusted.')


Trust = RecipeTrust
Validation = RecipeValidation
Metadata = RecipeMetadata


def compile_contract(source: ContractInput | str | Path, /) -> ContractSpec:
    """Compile a Python/authored contract source into canonical ``ContractSpec`` JSON."""
    if isinstance(source, ContractSpec):
        return source
    if isinstance(source, type) and issubclass(source, Contract):
        return ContractSpec.from_contract(source)
    if isinstance(source, Path):
        source = str(source)
    if isinstance(source, str) and source.endswith('.json'):
        return ContractSpec.model_validate_json(Path(source).read_text(encoding='utf-8'))
    return _contract_spec(cast(ContractInput, source))


def render_contract_py(source: Recipe | ContractSpec | ContractInput | str | Path, /) -> str:
    """Render a canonical contract spec as importable, reviewable Python."""
    spec = _contract_source_spec(source)
    lines = [
        'from __future__ import annotations',
        '',
        'import importlib',
        'from typing import Any',
        '',
        'import yosoi as ys',
        '',
        '',
        'def _load_ref(ref: str) -> object:',
        '    module_name, _, qualname = ref.partition(":")',
        '    obj = importlib.import_module(module_name)',
        '    for part in qualname.split("."):',
        '        obj = getattr(obj, part)',
        '    return obj',
        '',
        '',
    ]
    _render_contract_class(spec, lines, rendered=set())
    return '\n'.join(lines).rstrip() + '\n'


def selector_map(
    url: str,
    /,
    *,
    domain: str | None = None,
    discovered_at: datetime | None = None,
    source: str = 'discovered',
    **fields: SelectorValue,
) -> SnapshotMap:
    """Build a portable one-domain selector map from field CSS/XPath entries.

    Args:
        url: Source URL these selectors were minted from.
        domain: Optional domain override. Defaults to the URL host.
        discovered_at: Optional stable timestamp. Defaults to now.
        source: Selector provenance label accepted by :class:`SelectorSnapshot`.
        **fields: Field name to selector payload. Strings become primary selectors;
            dict values are kept as structured selector payloads.
    """
    ts = discovered_at or datetime.now(timezone.utc)
    snapshots = {
        name: SelectorSnapshot(
            primary=selector,
            discovered_at=ts,
            source=cast(Any, source),
            status=SnapshotStatus.ACTIVE,
        )
        for name, selector in fields.items()
    }
    return SnapshotMap(url=url, domain=domain or extract_domain(url), snapshots=snapshots)


def mint(
    contract: ContractInput,
    /,
    *,
    selectors: SelectorInput,
    out: str | Path | None = None,
    a3nodes: Sequence[Mapping[str, Any]] = (),
    validation: RecipeValidation | Mapping[str, Any] | None = None,
    name: str | None = None,
    domain_scope: Sequence[str] = (),
    source_urls: Sequence[str] = (),
    url_patterns: Sequence[str] = (),
    notes: str | None = None,
) -> Recipe:
    """Mint a deterministic flat recipe from normal Yosoi API objects.

    ``contract`` follows the same mental model as ``ys.scrape``: pass a
    ``ys.Contract`` subclass, a registered contract name, or a ``ContractSpec``.
    If ``out`` is provided, canonical JSON is written to that path.
    """
    contract_spec = _contract_spec(contract)
    selector_bundle = _selector_bundle(selectors)
    recipe = Recipe(
        contract=contract_spec,
        selectors=selector_bundle,
        a3nodes=cast(Any, list(a3nodes)),
        validation=validation
        if isinstance(validation, RecipeValidation)
        else RecipeValidation.model_validate(validation or {}),
        metadata=RecipeMetadata(
            name=name or contract_spec.name,
            domain_scope=list(domain_scope) or sorted(selector_bundle),
            source_urls=list(source_urls),
            url_patterns=list(url_patterns),
            notes=notes,
        ),
    )
    recipe.verify_integrity()
    if out is not None:
        atomic_write_text(out, recipe.canonical_json())
    return recipe


def mint_recipe(
    contract: ContractInput,
    /,
    *,
    selectors: SelectorInput,
    out: str | Path | None = None,
    a3nodes: Sequence[Mapping[str, Any]] = (),
    validation: RecipeValidation | Mapping[str, Any] | None = None,
    name: str | None = None,
    domain_scope: Sequence[str] = (),
    source_urls: Sequence[str] = (),
    url_patterns: Sequence[str] = (),
    notes: str | None = None,
) -> Recipe:
    """Backward-compatible alias for :func:`mint`."""
    return mint(
        contract,
        selectors=selectors,
        out=out,
        a3nodes=a3nodes,
        validation=validation,
        name=name,
        domain_scope=domain_scope,
        source_urls=source_urls,
        url_patterns=url_patterns,
        notes=notes,
    )


def load(
    source: str,
    /,
    *,
    recipe_id: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> Recipe:
    """Load and verify a local/HTTPS/``gh:`` flat recipe JSON under a trust policy."""
    effective_trust = _effective_trust(trust=trust, policy=policy)
    effective_trust.verify_source(source)
    recipe = _load_recipe(source, expected_recipe_id=recipe_id)
    effective_trust.verify_artifact(recipe)
    return recipe


def load_recipe(
    source: str,
    /,
    *,
    recipe_id: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> Recipe:
    """Backward-compatible alias for :func:`load`."""
    return load(source, recipe_id=recipe_id, trust=trust, policy=policy)


def check(
    source: str,
    /,
    *,
    recipe_id: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> Recipe:
    """Verify a recipe and return the loaded artifact for inspection."""
    return load(source, recipe_id=recipe_id, trust=trust, policy=policy)


def install(
    source: str,
    /,
    *,
    recipe_id: str | None = None,
    cache_dir: str | Path | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> RecipeInstallResult:
    """Fetch, verify, trust-check, and cache a recipe by content hash."""
    recipe = load_recipe(source, recipe_id=recipe_id, trust=trust, policy=policy)
    recipes_dir = Path(cache_dir) if cache_dir is not None else init_yosoi('recipes')
    recipes_dir.mkdir(parents=True, exist_ok=True)
    path = recipes_dir / f'{recipe.recipe_id.replace(":", "-")}.json'
    atomic_write_text(path, recipe.canonical_json())
    return RecipeInstallResult(recipe, path)


def install_recipe(
    source: str,
    /,
    *,
    recipe_id: str | None = None,
    cache_dir: str | Path | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> RecipeInstallResult:
    """Backward-compatible alias for :func:`install`."""
    return install(source, recipe_id=recipe_id, cache_dir=cache_dir, trust=trust, policy=policy)


async def validate(
    recipe: Recipe | str,
    urls: str | Sequence[str],
    /,
    *,
    recipe_id: str | None = None,
    write: bool = False,
    out: str | Path | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
    allow_llm: bool = False,
    **scrape_kwargs: Any,
) -> RecipeValidateResult:
    """Replay a recipe against fixture URL(s) and attach validation evidence.

    Validation runs fail-fast by default (``allow_llm=False``). Writing validation
    changes the recipe identity because validation evidence is part of the
    portable artifact.
    """
    source = recipe if isinstance(recipe, str) else None
    artifact = load(recipe, recipe_id=recipe_id, trust=trust, policy=policy) if isinstance(recipe, str) else recipe
    raw_result = await run(
        artifact,
        urls,
        trust=trust,
        policy=policy,
        allow_llm=allow_llm,
        **scrape_kwargs,
    )
    fixture_urls = [urls] if isinstance(urls, str) else list(urls)
    validation = _validation_from_scrape_result(
        raw_result,
        fixture_urls=fixture_urls,
        required_fields=sorted(artifact.contract.fields),
    )
    updated = Recipe(
        contract=artifact.contract,
        selectors=artifact.selectors,
        a3nodes=artifact.a3nodes,
        validation=validation,
        metadata=artifact.metadata,
    )
    path: Path | None = Path(out) if out is not None else None
    if write or path is not None:
        if path is None:
            if source is None or not _is_local_source(source):
                raise ValueError('write=True requires a local recipe source or out=...')
            path = Path(source)
        atomic_write_text(path, updated.canonical_json())
    return RecipeValidateResult(
        recipe=updated,
        validation=validation,
        status=str(validation.summary.get('status') or 'unknown'),
        source=source,
        path=path,
        raw_result=raw_result,
    )


def validate_sync(
    recipe: Recipe | str,
    urls: str | Sequence[str],
    /,
    *,
    recipe_id: str | None = None,
    write: bool = False,
    out: str | Path | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
    allow_llm: bool = False,
    **scrape_kwargs: Any,
) -> RecipeValidateResult:
    """Synchronous wrapper for :func:`validate`."""
    import asyncio

    return asyncio.run(
        validate(
            recipe,
            urls,
            recipe_id=recipe_id,
            write=write,
            out=out,
            trust=trust,
            policy=policy,
            allow_llm=allow_llm,
            **scrape_kwargs,
        )
    )


def publish(
    recipe: Recipe | str,
    /,
    *,
    repo: str | None = None,
    gist: bool = False,
    direct: bool = False,
    path: str | None = None,
    branch: str = 'main',
    token: str | None = None,
    message: str | None = None,
    filename: str | None = None,
    description: str | None = None,
    public: bool = False,
    allow_unvalidated: bool = False,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> list[RecipePublishResult]:
    """Publish a verified recipe to GitHub repo and/or Gist.

    GitHub repo publishes open a pull request by default, matching the CLI.
    Pass ``direct=True`` to commit through the Contents API instead.
    """
    if not repo and not gist:
        raise ValueError('Choose at least one publish target: repo or gist=True')
    artifact = load(recipe, trust=trust, policy=policy) if isinstance(recipe, str) else recipe
    _effective_trust(trust=trust, policy=policy).verify_artifact(artifact)
    if not allow_unvalidated and not _has_validation_evidence(artifact):
        raise ValueError(
            'Recipe has no validation evidence; run ys.recipe.validate(..., write=True) or pass allow_unvalidated=True'
        )
    results: list[RecipePublishResult] = []
    if gist:
        gist_result = publish_recipe_gist(
            artifact,
            filename=filename,
            description=description,
            public=public,
            token=token,
        )
        results.append(_gist_publish_result(artifact, gist_result))
    if repo:
        repo_path = path or _default_remote_path(artifact)
        if direct:
            url = publish_recipe_github(
                artifact,
                repo=repo,
                path=repo_path,
                branch=branch,
                token=token,
                message=message,
            )
            results.append(
                RecipePublishResult(
                    backend='github',
                    mode='direct',
                    url=url,
                    recipe_id=artifact.recipe_id,
                    path=repo_path,
                )
            )
        else:
            pr_result = publish_recipe_github_pr(
                artifact,
                repo=repo,
                path=repo_path,
                branch=branch,
                token=token,
                message=message,
            )
            results.append(_github_pr_publish_result(artifact, pr_result))
    return results


async def run(
    recipe: Recipe | str,
    url: str | Sequence[str],
    /,
    *,
    recipe_id: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
    allow_llm: bool = False,
    **scrape_kwargs: Any,
) -> Any:
    """Run a verified recipe against live URL(s) via ``ys.scrape``.

    The recipe's selectors are installed into the local selector cache for the
    requested URL domains, then scrape runs with the recipe contract. By default
    ``allow_llm=False`` so a recipe cache miss fails fast instead of discovering.
    """
    artifact = load(recipe, recipe_id=recipe_id, trust=trust, policy=policy) if isinstance(recipe, str) else recipe
    _effective_trust(trust=trust, policy=policy).verify_artifact(artifact)
    await _seed_recipe_selectors(artifact, [url] if isinstance(url, str) else list(url))
    await _seed_recipe_a3nodes(artifact)

    from yosoi.api import scrape as scrape_api

    return await scrape_api(
        url,
        artifact.to_contract(),
        policy=policy,
        allow_llm=allow_llm,
        experimental_a3node=bool(artifact.a3nodes) or bool(scrape_kwargs.pop('experimental_a3node', False)),
        **scrape_kwargs,
    )


run_recipe = run
validate_recipe = validate


def run_sync(
    recipe: Recipe | str,
    url: str | Sequence[str],
    /,
    *,
    recipe_id: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
    allow_llm: bool = False,
    **scrape_kwargs: Any,
) -> Any:
    """Synchronous wrapper for :func:`run`."""
    import asyncio

    return asyncio.run(
        run(
            recipe,
            url,
            recipe_id=recipe_id,
            trust=trust,
            policy=policy,
            allow_llm=allow_llm,
            **scrape_kwargs,
        )
    )


def gist(
    recipe: Recipe | str,
    /,
    *,
    filename: str | None = None,
    description: str | None = None,
    public: bool = False,
    token: str | None = None,
    allow_unvalidated: bool = False,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> GistPublishResult:
    """Publish a verified recipe as a GitHub secret/unlisted Gist."""
    artifact = load(recipe, trust=trust, policy=policy) if isinstance(recipe, str) else recipe
    _effective_trust(trust=trust, policy=policy).verify_artifact(artifact)
    if not allow_unvalidated and not _has_validation_evidence(artifact):
        raise ValueError(
            'Recipe has no validation evidence; run ys.recipe.validate(..., write=True) or pass allow_unvalidated=True'
        )
    return publish_recipe_gist(
        artifact,
        filename=filename,
        description=description,
        public=public,
        token=token,
    )


async def export_a3nodes(*, domains: Sequence[str] = (), source_urls: Sequence[str] = ()) -> list[RecipeA3Node]:
    """Export local scoped A3Node cache entries as portable recipe nodes."""
    from urllib.parse import urlparse

    from yosoi.storage.a3node import A3NodeStorage
    from yosoi.utils.urls import extract_domain

    allowed_domains = set(domains) | {extract_domain(url) for url in source_urls}
    allowed_routes = {(urlparse(url).path or '/') for url in source_urls}
    storage = A3NodeStorage()
    nodes = await storage.load_all()
    exported: list[RecipeA3Node] = []
    for node in nodes.values():
        if allowed_domains and node.domain not in allowed_domains:
            continue
        if allowed_routes and node.route_signature not in allowed_routes:
            continue
        exported.append(_recipe_a3node_from_storage(node))
    return sorted(exported, key=lambda item: item.scope.scope_key)


def export_a3nodes_sync(*, domains: Sequence[str] = (), source_urls: Sequence[str] = ()) -> list[RecipeA3Node]:
    """Synchronous wrapper for :func:`export_a3nodes`."""
    import asyncio

    return asyncio.run(export_a3nodes(domains=domains, source_urls=source_urls))


def _recipe_a3node_from_storage(node: Any) -> RecipeA3Node:
    return RecipeA3Node(
        scope=RecipeA3Scope(
            scope_key=node.scope_key or node.domain,
            domain=node.domain,
            page_profile=node.page_profile,
            intent=node.intent,
            browser_fingerprint=node.browser_fingerprint,
            route_signature=node.route_signature,
            query_signature=node.query_signature,
        ),
        acts=[
            RecipeA3Act(
                kind=act.kind,
                cycles=act.cycles,
                target=act.target.model_dump(exclude_none=True) if act.target else None,
            )
            for act in node.acts
        ],
        provenance={
            'discovered_at': node.discovered_at,
            'replay_count': node.replay_count,
            'last_replayed_at': node.last_replayed_at,
        },
    )


async def _seed_recipe_a3nodes(recipe: Recipe) -> None:
    if not recipe.a3nodes:
        return
    from yosoi.models.selectors import SelectorEntry
    from yosoi.storage.a3node import A3NodeScope, A3NodeStorage, ActRecord

    storage = A3NodeStorage()
    for node in recipe.a3nodes:
        scope = A3NodeScope(
            scope_key=node.scope.scope_key,
            domain=node.scope.domain,
            page_profile=node.scope.page_profile,
            intent=node.scope.intent,
            browser_fingerprint=node.scope.browser_fingerprint,
            route_signature=node.scope.route_signature,
            query_signature=node.scope.query_signature,
        )
        acts = [
            ActRecord(
                kind=act.kind,
                cycles=act.cycles,
                target=SelectorEntry.model_validate(act.target) if act.target else None,
            )
            for act in node.acts
        ]
        await storage.save(scope, acts)


async def _seed_recipe_selectors(recipe: Recipe, urls: Sequence[str]) -> None:
    from yosoi.models.snapshot import SnapshotStatus
    from yosoi.storage.persistence import SelectorStorage
    from yosoi.utils.signatures import contract_signature
    from yosoi.utils.urls import extract_domain

    storage = SelectorStorage()
    recipe_contract = recipe.to_contract()
    contract_sigs = {recipe.contract.fingerprint, contract_signature(recipe_contract)}
    seeded = 0
    for target_url in urls:
        domain = extract_domain(target_url)
        selector_map = recipe.selectors_for(domain)
        if selector_map is None:
            raise ValueError(f'Recipe {recipe.recipe_id} has no selectors for domain {domain!r}')
        snapshots = {
            field: snapshot.model_copy(
                update={
                    'failure_count': 0,
                    'last_failed_at': None,
                    'status': SnapshotStatus.ACTIVE,
                    'status_reason': None,
                }
            )
            for field, snapshot in selector_map.snapshots.items()
        }
        for contract_sig in contract_sigs:
            await storage.save_snapshots(
                target_url,
                snapshots,
                contract_sig=contract_sig,
                contract=recipe_contract,
            )
        seeded += 1
    if seeded == 0:
        raise ValueError('recipe run requires at least one URL')


def _validation_from_scrape_result(
    raw_result: Any, *, fixture_urls: list[str], required_fields: Sequence[str]
) -> RecipeValidation:
    status = str(getattr(raw_result, 'status', '') or 'unknown')
    units = list(getattr(raw_result, 'results', []) or [])
    records = [record for unit in units for record in list(getattr(unit, 'records', []) or [])]
    errors = [str(error) for unit in units if (error := getattr(unit, 'error', None))]
    field_coverage: dict[str, int] = {}
    for record in records:
        if isinstance(record, dict):
            for key, value in record.items():
                if value not in (None, '', []):
                    field_coverage[key] = field_coverage.get(key, 0) + 1
    expected_shape = {
        key: type(value).__name__ for record in records[:1] if isinstance(record, dict) for key, value in record.items()
    }
    missing_fields = [field for field in required_fields if field_coverage.get(field, 0) == 0]
    summary_status = 'passed' if status == 'ok' and not errors and records and not missing_fields else 'failed'
    summary: dict[str, Any] = {
        'status': summary_status,
        'scrape_status': status,
        'validated_at': datetime.now(timezone.utc).isoformat(),
        'fixture_count': len(fixture_urls),
        'record_count': len(records),
        'field_coverage': field_coverage,
        'missing_fields': missing_fields,
    }
    if errors:
        summary['errors'] = errors
    return RecipeValidation(fixture_urls=fixture_urls, expected_shape=expected_shape, summary=summary)


def _has_validation_evidence(recipe: Recipe) -> bool:
    return bool(recipe.validation.fixture_urls and recipe.validation.summary.get('status') == 'passed')


def _default_remote_path(recipe: Recipe) -> str:
    digest = recipe.recipe_id.split(':')[-1][:12]
    stem = re.sub(r'[^a-z0-9._-]+', '-', recipe.contract.name.lower()).strip('-') or 'recipe'
    domains = sorted(recipe.selectors)
    domain = domains[0] if len(domains) == 1 else 'multi-domain'
    return f'recipes/{domain}/{stem}-{digest}.recipe.json'


def _gist_publish_result(recipe: Recipe, result: GistPublishResult) -> RecipePublishResult:
    return RecipePublishResult(
        backend='gist',
        mode='secret' if not result.public else 'public',
        url=result.raw_url,
        recipe_id=recipe.recipe_id,
        raw_url=result.raw_url,
        html_url=result.html_url,
        filename=result.filename,
        public=result.public,
    )


def _github_pr_publish_result(recipe: Recipe, result: GitHubPrPublishResult) -> RecipePublishResult:
    return RecipePublishResult(
        backend='github',
        mode='pr',
        url=result.html_url,
        recipe_id=recipe.recipe_id,
        path=result.path,
        branch=result.branch,
        fork_repo=result.fork_repo,
    )


def _contract_source_spec(source: Recipe | ContractSpec | ContractInput | str | Path) -> ContractSpec:
    if isinstance(source, Recipe):
        return source.contract
    if isinstance(source, ContractSpec):
        return source
    if isinstance(source, Path):
        source = str(source)
    if isinstance(source, str):
        path = Path(source)
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'contract' in data:
                return Recipe.model_validate(data).contract
            return ContractSpec.model_validate(data)
    return compile_contract(cast(ContractInput | str | Path, source))


def _render_contract_class(spec: ContractSpec, lines: list[str], *, rendered: set[str]) -> None:
    class_name = _safe_class_name(spec.name)
    if class_name in rendered:
        return
    for nested in spec.nested.values():
        _render_contract_class(nested, lines, rendered=rendered)
    rendered.add(class_name)
    lines.append(f'class {class_name}(ys.Contract):')
    if spec.doc:
        lines.append(f'    {_string_literal(spec.doc)}')
    if spec.root is not None:
        from yosoi.models.selectors import SelectorEntry

        normalized_root = SelectorEntry.model_validate(spec.root).model_dump(mode='json')
        if spec.root != normalized_root:
            raise ValueError('Contract root must be normalized before rendering Python mirror')
        lines.append(f'    root = ys.SelectorEntry.model_validate({spec.root!r})')
    if not spec.doc and spec.root is None and spec.validators is None and not spec.fields and not spec.nested:
        lines.append('    pass')
    for field_name, field in spec.fields.items():
        lines.append(
            f'    {_safe_field_name(field_name)}: {_annotation_expr(field.python_type)} = {_field_expr(field)}'
        )
    for field_name, nested in spec.nested.items():
        lines.append(f'    {_safe_field_name(field_name)}: {_safe_class_name(nested.name)}')
    lines.append('')
    if spec.validators is not None:
        lines.append(f'{class_name}._validators_cls = _load_ref({spec.validators!r})')
        lines.append('')
    lines.append('')


def _field_expr(field: Any) -> str:
    kwargs: list[str] = []
    if field.description is not None:
        kwargs.append(f'description={field.description!r}')
    if field.selector is not None:
        kwargs.append(f'selector={field.selector!r}')
    if field.delimiter is not None:
        kwargs.append(f'delimiter={field.delimiter!r}')
    if field.frozen:
        kwargs.append('frozen=True')
    if field.required is False:
        kwargs.append('default=None')
    extra: dict[str, Any] = {}
    if field.yosoi_type:
        extra['yosoi_type'] = field.yosoi_type
    if field.action is not None:
        extra['yosoi_action'] = field.action
    if extra:
        kwargs.append(f'json_schema_extra={extra!r}')
    return f'ys.Field({", ".join(kwargs)})'


def _annotation_expr(raw: str) -> str:
    allowed = {'str', 'int', 'float', 'bool', 'Any', 'dict', 'list'}
    return raw if raw in allowed or raw.startswith(('list[', 'dict[')) else 'str'


def _safe_class_name(name: str) -> str:
    if name.isidentifier() and not keyword.iskeyword(name):
        return name
    cleaned = ''.join(part for part in re.sub(r'[^0-9A-Za-z_]+', '_', name).strip('_').title() if part != '_')
    if not cleaned or cleaned[0].isdigit() or keyword.iskeyword(cleaned):
        return 'RecipeContract'
    return cleaned


def _safe_field_name(name: str) -> str:
    cleaned = re.sub(r'\W+', '_', name).strip('_') or 'field'
    if cleaned[0].isdigit() or keyword.iskeyword(cleaned):
        cleaned = f'{cleaned}_field'
    return cleaned


def _string_literal(value: str) -> str:
    return repr(value)


def _effective_trust(*, trust: RecipeTrust | None, policy: Policy | None) -> RecipeTrust:
    if trust is not None:
        return trust
    if policy is not None and policy.recipe is not None:
        return cast(RecipeTrust, policy.recipe.to_trust())
    return RecipeTrust.local_only()


def _contract_spec(contract: ContractInput) -> ContractSpec:
    if isinstance(contract, ContractSpec):
        return contract
    if isinstance(contract, str):
        return resolve_contract(contract.removeprefix('@')).to_spec()
    return ContractSpec.from_contract(contract)


def _selector_bundle(selectors: SelectorInput) -> dict[str, SnapshotMap]:
    if isinstance(selectors, SnapshotMap):
        return {selectors.domain: selectors}
    return dict(selectors)


def _replace_trust(trust: RecipeTrust, **updates: Any) -> RecipeTrust:
    return RecipeTrust(
        allow_local=updates.get('allow_local', trust.allow_local),
        allowed_hosts=updates.get('allowed_hosts', trust.allowed_hosts),
        allowed_github_owners=updates.get('allowed_github_owners', trust.allowed_github_owners),
        allowed_recipe_ids=updates.get('allowed_recipe_ids', trust.allowed_recipe_ids),
        allowed_contract_fingerprints=updates.get('allowed_contract_fingerprints', trust.allowed_contract_fingerprints),
    )


def _is_local_source(source: str) -> bool:
    parsed = urlparse(source)
    return not source.startswith(GH_PREFIX) and parsed.scheme not in {'http', 'https'}


def _github_owner(source: str) -> str | None:
    if source.startswith(GH_PREFIX):
        parts = [part for part in source[len(GH_PREFIX) :].split('/') if part]
        return parts[0] if parts else None
    parsed = urlparse(source)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split('/') if part]
    if host == 'github.com' and parts:
        return parts[0]
    if host in {'raw.githubusercontent.com', 'gist.githubusercontent.com'} and parts:
        return parts[0]
    return None
