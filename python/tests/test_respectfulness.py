from __future__ import annotations

import asyncio
import json
import re
from typing import Any, cast

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.errors import SearchError


def policy_for(url: str, **constraints: Any) -> ys.Policy:
    return ys.Policy(
        respectfulness=ys.policy.Respectfulness(
            groups=[
                ys.policy.RespectfulnessGroup(
                    id="python-loopback",
                    patterns=["^" + re.escape(url)],
                    concurrency=1,
                    **constraints,
                )
            ]
        )
    )


def test_policy_roundtrip_identity_and_snapshot_are_explicit():
    ordinary = ys.Policy()
    assert "respectfulness" not in json.loads(ordinary.to_json())
    assert ordinary.identity().version == 7
    policy = policy_for("https://example.com/", spacing_ms=100)
    assert policy.identity().version == 9
    restored = ys.Policy.model_validate_json(policy.to_json())
    assert restored.identity() == policy.identity()
    snapshot = policy.snapshot()
    assert snapshot.policy.respectfulness is not None
    with pytest.raises(ValidationError):
        cast(Any, snapshot.policy.respectfulness.groups[0]).spacing_ms = 2
    assert policy.respectfulness is not None
    policy.respectfulness.groups[0].spacing_ms = 200
    assert snapshot.policy.respectfulness.groups[0].spacing_ms == 100


def test_native_regex_and_shared_group_configuration_are_validated():
    with pytest.raises(ValidationError):
        ys.Policy(
            respectfulness=ys.policy.Respectfulness(
                groups=[
                    ys.policy.RespectfulnessGroup(
                        id="bad", patterns=["["], concurrency=1
                    )
                ]
            )
        )


@pytest.mark.parametrize("binding", ["policy_path", "bound_registry"])
def test_requests_share_the_registry_and_reject_before_dispatch(tmp_path, binding):
    async def run():
        calls = 0

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal calls
            await reader.readuntil(b"\r\n\r\n")
            calls += 1
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                b"Content-Length: 2\r\nConnection: close\r\n\r\nhi"
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(handle, "127.0.0.1", 0) as server:
            url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
            policy = policy_for(url, spacing_ms=60_000)
            path = tmp_path / "traffic.jsonl"
            assert policy.respectfulness is not None
            policy.respectfulness.registry_path = str(path)
            registry = ys.registry.Registry(path)
            bound = ys.request.new(url).bind(policy)
            if binding == "bound_registry":
                bound = bound.with_registry(registry)
            first = await bound.send()
            assert first.attempts[0].http_status == 200
            # A fresh binding and independent handle must see the same budget.
            second = await ys.request.new(url).bind(policy).send()
            rejected = [
                event for event in second.respectfulness if event.kind == "rejected"
            ]
            assert rejected and rejected[0].error is not None
            assert rejected[0].error.kind == "limited"
            assert rejected[0].error.reason == "spacing"
            assert calls == 1

    asyncio.run(run())


def test_explicit_retry_retains_the_prior_error_and_charges_again(tmp_path):
    async def run():
        calls = 0

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal calls
            await reader.readuntil(b"\r\n\r\n")
            calls += 1
            writer.write(
                (
                    b"HTTP/1.1 429 Too Many Requests\r\nRetry-After: 0\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
                if calls == 1
                else (
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                    b"Content-Length: 2\r\nConnection: close\r\n\r\nhi"
                )
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(handle, "127.0.0.1", 0) as server:
            url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
            policy = policy_for(
                url,
                cooldown=ys.policy.RespectfulnessCooldown(
                    statuses=[429], fallback_ms=1000
                ),
            )
            assert policy.respectfulness is not None
            policy.respectfulness.registry_path = str(tmp_path / "retry.jsonl")
            policy.respectfulness.retry = ys.policy.RespectfulnessRetry(
                max_attempts=2, statuses=[429], backoff_ms=1
            )
            response = await ys.request.new(url).bind(policy).send()
            assert response.attempts[0].http_status == 200
            assert [
                e.status for e in response.respectfulness if e.kind == "response"
            ] == [429, 200]
            assert sum(e.kind == "admitted" for e in response.respectfulness) == 2
            assert calls == 2

    asyncio.run(run())


def test_browser_search_fails_before_any_provider_work():
    policy = policy_for("https://example.com/")
    with pytest.raises(SearchError, match="per-request respectfulness"):
        ys.search.new("offline preflight").bind(policy).check()
