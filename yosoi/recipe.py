"""Ergonomic public API for flat Yosoi recipe artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from yosoi.models.contract import Contract
from yosoi.models.recipe import Recipe, RecipeMetadata, RecipeValidation
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap, SnapshotStatus
from yosoi.models.spec import ContractSpec
from yosoi.storage.recipe_store import (
    GH_PREFIX,
    GistPublishResult,
    RecipeInstallResult,
    publish_recipe_gist,
    publish_recipe_github,
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
        a3nodes=[dict(node) for node in a3nodes],
        validation=validation
        if isinstance(validation, RecipeValidation)
        else RecipeValidation.model_validate(validation or {}),
        metadata=RecipeMetadata(
            name=name or contract_spec.name,
            domain_scope=list(domain_scope) or sorted(selector_bundle),
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
    path = recipes_dir / f'{recipe.recipe_id.removeprefix("sha256:")}.json'
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


def publish(
    recipe: Recipe | str,
    /,
    *,
    repo: str,
    path: str,
    branch: str = 'main',
    token: str | None = None,
    message: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> str:
    """Publish a verified recipe to GitHub via the Contents API."""
    artifact = load(recipe, trust=trust, policy=policy) if isinstance(recipe, str) else recipe
    _effective_trust(trust=trust, policy=policy).verify_artifact(artifact)
    return publish_recipe_github(artifact, repo=repo, path=path, branch=branch, token=token, message=message)


def gist(
    recipe: Recipe | str,
    /,
    *,
    filename: str | None = None,
    description: str | None = None,
    public: bool = False,
    token: str | None = None,
    trust: RecipeTrust | None = None,
    policy: Policy | None = None,
) -> GistPublishResult:
    """Publish a verified recipe as a GitHub secret/unlisted Gist."""
    artifact = load(recipe, trust=trust, policy=policy) if isinstance(recipe, str) else recipe
    _effective_trust(trust=trust, policy=policy).verify_artifact(artifact)
    return publish_recipe_gist(
        artifact,
        filename=filename,
        description=description,
        public=public,
        token=token,
    )


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
