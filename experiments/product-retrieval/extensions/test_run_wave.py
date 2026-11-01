"""A completed shard is reusable only with matching inputs and intact outputs."""

import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest
import run_wave


def test_wave_runs_serially_and_resumes_only_verified_shards(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    config = {"version": 1}
    (source / "frozen.json").write_text(json.dumps(config))
    (source / "corpus.json").write_text(
        json.dumps({"cases": [{"id": "case-1", "split": "fresh_cross_site"}]})
    )
    (source / "preparation.json").write_text("{}")
    code = source / "implementation/extensions"
    code.mkdir(parents=True)
    (code / "campaign.py").write_text("# frozen experiment")
    model = tmp_path / "model.json"
    model.write_text("{}")
    model.with_suffix(".batches.jsonl").write_text(
        json.dumps({"kind": "run_complete", "artifact_sha256": run_wave.digest(model)})
        + "\n"
    )
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["OMP_NUM_THREADS"] == "1"
        output = run_wave.Path(command[command.index("--output") + 1])
        with gzip.open(output / "rows.jsonl.gz", "wt") as stream:
            stream.write("{}\n")
        with gzip.open(output / "failures.jsonl.gz", "wt"):
            pass
        summary = {
            "filters": {
                "group": "javascript_product_detail/2",
                "case": "case-1",
                "split": "fresh_cross_site",
            },
            "frozen_checksum": hashlib.sha256(
                json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "semantic": {"artifact_sha256": run_wave.digest(model)},
            "rows": 1,
            "score_event_counts": {},
        }
        (output / "summary.json").write_text(json.dumps(summary))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_wave.subprocess, "run", execute)
    destination = tmp_path / "wave"
    run_wave.run(source, {"minilm": model}, destination)
    assert len(calls) == 1
    run_wave.run(source, {"minilm": model}, destination)
    assert len(calls) == 1
    (destination / "minilm/case-1/summary.json").write_text("tampered")
    with pytest.raises(ValueError, match="completed shard changed"):
        run_wave.run(source, {"minilm": model}, destination)


def test_missing_completion_ledger_is_not_success(tmp_path):
    model = tmp_path / "model.json"
    model.write_text("{}")
    model.with_suffix(".batches.jsonl").write_text(
        json.dumps({"kind": "run_start"}) + "\n"
    )
    with pytest.raises(ValueError, match="not complete"):
        run_wave.ready_artifact(model)
