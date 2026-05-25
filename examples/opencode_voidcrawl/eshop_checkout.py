"""qscrape eshop — a full checkout as a canonical ReplayPlan, executed + verified, no LLM.

A mock sandbox (mock card/address). The whole transaction is one ReplayPlan: deep-link a
product under 100 GS -> Add to Cart -> cart -> Proceed to Checkout -> fill 10 form fields
-> Place Order -> assert the order-confirmation element. It mixes selector kinds in one
model: **role** selectors for the AX-visible buttons and **css** (`data-label`/`data-sku`)
for the AX-blind product grid and form inputs — exactly what the unified SelectorEntry is
for. Recipe discovered by the recon subagents; locked in here and replayed deterministically.

    uv run python examples/opencode_voidcrawl/eshop_checkout.py   # voidcrawl>=0.3.2 + Chromium
"""

from __future__ import annotations

import asyncio

from replay_runtime import execute_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.models.replay import A3Node, Act, Parallel, ReplayPlan, click, css, fill, navigate, role, selector_present

# Standard Iron Pickaxe — 14.50 GS (< 100), in stock. Deep-link the detail view.
_SKU_URL = 'https://qscrape.dev/l2/eshop/?sku=VM-MIN-001'
_ORDER_OK = selector_present(css('strong[data-order-id]'))  # success: confirmation element
_FIELDS: list[tuple[str, str]] = [
    ('First name', 'Test'),
    ('Last name', 'Buyer'),
    ('Email', 'test@example.com'),
    ('Address', '123 Test Street'),
    ('City', 'Testville'),
    ('Province', 'California'),
    ('Post code', '90210'),
    ('Card number', '4111 1111 1111 1111'),
    ('Expiry', '12/30'),
    ('CVV', '123'),
]


def _gated_click(name: str, intent: str) -> A3Node:
    """Click a button, gated on that button being present (assertion-driven settle)."""
    node = click(role('button', name), intent=intent)
    node.assess = selector_present(role('button', name))
    return node


def _gated_fill(label: str, value: str) -> A3Node:
    """Fill a field, gated on that field's input being present."""
    node = fill(f'input[data-label="{label}"]', value, intent=f'fill {label}')
    node.assess = selector_present(css(f'input[data-label="{label}"]'))
    return node


def build_checkout_plan() -> ReplayPlan:
    """The locked-in checkout flow: role for buttons, css(data-label) for fields.

    Settling is purely assertion-driven — every node waits on its own precondition
    (the button/field it needs), no sleeps. Fills are sequential here; the fan-out
    variant lives in fanout_checkout.py.
    """
    nodes: list[A3Node | Parallel] = [
        # dwell: SPA hydration has no DOM signal — the button is in the AX tree before its
        # click handler is wired, so a presence gate alone would click a dead button.
        navigate(_SKU_URL, dwell=2.5),
        _gated_click('Add to Cart', 'add the <100 GS item to the cart'),
        _gated_click('Cart (1)', 'open the cart'),
        _gated_click('Proceed to Checkout', 'go to the checkout form'),
        *[_gated_fill(label, value) for label, value in _FIELDS],
        _gated_click('Place Order', 'submit the order'),
        A3Node(act=Act(op='wait'), assess=_ORDER_OK, expect=_ORDER_OK, intent='await order confirmation'),
    ]
    return ReplayPlan(
        target='qscrape.dev/l2/eshop',
        task='buy a product under 100 GS and check out',
        source='scripted',
        nodes=nodes,
    )


async def main() -> None:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    plan = build_checkout_plan()
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')
        report = await execute_plan(plan, page)
        order_id = await page.evaluate_js(
            "document.querySelector('strong[data-order-id]')?.getAttribute('data-order-id')"
        )

    passed = sum(r.passed for r in report.results)
    print(f'verify score = {report.score:.0%}  ({passed}/{len(report.results)} nodes)', flush=True)
    for r, node in zip(report.results, plan.nodes, strict=True):
        mark = 'ok ' if r.passed else 'FAIL'
        print(f'  [{mark}] {r.op:9s} {node.intent or ""}{"  <- " + r.detail if r.detail else ""}', flush=True)
    print(f'\norder confirmed: {bool(order_id)}   order_id={order_id}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
