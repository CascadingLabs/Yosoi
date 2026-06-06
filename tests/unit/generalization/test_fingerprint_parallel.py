"""The fingerprint hashing path is pure, parallelizable, and async-offloadable.

Fingerprinting is a SIGNAL-LANE concern: it forks off the critical path (fetch -> extract ->
return) and runs as low-priority background work, so it must be —

  1. **pure / deterministic** — same HTML -> same fingerprint, with no shared mutable state, so
     concurrent computations can't corrupt each other;
  2. **parallelizable** — running across a thread pool yields results identical to serial (lxml
     releases the GIL during parse, so threads give real structural parallelism);
  3. **async-offloadable** — ``asyncio.to_thread(PageFingerprint.of, html)`` runs WITHOUT blocking
     the event loop that the extraction/response path is using.

These tests lock those three properties; ``tests/benchmarks/test_fingerprint_bench.py`` pins the cost.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from yosoi.generalization.fingerprint import PageFingerprint


def _page(seed: int, rows: int) -> str:
    """A deterministic listing page; ``seed`` varies the template, ``rows`` the content volume."""
    cards = ''.join(
        f'<article class="card s{seed}"><h3><a href="/i/{i}">Item {i}</a></h3>'
        f'<p class="price">£{i}.00</p><span class="meta">m{i}</span></article>'
        for i in range(rows)
    )
    return (
        f'<!DOCTYPE html><html lang="en"><head><title>seed {seed}</title></head>'
        '<body><header><nav><a href="/">home</a></nav></header>'
        f'<main><section class="grid"><ol class="row">{cards}</ol></section></main>'
        '<footer><p>footer</p></footer></body></html>'
    )


_BIG = _page(7, 800)  # a single heavy page so async offload spans a real wall-clock window


@pytest.fixture
def corpus() -> dict[str, str]:
    """A small, deterministic, network-free multi-shape corpus."""
    return {
        'A-small': _page(1, 8),
        'A-large': _page(1, 400),  # same template as A-small, more rows
        'B': _page(2, 30),  # a different template family
        'C-article': (
            '<!DOCTYPE html><html lang="en"><head><title>x</title></head>'
            '<body><header><nav><a>h</a></nav></header><main><article>'
            + ''.join(f'<p>para {i}</p>' for i in range(50))
            + '</article></main><footer>f</footer></body></html>'
        ),
    }


@pytest.fixture
def fingerprints(corpus: dict[str, str]) -> dict[str, PageFingerprint]:
    return {label: PageFingerprint.of(html) for label, html in corpus.items()}


# ── helpers run inside worker threads (must be top-level, picklable, stateless) ──────────────
def _skeleton_of(html: str) -> frozenset[str]:
    return PageFingerprint.of(html).skeleton


def _same_shape(pair: tuple[PageFingerprint, PageFingerprint]) -> bool:
    return pair[0].similarity(pair[1]).same_shape


# ── (1) purity / determinism / no shared state ───────────────────────────────────────────────
def test_of_is_deterministic(corpus: dict[str, str]) -> None:
    for html in corpus.values():
        a, b = PageFingerprint.of(html), PageFingerprint.of(html)
        assert a.skeleton == b.skeleton
        assert a.semantic == b.semantic


def test_feature_sets_are_immutable(fingerprints: dict[str, PageFingerprint]) -> None:
    # frozenset layers → a fingerprint can be shared across threads without copying or locking.
    for fp in fingerprints.values():
        assert isinstance(fp.skeleton, frozenset)
        assert isinstance(fp.semantic, frozenset)


def test_interleaving_does_not_leak_state(corpus: dict[str, str]) -> None:
    # Computing other pages between two computes of the same page must not perturb its result.
    target = corpus['A-large']
    first = PageFingerprint.of(target).skeleton
    for other in corpus.values():
        PageFingerprint.of(other)
    assert PageFingerprint.of(target).skeleton == first


# ── (2) parallelizable: thread pool == serial ────────────────────────────────────────────────
def test_threadpool_skeleton_matches_serial(corpus: dict[str, str]) -> None:
    htmls = list(corpus.values()) * 6  # 24 jobs across 8 workers
    serial = [_skeleton_of(h) for h in htmls]
    with ThreadPoolExecutor(max_workers=8) as pool:
        parallel = list(pool.map(_skeleton_of, htmls))
    assert parallel == serial


def test_parallel_similarity_matrix_matches_serial(fingerprints: dict[str, PageFingerprint]) -> None:
    items = list(fingerprints.values())
    pairs = [(a, b) for a in items for b in items]
    serial = [_same_shape(p) for p in pairs]
    with ThreadPoolExecutor(max_workers=8) as pool:
        parallel = list(pool.map(_same_shape, pairs))
    assert parallel == serial


# ── (3) async-offloadable: to_thread does NOT block the event loop ───────────────────────────
async def test_to_thread_offload_keeps_loop_responsive() -> None:
    """Offloading fingerprints via to_thread must leave the event loop free for the response path.

    A heartbeat coroutine counts loop ticks while a batch of heavy fingerprints computes in worker
    threads. If the hashing ran ON the loop it would freeze the heartbeat during each synchronous
    compute; because it is offloaded, the loop keeps ticking — and the results still match serial.
    """
    heavy = [_BIG] * 12
    serial = [PageFingerprint.of(h).skeleton for h in heavy]

    ticks = 0
    stop = False

    async def heartbeat() -> None:
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(0)  # yield; only advances while the loop is actually running

    hb = asyncio.create_task(heartbeat())
    results = await asyncio.gather(*(asyncio.to_thread(PageFingerprint.of, h) for h in heavy))
    stop = True
    await hb

    assert [r.skeleton for r in results] == serial  # correctness preserved off-thread
    assert ticks > 20  # loop stayed live throughout the offloaded compute → not blocked


async def test_gather_many_fingerprints_concurrently() -> None:
    htmls = [_page(s, 60) for s in range(16)]
    serial = [PageFingerprint.of(h).skeleton for h in htmls]
    concurrent = await asyncio.gather(*(asyncio.to_thread(_skeleton_of, h) for h in htmls))
    assert concurrent == serial
