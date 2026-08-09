"""Independent CAS-270 tests for bounded response capture around retained-tab clicks.

These tests intentionally use only a deterministic fake tab.  The contract under test is that
an expectation obtained from the *injected* tab is entered before the click and that only the
sanitized ``CapturedResponse`` fields cross the action boundary.  They assume the adapter exposes
one bounded response expectation declared on the immutable ``ActionSpec``.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from test_voidcrawl_adapter import FakeCapture, FakeTab, PassingVerifier, _click

from yosoi.actions.adapters.voidcrawl import (
    AdapterCapabilityPolicy,
    AxEvidenceResolver,
    RetainedVoidCrawlSession,
)
from yosoi.actions.models import ActionErrorCode, ActionSpec, OutcomeStatus, ResponseExpectationSpec
from yosoi.actions.runtime import ActionRuntime


class FakeResponseTimeout(Exception):
    """Expected response timeout kept distinct from generic adapter errors."""


class FakeCapturedResponse:
    url = 'https://api.example.test/v1/items?token=must-not-escape'
    status = 200
    headers: ClassVar[dict[str, str]] = {'authorization': 'Bearer secret', 'content-type': 'application/json'}
    mime_type = 'application/json'
    resource_type = 'xhr'
    from_cache = False
    from_service_worker = False
    body_state = 'truncated'
    truncated = True

    async def text(self) -> str:
        return '{"secret":"must-not-escape"}'


class FakeExpectation:
    def __init__(self, tab: NetworkTab) -> None:
        self.tab = tab
        self._response = FakeCapturedResponse()
        self.entered = False
        self.exited = False

    @property
    def value(self) -> Any:
        async def response() -> FakeCapturedResponse:
            return self._response

        return response()

    async def __aenter__(self) -> FakeExpectation:
        self.entered = True
        self.tab.events.append('expect-enter')
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.exited = True
        self.tab.events.append('expect-exit')
        if exc_type is not None and self.tab.cleanup_error is not None:
            raise self.tab.cleanup_error
        return False


class NetworkTab(FakeTab):
    def __init__(self, *, response: FakeCapturedResponse | None = None) -> None:
        super().__init__()
        self.events: list[str] = []
        self.response = response
        self.expectations: list[FakeExpectation] = []
        self.expectation_error: BaseException | None = None
        self.click_error: BaseException | None = None
        self.cleanup_error: BaseException | None = None

    def expect_response(
        self,
        pattern: str,
        timeout: float = 30.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_total_bytes: int = 8 * 1024 * 1024,
    ) -> FakeExpectation:
        self.events.append('expect-call')
        assert pattern == '**/v1/items'
        assert timeout == 1.25
        assert max_response_bytes == 128
        assert max_total_bytes == 256
        if self.expectation_error is not None:
            raise self.expectation_error
        expectation = FakeExpectation(self)
        self.expectations.append(expectation)
        return expectation

    async def click_by_role(self, role: str, name: str, nth: int = 0) -> None:
        self.events.append('click')
        if self.click_error is not None:
            raise self.click_error
        await super().click_by_role(role, name, nth)


async def _network_wire(
    tab: NetworkTab,
) -> tuple[ActionRuntime, NetworkTab, FakeCapture, Any, Any]:
    capture = FakeCapture()
    before = await capture.capture()
    from yosoi.actions.adapters.voidcrawl import capture_ref_for

    before_ref = capture_ref_for(before)
    session = RetainedVoidCrawlSession(
        tab=tab,
        capture=capture,
        active=before_ref,
        adapter_errors=(RuntimeError, TimeoutError, OSError),
        response_timeout_error_types=(FakeResponseTimeout, TimeoutError),
    )
    runtime = ActionRuntime(
        session=session,
        resolver=AxEvidenceResolver(tab=tab, adapter_errors=(RuntimeError, TimeoutError, OSError)),
        policy=AdapterCapabilityPolicy(tab=tab),
        verifier=PassingVerifier(),
        redaction_version='redaction-v1',
    )
    return runtime, tab, capture, session, before_ref


def _response_click(snapshot_id: str) -> ActionSpec:
    base = _click(snapshot_id)
    return ActionSpec(
        kind=base.kind,
        effect=base.effect,
        target=base.target,
        response_expectation=ResponseExpectationSpec(
            pattern_id='items-api',
            pattern='**/v1/items',
            timeout=1.25,
            max_response_bytes=128,
            max_total_bytes=256,
        ),
    )


def _dumped_response_evidence(receipt: Any) -> dict[str, Any]:
    """Find the public response evidence without coupling this test to field placement."""
    dumped = receipt.model_dump(mode='json')
    candidates: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if {'path', 'status', 'resource_type', 'mime_type', 'body_state', 'truncated'} <= value.keys():
                candidates.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(dumped)
    assert len(candidates) == 1
    return candidates[0]


@pytest.mark.asyncio
async def test_expectation_is_armed_on_the_injected_tab_before_same_tab_click() -> None:
    runtime, tab, _, _, before = await _network_wire(NetworkTab(response=FakeCapturedResponse()))

    receipt = await runtime.perform(before=before, action=_response_click(before.snapshot_id))

    assert receipt.outcome is OutcomeStatus.SUCCESS
    assert tab.events.index('expect-enter') < tab.events.index('click')
    assert tab.expectations[0].entered
    assert tab.expectations[0].exited
    assert tab.expectations[0].tab is tab
    evidence = _dumped_response_evidence(receipt)
    assert evidence['path'] == '/v1/items'
    assert evidence['status'] == 200
    assert evidence['resource_type'] == 'xhr'
    assert evidence['mime_type'] == 'application/json'
    assert evidence['body_state'] == 'truncated'
    assert evidence['truncated'] is True
    assert len(evidence['request_url_sha256']) == 64
    assert len(evidence['origin_sha256']) == 64
    serialized = receipt.model_dump_json()
    assert 'authorization' not in serialized
    assert 'Bearer secret' not in serialized
    assert 'must-not-escape' not in serialized


@pytest.mark.asyncio
async def test_ajax_verifier_can_assert_the_captured_endpoint_directly() -> None:
    runtime, _, _, _, before = await _network_wire(NetworkTab(response=FakeCapturedResponse()))
    receipt = await runtime.perform(before=before, action=_response_click(before.snapshot_id))
    evidence = _dumped_response_evidence(receipt)

    assert evidence['path'] == '/v1/items'
    assert evidence['status'] == 200
    assert receipt.settlement_observations


@pytest.mark.parametrize('failure', ['timeout', 'missing-capability', 'error', 'failed-click'])
@pytest.mark.asyncio
async def test_response_failures_clean_up_and_never_yield_success(failure: str) -> None:
    tab = NetworkTab(response=FakeCapturedResponse())
    if failure == 'timeout':
        tab.expectation_error = TimeoutError()
    elif failure == 'missing-capability':
        tab.expect_response = None  # type: ignore[method-assign]
    elif failure == 'error':
        tab.expectation_error = RuntimeError('secret must not escape')
    else:
        tab.click_error = RuntimeError('click secret must not escape')

    runtime, tab, _, _, before = await _network_wire(tab)
    receipt = await runtime.perform(before=before, action=_response_click(before.snapshot_id))

    assert receipt.outcome is not OutcomeStatus.SUCCESS
    assert receipt.error_code in {
        ActionErrorCode.ADAPTER_ERROR,
        ActionErrorCode.DISPATCH_FAILED,
        ActionErrorCode.UNSUPPORTED_ACTION,
        ActionErrorCode.SETTLEMENT_TIMEOUT,
    }
    assert 'secret' not in receipt.model_dump_json()
    if tab.expectations:
        assert tab.expectations[0].exited


@pytest.mark.asyncio
async def test_dispatch_failure_is_not_masked_by_response_cleanup_timeout() -> None:
    tab = NetworkTab(response=FakeCapturedResponse())
    tab.click_error = RuntimeError('click failed')
    tab.cleanup_error = FakeResponseTimeout()
    runtime, tab, _, _, before = await _network_wire(tab)

    receipt = await runtime.perform(before=before, action=_response_click(before.snapshot_id))

    assert receipt.error_code is ActionErrorCode.DISPATCH_FAILED
    assert tab.expectations[0].exited


@pytest.mark.asyncio
async def test_cancellation_exits_expectation_and_cannot_settle_successfully() -> None:
    tab = NetworkTab(response=FakeCapturedResponse())
    tab.click_error = asyncio.CancelledError()
    runtime, tab, _, _, before = await _network_wire(tab)

    with pytest.raises(asyncio.CancelledError):
        await runtime.perform(before=before, action=_response_click(before.snapshot_id))

    assert tab.expectations[0].exited
    assert 'secret' not in repr(tab.expectations[0]._response)
