"""Public outcome defaults and counters match the Rust SDK shapes."""

import pytest
from pydantic import ValidationError

from yosoi.map import Summary
from yosoi.search import SearchHitMetadata


def test_summary_defaults_are_zero_unsigned_counters():
    summary = Summary()
    assert set(summary.model_dump().values()) == {0}
    for invalid in (-1, True, 1 << 32):
        with pytest.raises(ValidationError):
            Summary(requests=invalid)
    with pytest.raises(ValidationError):
        Summary(response_bytes=1 << 64)


def test_search_metadata_defaults_preserve_explicit_nullable_fields():
    metadata = SearchHitMetadata()
    assert metadata.model_dump() == {
        "title": None,
        "snippet": None,
        "display_url": None,
        "publisher": None,
        "published_at": None,
        "thumbnail_url": None,
    }
    assert SearchHitMetadata(title="SDK").title == "SDK"
