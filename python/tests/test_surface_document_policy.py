"""Per-type policies and shared browser evidence through the native binding."""

import asyncio
import json

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi import surface as sf


def test_partial_ax_policy_defaults_and_depth_conversion():
    policy = sf.SurfacePolicy.model_validate({"documents": {"ax": {"max_depth": 2}}})
    assert policy.documents.ax.max_nodes == 100000
    assert policy.documents.ax.limits().overview_depth == 2
    assert policy.documents.dom.max_bytes == 33554432
    assert (
        json.loads(policy.model_dump_json())["documents"]["json"]["max_bytes"]
        == 8388608
    )
    with pytest.raises(ValidationError):
        sf.DocumentPolicies(ax=sf.DocumentPolicy(max_nodes=100001))


def test_native_policy_selects_source_type_and_applies_bytes():
    policies = sf.DocumentPolicies(html=sf.DocumentPolicy(max_bytes=512))
    text = "x" * 600
    with pytest.raises(sf.SurfaceError):
        sf.Surface.with_policy(ys.Document.html("html", f"<p>{text}</p>"), policies)
    index = sf.Surface.with_policy(ys.Document.text("text", text), policies)
    assert index.source_bytes == 600


def test_native_web_reader_honors_policy_and_preserves_network_uncertainty():
    source = {
        "schema": "yosoi.network.v1",
        "events": [
            {"method": "Network.responseReceived", "url": "https://owned.example/api"},
        ],
    }
    index = sf.Surface(ys.Document.from_json("network", json.dumps(source)))
    web = sf.WebSurface(index, "network", sf.DocumentPolicy(response_bytes=1024))
    result = web.read(
        sf.ReadRequest(
            operation=sf.Search(query="owned.example"), budget=sf.Budget(bytes=65536)
        )
    )
    assert result.kind == "page"
    assert not result.data.coverage.complete
    assert result.data.entries
    assert len(result.model_dump_json().encode()) <= 1024
    assert not web.descriptor.controllable


def test_prepared_document_read_cap_survives_shared_reader():
    document = ys.Document.html("many", "<button>Needle</button>" * 30)
    index = sf.Surface.with_policy(
        document,
        sf.DocumentPolicies(
            html=sf.DocumentPolicy(response_bytes=1024),
        ),
    )
    page = index.find("Needle", budget=sf.Budget(bytes=65536, items=100))
    assert len(page.model_dump_json().encode()) <= 1024
    assert page.next is not None
    reader = sf.WebSurface(index, "bounded")
    page = reader.read(
        sf.ReadRequest(
            operation=sf.Search(query="Needle"),
            budget=sf.Budget(bytes=65536, items=100),
        )
    )
    assert len(page.model_dump_json().encode()) <= 1024


def test_browser_typed_reads_reserve_envelope_without_raising_small_budget():
    class RecordingBrowser(sf.BrowserSurface):
        def __init__(self):
            self.commands = []

        async def execute(self, command):
            self.commands.append(command)
            return {
                "kind": "page",
                "data": {
                    "observation": "fixture:observation",
                    "total": 0,
                    "offset": 0,
                    "entries": [],
                    "next": None,
                    "coverage": {"complete": False, "reason": "fixture"},
                },
            }

    browser = RecordingBrowser()
    asyncio.run(
        browser.read(
            "network",
            sf.ReadRequest(
                operation=sf.Overview(),
                budget=sf.Budget(bytes=512),
            ),
        )
    )
    (command,) = browser.commands
    assert command["budget"] == 1024
    assert command["request"]["budget"]["bytes"] == 512
