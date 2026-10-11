"""Acceptance checks for the public Python browser SDK and installed wheel."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Generator
from contextlib import contextmanager
from importlib.metadata import distribution
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

import yosoi as ys

MAX_TIMEOUT_MS = ((1 << 64) - 1) // 1_000
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "browser-beta.html"
_BROWSER_SKIP = pytest.mark.skipif(
    os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires explicit opt-in with current regular Chrome Stable",
)


def _yield_mode() -> Literal["headless", "headful"]:
    value = os.environ.get("YOSOI_YIELD_MODE", "headless")
    if value not in {"headless", "headful"}:
        raise ValueError("YOSOI_YIELD_MODE must be headless or headful")
    return value


class Cart(ys.Contract):
    """The typed order summary rendered by the deterministic browser fixture."""

    contract_id = "browser_beta_cart"
    root = ys.css("[data-cart]")

    sku: str = ys.Field("Product SKU", locator=ys.css('[data-field="sku"]'))
    quantity: str = ys.Field("Quantity", locator=ys.css('[data-field="quantity"]'))
    total: ys.Money = ys.Field("Cart total", locator=ys.css('[data-field="total"]'))


def test_installed_wheel_is_used_when_requested() -> None:
    """The dedicated wheel run must import code from site packages."""
    if os.environ.get("YOSOI_EXPECT_INSTALLED") != "1":
        pytest.skip("set YOSOI_EXPECT_INSTALLED=1 for installed-wheel provenance")

    installed = distribution("yosoi")
    files = installed.files
    assert files is not None
    recorded = {str(item).replace("\\", "/"): item for item in files}
    package_init = recorded["yosoi/__init__.py"]
    extension = next(
        item
        for name, item in recorded.items()
        if name.startswith("yosoi/_native.") and name.endswith((".so", ".pyd"))
    )

    package_path = Path(ys.__file__).resolve()
    native_path = Path(ys._native.__file__).resolve()
    assert package_path == Path(str(installed.locate_file(package_init))).resolve()
    assert native_path == Path(str(installed.locate_file(extension))).resolve()

    checkout_package = Path(__file__).resolve().parents[1] / "yosoi"
    assert not package_path.is_relative_to(checkout_package)
    assert not native_path.is_relative_to(checkout_package)


def test_public_models_keep_defaults_and_positive_millisecond_bounds() -> None:
    settings = ys.SessionPolicy()
    assert settings.allow_arbitrary_js is False
    assert "evaluate" not in settings.allowed_actions

    bounded = ys.flow([ys.timed(ys.wait(1), timeout_ms=25)]).with_timeout_ms(50)
    wire = json.loads(bounded.to_json())
    assert wire["timeout"] == {"secs": 0, "nanos": 50_000_000}
    assert wire["steps"][0]["timeout"] == {"secs": 0, "nanos": 25_000_000}

    for invalid in (0, -1, True, MAX_TIMEOUT_MS + 1):
        with pytest.raises(ValidationError):
            ys.timed(ys.wait(1), timeout_ms=invalid)
        with pytest.raises(ValidationError):
            ys.flow([]).with_timeout_ms(invalid)


def test_javascript_file_and_module_sources_are_snapshotted_at_construction(
    tmp_path: Path,
) -> None:
    script = tmp_path / "cart-check.js"
    script.write_text(
        "document.documentElement.dataset.check = 'before';", encoding="utf-8"
    )
    file_flow = ys.flow([ys.evaluate_file(str(script))])
    file_snapshot = file_flow.to_json()
    script.write_text(
        "document.documentElement.dataset.check = 'after';", encoding="utf-8"
    )
    assert file_flow.to_json() == file_snapshot

    dependency = tmp_path / "price.mjs"
    entry = tmp_path / "cart.mjs"
    dependency.write_text("export const cents = 2400;\n", encoding="utf-8")
    entry.write_text(
        "import { cents } from './price.mjs';\n"
        "export const total = cents / 100;\n"
        "export const label = 'cart';\n",
        encoding="utf-8",
    )
    module_step = ys.run_module_with_export(str(entry), "total")
    module_flow = ys.flow([module_step])
    module_snapshot = module_flow.to_json()
    selected_label = ys.flow([ys.run_module_with_export(str(entry), "label")]).to_json()
    assert selected_label != module_snapshot

    dependency.write_text("export const cents = 9900;\n", encoding="utf-8")
    entry.write_text(
        "import { cents } from './price.mjs';\n"
        "export const total = cents / 100;\n"
        "export const label = 'changed';\n",
        encoding="utf-8",
    )
    assert module_flow.to_json() == module_snapshot


def test_typed_assertion_requires_local_predicates_before_browser_acquisition() -> None:
    plan = Cart.plan()
    with pytest.raises(ValueError, match="at least one check"):
        ys.assert_all(Cart, plan=plan, checks=[])

    assertion = ys.assert_all(
        Cart,
        plan=plan,
        checks=[ys.check("cart-is-valid", lambda cart: cart.quantity == "2")],
    )
    assert assertion.kind == "assert_all"


def test_require_completed_rejects_uncertain_or_inconsistent_evidence() -> None:
    from yosoi.browser import (
        FlowOutcome,
        FlowStopReason,
        OperationReceipt,
        SkippedStep,
        StepOutcome,
    )

    clean = FlowOutcome(
        version=3,
        flow=ys.flow([]),
        steps=(
            StepOutcome(
                index=0,
                receipt=OperationReceipt(
                    id="observed-step", kind="wait", status="observed"
                ),
            ),
        ),
        terminal="completed",
    )
    assert clean.require_completed() is clean

    uncertain_receipt = OperationReceipt(
        id="uncertain-step", kind="wait", status="unknown", error="settlement lost"
    )
    observed_receipt = OperationReceipt(
        id="observed-step", kind="wait", status="observed"
    )
    invalid_outcomes = (
        clean.model_copy(
            update={"stop_reason": FlowStopReason(flow_path=(0,), cause="failure")}
        ),
        clean.model_copy(
            update={
                "skipped_steps": (
                    SkippedStep(
                        flow_path=(1,),
                        stopped_by=(0,),
                        cause="failure",
                        scope="invocation",
                    ),
                )
            }
        ),
        clean.model_copy(
            update={
                "cleanup": (
                    OperationReceipt(
                        id="uncertain-cleanup",
                        kind="session.close",
                        status="unknown",
                        error="close evidence lost",
                    ),
                )
            }
        ),
        clean.model_copy(
            update={"steps": (StepOutcome(index=0, receipt=uncertain_receipt),)}
        ),
        clean.model_copy(
            update={
                "steps": (
                    StepOutcome(index=0, receipt=observed_receipt, failure="rejected"),
                )
            }
        ),
        clean.model_copy(
            update={
                "steps": (
                    StepOutcome(
                        index=0,
                        receipt=observed_receipt,
                        cancellation="invocation",
                    ),
                )
            }
        ),
    )
    for outcome in invalid_outcomes:
        with pytest.raises(ys.browser.FlowExecutionError) as error:
            outcome.require_completed()
        assert error.value.outcome is outcome


def test_bound_flow_javascript_configuration_is_immutable() -> None:
    recipe = ys.flow([ys.evaluate("1 + 1")])
    bound = recipe.bind(ys.Policy())

    allowed = bound.allow_javascript()

    assert isinstance(allowed, ys.BoundFlow)
    assert allowed is not bound
    assert allowed.policy == bound.policy
    assert bound.flow._javascript_allowed is False
    assert allowed.flow._javascript_allowed is True
    assert recipe._javascript_allowed is False


class _FixtureState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._later_posts = 0
        self._get_paths: dict[str, int] = {}
        self.later_posted = threading.Event()
        self.background_started = threading.Event()
        self.release_background = threading.Event()

    @property
    def later_posts(self) -> int:
        with self._lock:
            return self._later_posts

    def record_later(self) -> None:
        with self._lock:
            self._later_posts += 1
        self.later_posted.set()

    def clear_later(self) -> None:
        with self._lock:
            self._later_posts = 0
        self.later_posted.clear()

    def record_get(self, path: str) -> None:
        with self._lock:
            self._get_paths[path] = self._get_paths.get(path, 0) + 1

    def get_count(self, path: str) -> int:
        with self._lock:
            return self._get_paths.get(path, 0)


@contextmanager
def _browser_fixture() -> Generator[tuple[str, _FixtureState], None, None]:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = _FixtureState()
    body = FIXTURE_PATH.read_bytes()

    class FixtureHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            state.record_get(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0"))
            if size:
                self.rfile.read(size)
            if self.path == "/api/later":
                state.record_later()
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/api/background":
                state.background_started.set()
                state.release_background.wait(timeout=15)
                response = b'{"status":"finished"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/"
    try:
        yield base_url, state
    finally:
        state.release_background.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _browser_settings() -> ys.SessionPolicy:
    return ys.SessionPolicy(
        mode=_yield_mode(),
        maximum_tabs=1,
        execution_concurrency=1,
    )


def _browser_request_policy() -> ys.Policy:
    acquisition = ys.policy.Acquisition.browser(_yield_mode()).with_documents(
        ("rendered_dom",)
    )
    return ys.Policy(page=ys.policy.Page(acquisitions=[acquisition]))


def _stop_on_failure_policy() -> ys.Policy:
    return ys.Policy(
        flow=ys.policy.FlowPolicy(
            on_failure=ys.policy.Stop(scope="invocation"),
            on_cancellation=ys.policy.Stop(scope="invocation"),
        )
    )


def _cart_check() -> Any:
    return ys.assert_all(
        Cart,
        plan=Cart.plan(),
        checks=[
            ys.check(
                "cart-matches-order",
                lambda cart: (
                    cart.sku == "SKU-74"
                    and cart.quantity == "2"
                    and cart.total == ys.Money(minor_units=2400)
                ),
            )
        ],
    )


def _assertion_report(outcome: Any) -> dict[str, Any]:
    step = next(item for item in outcome.steps if item.receipt.kind == "assert_all")
    assert isinstance(step.receipt.result, dict)
    return step.receipt.result


def _assert_cart_response(response: Any) -> None:
    assert response.termination == "completed"
    assert len(response.attempts) == 1
    attempt = response.attempts[0]
    assert attempt.state == "completed"
    assert attempt.acquisition.kind == "browser"
    assert attempt.acquisition.mode == _yield_mode()
    assert len(attempt.documents) == 1
    captured = attempt.documents[0]
    assert captured.requested == "rendered_dom"
    assert captured.outcome.status == "produced"

    documents = response.documents
    assert len(documents) == 1
    assert documents[0].document_class == "rendered_dom"
    records = ys.extract(documents[0], Cart).validate().require_all()
    assert len(records) == 1
    assert records[0].sku == "SKU-74"
    assert records[0].quantity == "2"
    assert records[0].total == ys.Money(minor_units=2400)


async def _assert_no_later_posts(state: _FixtureState) -> None:
    assert not await asyncio.to_thread(state.later_posted.wait, 0.25)
    assert state.later_posts == 0


@_BROWSER_SKIP
def test_managed_and_borrowed_flows_scope_cleanup_and_javascript_permission(
    tmp_path: Path,
) -> None:
    with _browser_fixture() as (url, state):

        async def run() -> None:
            managed = await ys.flow(
                [
                    ys.navigate(url),
                    _cart_check(),
                    ys.click("#record-later"),
                    ys.wait_until(ys.exists("#later-confirmation"), timeout_ms=5_000),
                ]
            ).invoke()
            assert managed.require_completed() is managed
            assert managed.cleanup
            assert all(item.status == "observed" for item in managed.cleanup)
            assert [item.kind for item in managed.cleanup] == [
                "session.release",
                "session.close",
            ]
            assert await asyncio.to_thread(state.later_posted.wait, 5)
            assert state.later_posts == 1
            assert _assertion_report(managed)["passed"] is True

            state.clear_later()
            false_check = ys.assert_all(
                Cart,
                plan=Cart.plan(),
                checks=[ys.check("wrong-sku", lambda cart: cart.sku == "SKU-00")],
            )
            continued = await ys.flow(
                [
                    ys.navigate(url),
                    false_check,
                    ys.click("#record-later"),
                    ys.wait_until(ys.exists("#later-confirmation"), timeout_ms=5_000),
                ]
            ).invoke()
            assert continued.terminal == "completed_with_issues"
            assert len(continued.steps) == 4
            assert not continued.skipped_steps
            assert await asyncio.to_thread(state.later_posted.wait, 5)
            assert _assertion_report(continued)["checks"][0]["passed"] is False

            state.clear_later()
            failed = (
                await ys.flow(
                    [
                        ys.navigate(url),
                        false_check,
                        ys.click("#record-later"),
                        ys.wait_until(
                            ys.exists("#later-confirmation"), timeout_ms=5_000
                        ),
                    ]
                )
                .bind(_stop_on_failure_policy())
                .invoke()
            )
            assert failed.terminal == "failed"
            assert len(failed.steps) == 2
            assert failed.skipped_steps
            with pytest.raises(ys.browser.FlowExecutionError) as failure:
                failed.require_completed()
            assert failure.value.outcome is failed
            report = _assertion_report(failed)
            assert report["passed"] is False
            assert report["checks"][0]["passed"] is False
            await _assert_no_later_posts(state)

            def broken_predicate(cart: Any) -> bool:
                del cart
                raise RuntimeError("predicate could not evaluate")

            exceptional = ys.assert_all(
                Cart,
                plan=Cart.plan(),
                checks=[ys.check("raises", broken_predicate)],
            )
            exception_outcome = (
                await ys.flow(
                    [
                        ys.navigate(url),
                        exceptional,
                        ys.click("#record-later"),
                        ys.wait_until(
                            ys.exists("#later-confirmation"), timeout_ms=5_000
                        ),
                    ]
                )
                .bind(_stop_on_failure_policy())
                .invoke()
            )
            assert exception_outcome.terminal == "failed"
            assert len(exception_outcome.steps) == 2
            assert exception_outcome.skipped_steps
            exception_report = _assertion_report(exception_outcome)
            assert exception_report["passed"] is False
            assert exception_report["checks"][0]["passed"] is None
            assert exception_report["checks"][0]["error"] == {
                "evaluation_failed": {"message": "predicate could not evaluate"}
            }
            with pytest.raises(ys.browser.FlowExecutionError) as exception:
                exception_outcome.require_completed()
            assert exception.value.outcome is exception_outcome
            await _assert_no_later_posts(state)

            script = tmp_path / "managed-source.js"
            script.write_text("40 + 2", encoding="utf-8")
            file_step = ys.evaluate_file(str(script))
            dependency = tmp_path / "managed-values.mjs"
            module = tmp_path / "managed-entry.mjs"
            dependency.write_text("export const answer = 42;\n", encoding="utf-8")
            module.write_text(
                "import { answer } from './managed-values.mjs';\n"
                "export const selected = answer;\n"
                "export const ignored = 7;\n",
                encoding="utf-8",
            )
            module_step = ys.run_module_with_export(str(module), "selected")
            script.write_text("0", encoding="utf-8")
            dependency.write_text("export const answer = 0;\n", encoding="utf-8")

            js_managed = (
                await ys.flow(
                    [
                        ys.navigate(url),
                        ys.evaluate(
                            "document.documentElement.dataset.managed = 'yes'; 42"
                        ),
                        file_step,
                        module_step,
                    ]
                )
                .allow_javascript()
                .bind(ys.Policy())
                .invoke()
            )
            assert js_managed.require_completed() is js_managed
            assert js_managed.steps[-1].receipt.result == 42
            assert js_managed.steps[-2].receipt.result == 42
            assert js_managed.steps[-3].receipt.result == 42

            # A Flow flag cannot add capability to caller-owned Work. Session
            # settings are the explicit grant for borrowed JavaScript.
            retained_work = None
            retained_session = None
            with pytest.raises(RuntimeError, match="context exit probe"):
                async with ys.session(
                    policy=_stop_on_failure_policy(), settings=_browser_settings()
                ) as session:
                    retained_session = session
                    async with session.work() as work:
                        borrowed = (
                            await ys.flow(
                                [
                                    ys.navigate(url),
                                    ys.evaluate(
                                        "document.documentElement.dataset.borrowed = "
                                        "'yes'; 42"
                                    ),
                                    ys.click("#record-later"),
                                    ys.wait_until(
                                        ys.exists("#later-confirmation"),
                                        timeout_ms=5_000,
                                    ),
                                ]
                            )
                            .allow_javascript()
                            .invoke(work)
                        )
                        assert borrowed.terminal == "failed"
                        assert len(borrowed.steps) == 2
                        assert borrowed.skipped_steps
                        assert borrowed.cleanup == ()
                        await _assert_no_later_posts(state)

                        reused = await ys.flow([ys.navigate(url)]).invoke(work)
                        assert reused.require_completed() is reused
                        retained_work = work
                        raise RuntimeError("context exit probe")

            assert retained_work is not None
            assert retained_work.released is True
            assert retained_session is not None
            assert retained_session.closed is True
            with pytest.raises(ys.browser.BrowserError):
                await ys.flow([ys.navigate(url)]).invoke(retained_work)

            default = ys.SessionPolicy()
            capability_only = ys.SessionPolicy(
                mode=_yield_mode(),
                maximum_tabs=1,
                execution_concurrency=1,
                allow_arbitrary_js=True,
            )
            assert "evaluate" not in capability_only.allowed_actions
            async with ys.session(
                policy=_stop_on_failure_policy(), settings=capability_only
            ) as session:
                async with session.work() as work:
                    denied_by_action = await ys.flow(
                        [
                            ys.navigate(url),
                            ys.evaluate(
                                "document.documentElement.dataset.excess = 'blocked'"
                            ),
                            ys.click("#record-later"),
                        ]
                    ).invoke(work)
                    assert denied_by_action.terminal == "failed"
                    assert len(denied_by_action.steps) == 2
                    assert denied_by_action.skipped_steps
                    await _assert_no_later_posts(state)

            js_settings = ys.SessionPolicy(
                mode=_yield_mode(),
                maximum_tabs=1,
                execution_concurrency=1,
                allow_arbitrary_js=True,
                allowed_actions=(*default.allowed_actions, "evaluate"),
            )
            async with ys.session(policy=ys.Policy(), settings=js_settings) as session:
                async with session.work() as work:
                    permitted = await ys.flow(
                        [
                            ys.navigate(url),
                            ys.evaluate(
                                "document.documentElement.dataset.borrowed = "
                                "'allowed'; 7"
                            ),
                        ]
                    ).invoke(work)
                    assert permitted.require_completed() is permitted
                    assert permitted.steps[-1].receipt.result == 7
                    assert permitted.cleanup == ()

        asyncio.run(run())


@_BROWSER_SKIP
def test_page_requests_reuse_session_work_and_keep_cancellation_scoped() -> None:
    from yosoi.errors import RequestError, rust_error_details

    with _browser_fixture() as (url, state):

        async def run() -> None:
            browser_policy = _browser_request_policy()
            request = ys.request.new(url)
            async with ys.session(
                policy=browser_policy, settings=_browser_settings()
            ) as session:
                session_response = await request.in_session(session).send()
                _assert_cart_response(session_response)
                assert session.closed is False

                async with session.work() as work:
                    retained_response = await request.with_work(work).send()
                    _assert_cart_response(retained_response)
                    assert work.released is False

                    bound_response = await (
                        request.bind(browser_policy).with_work(work).send()
                    )
                    _assert_cart_response(bound_response)
                    assert work.released is False

                    direct_target = f"{url}direct-http-probe"
                    direct_policy = ys.Policy(
                        page=ys.policy.Page(
                            acquisitions=[ys.policy.Acquisition.direct_http()]
                        )
                    )
                    with pytest.raises(RequestError) as incompatible:
                        await (
                            ys.request.new(direct_target)
                            .bind(direct_policy)
                            .with_work(work)
                            .send()
                        )
                    incompatible_details = rust_error_details(incompatible.value)
                    assert incompatible_details is not None
                    assert (
                        incompatible_details.rust_type == "yosoi::session::SessionError"
                    )
                    assert incompatible_details.variant == "Unsupported"
                    assert state.get_count("/direct-http-probe") == 0
                    assert work.released is False

                    cancelled_target = f"{url}cancelled-request-probe"
                    cancellation = ys.CancellationToken()
                    cancellation.cancel()
                    with pytest.raises(RequestError) as cancelled:
                        await (
                            ys.request.new(cancelled_target)
                            .with_work(work)
                            .send(cancellation=cancellation)
                        )
                    cancellation_details = rust_error_details(cancelled.value)
                    assert cancellation_details is not None
                    assert (
                        cancellation_details.rust_type == "yosoi::session::SessionError"
                    )
                    assert cancellation_details.variant == "Cancelled"
                    assert cancellation.cancelled is True
                    assert state.get_count("/cancelled-request-probe") == 0
                    assert work.released is False

                    reused_flow = await ys.flow([_cart_check()]).invoke(work)
                    assert reused_flow.require_completed() is reused_flow
                    assert _assertion_report(reused_flow)["passed"] is True
                    assert work.released is False
                    await _assert_no_later_posts(state)

                assert work.released is True
                assert session.closed is False

            assert session.closed is True

        asyncio.run(run())


@_BROWSER_SKIP
def test_cancellation_preserves_until_scope_and_stops_later_dispatch() -> None:
    with _browser_fixture() as (url, state):

        async def run() -> None:
            token = ys.CancellationToken()
            async with ys.session(
                policy=_stop_on_failure_policy(), settings=_browser_settings()
            ) as session:
                async with session.work() as work:
                    flow = ys.flow(
                        [
                            ys.navigate(url),
                            ys.click("#start-background").until(
                                ys.visible("#never-visible")
                            ),
                            ys.click("#record-later"),
                        ]
                    )
                    pending = asyncio.create_task(flow.invoke(work, cancellation=token))
                    started = await asyncio.to_thread(state.background_started.wait, 10)
                    assert started, "fixture trigger did not reach the loopback server"
                    token.cancel()
                    state.release_background.set()
                    outcome = await asyncio.wait_for(pending, timeout=10)

                    assert outcome.terminal in {"cancelled", "unknown"}
                    assert len(outcome.steps) == 2
                    receipt = outcome.steps[-1].receipt
                    assert receipt.kind == "until"
                    assert receipt.status in {"rejected", "unknown"}
                    report = receipt.until_report()
                    assert report is not None
                    assert report.termination in {"cancelled", "unavailable"}
                    assert report.scope.session_id
                    assert report.scope.tab_id
                    assert report.scope.document_epoch > 0
                    assert report.trigger is not None
                    assert report.trigger.kind == "click"
                    assert report.trigger.status in {"observed", "unknown"}
                    if report.trigger.status == "unknown":
                        assert report.trigger.error
                    else:
                        assert isinstance(report.trigger.result, dict)
                        assert report.trigger.result["started_at_unix_us"] > 0
                    if report.termination == "unavailable":
                        assert receipt.status == "unknown"
                        assert report.error == (
                            "observation cleanup did not establish safe settlement"
                        )
                    await _assert_no_later_posts(state)
                    with pytest.raises(ys.browser.FlowExecutionError):
                        outcome.require_completed()

        asyncio.run(run())


@_BROWSER_SKIP
def test_predicate_cancellation_keeps_event_loop_responsive_and_work_reusable() -> None:
    with _browser_fixture() as (url, state):

        async def run() -> None:
            started = threading.Event()
            release_predicate = threading.Event()
            finished = threading.Event()

            def blocked_predicate(cart: Any) -> bool:
                del cart
                started.set()
                try:
                    return release_predicate.wait(timeout=5)
                finally:
                    finished.set()

            token = ys.CancellationToken()
            async with ys.session(
                policy=ys.Policy(), settings=_browser_settings()
            ) as session:
                async with session.work() as work:
                    blocking_assertion = ys.assert_all(
                        Cart,
                        plan=Cart.plan(),
                        checks=[ys.check("wait-for-release", blocked_predicate)],
                    )
                    flow = ys.flow(
                        [
                            ys.navigate(url),
                            blocking_assertion,
                            ys.click("#record-later"),
                        ]
                    )
                    pending = asyncio.create_task(flow.invoke(work, cancellation=token))
                    assert await asyncio.to_thread(started.wait, 3), (
                        "typed assertion predicate did not start"
                    )

                    event_loop_tick = asyncio.Event()
                    asyncio.get_running_loop().call_soon(event_loop_tick.set)
                    await asyncio.wait_for(event_loop_tick.wait(), timeout=1)

                    token.cancel()
                    try:
                        outcome = await asyncio.wait_for(
                            asyncio.shield(pending), timeout=1
                        )
                        assert not release_predicate.is_set()
                        assert not finished.is_set()
                        assert outcome.terminal in {"cancelled", "unknown"}
                        assert len(outcome.steps) == 2
                        assert outcome.skipped_steps
                        with pytest.raises(ys.browser.FlowExecutionError):
                            outcome.require_completed()
                        await _assert_no_later_posts(state)
                    finally:
                        release_predicate.set()
                        assert await asyncio.wait_for(
                            asyncio.to_thread(finished.wait, 3), timeout=4
                        )
                        if not pending.done():
                            await asyncio.wait_for(asyncio.shield(pending), timeout=4)
                        await _assert_no_later_posts(state)

                    assert work.released is False
                    reused = await ys.flow([ys.navigate(url)]).invoke(work)
                    assert reused.require_completed() is reused
                    assert work.released is False

        asyncio.run(run())


@_BROWSER_SKIP
def test_cancelled_session_acquisition_and_pre_dispatch_leave_no_effects() -> None:
    with _browser_fixture() as (url, state):

        async def run() -> None:
            acquisition = ys.CancellationToken()
            acquisition.cancel()
            session = ys.session(
                policy=ys.Policy(),
                settings=_browser_settings(),
                cancellation=acquisition,
            )
            with pytest.raises(ys.browser.BrowserError, match="(?i)cancel"):
                async with session:
                    pytest.fail("cancelled acquisition unexpectedly succeeded")

            dispatch = ys.CancellationToken()
            dispatch.cancel()
            try:
                result = await ys.flow(
                    [ys.navigate(url), ys.click("#record-later")]
                ).invoke(cancellation=dispatch)
            except ys.browser.BrowserError as error:
                assert "cancel" in str(error).lower()
            else:
                assert result.terminal in {"cancelled", "unknown"}
                assert all(step.receipt.kind != "click" for step in result.steps)
                with pytest.raises(ys.browser.FlowExecutionError):
                    result.require_completed()
            await _assert_no_later_posts(state)

        asyncio.run(run())
