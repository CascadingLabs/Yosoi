import asyncio
import json

import pytest
from pydantic import ValidationError

from yosoi import request
from yosoi.policy import IpFamily, Network, Policy


def test_network_policy_roundtrip_identity_snapshot_and_redaction() -> None:
    default = Policy()
    assert "network" not in json.loads(default.to_json())
    policy = Policy(
        network=Network(
            ip_family="ipv6_only",
            source_address="::1",
            proxy="socks5h://user:secret@[::1]:1080",
        )
    )
    assert policy.identity() != default.identity()
    snapshot = policy.snapshot()
    assert snapshot.policy.network.ip_family == "ipv6_only"
    assert snapshot.effective_policy.network.proxy == policy.network.proxy
    policy.network.proxy = "http://localhost:8080"
    assert snapshot.policy.network.proxy == "socks5h://user:secret@[::1]:1080"
    assert "secret" not in repr(snapshot)
    with pytest.raises(ValidationError):
        snapshot.policy.network.ip_family = "ipv4_only"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    "network",
    [
        Network(ip_family="ipv4_only", source_address="::1"),
        Network(ip_family="ipv6_only", source_address="127.0.0.1"),
        Network(proxy="ftp://localhost:80"),
        Network(proxy="http://localhost:80/path"),
        Network(proxy="http://localhost:80/?query=1"),
    ],
)
def test_network_policy_native_validation(network: Network) -> None:
    with pytest.raises(ValidationError):
        Policy(network=network)


def test_network_source_uses_rust_canonical_ip_and_sparse_json() -> None:
    value = Network(source_address="0:0:0:0:0:ffff:7f00:1")
    assert value.source_address == "::ffff:127.0.0.1"
    assert value.model_dump(mode="json") == {
        "ip_family": "system_default",
        "source_address": "::ffff:127.0.0.1",
    }
    assert Network().model_dump(mode="json") == {"ip_family": "system_default"}
    with pytest.raises(ValidationError):
        Network(source_address="not-an-ip")


def test_invalid_raw_policy_does_not_echo_proxy_credentials() -> None:
    with pytest.raises(ValidationError) as rejected:
        Policy.model_validate(
            {
                "network": {
                    "ip_family": "ipv4_only",
                    "source_address": "::1",
                    "proxy": "http://user:credential-secret@localhost:8080",
                }
            }
        )
    assert "credential-secret" not in str(rejected.value)
    with pytest.raises(ValidationError) as malformed:
        Network.model_validate(
            {"proxy": ["http://user:credential-secret@localhost:8080"]}
        )
    assert "credential-secret" not in str(malformed.value)


@pytest.mark.parametrize(
    "source,family", [("127.0.0.1", "ipv4_only"), ("::1", "ipv6_only")]
)
def test_network_request_observes_bound_source(source: str, family: IpFamily) -> None:
    async def run() -> None:
        observed = asyncio.get_running_loop().create_future()

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                observed.set_result((writer.get_extra_info("peername")[0], head))
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                    b"Content-Length: 15\r\nConnection: close\r\n\r\n<h1>route</h1>\n"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, source, 0)
        try:
            port = server.sockets[0].getsockname()[1]
            host = f"[{source}]" if ":" in source else source
            policy = Policy(network=Network(ip_family=family, source_address=source))
            response = (
                await request.new(f"http://{host}:{port}/route").bind(policy).send()
            )
            attempt = response.attempts[0]
            assert attempt.state == "completed"
            assert attempt.body == b"<h1>route</h1>\n"
            peer, head = await asyncio.wait_for(observed, 5)
            assert peer == source
            assert head.startswith(b"GET /route HTTP/1.1")
            assert response.policy_snapshot.policy.network.source_address == source
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(asyncio.wait_for(run(), 20))
