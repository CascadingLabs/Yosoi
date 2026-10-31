"""Public Python Search replay uses the native parser and existing Archive."""

import asyncio
import os
from pathlib import Path

import pytest

from yosoi import search
from yosoi.archive import Archive
from yosoi.documents import Document
from yosoi.errors import ArchiveError, SearchError, rust_error_details

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "crates"
    / "yosoi"
    / "src"
    / "internal"
    / "engine"
    / "tests"
    / "fixtures"
    / "search-diagnostics"
)
ORIGINAL_URL = "https://www.bing.com/search?q=history+of+photosynthesis"


def test_replay_policy_accepts_valid_search_output_budget_over_64_mib():
    """Replay accepts budgets valid for a captured live search."""
    policy = search.SearchReplayPolicy(output_limit=67_108_865)
    assert policy.output_limit == 67_108_865


def test_original_and_recovery_documents_have_distinct_parser_decisions():
    """A mismatch and a shorter-query success remain separate replay decisions."""
    policy = search.SearchReplayPolicy()
    original = search.replay_document(
        "bing",
        Document.html(
            "original", (FIXTURES / "bing-synthetic-original.html").read_bytes()
        ),
        ORIGINAL_URL,
        policy,
    )
    recovery = search.replay_document(
        "bing",
        Document.html(
            "recovery", (FIXTURES / "bing-synthetic-recovery.html").read_bytes()
        ),
        "https://www.bing.com/search?q=photosynthesis",
        policy,
    )
    assert original.parser_diagnostic == "query_mismatch"
    assert original.decision().status == "failed"
    assert recovery.decision().status == "results"
    assert recovery.decision().hit_count == 3


def test_saved_document_replays_offline_with_the_same_typed_failure(tmp_path):
    """Restoring an Archive document does not need a provider request or browser."""

    async def run():
        if os.name != "posix":
            with pytest.raises(ArchiveError, match="not certified") as failure:
                await Archive.open(tmp_path / "archive")
            details = rust_error_details(failure.value)
            assert details is not None
            assert details.variant == "UnsupportedPlatform"
            return
        archive = await Archive.open(tmp_path / "archive")
        document = Document.html(
            "original", (FIXTURES / "bing-synthetic-original.html").read_bytes()
        )
        reference = await archive.write(document)
        policy = search.SearchReplayPolicy()
        original = search.replay_document("bing", document, ORIGINAL_URL, policy)
        record = search.SearchReplay(
            schema_version=1,
            sdk_version="synthetic-control",
            source_revision=None,
            provider="bing",
            adapter_version="synthetic-control",
            parser_version="synthetic-control",
            profile={},
            request_id="synthetic-original",
            capture_id="synthetic-capture",
            original_provider_page_url=ORIGINAL_URL,
            provider_page_url=ORIGINAL_URL,
            final_url=ORIGINAL_URL,
            http_status=200,
            capture_complete=True,
            environment={"kind": "synthetic"},
            replay_policy=policy,
            selected_for_parsing=True,
            document_class=document.document_class,
            document_bytes=document.byte_len,
            document=reference.value,
            observed=original.decision(),
        )
        replayed = await record.replay(archive)
        assert replayed.decision() == record.observed
        assert "photosynthesis" not in repr(record)
        for changed, variant, payload in [
            (
                record.model_copy(update={"schema_version": 2}),
                "UnsupportedVersion",
                {"version": 2},
            ),
            (
                record.model_copy(
                    update={
                        "replay_policy": policy.model_copy(update={"output_limit": 0})
                    }
                ),
                "InvalidBounds",
                {},
            ),
            (
                record.model_copy(
                    update={
                        "document": "document:v1:123e4567-e89b-42d3-a456-426614174000"
                    }
                ),
                "Archive",
                None,
            ),
        ]:
            with pytest.raises(SearchError) as failure:
                await changed.replay(archive)
            details = rust_error_details(failure.value)
            assert details is not None
            assert details.variant == variant
            if payload is None:
                assert details.details["source"]["message"] == str(failure.value)
            else:
                assert dict(details.details) == payload

    asyncio.run(run())
