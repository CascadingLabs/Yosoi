"""Evidence-ledgered, browser-neutral transition execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.actions.errors import ActionBoundaryError as ActionBoundaryError
    from yosoi.actions.models import ACTION_SCHEMA_VERSION as ACTION_SCHEMA_VERSION
    from yosoi.actions.models import ActionErrorCode as ActionErrorCode
    from yosoi.actions.models import ActionKind as ActionKind
    from yosoi.actions.models import ActionSpec as ActionSpec
    from yosoi.actions.models import AssertionResult as AssertionResult
    from yosoi.actions.models import AssertionStatus as AssertionStatus
    from yosoi.actions.models import CaptureRef as CaptureRef
    from yosoi.actions.models import DispatchEvidence as DispatchEvidence
    from yosoi.actions.models import DispatchStatus as DispatchStatus
    from yosoi.actions.models import EffectClass as EffectClass
    from yosoi.actions.models import ElementRef as ElementRef
    from yosoi.actions.models import FreshnessStatus as FreshnessStatus
    from yosoi.actions.models import NetworkResponseEvidence as NetworkResponseEvidence
    from yosoi.actions.models import OutcomeStatus as OutcomeStatus
    from yosoi.actions.models import PolicyEvidence as PolicyEvidence
    from yosoi.actions.models import PolicyStatus as PolicyStatus
    from yosoi.actions.models import ReceiptTiming as ReceiptTiming
    from yosoi.actions.models import ResolutionEvidence as ResolutionEvidence
    from yosoi.actions.models import ResolutionStatus as ResolutionStatus
    from yosoi.actions.models import ResponseBodyState as ResponseBodyState
    from yosoi.actions.models import ResponseExpectationSpec as ResponseExpectationSpec
    from yosoi.actions.models import ScrollDirection as ScrollDirection
    from yosoi.actions.models import ScrollExtent as ScrollExtent
    from yosoi.actions.models import ScrollSpec as ScrollSpec
    from yosoi.actions.models import SettlementObservation as SettlementObservation
    from yosoi.actions.models import SettlementSignal as SettlementSignal
    from yosoi.actions.models import SettlementStatus as SettlementStatus
    from yosoi.actions.models import TransitionReceipt as TransitionReceipt
    from yosoi.actions.protocols import ActionPolicy as ActionPolicy
    from yosoi.actions.protocols import ResolvedTarget as ResolvedTarget
    from yosoi.actions.protocols import RetainedActionSession as RetainedActionSession
    from yosoi.actions.protocols import SettlementResult as SettlementResult
    from yosoi.actions.protocols import TargetResolver as TargetResolver
    from yosoi.actions.protocols import TransitionVerifier as TransitionVerifier
    from yosoi.actions.runtime import ActionRuntime as ActionRuntime
    from yosoi.actions.runtime import Clock as Clock

_MODEL_EXPORTS = {
    'ACTION_SCHEMA_VERSION',
    'ActionErrorCode',
    'ActionKind',
    'ActionSpec',
    'AssertionResult',
    'AssertionStatus',
    'CaptureRef',
    'DispatchEvidence',
    'DispatchStatus',
    'EffectClass',
    'ElementRef',
    'FreshnessStatus',
    'NetworkResponseEvidence',
    'OutcomeStatus',
    'PolicyEvidence',
    'PolicyStatus',
    'ReceiptTiming',
    'ResolutionEvidence',
    'ResolutionStatus',
    'ResponseBodyState',
    'ResponseExpectationSpec',
    'ScrollDirection',
    'ScrollExtent',
    'ScrollSpec',
    'SettlementObservation',
    'SettlementSignal',
    'SettlementStatus',
    'TransitionReceipt',
}
_PROTOCOL_EXPORTS = {
    'ActionPolicy',
    'ResolvedTarget',
    'RetainedActionSession',
    'SettlementResult',
    'TargetResolver',
    'TransitionVerifier',
}
_LAZY = dict.fromkeys(_MODEL_EXPORTS, 'yosoi.actions.models')
_LAZY.update(dict.fromkeys(_PROTOCOL_EXPORTS, 'yosoi.actions.protocols'))
_LAZY.update(
    {
        'ActionBoundaryError': 'yosoi.actions.errors',
        'ActionRuntime': 'yosoi.actions.runtime',
        'Clock': 'yosoi.actions.runtime',
    }
)

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
