from types import MappingProxyType
from typing import Any, cast

import pytest

import yosoi as ys
from yosoi._models import NativeAuthoringModel
from yosoi.documents import DocumentId
from yosoi.outcomes import (
    Complete,
    Finding,
    JsonValueProjection,
    SourceTreeLocation,
    TreeCoordinate,
)
from yosoi.runtime_contracts import (
    RuntimeCandidate,
    RuntimeExactlyOne,
    RuntimeString,
    RuntimeValidatedRecord,
)
from yosoi.scalars import OutputId


class _ListNativeAuthoringValue(NativeAuthoringModel):
    tags: list[str]


class _TagsRecord(ys.Contract):
    tags: list[str] = ys.Field("Tag values")


def test_policy_clone_detaches_nested_filters() -> None:
    original = ys.Policy()
    cloned = original.clone()

    cloned.map.filters.excluded_query_keys.append("clone-only")

    assert "clone-only" not in original.map.filters.excluded_query_keys


def test_finding_clone_detaches_nested_json_projection() -> None:
    finding = Finding.try_new(
        document_id=DocumentId("document"),
        output_id=OutputId("json"),
        order=0,
        coordinate=SourceTreeLocation(
            kind="source_tree", coordinate=TreeCoordinate.try_new((1,))
        ),
        projected=JsonValueProjection(kind="json", value={"tags": ["source"]}),
        completeness=Complete(status="complete"),
    )

    cloned = finding.clone()
    assert isinstance(cloned.projected, JsonValueProjection)
    assert isinstance(cloned.projected.value, dict)
    tags = cloned.projected.value["tags"]
    assert isinstance(tags, list)
    tags.append("clone-only")

    assert finding.projected.value == {"tags": ["source"]}


def test_runtime_record_clones_keep_mapping_proxies_immutable() -> None:
    candidate = RuntimeCandidate(document_id="document", fields={"title": ()})
    candidate_clone = candidate.clone()
    record = RuntimeValidatedRecord(
        candidate=candidate,
        value={
            "title": RuntimeExactlyOne(
                cardinality="exactly_one",
                value=RuntimeString(type="string", value="Yosoi"),
            )
        },
    )
    record_clone = record.clone()

    assert isinstance(candidate_clone.fields, MappingProxyType)
    assert candidate_clone.fields is not candidate.fields
    assert isinstance(record_clone.value, MappingProxyType)
    assert record_clone.value is not record.value
    assert isinstance(record_clone.candidate.fields, MappingProxyType)
    with pytest.raises(TypeError):
        cast(Any, candidate_clone.fields)["other"] = ()
    with pytest.raises(TypeError):
        cast(Any, record_clone.value)["other"] = record_clone.value["title"]


def test_native_request_clone_keeps_rust_identity_and_handle_alive() -> None:
    original = ys.request.new("https://example.org/")
    original_id = original.id
    cloned = original.clone()

    assert cloned is not original
    assert cloned.id == original_id
    assert cloned._handle is original._handle

    del original
    assert cloned.id == original_id
    cloned.check()


def test_deep_clone_detaches_native_authoring_and_contract_lists() -> None:
    authoring = _ListNativeAuthoringValue(tags=["source"])
    authoring_clone = authoring.clone()
    authoring_clone.tags.append("clone-only")

    record = _TagsRecord(tags=["source"])
    record_clone = record.clone()
    record_clone.tags.append("clone-only")

    assert authoring.tags == ["source"]
    assert record.tags == ["source"]
