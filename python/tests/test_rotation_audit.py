from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import yosoi as ys
from yosoi.search import AutoRotationTrace


@pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="Archive format is Unix-only"
)
def test_metadata_only_audit_persists_rejections_and_restores_offline(tmp_path: Path):
    async def run():
        registry = ys.registry.Registry(tmp_path / "registry.jsonl")
        archive = await ys.archive.Archive.open(tmp_path / "archive")
        policy = ys.Policy(
            respectfulness=ys.policy.Respectfulness(
                groups=[
                    ys.policy.RespectfulnessGroup(
                        id="blocked", patterns=["^https://"], blocked=True
                    )
                ]
            )
        )
        response = (
            await ys.search.new("no outbound work")
            .bind(policy)
            .with_registry(registry)
            .send(diagnostic_archive=archive)
        )
        assert response.rotation is not None and response.rotation_ref is not None
        trace = response.rotation
        assert trace.search_request_id == response.request_id
        assert trace.selected_provider is None and trace.transaction is None
        assert trace.cursor_before is None and trace.cursor_after is None
        assert trace.revision_before == trace.revision_after
        assert len(trace.skipped) == 4
        assert all(not provider.captures for provider in response.providers)
        before = registry.snapshot()
        registry.compact()
        assert registry.snapshot() == before
        registry.path.rename(tmp_path / "registry-offline.jsonl")
        reopened = await ys.archive.Archive.open(tmp_path / "archive")
        assert (
            await AutoRotationTrace.read_from(reopened, response.rotation_ref) == trace
        )
        assert not (tmp_path / "registry.jsonl").exists()
        restored = ys.search.SearchResponse.model_validate_json(
            response.model_dump_json()
        )
        assert (
            restored.rotation == trace
            and restored.rotation_ref == response.rotation_ref
        )

    asyncio.run(run())
