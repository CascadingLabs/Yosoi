"""The policy **core** — one resolved, immutable value object over every pipeline stack.

A :class:`Policy` collapses the decisions that change *how* the pipeline behaves (not *what* a
contract means) into a single frozen value, **resolved once at the edge** and threaded through the
pure core — so the replay ``resolve()`` stays a deterministic function of its inputs and never reads
the environment deep in the stack (the CAS-119 purity contract).

``Policy`` holds the always-on knobs (atom reads, trust tier) plus an optional per-stack sub-policy
(``crawl`` today). Each stack lives in its own module (:mod:`yosoi.policy.crawl`, …) so the surface
grows horizontally; ``core`` only knows how to *carry and resolve* them.

Precedence (lowest → highest): ``defaults < env < session < contract < call-site``.
:meth:`Policy.cascade` merges partial overrides (only the fields each layer explicitly set) into
one effective Policy.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from yosoi.models.selectors import SelectorLevel
from yosoi.policy._base import (
    _TRUTHY,
    QUARANTINED_SOURCES,
    TRUSTED_SOURCES,
    Trust,
    TrustTier,
    _classify_tier,
)
from yosoi.policy.crawl import (
    _PRESET_ALIASES,
    _PRESET_CRAWL_POLICIES,
    CrawlPolicy,
    CrawlRuntimeConfig,
)
from yosoi.policy.fingerprint import FingerprintPolicy
from yosoi.policy.run import (
    DiscoveryPolicy,
    DownloadPolicy,
    ModelPolicy,
    OutputPolicy,
    ResolvedRunSpec,
    ScrapePolicy,
    SecretRef,
    TelemetryPolicy,
    find_secret_ref,
    resolve_telemetry_values,
)


class PolicyCheck(BaseModel):
    """Dry-run validation result for policy-as-code workflows."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    policy_hash: str
    warnings: tuple[str, ...] = ()
    runtime: CrawlRuntimeConfig | None = None


class Policy(BaseModel):
    """Effective pipeline policy. Frozen — share freely across threads/sessions without copying.

    Attributes:
        atom_reads: Serve a contract from the field-atom index on a legacy-cache miss. Default-deny.
        trust_tier: ``strict`` serves only :data:`TRUSTED_SOURCES` (quarantines the risky
            fingerprint-generalized reuse); ``yellow`` ("let it ride") serves every tier.
        crawl: Optional crawl-stack sub-policy (see :mod:`yosoi.policy.crawl`).
        fingerprint: Optional signal-lane sub-policy (see :mod:`yosoi.policy.fingerprint`).
    """

    model_config = ConfigDict(frozen=True)

    atom_reads: bool = False
    trust_tier: TrustTier = 'strict'
    model: ModelPolicy | None = None
    scrape: ScrapePolicy | None = None
    discovery: DiscoveryPolicy | None = None
    telemetry: TelemetryPolicy | None = None
    output: OutputPolicy | None = None
    download: DownloadPolicy | None = None
    crawl: CrawlPolicy | None = None
    fingerprint: FingerprintPolicy | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Policy:  # noqa: C901
        """The ``env`` layer of the cascade: read the (legacy) ``YOSOI_*`` switches.

        Only sets a field when its env var is actually PRESENT, so an unset var contributes nothing
        to a :meth:`cascade` — an absent ``YOSOI_ATOM_TRUST`` can never reset a lower layer's tier.
        """
        src = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        if 'YOSOI_ATOM_READS' in src:
            kwargs['atom_reads'] = src['YOSOI_ATOM_READS'].strip().lower() in _TRUTHY
        if 'YOSOI_ATOM_TRUST' in src:
            kwargs['trust_tier'] = _classify_tier(src['YOSOI_ATOM_TRUST'])
        if 'YOSOI_MODEL' in src and src['YOSOI_MODEL'].strip():
            model = ModelPolicy.from_string(src['YOSOI_MODEL'].strip())
            ref = find_secret_ref(model.provider, src) if model.provider is not None else None
            kwargs['model'] = model.model_copy(update={'credential_ref': ref}) if ref is not None else model
        if 'YOSOI_FORCE' in src or 'YOSOI_FETCHER_TYPE' in src or 'YOSOI_SELECTOR_LEVEL' in src:
            scrape_payload: dict[str, Any] = {}
            if 'YOSOI_FORCE' in src:
                scrape_payload['force'] = src['YOSOI_FORCE'].strip().lower() in _TRUTHY
            if 'YOSOI_FETCHER_TYPE' in src:
                scrape_payload['fetcher_type'] = src['YOSOI_FETCHER_TYPE'].strip().lower()
            if 'YOSOI_SELECTOR_LEVEL' in src:
                level = src['YOSOI_SELECTOR_LEVEL'].strip().lower()
                try:
                    scrape_payload['selector_level'] = SelectorLevel[level.upper()]
                except KeyError as exc:
                    valid = ', '.join(sorted(member.name.lower() for member in SelectorLevel))
                    raise ValueError(f'Invalid YOSOI_SELECTOR_LEVEL {level!r}; choose one of: {valid}') from exc
            kwargs['scrape'] = ScrapePolicy.model_validate(scrape_payload)
        if 'YOSOI_DISCOVERY_MODE' in src:
            kwargs['discovery'] = DiscoveryPolicy.model_validate({'mode': src['YOSOI_DISCOVERY_MODE'].strip().lower()})
        telemetry_payload: dict[str, Any] = {}
        if 'LANGFUSE_PUBLIC_KEY' in src:
            telemetry_payload['langfuse_public_key_ref'] = SecretRef.env('LANGFUSE_PUBLIC_KEY')
        if 'LANGFUSE_SECRET_KEY' in src:
            telemetry_payload['langfuse_secret_key_ref'] = SecretRef.env('LANGFUSE_SECRET_KEY')
        if 'LANGFUSE_BASE_URL' in src or 'LANGFUSE_HOST' in src:
            telemetry_payload['langfuse_host'] = src.get('LANGFUSE_BASE_URL') or src.get('LANGFUSE_HOST')
        if telemetry_payload:
            kwargs['telemetry'] = TelemetryPolicy(**telemetry_payload)
        return cls(**kwargs)

    @classmethod
    def for_crawl(
        cls,
        preset: str | None = 'crawl.conservative',
        **overrides: Any,
    ) -> Policy:
        """Build a policy with a resolved crawl preset and validated overrides."""
        crawl = resolve_crawl_policy(preset)
        if overrides:
            crawl_payload = crawl.model_dump()
            crawl_payload.update(overrides)
            crawl = CrawlPolicy.model_validate(crawl_payload)
        return cls(crawl=crawl)

    @classmethod
    def cascade(cls, *layers: Policy | None) -> Policy:
        """Merge cascade layers (lowest precedence first) into one effective Policy.

        Precedence ``defaults < env < session < contract < call-site``, e.g.
        ``Policy.cascade(Policy.from_env(), session_policy, contract_policy, call_policy)``.
        Each layer contributes only the fields it explicitly set (``exclude_unset``), so a partial
        override like ``Policy(trust_tier='yellow')`` changes only the tier; ``None`` layers are
        skipped so callers can pass optional overrides positionally.

        ``model`` merges with a credential firewall: a layer that changes the model *identity*
        (``provider``/``model_name``) replaces the model wholesale, so a lower layer's
        ``credential_ref``/runtime key can never be transmitted to a different provider. A layer
        that only tweaks non-identity fields (e.g. ``temperature``) field-merges and keeps the
        existing credentials.
        """
        merged: dict[str, Any] = {}
        for layer in layers:
            if layer is not None:
                for key in layer.model_fields_set:
                    value = getattr(layer, key)
                    existing = merged.get(key)
                    if isinstance(value, ModelPolicy):
                        merged[key] = cls._merge_model_layer(existing, value)
                    elif isinstance(value, BaseModel) and isinstance(existing, BaseModel):
                        # Re-validate so nested models (e.g. SecretRef) survive the dump/merge
                        # round-trip as models, not raw dicts.
                        merged[key] = type(value).model_validate(
                            {**existing.model_dump(), **value.model_dump(exclude_unset=True)}
                        )
                    else:
                        merged[key] = value
        return cls(**merged)

    @staticmethod
    def _merge_model_layer(existing: Any, value: ModelPolicy) -> ModelPolicy:
        """Merge one ``model`` cascade layer under the credential firewall."""
        identity_change = bool({'provider', 'model_name'} & value.model_fields_set)
        if identity_change or value._runtime_api_key is not None or not isinstance(existing, ModelPolicy):
            return value
        updated = ModelPolicy.model_validate({**existing.model_dump(), **value.model_dump(exclude_unset=True)})
        updated._runtime_api_key = existing._runtime_api_key
        return updated

    @property
    def policy_hash(self) -> str:
        """Stable content hash for provenance and artifact records."""
        payload = self.model_dump(mode='json', exclude_unset=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()[:16]

    def resolve_run_spec(self, env: Mapping[str, str] | None = None) -> ResolvedRunSpec:
        """Resolve runtime-only values, including raw secrets, from this public policy."""
        from yosoi.core.configs import PROVIDER_FALLBACK_ORDER, TelemetryConfig
        from yosoi.core.discovery.config import _PROVIDER_ENV_VARS, NO_API_KEY_REQUIRED_PROVIDERS, LLMConfig

        src = os.environ if env is None else env
        model = self.model
        if model is None or model.provider is None or model.model_name is None:
            found: tuple[str, str, str] | None = None
            for provider, default_model in PROVIDER_FALLBACK_ORDER:
                for env_var in _PROVIDER_ENV_VARS.get(provider, ()):
                    if key := src.get(env_var):
                        found = (provider, default_model, key)
                        break
                if found is not None:
                    break
            if found is None:
                raise ValueError(
                    'No model specified and no API key found. '
                    'Pass policy=ys.Policy(model=ys.ModelPolicy.from_string("groq:...")) '
                    'or set YOSOI_MODEL and a provider API key.'
                )
            provider, model_name, _key = found
            model = ModelPolicy(provider=provider, model_name=model_name, credential_ref=find_secret_ref(provider, src))

        provider_name = model.provider
        model_name_value = model.model_name
        if provider_name is None or model_name_value is None:  # pragma: no cover - validator enforces the pair
            raise ValueError('model.provider and model.model_name must be resolved before execution')

        api_key = model._runtime_api_key
        if api_key is None and model.credential_ref is not None:
            api_key = model.credential_ref.resolve(src)
        if api_key is None and provider_name not in NO_API_KEY_REQUIRED_PROVIDERS:
            ref = find_secret_ref(provider_name, src)
            api_key = ref.resolve(src) if ref is not None else None
        if api_key is None and provider_name not in NO_API_KEY_REQUIRED_PROVIDERS:
            expected = ', '.join(_PROVIDER_ENV_VARS.get(provider_name, ())) or 'a provider-specific API key'
            raise ValueError(f'No API key found for explicit provider {provider_name!r}; set {expected}')

        telemetry = self.telemetry
        scrape = self.scrape or ScrapePolicy()
        discovery = self.discovery or DiscoveryPolicy()
        output = self.output or OutputPolicy()
        download = self.download or DownloadPolicy()

        return ResolvedRunSpec(
            policy_hash=self.policy_hash,
            llm_config=LLMConfig(
                provider=provider_name,
                model_name=model_name_value,
                api_key=api_key,
                temperature=model.temperature,
                max_tokens=model.max_tokens,
                extra_params=dict(model.extra_params) if model.extra_params is not None else None,
            ),
            telemetry_config=TelemetryConfig(**resolve_telemetry_values(telemetry, src)),
            debug_html=output.debug_html,
            debug_html_dir=output.debug_html_dir,
            force=scrape.force,
            skip_verification=scrape.skip_verification,
            fetcher_type=scrape.fetcher_type,
            selector_level=scrape.selector_level,
            max_concurrency=scrape.max_concurrency,
            output_formats=output.formats,
            quiet=output.quiet,
            json_output=output.json_output,
            allow_downloads=download.allow,
            allowed_download_types=download.allowed_types,
            download_dir=download.directory,
            max_download_bytes=download.max_bytes,
            keep_downloads=download.keep,
            discovery_max_concurrent=discovery.max_concurrent,
            discovery_mode=discovery.mode,
            lesson_cache=discovery.lesson_cache,
            replay_verify_threshold=discovery.replay_verify_threshold,
            static_mode_warning=discovery.static_mode_warning,
        )

    def require_crawl(self) -> CrawlPolicy:
        """Return the crawl policy or fail before a crawl can start."""
        if self.crawl is None:
            raise ValueError('Policy does not include crawl settings')
        return self.crawl

    def check_crawl(self, *, seeds: tuple[str, ...] = ()) -> PolicyCheck:
        """Dry-run crawl policy validation and runtime config derivation."""
        crawl = self.require_crawl()
        runtime = crawl.to_runtime_config(seeds=seeds)
        warnings: list[str] = []
        if runtime.max_workers > runtime.max_pages:
            warnings.append('max_workers exceeds max_pages; some workers will be idle')
        if runtime.max_depth > 0 and runtime.max_pages <= runtime.max_depth:
            warnings.append('max_pages may be too small to use the requested max_depth')
        if not runtime.allowed_hosts and not runtime.allow_cross_domain:
            warnings.append('no allowed_hosts resolved; pass seeds or set safety.allowed_hosts')
        if runtime.per_host_concurrency > 1 and runtime.politeness_delay == 0:
            warnings.append('same-host concurrency without politeness_delay can be impolite')
        return PolicyCheck(valid=True, policy_hash=self.policy_hash, warnings=tuple(warnings), runtime=runtime)

    @property
    def allowed_sources(self) -> frozenset[str] | None:
        """Provenance tiers eligible to serve under this policy; ``None`` = all (yellow).

        Strict returns the positive :data:`TRUSTED_SOURCES` allow-list (default-deny the risky);
        yellow returns ``None`` (serve every tier, including fingerprint-generalized reuse).
        """
        return None if self.trust_tier == 'yellow' else TRUSTED_SOURCES

    def source_trust(self, source: str) -> Trust:
        """Classify a provenance source in the trust lattice, independent of serving policy.

        Known verified/manual/LLM sources are verified. Known fingerprint-generalized
        sources are quarantined. Unknown sources are rejected so newly-added tiers
        fail closed until explicitly classified.
        """
        if source in TRUSTED_SOURCES:
            return Trust.VERIFIED
        if source in QUARANTINED_SOURCES:
            return Trust.QUARANTINED
        return Trust.REJECTED

    def allows_source(self, source: str) -> bool:
        """Whether this policy may serve a source at all."""
        trust = self.source_trust(source)
        if trust is Trust.REJECTED:
            return False
        if trust is Trust.QUARANTINED:
            return self.trust_tier == 'yellow'
        return True

    def output_trust(self, source: str) -> Trust:
        """Trust state of output produced from ``source`` under this policy."""
        trust = self.source_trust(source)
        if trust is Trust.QUARANTINED and not self.allows_source(source):
            return Trust.REJECTED
        return trust


def resolve_crawl_policy(policy: str | CrawlPolicy | Policy | None = None) -> CrawlPolicy:
    """Resolve a crawl policy preset, ARN, inline crawl policy, or full Policy."""
    if isinstance(policy, Policy):
        return policy.require_crawl()
    if isinstance(policy, CrawlPolicy):
        return policy
    key = policy or 'crawl.local_single'
    key = _PRESET_ALIASES.get(key, key)
    if key in _PRESET_CRAWL_POLICIES:
        return _PRESET_CRAWL_POLICIES[key]
    raise KeyError(f'Unknown crawl policy: {policy}')


def check_policy(policy: str | CrawlPolicy | Policy | None = None, *, seeds: tuple[str, ...] = ()) -> PolicyCheck:
    """Validate a crawl policy reference without running network, browser, or model work."""
    resolved = policy if isinstance(policy, Policy) else Policy(crawl=resolve_crawl_policy(policy))
    return resolved.check_crawl(seeds=seeds)
