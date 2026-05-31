"""Smoke-test qscrape L2 e-shop through native Yosoi/VoidCrawl AX probing.

This runs the same simple product contract twice against the JS-rendered L2
e-shop: once with Yosoi's VoidCrawl-backed headless fetcher and once with the
headful fetcher. Yosoi's DOMLoader probes the browser-computed accessibility
tree via VoidCrawl (`get_full_ax_tree`) and prefers AX click targets when they
are available.

Run:
    uv run python examples/l2/eshop/opencode_ax_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yosoi as ys
from yosoi.core.fetcher.dom import flows, probes
from yosoi.core.fetcher.dom.ax import AxSnapshot
from yosoi.storage.persistence import SelectorStorage

sys.path.insert(0, str(Path(__file__).parents[2]))

from opencode_server import ensure_opencode_server

URL = os.getenv('QSCRAPE_L2_ESHOP_URL', 'http://qscrape.dev/l2/eshop/')
MODEL = os.getenv('OPENCODE_MODEL', 'openai/gpt-5.3-codex')


class Product(ys.Contract):
    """Simple product data from the qscrape L2 e-shop catalog."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='Product price as a number')


class AxStats:
    """Counts native VoidCrawl AX usage during one Yosoi scrape."""

    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.snapshots_with_targets = 0
        self.click_by_role_calls = 0
        self.max_node_count = 0
        self.max_named_count = 0
        self.sample_targets: list[dict[str, Any]] = []

    def record_snapshot(self, snap: AxSnapshot | None) -> None:
        self.snapshot_calls += 1
        if snap is None:
            return
        self.max_node_count = max(self.max_node_count, snap.node_count)
        self.max_named_count = max(self.max_named_count, snap.named_count)
        if snap.targets:
            self.snapshots_with_targets += 1
        if not self.sample_targets:
            self.sample_targets = [
                {'role': target.role, 'name': target.name, 'nth': target.nth} for target in snap.targets[:8]
            ]

    def record_click_by_role(self) -> None:
        self.click_by_role_calls += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            'snapshot_calls': self.snapshot_calls,
            'snapshots_with_targets': self.snapshots_with_targets,
            'click_by_role_calls': self.click_by_role_calls,
            'max_node_count': self.max_node_count,
            'max_named_count': self.max_named_count,
            'sample_targets': self.sample_targets,
        }


@contextmanager
def instrument_ax(stats: AxStats):
    """Record Yosoi's native AX probe/click path for one run."""
    original_ax_snapshot = probes._ax_snapshot
    original_click_by_role = flows.ClickByRole.run

    async def wrapped_ax_snapshot(tab: Any) -> AxSnapshot | None:
        snap = await original_ax_snapshot(tab)
        stats.record_snapshot(snap)
        return snap

    async def wrapped_click_by_role(self: flows.ClickByRole, tab: Any) -> None:
        stats.record_click_by_role()
        await original_click_by_role(self, tab)

    probes._ax_snapshot = wrapped_ax_snapshot
    flows.ClickByRole.run = wrapped_click_by_role
    try:
        yield
    finally:
        probes._ax_snapshot = original_ax_snapshot
        flows.ClickByRole.run = original_click_by_role


async def run(fetcher_type: str) -> dict[str, Any]:
    """Run one fresh scrape and return extracted items, selectors, and AX stats."""
    stats = AxStats()
    with instrument_ax(stats):
        items = await ys.scrape(
            URL,
            Product,
            model=ys.opencode(MODEL),
            force=True,
            fetcher_type=fetcher_type,
            selector_level=ys.SelectorLevel.XPATH,
            save_formats=(),
            quiet=False,
        )

    selectors = await SelectorStorage().load_selectors('qscrape.dev') or {}
    if not items:
        raise RuntimeError(f'{fetcher_type} run returned no extracted items')
    if not selectors.get('name') or not selectors.get('price'):
        raise RuntimeError(f'{fetcher_type} run did not persist real selectors for Product')
    if stats.max_node_count == 0 or stats.snapshots_with_targets == 0:
        raise RuntimeError(f'{fetcher_type} run did not observe a browser accessibility tree')
    return {
        'fetcher': fetcher_type,
        'item_count': len(items),
        'sample_item': items[0],
        'selectors': selectors,
        'ax': stats.as_dict(),
    }


async def main() -> None:
    """Run headless and headful smoke checks using OpenCode/Codex."""
    results = []
    async with ensure_opencode_server():
        results.extend([await run(fetcher_type) for fetcher_type in ('headless', 'headful')])
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
