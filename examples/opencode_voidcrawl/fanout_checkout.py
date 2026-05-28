"""Fan-out experiment (SHELVED): fill the N independent checkout fields concurrently.

FINDING — concurrency is shelved because the fundamental isn't there: voidcrawl's Page
has a single, serial CDP command channel, so firing N evaluate_js calls at one tab via
asyncio.gather collides — measured 9/10 RuntimeError, only the first write lands. The 10
form fields are logically independent, but they all write into ONE tab, so they cannot be
parallelized at the protocol layer. Real fan-out would need N tabs (separate channels),
which is meaningless for a single shared form. The parallel run here therefore FAILS by
design; it is kept as the artifact that demonstrates why. Sequential is the correct path.

    uv run python examples/opencode_voidcrawl/fanout_checkout.py
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from eshop_checkout import _FIELDS, _ORDER_OK, _SKU_URL, _gated_click, _gated_fill
from replay_runtime import execute_plan, open_page
from voidcrawl import BrowserConfig

from yosoi.models.replay import A3Node, ReplayPlan, css, fill, navigate, parallel, role, selector_present


def _bare_fill(label: str, value: str) -> A3Node:
    return fill(f'input[data-label="{label}"]', value, intent=f'fill {label}')


def build_plan(*, fan_out: bool) -> ReplayPlan:
    if fan_out:
        group = parallel(*[_bare_fill(label, value) for label, value in _FIELDS], intent='fill all fields concurrently')
        group.assess = selector_present(css('input[data-label="First name"]'))  # form present, asserted once
        fill_part: list[Any] = [group]
    else:
        fill_part = [_gated_fill(label, value) for label, value in _FIELDS]
    return ReplayPlan(
        target='qscrape.dev/l2/eshop',
        task=f'checkout (fan_out={fan_out})',
        source='scripted',
        nodes=[
            navigate(_SKU_URL, expect=selector_present(role('button', 'Add to Cart'))),
            _gated_click('Add to Cart', 'add', selector_present(role('button', 'Cart (1)'))),
            _gated_click('Cart (1)', 'open cart', selector_present(role('button', 'Proceed to Checkout'))),
            _gated_click('Proceed to Checkout', 'checkout', selector_present(css('input[data-label="First name"]'))),
            *fill_part,
            _gated_click('Place Order', 'place order', _ORDER_OK),
        ],
    )


async def _run(*, fan_out: bool) -> tuple[float, float, str | None]:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    plan = build_plan(fan_out=fan_out)
    t0 = time.monotonic()
    async with open_page(cfg) as page:
        report = await execute_plan(plan, page)
        order = await page.evaluate_js("document.querySelector('strong[data-order-id]')?.getAttribute('data-order-id')")
    return time.monotonic() - t0, report.score, (str(order) if order else None)


async def main() -> None:
    for fan_out in (False, True):
        dt, score, order = await _run(fan_out=fan_out)
        tag = 'PARALLEL fills' if fan_out else 'SEQUENTIAL fills'
        print(f'  {tag:16s}: {dt:5.1f}s  verify {score:.0%}  order={order}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
