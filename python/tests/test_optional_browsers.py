"""Optional engine declarations and explicit native SDK acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from yosoi import request
from yosoi.archive import Archive, AutomationRecord
from yosoi.browser import (
    BrowserConfig,
    Click,
    EnterText,
    Evaluate,
    Exists,
    Flow,
    Navigate,
    Screenshot,
    Session,
    SessionPolicy,
    WaitUntil,
)
from yosoi.policy import Acquisition, Page, Policy


def test_optional_engine_identity_preserves_legacy_defaults() -> None:
    default = Policy()
    assert default.identity().version == 7
    assert "browser" not in json.loads(default.to_json())
    policy = Policy(browser=BrowserConfig(engine="firefox"))
    assert policy.identity().version == 8
    assert policy.identity() != default.identity()
    assert json.loads(policy.to_json())["browser"]["engine"] == "firefox"
    assert Policy.model_validate_json(policy.to_json()).identity() == policy.identity()
    snapshot = policy.effective_policy()
    policy.browser.engine = "moli"
    assert snapshot.browser.engine == "firefox"
    with pytest.raises(ValidationError):
        snapshot.browser.engine = "moli"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost/session",
        "ws://user:private-token@localhost/session",
        "ws://localhost/session?token=private-token",
        "ws://localhost/session#private-token",
    ],
)
def test_endpoint_validation_redacts_secrets(endpoint: str) -> None:
    with pytest.raises(ValidationError) as error:
        BrowserConfig(engine="moli", endpoint=endpoint)
    assert "private-token" not in str(error.value)


def test_optional_profiles_cannot_be_ignored_or_coerced() -> None:
    with pytest.raises(ValidationError):
        BrowserConfig(engine="firefox", moli_profile="layout")
    with pytest.raises(ValidationError):
        BrowserConfig.model_validate({"engine": "moli", "moli_resources": "yes"})
    with pytest.raises(ValidationError):
        Policy(
            browser=BrowserConfig(engine="moli"),
            page=Page(acquisitions=[Acquisition.browser("headful")]),
        )


@pytest.mark.skipif(
    os.environ.get("YOSOI_BIDI_TESTS") != "1",
    reason="requires explicitly installed admitted optional engines",
)
@pytest.mark.parametrize("engine", ["firefox", "moli"])
def test_native_python_session_and_requests(
    engine: Literal["firefox", "moli"], tmp_path: Path
) -> None:
    body = (Path(__file__).parent / "fixtures" / "optional-browser.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    host = os.environ.get("YOSOI_BIDI_FIXTURE_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = os.environ.get(
        "YOSOI_BIDI_FIXTURE_URL", f"http://{host}:{server.server_port}/"
    )
    endpoint = os.environ.get("YOSOI_MOLI_ENDPOINT") if engine == "moli" else None
    mode = cast(
        Literal["headless", "headful"], os.environ.get("YOSOI_BIDI_MODE", "headless")
    )
    policy = Policy(
        browser=BrowserConfig(
            engine=engine,
            endpoint=endpoint,
            moli_profile="layout" if engine == "moli" else "dom",
            moli_allow_private_networks=engine == "moli",
            moli_resources=engine == "moli"
            and os.environ.get("YOSOI_MOLI_RESOURCES") == "1",
        ),
        page=Page(
            acquisitions=[Acquisition.browser(mode).with_documents(["rendered_dom"])]
        ),
    )

    async def run(archive_record: bool) -> None:
        async with Session(policy=policy) as session:
            async with session.work() as work:
                outcome = await work.run(
                    Flow(
                        steps=(
                            Navigate(url=url),
                            Click(selector="#go"),
                            EnterText(selector="#input", text="native"),
                            WaitUntil(
                                condition=Exists(selector="#ready"), timeout_ms=5_000
                            ),
                            Screenshot(),
                        )
                    )
                )
                assert outcome.terminal == "completed", [
                    (step.receipt.kind, step.receipt.status, step.receipt.error)
                    for step in outcome.steps
                ]
                assert all(step.receipt.status == "observed" for step in outcome.steps)
                for step in outcome.steps:
                    identity = step.receipt.browser
                    assert identity is not None
                    assert identity.engine == engine and identity.protocol == "bidi"
                    assert identity.controller_version is not None
                    assert identity.capability_profile is not None
                    if engine == "firefox":
                        assert identity.reported_headless is (mode == "headless")
                    assert identity.process_owned is (endpoint is None)
                    assert (identity.executable_sha256 is not None) is (
                        endpoint is None
                    )
                    if step.receipt.observation is not None:
                        assert step.receipt.observation.browser == identity
                observation = outcome.steps[-1].receipt.observation
                assert observation is not None
                assert observation.html is not None
                assert 'data-click-trusted="true"' in observation.html
                assert 'data-key-trusted="true"' in observation.html
                assert observation.screenshot_bytes is not None
                assert observation.screenshot_bytes.startswith(b"\x89PNG\r\n\x1a\n")
                response = await request.new(url).bind(policy).with_work(work).send()
                assert len(response.attempts) == 1
                assert response.attempts[0].state == "completed", response.attempts[
                    0
                ].model_dump(mode="json")
                assert len(response.documents) == 1
                assert all(
                    selected.outcome.status == "produced"
                    for attempt in response.attempts
                    for selected in attempt.documents
                )
                record = AutomationRecord.from_flow(f"native-{engine}", outcome)
        if archive_record:
            archive = await Archive.open(tmp_path)
            reference = await archive.write(record)
            restored = await archive.read(reference)
            assert isinstance(restored, AutomationRecord)
            assert restored.operations == record.operations
            assert restored.observations == record.observations
        response = await request.new(url).bind(policy).send()
        assert len(response.attempts) == 1
        assert response.attempts[0].state == "completed", response.attempts[
            0
        ].model_dump(mode="json")
        assert len(response.documents) == 1
        assert all(
            selected.outcome.status == "produced"
            for attempt in response.attempts
            for selected in attempt.documents
        )

    try:
        iterations = int(os.environ.get("YOSOI_BIDI_STRESS_ITERATIONS", "1"))
        assert 1 <= iterations <= 1_000
        elapsed_ms = []
        for index in range(iterations):
            started = time.perf_counter_ns()
            asyncio.run(run(index == 0))
            elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000)
            if iterations > 1 and (index + 1) % 25 == 0:
                print(
                    f"{engine}: {index + 1}/{iterations} verified SDK cycles",
                    flush=True,
                )
        evidence = os.environ.get("YOSOI_BIDI_EVIDENCE_PATH")
        if evidence:
            with Path(evidence).open("x", encoding="utf-8") as output:
                json.dump(
                    {
                        "engine": engine,
                        "source_revision": os.environ.get("YOSOI_BIDI_SOURCE_REVISION"),
                        "cycles": iterations,
                        "flow_steps_per_cycle": 5,
                        "dom_requests_per_cycle": 2,
                        "elapsed_ms": elapsed_ms,
                        "policy_identity": policy.identity().model_dump(),
                        "remote_endpoint": endpoint is not None,
                        "moli_profile": policy.browser.moli_profile,
                        "moli_resources": policy.browser.moli_resources,
                    },
                    output,
                    indent=2,
                )
                output.write("\n")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.skipif(
    os.environ.get("YOSOI_BIDI_TESTS") != "1"
    or not os.environ.get("YOSOI_MOLI_ENDPOINT")
    or not os.environ.get("YOSOI_BIDI_FIXTURE_URL"),
    reason="requires the explicitly started headless Moli acceptance service",
)
def test_container_clients_isolate_state_and_close_only_their_scope() -> None:
    policy = Policy(
        browser=BrowserConfig(
            engine="moli",
            endpoint=os.environ["YOSOI_MOLI_ENDPOINT"],
            moli_profile="layout",
            moli_resources=True,
            moli_allow_private_networks=True,
        ),
        page=Page(
            acquisitions=[Acquisition.browser().with_documents(["rendered_dom"])]
        ),
    )
    defaults = SessionPolicy()
    settings = SessionPolicy(
        allow_arbitrary_js=True, allowed_actions=(*defaults.allowed_actions, "evaluate")
    )
    namespace = "yosoi-isolation-" + uuid.uuid4().hex
    tokens = [uuid.uuid4().hex, uuid.uuid4().hex]
    url = os.environ["YOSOI_BIDI_FIXTURE_URL"]

    async def inspect(work):
        source = (
            f"({{stored:localStorage.getItem({json.dumps(namespace)}),"
            "cookie:document.cookie})"
        )
        result = await work.run(Flow(steps=(Evaluate(source=source),)))
        assert result.terminal == "completed"
        return result.steps[-1].receipt.result

    async def seed(work, token):
        cookie = f"{namespace}={token}; SameSite=Lax; path=/"
        source = (
            f"localStorage.setItem({json.dumps(namespace)},{json.dumps(token)});"
            f"document.cookie={json.dumps(cookie)};true"
        )
        result = await work.run(Flow(steps=(Evaluate(source=source),)))
        assert result.terminal == "completed"

    async def navigate(work):
        result = await work.run(Flow(steps=(Navigate(url=url),)))
        assert result.terminal == "completed"

    async def run():
        async with asyncio.timeout(30):
            async with (
                Session(policy=policy, settings=settings) as first,
                Session(policy=policy, settings=settings) as second,
            ):
                async with first.work() as left, second.work() as right:
                    await asyncio.gather(navigate(left), navigate(right))
                    initial = await asyncio.gather(inspect(left), inspect(right))
                    assert all(
                        value["stored"] is None and namespace not in value["cookie"]
                        for value in initial
                    )
                    await asyncio.gather(seed(left, tokens[0]), seed(right, tokens[1]))
                    await asyncio.gather(navigate(left), navigate(right))
                    stored = await asyncio.gather(inspect(left), inspect(right))
                    for token, value in zip(tokens, stored, strict=True):
                        assert value["stored"] == token
                        assert f"{namespace}={token}" in value["cookie"]
                    await left.release()
                    await first.close()
                    assert (await inspect(right))["stored"] == tokens[1]
                    async with Session(policy=policy, settings=settings) as third:
                        async with third.work() as fresh:
                            await navigate(fresh)
                            value = await inspect(fresh)
                            assert (
                                value["stored"] is None
                                and namespace not in value["cookie"]
                            )

    asyncio.run(run())
