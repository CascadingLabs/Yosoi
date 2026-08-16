"""Concrete browser adapters for the browser-neutral action ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.actions.adapters.voidcrawl import ADAPTER_POLICY_VERSION as ADAPTER_POLICY_VERSION
    from yosoi.actions.adapters.voidcrawl import DEFAULT_REQUIRE_NETWORK_IDLE as DEFAULT_REQUIRE_NETWORK_IDLE
    from yosoi.actions.adapters.voidcrawl import SUPPORTED_ACTION_KINDS as SUPPORTED_ACTION_KINDS
    from yosoi.actions.adapters.voidcrawl import UNSUPPORTED_CAPABILITY_REASONS as UNSUPPORTED_CAPABILITY_REASONS
    from yosoi.actions.adapters.voidcrawl import AdapterCapabilityPolicy as AdapterCapabilityPolicy
    from yosoi.actions.adapters.voidcrawl import AxClickTarget as AxClickTarget
    from yosoi.actions.adapters.voidcrawl import AxEvidenceResolver as AxEvidenceResolver
    from yosoi.actions.adapters.voidcrawl import RetainedBrowserTab as RetainedBrowserTab
    from yosoi.actions.adapters.voidcrawl import RetainedVoidCrawlSession as RetainedVoidCrawlSession
    from yosoi.actions.adapters.voidcrawl import SnapshotCapture as SnapshotCapture
    from yosoi.actions.adapters.voidcrawl import UnsupportedPostconditionVerifier as UnsupportedPostconditionVerifier
    from yosoi.actions.adapters.voidcrawl import accessible_name_digest as accessible_name_digest
    from yosoi.actions.adapters.voidcrawl import capture_ref_for as capture_ref_for
    from yosoi.actions.adapters.voidcrawl import snapshot_manifest_digest as snapshot_manifest_digest

_LAZY = dict.fromkeys(
    (
        'ADAPTER_POLICY_VERSION',
        'DEFAULT_REQUIRE_NETWORK_IDLE',
        'SUPPORTED_ACTION_KINDS',
        'UNSUPPORTED_CAPABILITY_REASONS',
        'AdapterCapabilityPolicy',
        'AxClickTarget',
        'AxEvidenceResolver',
        'UnsupportedPostconditionVerifier',
        'RetainedBrowserTab',
        'RetainedVoidCrawlSession',
        'SnapshotCapture',
        'accessible_name_digest',
        'capture_ref_for',
        'snapshot_manifest_digest',
    ),
    'yosoi.actions.adapters.voidcrawl',
)

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
