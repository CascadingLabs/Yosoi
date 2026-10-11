"""Compose a browser Flow from application-owned actions and Contract plans.

The application supplies site bindings and a Rust-compiled Plan for its Cart
Contract. This example contains no selectors and does not discover a website.
"""

from __future__ import annotations

from dataclasses import dataclass

import yosoi as ys


class CartContract(ys.Contract):
    """The values the application needs from one cart observation."""

    product_sku: str = ys.Field("The product SKU shown in the cart.")
    quantity: str = ys.Field("The selected quantity shown in the cart.")


@dataclass(frozen=True)
class CheckoutBindings:
    """Site-specific actions, expectations, and a caller-compiled Plan."""

    cart_url: str
    open_cart: ys.browser.Step
    cart_ready: ys.browser.UntilExpectation
    cart_plan: ys.Plan
    expected_sku: str
    place_order: ys.browser.Step
    confirmation_ready: ys.browser.UntilExpectation
    policy: ys.Policy
    session_settings: ys.SessionPolicy


def checkout_flow(site: CheckoutBindings) -> ys.Flow:
    """Build one order flow using the application's existing site bindings."""
    return ys.flow(
        (
            ys.navigate(site.cart_url),
            site.open_cart,
            ys.until(site.cart_ready),
            ys.assert_all(
                CartContract,
                plan=site.cart_plan,
                checks=(
                    ys.check(
                        "cart contains the requested product",
                        lambda cart: cart.product_sku == site.expected_sku,
                    ),
                    ys.check("cart has one item", lambda cart: cart.quantity == "1"),
                ),
            ),
            site.place_order,
            ys.until(site.confirmation_ready),
            ys.screenshot(),
        ),
        timeout_ms=30_000,
        on_failure=ys.policy.Stop(scope="invocation"),
        on_cancellation=ys.policy.Stop(scope="invocation"),
    )


async def checkout_with_managed_browser(site: CheckoutBindings) -> ys.FlowOutcome:
    """Let Yosoi acquire and clean up the browser for this Flow."""
    outcome = await checkout_flow(site).bind(site.policy).invoke()
    return outcome.require_completed()


async def checkout_with_borrowed_work(site: CheckoutBindings) -> ys.FlowOutcome:
    """Borrow one Work lease while the caller retains Session ownership."""
    async with ys.session(
        policy=site.policy, settings=site.session_settings
    ) as browser:
        async with browser.work() as work:
            outcome = await checkout_flow(site).invoke(work)
            return outcome.require_completed()
