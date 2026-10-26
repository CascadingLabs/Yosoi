"""Owning capture views and explicit retention, without live CI providers."""

import asyncio
import gc
import json
import os

import pytest

from yosoi import _native, search
from yosoi.archive import Archive
from yosoi.cancellation import CancellationToken
from yosoi.documents import Document
from yosoi.policy import Policy, ProviderSelection, Search

URL = "https://www.bing.com/search?q=synthetic+control"
BODY = b"<html><body>synthetic retained payload</body></html>"


def policy():
    return Policy(search=Search(providers=[ProviderSelection(provider="bing")]))


def test_cancelled_capture_modes_start_no_provider_and_preserve_disabled_binding():
    """Exercise the actual native bridge without contacting a fixed provider URL."""

    async def run():
        bound = search.new("synthetic control").bind(policy())
        enabled = bound.with_diagnostic_capture()
        token = CancellationToken()
        token.cancel()
        for binding, capture in [(bound, False), (enabled, False), (bound, True)]:
            response = await binding.send(cancellation=token, capture=capture)
            assert response.termination == "cancelled"
            assert all(not item.diagnostic_captures for item in response.providers)
            assert all(not item.attempts for item in response.providers)
        assert bound._capture is False
        assert enabled._capture is True

    asyncio.run(run())


def test_python_capture_view_owns_controlled_handle_and_excludes_payload(
    monkeypatch, tmp_path
):
    """Isolate Python caching; native Arc ownership has a live opt-in below."""
    authored_policy = policy()
    calls = []

    class ControlledCapture:
        def __init__(self):
            self.doc = Document.html("synthetic-capture", BODY)
            self.document_calls = 0
            self.result = search.replay_document(
                "bing", self.doc, URL, search.SearchReplayPolicy()
            )
            controlled_captures.append(self)

        def metadata(self):
            return json.dumps(
                {
                    "provider": "bing",
                    "request_id": "synthetic-request",
                    "capture_id": "synthetic-capture",
                    "original_provider_page_url": URL,
                    "provider_page_url": URL,
                    "final_url": URL,
                    "http_status": 200,
                    "capture_complete": True,
                    "environment": {"kind": "synthetic"},
                    "replay_policy": search.SearchReplayPolicy().model_dump(
                        mode="json"
                    ),
                    "selected_for_parsing": True,
                    "observed": self.result.model_dump(mode="json"),
                }
            )

        def document(self):
            self.document_calls += 1
            return self.doc._handle

        def replay(self):
            return self.result.model_dump_json()

        async def save(self, root):
            archive = await Archive.open(root)
            reference = await archive.write(self.doc)
            return search.SearchReplay(
                schema_version=1,
                sdk_version="synthetic-control",
                source_revision=None,
                provider="bing",
                adapter_version=None,
                parser_version="synthetic-control",
                profile={},
                request_id="synthetic-request",
                capture_id="synthetic-capture",
                original_provider_page_url=URL,
                provider_page_url=URL,
                final_url=URL,
                http_status=200,
                capture_complete=True,
                environment={"kind": "synthetic"},
                replay_policy=search.SearchReplayPolicy(),
                selected_for_parsing=True,
                document_class=self.doc.document_class,
                document_bytes=self.doc.byte_len,
                document=reference.value,
                observed=self.result.decision(),
            ).model_dump_json()

    class ControlledResponse:
        def __init__(self, enabled):
            self.views = [ControlledCapture()] if enabled else []

        def to_json(self):
            return json.dumps(
                {
                    "request_id": "synthetic-search",
                    "policy_identity": authored_policy.identity().model_dump(
                        mode="json"
                    ),
                    "termination": "completed",
                    "providers": [
                        {
                            "provider": "bing",
                            "identity": {
                                "provider": "bing",
                                "endpoint": None,
                                "adapter_version": None,
                                "parser_version": None,
                            },
                            "profile": {
                                "acquisition": None,
                                "defaults_status": {"status": "exact"},
                                "defaults_version": None,
                                "effective_request_policy": None,
                            },
                            "request_id": "synthetic-request",
                            "recovery_query": None,
                            "attempts": [],
                            "captures": [],
                            "outcome": {
                                "status": "failed",
                                "value": "malformed_response",
                            },
                            "charge": {"status": "unknown"},
                        }
                    ],
                }
            )

        def capture_count(self, provider):
            return len(self.views)

        def capture(self, provider, index):
            return self.views[index]

    class ControlledRequest:
        def __init__(self, query: str):
            self.query = query

        async def send(self, *args, **kwargs):
            calls.append(kwargs["capture"])
            return ControlledResponse(kwargs["capture"])

    controlled_captures: list[ControlledCapture] = []
    monkeypatch.setattr(_native, "SearchCapture", ControlledCapture)
    monkeypatch.setattr(_native, "SearchRequest", ControlledRequest)

    async def run():
        request = search.new("synthetic control")
        bound = request.bind(authored_policy)
        disabled = await bound.send()
        assert not disabled.providers[0].diagnostic_captures
        response = await bound.with_diagnostic_capture().send()
        view = response.providers[0].diagnostic_captures[0]
        assert "diagnostic_captures" not in response.providers[0].model_dump()
        assert "synthetic retained payload" not in view.model_dump_json()
        assert URL not in repr(view)
        del response, request, bound
        gc.collect()
        document = view.document
        assert view.document is document
        assert len(controlled_captures) == 1
        assert controlled_captures[0].document_calls == 1
        assert document.data == BODY
        assert view.replay().decision() == view.observed.decision()
        if os.name == "posix":
            archive = await Archive.open(tmp_path / "saved")
            saved = await view.save(archive)
            assert (await saved.replay(archive)).decision() == view.observed.decision()
        del view
        gc.collect()
        assert document.data == BODY

    asyncio.run(run())
    assert calls == [False, True]


@pytest.mark.skipif(
    os.environ.get("YOSOI_SEARCH_LIVE") != "1",
    reason="explicit one-query live capture acceptance",
)
def test_live_native_capture_keeps_document_after_response_drop(tmp_path):
    """One serial public query; replay/save make no further provider requests."""

    async def run():
        response = (
            await search.new("photosynthesis")
            .bind(policy())
            .with_diagnostic_capture()
            .send()
        )
        captures = response.providers[0].diagnostic_captures
        assert captures, "provider acquisition did not retain replay evidence"
        view = captures[0]
        del response, captures
        gc.collect()
        document = view.document
        assert document.byte_len > 0
        assert view.replay().decision() == view.observed.decision()
        if os.name == "posix":
            archive = await Archive.open(tmp_path / "capture")
            record = await view.save(archive)
            assert (await record.replay(archive)).decision() == view.observed.decision()
        del view
        gc.collect()
        assert document.byte_len == len(document.data)

    asyncio.run(run())
