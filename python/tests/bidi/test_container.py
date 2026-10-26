"""Black-box network policy and dispatch faults against the installed Moli SDK."""

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

import pytest

from yosoi.browser import (
    BrowserCleanupError,
    BrowserConfig,
    BrowserError,
    Evaluate,
    Flow,
    JsonMatch,
    Navigate,
    Screenshot,
    Session,
    SessionPolicy,
    response,
)
from yosoi.cancellation import CancellationToken
from yosoi.policy import Acquisition, Page, Policy

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_BIDI_CONTAINER_TESTS") != "1",
    reason="requires the test-only Moli Compose project",
)
REDIRECT = "http://[2001:2:0:b1d1::2]:8080/cgi-bin/request.cgi?url="


def fixture_command(*arguments):
    return ["docker", "exec", os.environ["YOSOI_BIDI_FIXTURE_CONTAINER"], *arguments]


def hits(marker, record="hits"):
    result = subprocess.run(
        fixture_command("cat", f"/state/{record}"),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0 or "No such file" in result.stderr
    return sum(marker in line for line in result.stdout.splitlines())


@asynccontextmanager
async def client(endpoint, private=True):
    policy = Policy(
        browser=BrowserConfig(
            engine="moli",
            endpoint=endpoint,
            moli_profile="layout",
            moli_resources=True,
            moli_allow_private_networks=private,
        ),
        page=Page(
            acquisitions=[Acquisition.browser().with_documents(["rendered_dom"])]
        ),
        default_action_timeout_ms=30_000,
    )
    settings = SessionPolicy(
        allow_arbitrary_js=True,
        allowed_actions=(*SessionPolicy().allowed_actions, "evaluate"),
        operation_timeout_ms=30_000,
    )
    async with Session(policy=policy, settings=settings) as session:
        async with session.work() as work:
            yield work


async def evaluate(work, source):
    outcome = await work.run(Flow(steps=(Evaluate(source=source),)))
    assert outcome.terminal == "completed"
    return outcome.steps[-1].receipt.result


def test_selected_body_watch_cleanup_preserves_a_container_peer(tmp_path):
    async def capture(work, marker):
        url = f"http://fixture:8080/cgi-bin/request.cgi?nonce={marker}&kind=json"
        source = (
            "async function () { await new Promise(resolve=>setTimeout(resolve,20)); "
            f"return fetch({json.dumps(url)}).then(r=>r.json()); }}"
        )
        outcome = await work.run(
            Flow(
                steps=(
                    Evaluate(source=source).until(
                        response(
                            url,
                            status=200,
                            json_matches=(
                                JsonMatch(pointer="/nonce", value=marker),
                                JsonMatch(pointer="/status", value="captured"),
                            ),
                        )
                    ),
                )
            )
        )
        assert outcome.terminal == "completed", outcome.steps[-1].receipt.model_dump()
        report = outcome.steps[-1].receipt.until_report()
        assert report is not None and report.termination == "satisfied"
        assert report.scope.protocol == "bidi" and report.scope.loader_id is None
        assert hits(marker) == 1
        (tmp_path / f"body-{marker}.json").write_text(
            outcome.model_dump_json(), encoding="utf-8"
        )

    async def run():
        endpoint = os.environ["YOSOI_MOLI_ENDPOINT"]
        url = os.environ["YOSOI_BIDI_FIXTURE_URL"]
        async with client(endpoint) as peer:
            await peer.run(Flow(steps=(Navigate(url=url),)))
            async with client(endpoint) as first:
                await first.run(Flow(steps=(Navigate(url=url),)))
                await capture(first, uuid.uuid4().hex)
            await capture(peer, uuid.uuid4().hex)

    asyncio.run(run())


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize(
    "case", ["direct", "fetch", "image", "iframe", "redirect", "large", "timeout"]
)
def test_network_policy(allowed, case, tmp_path):
    async def run():
        marker = uuid.uuid4().hex
        kind = case if case in {"image", "large", "timeout"} else "small"
        url = f"http://fixture:8080/cgi-bin/request.cgi?nonce={marker}&kind={kind}"
        target = REDIRECT + quote(url, safe="") if case == "redirect" else url
        endpoint = os.environ[
            "YOSOI_MOLI_ENDPOINT" if allowed else "YOSOI_MOLI_BLOCKED_ENDPOINT"
        ]
        async with client(endpoint, allowed) as work:
            if case == "direct":
                steps = (Navigate(url=target),)
            elif case in {"image", "iframe"}:
                tag = "img" if case == "image" else "iframe"
                source = f"""(()=>{{window.networkResult=new Promise(resolve=>{{
                    const node=document.createElement({json.dumps(tag)});let timer;
                    const done=event=>{{clearTimeout(timer);resolve({{event}})}};
                    node.onload=()=>done('load');node.onerror=()=>done('error');
                    node.src={json.dumps(target)};document.body.append(node);
                    timer=setTimeout(()=>done('deadline'),3000);
                }});return true}})()"""
                steps = (
                    Evaluate(source=source),
                    Screenshot(),
                    Evaluate(source="window.networkResult"),
                )
            else:
                source = (
                    f"fetch({json.dumps(target)}).then(async r=>"
                    "({ok:true,length:(await r.text()).length}))"
                    ".catch(e=>({ok:false,message:e.message}))"
                )
                steps = (Evaluate(source=source),)
            started = time.perf_counter()
            outcome = await work.run(Flow(steps=steps))
            elapsed = time.perf_counter() - started
        value = outcome.steps[-1].receipt.result
        count = hits(marker)
        (tmp_path / "result.json").write_text(
            json.dumps(
                {
                    "allowed": allowed,
                    "case": case,
                    "fixture_hits": count,
                    "elapsed_seconds": elapsed,
                    "terminal": outcome.terminal,
                    "receipts": [
                        {
                            "kind": step.receipt.kind,
                            "status": step.receipt.status,
                            "result": step.receipt.result,
                            "error": step.receipt.error,
                        }
                        for step in outcome.steps
                    ],
                },
                indent=2,
            )
        )
        assert count == (1 if allowed else 0)
        if case == "redirect":
            assert hits(marker, "redirects") == 1
        if not allowed and case == "direct":
            assert outcome.terminal != "completed"
            return
        assert outcome.terminal == "completed"
        if case in {"fetch", "redirect", "large", "timeout"}:
            assert isinstance(value, dict)
            assert value["ok"] is (allowed and case not in {"large", "timeout"})
            if value["ok"]:
                assert value["length"] == 3
            elif allowed and case == "large":
                assert (
                    "response exceeded configured limit of 16777216" in value["message"]
                )
            elif allowed:
                assert "[28] Timeout was reached" in value["message"]
                active = re.search(r"active=(\d+)ms", value["message"])
                assert active and 14_900 <= int(active.group(1)) <= 15_100
                assert 14 <= elapsed <= 18

    asyncio.run(run())


@asynccontextmanager
async def proxy(endpoint):
    target = urlsplit(endpoint)
    writers, tasks = set(), set()

    async def accept(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        upstream = None
        try:
            remote, upstream = await asyncio.open_connection(
                target.hostname, target.port
            )
            writers.update((writer, upstream))

            async def copy(source, destination):
                try:
                    while data := await source.read(65_536):
                        destination.write(data)
                        await destination.drain()
                finally:
                    destination.close()

            async with asyncio.TaskGroup() as group:
                group.create_task(copy(reader, upstream))
                group.create_task(copy(remote, writer))
        except (OSError, ExceptionGroup):
            pass
        finally:
            for connection in (writer, upstream):
                if connection is not None:
                    connection.close()
                    writers.discard(connection)
            tasks.discard(task)

    def disconnect():
        for writer in tuple(writers):
            writer.close()

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    try:
        yield f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/session", disconnect
    finally:
        server.close()
        disconnect()
        async with asyncio.timeout(3):
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
            await server.wait_closed()


@pytest.mark.parametrize("case", ["before", "cancel", "disconnect"])
def test_dispatch_fault(case, tmp_path):
    # A deliberately uncertain close keeps the client's global capacity fenced.
    # Isolate that runtime, not the shared server or the surviving peer client.
    if os.environ.get("YOSOI_BIDI_FAULT_CHILD") != case:
        subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "-q",
                f"{__file__}::test_dispatch_fault[{case}]",
                "--basetemp",
                str(tmp_path / "client"),
            ],
            env=os.environ | {"YOSOI_BIDI_FAULT_CHILD": case},
            check=True,
            timeout=45,
        )
        return

    async def run():
        endpoint = os.environ["YOSOI_MOLI_ENDPOINT"]
        marker = uuid.uuid4().hex
        fifo = f"/state/notify-{marker}"
        cleanup = []
        async with (
            asyncio.timeout(30),
            client(endpoint) as peer,
            proxy(endpoint) as (proxied, cut),
        ):
            assert await evaluate(peer, "window.sentinel='alive';true") is True
            target = client(proxied if case == "disconnect" else endpoint)
            work = await target.__aenter__()
            observer = None
            try:
                token = CancellationToken()
                kind = "small" if case == "before" else "signal"
                url = f"http://fixture:8080/cgi-bin/request.cgi?kind={kind}&channel={marker}&nonce={marker}"
                if case == "before":
                    token.cancel()
                else:
                    subprocess.run(
                        fixture_command("mkfifo", fifo), check=True, timeout=5
                    )
                    observer = await asyncio.create_subprocess_exec(
                        *fixture_command("cat", fifo),
                        stdout=asyncio.subprocess.PIPE,
                    )
                source = (
                    f"fetch({json.dumps(url)}).catch(()=>null);"
                    + "new Promise(r=>setTimeout(()=>r('late'),1500))"
                )
                pending = asyncio.create_task(
                    work.run(Flow(steps=(Evaluate(source=source),)), cancellation=token)
                )
                if observer is not None:
                    assert observer.stdout is not None
                    async with asyncio.timeout(5):
                        assert (
                            await observer.stdout.readline()
                        ).decode().strip() == marker
                        assert await observer.wait() == 0
                    token.cancel() if case == "cancel" else cut()
                if case == "before":
                    with pytest.raises(BrowserError, match="cancelled before dispatch"):
                        await pending
                else:
                    outcome = await pending
                    assert outcome.terminal == "unknown"
                    assert any(
                        step.receipt.status == "unknown" and step.receipt.browser
                        for step in outcome.steps
                    )
            finally:
                try:
                    await target.__aexit__(None, None, None)
                    cleanup.append("confirmed")
                except (BrowserError, BrowserCleanupError):
                    cleanup.append("unconfirmed remote cleanup")
                if observer is not None and observer.returncode is None:
                    observer.terminate()
                    await observer.wait()
                if case != "before":
                    subprocess.run(
                        fixture_command("rm", "-f", fifo), check=True, timeout=5
                    )
            assert await evaluate(peer, "window.sentinel") == "alive"
        assert hits(marker) == (0 if case == "before" else 1)
        if case == "before":
            assert cleanup == ["confirmed"]
        (tmp_path / "result.json").write_text(
            json.dumps({"case": case, "cleanup": cleanup})
        )

    asyncio.run(run())
