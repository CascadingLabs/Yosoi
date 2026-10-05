import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.errors import MapError, RequestError, SearchError


def test_request_copy_rebuilds_changed_target_and_keeps_unchanged_identity() -> None:
    original = ys.request.new("https://example.org/")
    changed = original.model_copy(update={"target": "https://example.net/"})
    assert changed.target == changed._handle.target == "https://example.net/"
    assert changed.id != original.id
    assert original.model_copy(deep=True).id == original.id
    with pytest.raises(RequestError):
        original.model_copy(update={"target": "ftp://example.org/"}).check()
    with pytest.raises(ValidationError):
        original.model_copy(update={"target": None})


def test_map_copy_rebuilds_changed_seed() -> None:
    original = ys.map.new("https://example.org/")
    changed = original.model_copy(update={"seed": "ftp://example.org/"})
    with pytest.raises(MapError):
        changed.check()
    original.check()
    assert original.model_copy(deep=True).seed == original.seed


def test_search_copy_validates_changed_query_and_preserves_unchanged_identity() -> None:
    original = ys.search.new("rust sdk")
    changed = original.model_copy(update={"query": "python sdk"})
    assert changed.query == "python sdk"
    assert changed.id != original.id
    assert original.model_copy(deep=True).id == original.id
    with pytest.raises(SearchError):
        original.model_copy(update={"query": " "})
