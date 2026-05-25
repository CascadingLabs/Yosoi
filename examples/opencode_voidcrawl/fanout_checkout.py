"""Fan-out experiment: fill the N independent checkout fields concurrently.

The 10 form fields are independent, so a Parallel group asserts the form is present
ONCE and fans the fills out concurrently (asyncio.gather), vs the sequential plan
where each fill is its own gated node. Times both; both must still place the order.

Note the subtlety: now that settling is assertion-driven (no arbitrary 1s/fill), the
sequential fills are already fast — the first waits for the form, the rest find their
field immediately. So fan-out's win here is expected to be modest; it pays off where
steps have real per-step latency, not instant local writes. This run measures that.

    uv run python examples/opencode_voidcrawl/fanout_checkout.py
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from eshop_checkout import _FIELDS, _ORDER_OK, _SKU_URL, _gated_click, _gated_fill
from replay_runtime import execute_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.models.replay import A3Node, Act, ReplayPlan, css, fill, navigate, parallel, selector_present


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
            navigate(_SKU_URL, dwell=2.5),  # SPA hydration has no DOM signal
            _gated_click('Add to Cart', 'add'),
            _gated_click('Cart (1)', 'open cart'),
            _gated_click('Proceed to Checkout', 'checkout'),
            *fill_part,
            _gated_click('Place Order', 'place order'),
            A3Node(act=Act(op='wait'), assess=_ORDER_OK, expect=_ORDER_OK, intent='confirm'),
        ],
    )


async def _run(*, fan_out: bool) -> tuple[float, float, str | None]:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    plan = build_plan(fan_out=fan_out)
    t0 = time.monotonic()
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')
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
