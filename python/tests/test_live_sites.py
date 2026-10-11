"""Opt-in, bounded installed-SDK stress tests against public live sites.

Selectors here bind specific test sites, not reusable public recipes. No live
accounts or real purchases are used. Qscrape's checkout is a local simulation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

import yosoi as ys

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_LIVE_SITE_TESTS") != "1",
    reason="requires explicit live-site opt-in and regular sandboxed Chrome",
)

BOOKS = "https://books.toscrape.com/"
QUOTES = "https://quotes.toscrape.com/js-delayed/"
SHOP = "https://qscrape.dev/l2/eshop/"
ACTIVE = '[data-slot="product-grid"] [data-fw]:not([hidden])'
CART_ROOT = ", ".join(
    f"[data-slot='product-grid'][data-active-fw='{framework}'] "
    f"[data-fw='{framework}'] [data-component='eshop-cart']"
    for framework in ("react", "vue", "svelte", "solid")
)


class Book(ys.Contract):
    root = ys.css("article.product_pod")
    title: str = ys.Field("The book title", locator=ys.css("h3 a").attribute("title"))
    price: str = ys.Field("The displayed GBP price", locator=ys.css(".price_color"))


class Quote(ys.Contract):
    root = ys.css("body")
    texts: list[str] = ys.Field("Rendered quotations", locator=ys.css(".quote .text"))
    authors: list[str] = ys.Field("Quoted authors", locator=ys.css(".quote .author"))


class Cart(ys.Contract):
    root = ys.css(CART_ROOT)
    total: str = ys.Field(
        "The simulated GS total",
        locator=ys.css("[data-cart-total]").attribute("data-cart-total"),
    )
    skus: list[str] = ys.Field(
        "Product identities", locator=ys.css("[data-sku]").attribute("data-sku")
    )
    quantity: str = ys.Field(
        "Cart quantity", locator=ys.css("[data-qty]").attribute("data-qty")
    )


def _iterations() -> int:
    count = int(os.environ.get("YOSOI_LIVE_ITERATIONS", "3"))
    if not 1 <= count <= 10:
        raise ValueError("live iterations must be in 1..10")
    return count


def _settings() -> ys.SessionPolicy:
    mode = os.environ.get("YOSOI_YIELD_MODE", "headless")
    if mode == "headless":
        return ys.SessionPolicy(mode="headless", execution_concurrency=1)
    if mode == "headful":
        return ys.SessionPolicy(mode="headful", execution_concurrency=1)
    raise ValueError("invalid browser mode")


def _javascript_settings() -> ys.SessionPolicy:
    base = _settings()
    return base.model_copy(
        update={
            "allow_arbitrary_js": True,
            "allowed_actions": (*base.allowed_actions, "evaluate"),
        }
    )


def _select_framework(framework: str) -> Any:
    # Explicit diagnostic selection; never silently retry a shuffled failure.
    selected = json.dumps(framework)
    return ys.evaluate(
        "(() => { const grid=document.querySelector('[data-slot=\"product-grid\"]');"
        f"const fw={selected}; grid.setAttribute('data-active-fw',fw);"
        "for(const node of grid.querySelectorAll('[data-fw]'))"
        "{node.hidden=node.dataset.fw!==fw;} return {selectedFramework:fw}; })()"
    )


def _flow(steps: list[Any]) -> ys.Flow:
    return ys.flow(steps, timeout_ms=60_000, on_failure=ys.Stop(scope="invocation"))


def _record(name: str, value: Any) -> None:
    directory = Path(
        os.environ.get("YOSOI_BROWSER_OUTPUT_DIR", ".generated/live-sites")
    )
    directory.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    (directory / f"{name}.json").write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


async def _invoke(name: str, recipe: ys.Flow, lease: ys.Work | None = None) -> Any:
    started = time.perf_counter()
    try:
        outcome = await recipe.invoke(lease)
    except BaseException as error:
        _record(name, {"error_type": type(error).__name__, "error": str(error)})
        raise
    _record(name, outcome)
    _record(f"{name}-timing", {"elapsed_seconds": time.perf_counter() - started})
    outcome.require_completed()
    return outcome


def _assertion(contract: Any, name: str, predicate: Any) -> Any:
    return ys.assert_all(
        contract, plan=contract.plan(), checks=[ys.check(name, predicate)]
    )


def _ten_quotes(record: Any) -> bool:
    return (
        len(record.texts) == len(record.authors) == 10
        and all(text.strip() for text in record.texts)
        and all(author.strip() for author in record.authors)
    )


@pytest.mark.parametrize("framework", ["react", "vue", "svelte", "solid"])
def test_live_framework_render_diagnostics(framework: str) -> None:
    async def run() -> None:
        async with ys.session(settings=_javascript_settings()) as session:
            async with session.work() as lease:
                outcome = await _flow(
                    [
                        ys.navigate(SHOP),
                        ys.wait_until(
                            ys.exists('[data-slot="product-grid"][data-active-fw]'),
                            15_000,
                        ),
                        _select_framework(framework),
                        ys.wait_until(
                            ys.count_at_least(f"{ACTIVE} article[data-sku]", 1), 15_000
                        ),
                    ]
                ).invoke(lease)
                _record(f"framework-{framework}", outcome)
                # This probe retains unsupported live rendering as a failed
                # observation. It never converts it into a successful checkout.
                if outcome.terminal != "completed":
                    if (
                        outcome.terminal == "failed"
                        and outcome.steps[-1].receipt.kind == "wait_until"
                        and outcome.steps[-1].receipt.error
                        == "condition was not satisfied"
                    ):
                        pytest.xfail(
                            f"{framework}: live product grid did not render; recorded"
                        )
                    outcome.require_completed()
                outcome.require_completed()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("name", "url", "selector"),
    [
        ("books", BOOKS, "article.product_pod h3 a"),
        ("quotes", "https://quotes.toscrape.com/", ".quote .author"),
        ("wikipedia", "https://www.wikipedia.org/", "#searchInput"),
    ],
)
def test_live_managed_ownership(name: str, url: str, selector: str) -> None:
    async def run() -> None:
        outcome = await _invoke(
            f"managed-{name}",
            _flow([ys.navigate(url), ys.wait_until(ys.visible(selector), 15_000)]),
        )
        assert outcome.cleanup
        assert all(receipt.status == "observed" for receipt in outcome.cleanup)

    asyncio.run(run())


def test_live_borrowed_cross_site_pagination_and_typed_requests() -> None:
    async def run() -> None:
        async with ys.session(settings=_settings()) as session:
            async with session.work() as lease:
                for iteration in range(_iterations()):
                    await _invoke(
                        f"quotes-{iteration}",
                        _flow(
                            [
                                ys.navigate(QUOTES),
                                ys.timed(
                                    ys.until(ys.count_at_least(".quote", 10)), 20_000
                                ),
                                _assertion(
                                    Quote,
                                    "rendered-quote",
                                    _ten_quotes,
                                ),
                                ys.click(".next a"),
                                ys.timed(
                                    ys.until(ys.count_at_least(".quote", 10)), 20_000
                                ),
                                _assertion(
                                    Quote,
                                    "second-page-quote",
                                    _ten_quotes,
                                ),
                            ]
                        ),
                        lease,
                    )
                    url = f"{BOOKS}catalogue/page-{iteration + 1}.html"
                    await _invoke(
                        f"books-{iteration}",
                        _flow(
                            [
                                ys.navigate(url),
                                ys.wait_until(
                                    ys.count_at_least("article.product_pod", 20), 15_000
                                ),
                            ]
                        ),
                        lease,
                    )
                    response = await ys.request.new(url).with_work(lease).send()
                    _record(f"books-response-{iteration}", response)
                    assert response.termination == "completed"
                    assert response.documents
                    books = (
                        ys.extract(response.documents[0], Book).validate().require_all()
                    )
                    assert len(books) == 20
                    assert all(
                        book.title.strip() and book.price.startswith("£")
                        for book in books
                    )
                    assert not lease.released
            assert not session.closed
        assert session.closed

    asyncio.run(run())


def test_live_javascript_snapshots_permissions_and_exports(tmp_path: Path) -> None:
    script = tmp_path / "count.js"
    script.write_text("document.querySelectorAll('article.product_pod').length")
    module = tmp_path / "identity.mjs"
    module.write_text("export const host = location.hostname;")
    recipe = _flow(
        [
            ys.navigate(BOOKS),
            ys.evaluate_file(str(script)),
            ys.run_module_with_export(str(module), "host"),
        ]
    )
    script.write_text("-1")
    module.write_text("export const host = 'changed-after-snapshot';")

    async def run() -> None:
        outcome = await _invoke("live-javascript-snapshots", recipe.allow_javascript())
        assert outcome.steps[1].receipt.result == 20
        assert outcome.steps[2].receipt.result == "books.toscrape.com"
        async with ys.session(settings=_settings()) as session:
            async with session.work() as lease:
                await _invoke(
                    "javascript-owner-navigation", _flow([ys.navigate(BOOKS)]), lease
                )
                denied = (
                    await _flow([ys.evaluate("location.hostname")])
                    .allow_javascript()
                    .invoke(lease)
                )
                _record("javascript-borrowed-denied", denied)
                assert denied.terminal == "failed"
                assert denied.steps[0].receipt.status == "rejected"
                await _invoke(
                    "javascript-owner-recovery",
                    _flow(
                        [ys.assert_that(ys.count_at_least("article.product_pod", 20))]
                    ),
                    lease,
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    ("framework", "sku", "quantity", "total"),
    [
        ("react", "VM-MIN-001", 2, "29.00"),
        ("solid", "VM-MIN-003", 3, "19.50"),
    ],
)
def test_live_simulated_checkout_and_failure_stop(
    framework: str, sku: str, quantity: int, total: str
) -> None:
    async def run() -> None:
        for iteration in range(_iterations()):
            label = f"shop-{sku}-{iteration}"
            detail = (
                f'{ACTIVE} [data-component="eshop-product-detail"][data-sku="{sku}"]'
            )
            cart = f'{ACTIVE} [data-component="eshop-cart"]'
            row = f'{cart} [data-sku="{sku}"]'
            checkout = f'{ACTIVE} [data-component="eshop-checkout"]'
            async with ys.session(settings=_javascript_settings()) as session:
                async with session.work() as lease:
                    steps = [
                        ys.navigate(SHOP),
                        ys.wait_until(
                            ys.exists('[data-slot="product-grid"][data-active-fw]'),
                            15_000,
                        ),
                        _select_framework(framework),
                        ys.wait_until(
                            ys.visible(f'{ACTIVE} article[data-sku="{sku}"]'), 15_000
                        ),
                        ys.click(f'{ACTIVE} article[data-sku="{sku}"]'),
                        ys.wait_until(
                            ys.visible(f'{detail} [data-in-stock="true"] + button'),
                            15_000,
                        ),
                        ys.click(f'{detail} [data-in-stock="true"] + button'),
                        ys.wait_until(ys.visible(f'{row} [data-qty="1"]'), 15_000),
                    ]
                    steps.extend(
                        ys.click(f"{row} [data-qty] + button")
                        for _ in range(1, quantity)
                    )
                    steps.append(
                        _assertion(
                            Cart,
                            "correct-cart",
                            lambda record: (
                                record.total == total
                                and record.quantity == str(quantity)
                                and record.skus == [sku]
                            ),
                        )
                    )
                    await _invoke(f"{label}-cart", _flow(steps), lease)
                    failed = await _flow(
                        [
                            _assertion(
                                Cart,
                                "wrong-total",
                                lambda record: record.total == "0.00",
                            ),
                            ys.click(f"{cart} > button:last-of-type"),
                        ]
                    ).invoke(lease)
                    _record(f"{label}-negative", failed)
                    assert failed.terminal == "failed"
                    assert len(failed.steps) == 1 and failed.skipped_steps
                    token = ys.CancellationToken()
                    token.cancel()
                    with pytest.raises(
                        ys.BrowserError, match="cancelled before dispatch"
                    ) as cancelled:
                        await _flow([ys.navigate(BOOKS)]).invoke(
                            lease, cancellation=token
                        )
                    _record(
                        f"{label}-cancelled",
                        {
                            "status": "not_started",
                            "error": str(cancelled.value),
                        },
                    )
                    await _invoke(
                        f"{label}-recovery",
                        _flow(
                            [
                                _assertion(
                                    Cart,
                                    "unchanged-cart",
                                    lambda record: record.total == total,
                                ),
                                ys.click(f"{cart} > button:last-of-type"),
                                ys.wait_until(
                                    ys.visible(
                                        f'{checkout} [data-checkout-total="{total}"]'
                                    ),
                                    15_000,
                                ),
                            ]
                        ),
                        lease,
                    )
                    fields = {
                        "First name": "SDK",
                        "Last name": "Live Test",
                        "Email": "sdk-live-test@example.com",
                        "Address": "12 Test Lane",
                        "City": "Test City",
                        "Province": "Test Province",
                        "Post code": "TEST-001",
                        "Card number": "4111 1111 1111 1111",
                        "Expiry": "12 / 30",
                        "CVV": "123",
                    }
                    await _invoke(
                        f"{label}-confirmed",
                        _flow(
                            [
                                *(
                                    ys.enter_text(
                                        f'{checkout} input[data-label="{key}"]', value
                                    )
                                    for key, value in fields.items()
                                ),
                                ys.click(f"{checkout} div button"),
                                ys.wait_until(
                                    ys.visible(
                                        f'{ACTIVE} [data-component="eshop-confirm"] '
                                        '[data-order-id^="VM-312-"]'
                                    ),
                                    15_000,
                                ),
                            ]
                        ),
                        lease,
                    )
                    assert not lease.released

    asyncio.run(run())
