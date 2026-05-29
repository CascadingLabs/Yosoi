"""A4.4 — assert per-field concurrency under the orchestrator's semaphore.

Event-based synchronisation (no wall-clock, no sleep injection):

- Replace ``FieldDiscoveryAgent.discover_field`` with a stub that records
  entry/exit and awaits an ``asyncio.Event``. The driving test coordinates the
  event so the orchestrator's ``asyncio.gather`` can finish only when N fields
  are confirmed simultaneously inside the semaphore.
- Deterministic under CI load — there is no clock dependency.

Three cases:
  1. Concurrent entry under semaphore (5 of 5).
  2. Capping (peak <= 3 with field_count=10, max_concurrent=3).
  3. ``orchestrator_discover_selectors`` carries ``field_count`` + ``max_concurrent`` attrs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import pytest

import yosoi as ys
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator
from yosoi.models.contract import Contract
from yosoi.models.selectors import FieldSelectors
from yosoi.utils import observability as obs

CLEANED_HTML = '<body><h1>x</h1></body>'


def _make_contract(field_count: int) -> type[Contract]:
    """Build a Contract subclass with ``field_count`` plain string fields."""
    fields: dict[str, object] = {f'f{i}': ys.Title() for i in range(field_count)}
    fields['__annotations__'] = {f'f{i}': str for i in range(field_count)}
    return type(f'_FC{field_count}', (Contract,), fields)


def _stub_field_selectors() -> FieldSelectors:
    """A minimal FieldSelectors that satisfies the orchestrator's NA check."""
    return FieldSelectors(primary='h1')


@pytest.fixture
def _active_obs(mocker):
    from opentelemetry import trace

    fake = mocker.MagicMock()
    fake.tracer = trace.get_tracer('yosoi-test-discovery-concurrency')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


@pytest.fixture
def llm_config_fixture():
    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='test', temperature=0.0)


def _make_orchestrator(
    contract: type[Contract], llm_config: LLMConfig, max_concurrent: int, mocker
) -> DiscoveryOrchestrator:
    storage = mocker.MagicMock()
    storage.load_selectors = mocker.AsyncMock(return_value={})
    storage.load_snapshots = mocker.AsyncMock(return_value={})
    storage.save_snapshots = mocker.AsyncMock()
    return DiscoveryOrchestrator(
        contract=contract,
        llm_config=llm_config,
        storage=storage,
        max_concurrent=max_concurrent,
    )


def _instrument_concurrent_entry(
    mocker,
    orchestrator: DiscoveryOrchestrator,
    *,
    expected_entries: int,
) -> tuple[asyncio.Event, asyncio.Event, dict[str, int]]:
    """Patch the agent so all field calls block until `release` is set.

    Returns ``(release, all_entered, stats)``.
    The driving test awaits ``all_entered`` — set after `expected_entries`
    coroutines have entered the patched discover_field — then sets ``release``
    so the gather can complete. ``stats['peak']`` records max concurrent.
    """
    release = asyncio.Event()
    all_entered = asyncio.Event()
    stats = {'peak': 0, 'in_flight': 0}

    async def _stub(_self, field_name, *_args, **_kwargs):
        stats['in_flight'] += 1
        if stats['in_flight'] > stats['peak']:
            stats['peak'] = stats['in_flight']
        if stats['in_flight'] >= expected_entries:
            all_entered.set()
        try:
            await release.wait()
            return _stub_field_selectors()
        finally:
            stats['in_flight'] -= 1

    mocker.patch(
        'yosoi.core.discovery.field_agent.FieldDiscoveryAgent.discover_field',
        new=_stub,
    )
    return release, all_entered, stats


@pytest.mark.usefixtures('_active_obs')
async def test_all_fields_enter_semaphore_concurrently_when_uncapped(llm_config_fixture, mocker):
    """field_count=5, max_concurrent=5 → all 5 inside the semaphore at once."""
    contract = _make_contract(5)
    orch = _make_orchestrator(contract, llm_config_fixture, max_concurrent=5, mocker=mocker)
    release, all_entered, stats = _instrument_concurrent_entry(mocker, orch, expected_entries=5)

    discover_task = asyncio.create_task(orch.discover_selectors(CLEANED_HTML, url='https://t.example.com'))
    # Fail fast if the orchestrator runs sequentially.
    await asyncio.wait_for(all_entered.wait(), timeout=2.0)
    assert stats['peak'] == 5, f'expected peak=5 concurrent fields, got {stats["peak"]}'
    release.set()
    await discover_task


@pytest.mark.usefixtures('_active_obs')
async def test_semaphore_caps_concurrent_field_count(llm_config_fixture, mocker):
    """field_count=10, max_concurrent=3 → never more than 3 in flight."""
    contract = _make_contract(10)
    orch = _make_orchestrator(contract, llm_config_fixture, max_concurrent=3, mocker=mocker)
    release, _all_entered, stats = _instrument_concurrent_entry(mocker, orch, expected_entries=3)

    async def _release_after_first_three() -> None:
        # Wait for the cap to be reached, then release in waves so the gather
        # completes. Each release iteration lets one task finish, freeing a
        # semaphore slot for the next-queued task.
        while stats['in_flight'] < 3:  # noqa: ASYNC110 - polling a counter, not a coroutine
            await asyncio.sleep(0)
        for _ in range(10):
            release.set()
            await asyncio.sleep(0)
            release.clear()
            if stats['in_flight'] == 0:
                break
        release.set()  # final blanket release

    drain_task = asyncio.create_task(_release_after_first_three())
    await asyncio.wait_for(orch.discover_selectors(CLEANED_HTML, url='https://t.example.com'), timeout=5.0)
    await drain_task
    assert stats['peak'] <= 3, f'semaphore failed: peak={stats["peak"]} > 3'
    assert stats['peak'] >= 1, f'expected at least 1 in flight; got {stats["peak"]}'


@pytest.mark.usefixtures('_active_obs')
async def test_orchestrator_span_carries_field_count_and_max_concurrent(span_exporter, llm_config_fixture, mocker):
    """The orchestrator_discover_selectors span has the new A4.1 attributes."""
    contract = _make_contract(4)
    orch = _make_orchestrator(contract, llm_config_fixture, max_concurrent=2, mocker=mocker)
    release, all_entered, _stats = _instrument_concurrent_entry(
        mocker,
        orch,
        expected_entries=2,  # capped at 2 — only 2 ever enter at once
    )

    discover_task = asyncio.create_task(orch.discover_selectors(CLEANED_HTML, url='https://t.example.com'))
    await asyncio.wait_for(all_entered.wait(), timeout=2.0)
    release.set()
    await discover_task

    spans = list(span_exporter.get_finished_spans())
    orch_spans = [s for s in spans if s.name == 'orchestrator_discover_selectors']
    assert len(orch_spans) >= 1
    s = orch_spans[-1]
    # field_count is len(task_specs) — at least 4 (plus root if no contract.get_root()).
    assert s.attributes.get('max_concurrent') == 2, f'got attrs: {dict(s.attributes)}'
    fc = s.attributes.get('field_count')
    assert isinstance(fc, int), f'expected int field_count; got {fc!r}'
    assert fc >= 4, f'expected field_count >= 4; got {fc}'


@pytest.mark.usefixtures('_active_obs')
async def test_orchestrator_span_bypass_when_all_fields_overridden(span_exporter, llm_config_fixture, mocker):
    """All-overrides early-return path emits a span with bypass='all_overrides'."""
    from yosoi.types import Field as YsField

    # Use yosoi.types.Field(selector=...) to set the override correctly.
    # ``root`` is also fixed so _build_task_specs() returns []; an undeclared
    # root would still produce a discoverable container task and (correctly)
    # prevent the bypass.
    contract = type(
        '_AllOverrideContract',
        (Contract,),
        {
            '__annotations__': {'title': str},
            'title': YsField(description='Title', selector='h1.title'),
            'root': 'body',
        },
    )
    orch = _make_orchestrator(contract, llm_config_fixture, max_concurrent=5, mocker=mocker)

    result = await orch.discover_selectors(CLEANED_HTML, url='https://t.example.com')
    assert result is not None

    spans = list(span_exporter.get_finished_spans())
    orch_spans = [s for s in spans if s.name == 'orchestrator_discover_selectors']
    assert len(orch_spans) >= 1
    s = orch_spans[-1]
    assert s.attributes.get('bypass') == 'all_overrides'
    assert s.attributes.get('field_count') == 0
    assert s.attributes.get('max_concurrent') == 0


def _ignore(_: Iterable[object]) -> None:
    """Silence vulture for fixture-only modules."""
