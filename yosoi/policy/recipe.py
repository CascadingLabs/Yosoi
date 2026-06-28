"""Recipe trust policy for accepting portable recipe artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from yosoi.models.contract import Contract
    from yosoi.models.spec import ContractSpec


class RecipePolicy(BaseModel):
    """Policy-layer allowlist for loading/installing recipe artifacts.

    Remote recipes are deny-by-default unless an origin/user allowlist is set.
    Optional recipe-id and contract-fingerprint allowlists tighten acceptance to
    exact artifacts or exact contract shapes.
    """

    model_config = ConfigDict(frozen=True)

    allow_local: bool = True
    allowed_hosts: frozenset[str] = Field(default_factory=frozenset)
    allowed_github_owners: frozenset[str] = Field(default_factory=frozenset)
    allowed_recipe_ids: frozenset[str] = Field(default_factory=frozenset)
    allowed_contract_fingerprints: frozenset[str] = Field(default_factory=frozenset)

    @classmethod
    def local_only(cls) -> RecipePolicy:
        """Allow only local recipe files."""
        return cls(allow_local=True)

    @classmethod
    def github(cls, *owners: str) -> RecipePolicy:
        """Allow recipes fetched from specific GitHub users/orgs."""
        return cls(allowed_github_owners=frozenset(owners))

    @classmethod
    def hosts(cls, *hosts: str) -> RecipePolicy:
        """Allow recipes fetched from exact HTTPS hosts."""
        return cls(allowed_hosts=frozenset(host.lower() for host in hosts))

    def recipe_ids(self, *recipe_ids: str) -> RecipePolicy:
        """Require exact recipe ids in addition to existing source rules."""
        return self.model_copy(update={'allowed_recipe_ids': self.allowed_recipe_ids | frozenset(recipe_ids)})

    def contracts(self, *contracts: type[Contract] | str | ContractSpec) -> RecipePolicy:
        """Require exact contract fingerprints in addition to existing source rules."""
        from yosoi.recipe import _contract_spec

        fingerprints = frozenset(_contract_spec(contract).fingerprint for contract in contracts)
        return self.model_copy(
            update={'allowed_contract_fingerprints': self.allowed_contract_fingerprints | fingerprints}
        )

    def to_trust(self) -> Any:
        """Convert to the recipe module's executable trust checker."""
        from yosoi.recipe import RecipeTrust

        return RecipeTrust(
            allow_local=self.allow_local,
            allowed_hosts=self.allowed_hosts,
            allowed_github_owners=self.allowed_github_owners,
            allowed_recipe_ids=self.allowed_recipe_ids,
            allowed_contract_fingerprints=self.allowed_contract_fingerprints,
        )
