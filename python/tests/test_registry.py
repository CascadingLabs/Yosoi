from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import yosoi as ys


@pytest.fixture(params=["memory", "jsonl"])
def registry(request: pytest.FixtureRequest, tmp_path: Path) -> ys.registry.Registry:
    if request.param == "jsonl":
        return ys.registry.Registry.jsonl(tmp_path / "registry.jsonl")
    return ys.registry.Registry()


def test_atomic_commit_conflict_and_snapshot_ownership(registry: ys.registry.Registry):
    original = registry.snapshot()
    committed = registry.commit(
        original.revision,
        [ys.registry.Put(key="service", value={"active": 1})],
    )
    assert committed.revision.sequence == original.revision.sequence + 1
    assert committed.entries == {"service": {"active": 1}}
    with pytest.raises(ys.registry.RegistryError) as failure:
        registry.commit(original.revision, [ys.registry.Remove(key="service")])
    assert failure.value.variant == "Conflict"
    assert failure.value.rust_type == "yosoi::registry::RegistryError"
    committed.entries.clear()
    assert registry.snapshot().entries == {"service": {"active": 1}}


def test_failed_batch_does_not_commit_and_noop_keeps_revision(registry):
    original = registry.snapshot()
    with pytest.raises(ys.registry.RegistryError) as failure:
        registry.commit(
            original.revision,
            [
                ys.registry.Put(key="valid", value=True),
                ys.registry.Put(key="", value=1),
            ],
        )
    assert failure.value.variant == "InvalidKey"
    assert registry.snapshot() == original
    assert registry.commit(original.revision, []) == original


def test_registry_identity_prevents_cross_instance_commit(registry):
    unrelated = ys.registry.Registry().snapshot()
    with pytest.raises(ys.registry.RegistryError) as failure:
        registry.commit(unrelated.revision, [])
    assert failure.value.variant == "Conflict"


def test_clones_share_state_and_outlive_original(registry):
    clone = registry.clone()
    original = registry.snapshot()
    del registry
    gc.collect()
    clone.commit(original.revision, [ys.registry.Put(key="alive", value=True)])
    assert clone.snapshot().entries == {"alive": True}


def test_remove_and_compact_preserve_logical_state(registry):
    original = registry.snapshot()
    first = registry.commit(
        original.revision, [ys.registry.Put(key="temporary", value=1)]
    )
    final = registry.commit(first.revision, [ys.registry.Remove(key="temporary")])
    registry.compact()
    assert registry.snapshot() == final
    assert final.entries == {}
    assert ys.registry.Snapshot.model_validate_json(final.model_dump_json()) == final


def test_memory_is_the_default_and_independent_instances_are_isolated():
    first, second = ys.registry.Registry(), ys.registry.Registry()
    assert first.coordination == "instance"
    assert (
        first.snapshot().revision.registry_id != second.snapshot().revision.registry_id
    )


def test_jsonl_is_shared_with_a_new_process_and_survives_compaction(tmp_path):
    path = tmp_path / "shared.jsonl"
    registry = ys.registry.Registry.jsonl(path)
    assert registry.coordination == "local_processes"
    original = registry.snapshot()
    committed = registry.commit(
        original.revision, [ys.registry.Put(key="shared", value=7)]
    )
    code = """
import sys
import yosoi as ys
registry = ys.registry.Registry.jsonl(sys.argv[1])
registry.compact()
print(registry.snapshot().model_dump_json())
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert ys.registry.Snapshot.model_validate_json(child.stdout) == committed
    assert registry.snapshot() == committed
    assert len(path.read_text().splitlines()) == 1


def test_jsonl_recovers_partial_tail_but_rejects_corrupt_committed_record(tmp_path):
    path = tmp_path / "recovery.jsonl"
    registry = ys.registry.Registry.jsonl(path)
    original = registry.snapshot()
    with path.open("ab") as stream:
        stream.write(b'{"version":')
    assert registry.snapshot() == original
    committed = registry.commit(
        original.revision, [ys.registry.Put(key="recovered", value=True)]
    )
    assert ys.registry.Registry.jsonl(path).snapshot() == committed
    with path.open("ab") as stream:
        stream.write(b"invalid\n")
    with pytest.raises(ys.registry.RegistryError) as failure:
        registry.snapshot()
    assert failure.value.variant == "InvalidState"


@pytest.mark.skipif(os.name == "nt", reason="XDG user location is Unix-specific")
def test_global_jsonl_is_opt_in_and_uses_configured_user_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    memory = ys.registry.Registry()
    assert not (tmp_path / "yosoi").exists()
    registry = ys.registry.Registry.global_jsonl()
    path = tmp_path / "yosoi" / "registry.jsonl"
    assert path.exists()
    assert registry.snapshot() == ys.registry.Registry.jsonl(path).snapshot()
    assert memory.coordination == "instance"
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    with pytest.raises(ys.registry.RegistryError) as failure:
        ys.registry.Registry.global_jsonl()
    assert failure.value.variant == "NoGlobalLocation"


def test_public_dtos_roundtrip_without_live_backend_resources(registry):
    snapshot = registry.snapshot()
    assert set(json.loads(snapshot.model_dump_json())) == {"revision", "entries"}
    assert (
        ys.registry.Revision.model_validate_json(snapshot.revision.model_dump_json())
        == snapshot.revision
    )


def test_io_failure_exposes_native_variant_and_source(tmp_path):
    parent = tmp_path / "file"
    parent.write_text("not a directory")
    with pytest.raises(ys.registry.RegistryError) as failure:
        ys.registry.Registry.jsonl(parent / "registry.jsonl")
    assert failure.value.variant == "Io"
    assert failure.value.source_chain


@pytest.mark.parametrize("value", [2**64, -(2**63) - 1, {"nested": [2**100]}])
def test_unrepresentable_json_integers_are_rejected_before_commit(registry, value):
    original = registry.snapshot()
    with pytest.raises(ValueError, match="integers must fit"):
        registry.commit(original.revision, [ys.registry.Put(key="large", value=value)])
    assert registry.snapshot() == original


@pytest.mark.parametrize("value", [2**64 - 1, -(2**63)])
def test_json_integer_boundaries_survive_native_storage_exactly(registry, value):
    original = registry.snapshot()
    committed = registry.commit(
        original.revision, [ys.registry.Put(key="boundary", value=value)]
    )
    assert committed.entries["boundary"] == value
    assert type(committed.entries["boundary"]) is int
    assert registry.snapshot() == committed
