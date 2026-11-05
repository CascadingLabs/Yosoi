"""Archive replay must retain quality changes and reject unsafe reconstruction."""

import gzip
import json

import pytest
from archive_campaign import quality_digest, relative_path, replay


@pytest.mark.parametrize("value", ["../x", "/x", "a/../b", "a//b", "", "a\\b"])
def test_reconstruction_rejects_unsafe_or_noncanonical_paths(value):
    with pytest.raises(ValueError, match="unsafe"):
        relative_path(value)


def test_quality_digest_excludes_only_scoring_time(tmp_path):
    path = tmp_path / "rows.jsonl.gz"

    def save(score, timing):
        with gzip.open(path, "wt") as stream:
            stream.write(json.dumps({"top_score": score, "scoring_ns": timing}))
            stream.write("\n")
        return quality_digest(path)

    expected = save(0.5, 10)
    assert save(0.5, 20) == expected
    assert save(0.6, 20) != expected


def test_replay_checks_materialized_bytes_before_executing(tmp_path):
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "source.bin").write_bytes(b"tampered")
    (restored / "artifact-index.json").write_text(
        json.dumps(
            {"entries": [{"logical": "source.bin", "bytes": 8, "sha256": "wrong"}]}
        )
    )
    with pytest.raises(ValueError, match="evidence changed"):
        replay(restored, tmp_path / "output")
    assert not (tmp_path / "output").exists()
