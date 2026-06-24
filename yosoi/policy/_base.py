"""Shared policy primitives — the trust lattice and validation building blocks every stack reuses.

This is the stack-agnostic base of ``ys.policy``: the :class:`Trust`/:class:`Outcome` lattice, the
provenance allow-lists, the bool-rejecting numeric types, host/path coercion, and the ARN helper.
It depends on nothing else in ``yosoi.policy`` (``crawl`` and ``core`` build on it), so new stacks
import from here without pulling the :class:`~yosoi.policy.core.Policy` value object or any one stack.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import Enum
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BeforeValidator

TrustTier = Literal['strict', 'yellow']


class Trust(str, Enum):
    """Trust lattice for reuse output.

    ``QUARANTINED`` is the key middle state from the CAS-85 spike: output may be
    produced under an explicit ride/yellow policy, but it is not silently treated
    as verified until a later invariant/judge confirms it.
    """

    VERIFIED = 'verified'
    QUARANTINED = 'quarantined'
    REJECTED = 'rejected'


class Outcome(str, Enum):
    """Ground-truth outcome that resolves a quarantined reuse decision."""

    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    REFUTED = 'refuted'


# Strict serves ONLY these provenance tiers — a POSITIVE allow-list (deny-by-default). A new tier in
# storage.atoms.SOURCE_TRUST is refused under strict until it is consciously promoted here, so reuse
# can never silently fail OPEN as P5 adds tiers. The partition (TRUSTED | QUARANTINED == all known
# sources, disjoint) is asserted by test, forcing a deliberate classification when a tier is added.
TRUSTED_SOURCES = frozenset({'verified', 'manual', 'llm'})
QUARANTINED_SOURCES = frozenset({'fingerprint'})  # the fingerprint-generalized reuse — risky, strict-denied

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})
_YELLOW_ALIASES = frozenset({'yellow', 'ride'})  # "let it ride"; ANYTHING else (incl. unset) → strict
_POLICY_ARN_PREFIX = 'arn:yosoi:policy:'


def _classify_tier(raw: str) -> TrustTier:
    """Normalize a raw trust-mode string to a tier — the ONE place trust aliases are decided."""
    return 'yellow' if raw.strip().lower() in _YELLOW_ALIASES else 'strict'


def _normalize_host(host: str) -> str:
    """Normalize a policy host token without accepting path/query-shaped values."""
    value = host.strip().lower()
    if not value:
        raise ValueError('host entries must be non-empty strings')
    parsed = urlparse(value if '://' in value else f'//{value}')
    if parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError(f'host entries may not include paths or query strings: {host!r}')
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f'invalid host entry: {host!r}')
    return hostname


def _normalize_path_prefix(raw: str) -> str | None:
    """Normalize a blocked-path-prefix token; empty → None; non-anchored → ValueError."""
    prefix = raw.strip()
    if not prefix:
        return None
    if not prefix.startswith('/'):
        raise ValueError(f'blocked_path_prefixes must start with "/": {prefix!r}')
    return prefix


def _coerce_str_tuple(value: object, *, normalize: Callable[[str], str | None], label: str) -> tuple[str, ...]:
    """Coerce None/str/iterable into a deduped tuple of normalized (non-None) string tokens."""
    if value is None:
        return ()
    if isinstance(value, str):
        raw = (value,)
    elif isinstance(value, Iterable):
        raw = tuple(value)
    else:
        raise TypeError(label)
    return tuple(dict.fromkeys(n for n in (normalize(str(i)) for i in raw) if n is not None))


def policy_arn(namespace: str, name: str) -> str:
    """Return an ARN-like stable address for a local policy preset."""
    namespace = namespace.strip()
    name = name.strip()
    if not namespace or not name:
        raise ValueError('namespace and name must be non-empty')
    return f'{_POLICY_ARN_PREFIX}{namespace}/{name}'


def _reject_bool(value: object) -> object:
    """Reject bools before Pydantic treats them as ints."""
    if isinstance(value, bool):
        raise ValueError('boolean values are not valid numeric policy settings')
    return value


# Numeric policy types that reject bool (Python's bool is an int) before coercion. Each field keeps
# its own Field(default=..., ge=..., le=..., gt=...) — bounds differ per field, so don't fold them in.
StrictInt = Annotated[int, BeforeValidator(_reject_bool)]
StrictFloat = Annotated[float, BeforeValidator(_reject_bool)]
StrictOptInt = Annotated[int | None, BeforeValidator(_reject_bool)]


def promote_trust(trust: Trust, *, confirmed: bool) -> tuple[Trust, Outcome]:
    """Resolve a quarantined trust state with a later ground-truth signal.

    Terminal states remain terminal. A quarantined result promotes to verified
    when confirmed, or rejected when refuted.
    """
    if trust is Trust.QUARANTINED:
        return (
            Trust.VERIFIED if confirmed else Trust.REJECTED,
            Outcome.CONFIRMED if confirmed else Outcome.REFUTED,
        )
    return trust, Outcome.PENDING
