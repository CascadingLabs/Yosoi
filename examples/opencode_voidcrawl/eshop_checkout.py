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

from replay_runtime import execute_plan, open_page
from voidcrawl import BrowserConfig

from yosoi.models.replay import (
    A3Node,
    Assertion,
    Parallel,
    ReplayPlan,
    click,
    css,
    fill,
    navigate,
    role,
    selector_present,
)

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


def _gated_click(name: str, intent: str, effect: Assertion) -> A3Node:
    """Click a button, gated on its presence (assess), verified by its effect (expect).

    The effect — not mere presence — is how we beat SPA hydration: the button can be in
    the AX tree before its handler is wired, so a presence gate alone would 'succeed' on a
    dead button. We instead poll for what the click *causes* (cart increments, next view
    renders); run_node re-checks until it holds, no sleep.
    """
    node = click(role('button', name), intent=intent)
    node.assess = selector_present(role('button', name))
    node.expect = effect
    return node


def _gated_fill(label: str, value: str) -> A3Node:
    """Fill a field, gated on that field's input being present (the act raises if 0 match)."""
    node = fill(f'input[data-label="{label}"]', value, intent=f'fill {label}')
    node.assess = selector_present(css(f'input[data-label="{label}"]'))
    return node


def build_checkout_plan() -> ReplayPlan:
    """The locked-in checkout flow: role for buttons, css(data-label) for fields.

    Fully event-driven — every act is verified by its effect and every wait is a polled
    assertion, no sleeps anywhere. Each step's `expect` is literally the next step's
    precondition, so the chain self-paces. Fills are sequential here; the (shelved)
    fan-out variant lives in fanout_checkout.py.
    """
    nodes: list[A3Node | Parallel] = [
        navigate(_SKU_URL, expect=selector_present(role('button', 'Add to Cart'))),
        _gated_click('Add to Cart', 'add the <100 GS item to the cart', selector_present(role('button', 'Cart (1)'))),
        _gated_click('Cart (1)', 'open the cart', selector_present(role('button', 'Proceed to Checkout'))),
        _gated_click(
            'Proceed to Checkout', 'go to the checkout form', selector_present(css('input[data-label="First name"]'))
        ),
        *[_gated_fill(label, value) for label, value in _FIELDS],
        _gated_click('Place Order', 'submit the order', _ORDER_OK),  # effect = the confirmation element
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
    async with open_page(cfg) as page:
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
