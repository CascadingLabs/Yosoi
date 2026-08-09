from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.actions.models import ActionKind, ActionSpec, CaptureRef, EffectClass, ElementRef
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import RegionRef
from yosoi.qa import QAActionRequest, UnwiredQAActionHandler
from yosoi.qa.actions import QAActionCapabilities, QAActionOutcome, QAActionResult

_SHA = 'a' * 64


def _request() -> QAActionRequest:
    return QAActionRequest(
        before=CaptureRef(snapshot_id='before', manifest_sha256=_SHA),
        action=ActionSpec(kind=ActionKind.BACK, effect=EffectClass.OBSERVATION),
    )


def test_action_request_is_evidence_backed_and_has_no_payload_channel() -> None:
    assert _request().action.target is None
    with pytest.raises(ValidationError):
        QAActionRequest.model_validate({**_request().model_dump(), 'selector': '#raw', 'payload': {}})


def test_request_rejects_a_target_from_a_foreign_capture() -> None:
    target = ElementRef(
        snapshot_id='foreign',
        evidence=(
            RegionRef(
                snapshot_id='foreign',
                artifact_sha256=_SHA,
                modality=EvidenceKind.RENDERED_DOM,
                locator='//*[@id="target"]',
            ),
        ),
        semantic_role='button',
    )
    with pytest.raises(ValidationError, match='before capture'):
        QAActionRequest(
            before=CaptureRef(snapshot_id='before', manifest_sha256=_SHA),
            action=ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI, target=target),
        )


def test_compact_result_requires_exact_receipt_identity() -> None:
    fingerprint = 'b' * 64
    result = QAActionResult(
        status=QAActionOutcome.COMPLETED,
        receipt_handle='receipt:1',
        receipt_fingerprint=fingerprint,
        before_snapshot_id='before',
        after_snapshot_id='after',
    )
    assert result.receipt_fingerprint == fingerprint
    with pytest.raises(ValidationError, match='fingerprint and before'):
        QAActionResult(status=QAActionOutcome.COMPLETED, receipt_handle='receipt:1')


def test_capabilities_default_false() -> None:
    capabilities = QAActionCapabilities()
    assert capabilities.model_dump(exclude={'operations'}) == {
        'index': False,
        'capture': False,
        'actions': False,
        'deterministic_assertions': False,
        'a3_recording': False,
        'live_readiness': False,
    }


@pytest.mark.asyncio
async def test_unwired_handler_status_is_truthful_and_execution_refuses() -> None:
    handler = UnwiredQAActionHandler()
    status = await handler.status()
    assert status.ready is False
    assert all(not value for value in status.capabilities.model_dump(exclude={'operations'}).values())
    with pytest.raises(NotImplementedError, match='action execution is not wired'):
        await handler.execute(_request())
