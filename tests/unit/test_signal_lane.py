"""SignalLane + FingerprintPolicy: bounded, single-writer-drained, defer-not-drop (CAS-168 item 4)."""

from __future__ import annotations

import asyncio

import yosoi as ys
from yosoi.policy.signal_lane import LaneOutcome, SignalLane


async def _noop(_item: object) -> None:
    return None


def test_offer_is_off_when_disabled() -> None:
    lane = SignalLane(_noop, enabled=False)
    assert lane.offer('x') is LaneOutcome.OFF


def test_full_queue_defers_not_drops() -> None:
    lane = SignalLane(_noop, backpressure='defer', max_queue=1)
    assert lane.offer('a') is LaneOutcome.QUEUED
    assert lane.offer('b') is LaneOutcome.DEFERRED  # full → deferred, NOT dropped
    assert lane.pending == 2


def test_full_queue_drops_when_opted_in() -> None:
    lane = SignalLane(_noop, backpressure='drop', max_queue=1)
    assert lane.offer('a') is LaneOutcome.QUEUED
    assert lane.offer('b') is LaneOutcome.DROPPED
    assert lane.pending == 1


async def test_defer_drains_everything() -> None:
    seen: list[str] = []

    async def sink(item: str) -> None:
        seen.append(item)

    lane = SignalLane(sink, backpressure='defer', max_queue=2)
    await lane.start()
    for i in range(20):
        lane.offer(f'item-{i}')  # overflows the bounded queue → backlog
    await lane.aclose()

    assert sorted(seen) == sorted(f'item-{i}' for i in range(20))  # nothing dropped end-to-end


async def test_drop_loses_overflow() -> None:
    seen: list[str] = []

    async def sink(item: str) -> None:
        seen.append(item)

    lane = SignalLane(sink, backpressure='drop', max_queue=2)
    outcomes = [lane.offer(f'item-{i}') for i in range(20)]  # burst before any drain
    await lane.start()
    await lane.aclose()

    assert LaneOutcome.DROPPED in outcomes
    assert len(seen) <= 2  # only what fit the bounded queue survived


def test_fingerprint_policy_defaults_to_gather_on() -> None:
    fp = ys.FingerprintPolicy()
    assert fp.signal_lane is True  # gathering default-on
    assert fp.backpressure == 'defer'  # defer-not-drop default


def test_fingerprint_subpolicy_rides_the_cascade() -> None:
    effective = ys.Policy.cascade(ys.Policy(), ys.Policy(fingerprint=ys.FingerprintPolicy(backpressure='drop')))
    assert effective.fingerprint is not None
    assert effective.fingerprint.backpressure == 'drop'
    # default Policy has no fingerprint sub-policy (lane opt-in)
    assert ys.Policy().fingerprint is None


def test_concurrent_drop_under_slow_sink() -> None:
    async def main() -> None:
        seen: list[int] = []

        async def slow(item: int) -> None:
            await asyncio.sleep(0.005)
            seen.append(item)

        lane = SignalLane(slow, backpressure='defer', max_queue=4)
        await lane.start()
        for i in range(50):
            lane.offer(i)
        await lane.aclose()
        assert sorted(seen) == list(range(50))  # defer never loses work even with a slow sink

    asyncio.run(main())
