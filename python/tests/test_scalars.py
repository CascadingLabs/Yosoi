import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.errors import ContractError, DocumentError, LocatorError, PolicyError
from yosoi.locators import (
    AccessibilityLocation,
    ByteRange,
    DecodedTextCoordinate,
    DecodedTextLocation,
    DomCoordinate,
    ExpandedNamePathSegment,
    Finding,
    JsonCoordinate,
    JsonLocation,
    LocateResult,
    NodeReference,
    RegionLineage,
    RenderedDomLocation,
    TextRange,
    TreeCoordinate,
)
from yosoi.outcomes import (
    AccessibilityCoordinate,
    Complete,
    NodeValue,
    TextValue,
)
from yosoi.policy import Policy
from yosoi.scalars import (
    AccessibilityNodeLimit,
    AddressableByteLimit,
    Budget,
    ByteLimit,
    CaptureDeadline,
    CaptureDuration,
    ContractId,
    CountLimit,
    DocumentEpoch,
    DocumentId,
    DomNodeId,
    EventLimit,
    FieldId,
    MaximumElapsed,
    NonZeroU32,
    OutputId,
    ProviderDefaultsVersion,
    RedirectHopLimit,
    RegionId,
    ResourceLimit,
    StepLimit,
)


def test_public_id_and_positive_policy_scalar_constructors() -> None:
    assert DocumentId.try_new("doc").as_str() == "doc"
    assert ContractId.try_new("contract").as_str() == "contract"
    assert FieldId.try_new("field").as_str() == "field"
    assert OutputId.try_new("output").as_str() == "output"
    assert RegionId.try_new("region").as_str() == "region"
    assert DocumentEpoch.try_new(4).get() == 4
    assert DomNodeId.try_new(5).get() == 5
    assert CountLimit.try_new(6).get() == 6
    assert StepLimit.try_new(7).get() == 7
    assert AddressableByteLimit.try_new(8).as_usize() == 8
    assert EventLimit.try_new(9).as_usize() == 9
    assert ResourceLimit.try_new(10).get() == 10
    assert AccessibilityNodeLimit.try_new(11).get() == 11
    assert MaximumElapsed.try_new(12).as_microseconds() == 12
    assert RedirectHopLimit.try_new(13).get() == 13
    assert Budget.try_new(14).get() == 14
    assert ProviderDefaultsVersion.try_new(15).get() == 15

    accessibility_nonzero = AccessibilityNodeLimit.try_new(21).to_nonzero()
    resource_nonzero = ResourceLimit.try_new(22).to_nonzero()
    assert isinstance(accessibility_nonzero, NonZeroU32)
    assert isinstance(resource_nonzero, NonZeroU32)
    assert accessibility_nonzero.get() == 21
    assert resource_nonzero.get() == 22

    byte_limit = AddressableByteLimit.try_new(23).to_byte_limit()
    assert isinstance(byte_limit, ByteLimit)
    assert byte_limit.get() == byte_limit.as_usize() == 23

    deadline = MaximumElapsed.try_new(24).to_capture_deadline()
    assert isinstance(deadline, CaptureDeadline)
    assert deadline.as_microseconds() == 24
    duration = deadline.duration()
    assert isinstance(duration, CaptureDuration)
    assert duration.as_microseconds() == 24

    for factory, value, error in (
        (DocumentId, " \t", DocumentError),
        (ContractId, " ", ContractError),
        (FieldId, "", ContractError),
        (OutputId, "\n", LocatorError),
        (RegionId, "  ", LocatorError),
        (DocumentEpoch, 0, DocumentError),
        (DomNodeId, 0, LocatorError),
        (CountLimit, 0, PolicyError),
        (CountLimit, 1 << 64, PolicyError),
        (StepLimit, 0, PolicyError),
        (StepLimit, 1 << 32, PolicyError),
        (AddressableByteLimit, 0, PolicyError),
        (AddressableByteLimit, 1 << 64, PolicyError),
        (EventLimit, 0, PolicyError),
        (ResourceLimit, 0, PolicyError),
        (AccessibilityNodeLimit, 0, PolicyError),
        (MaximumElapsed, 0, PolicyError),
        (RedirectHopLimit, 0, PolicyError),
        (Budget, 0, PolicyError),
        (ProviderDefaultsVersion, 0, PolicyError),
        (DocumentEpoch, 1 << 64, DocumentError),
        (DomNodeId, 1 << 64, LocatorError),
    ):
        with pytest.raises(error):
            cast(Any, factory).try_new(value)


def test_policy_fields_use_public_newtypes_and_keep_scalar_json() -> None:
    policy = Policy()
    assert isinstance(policy.documents.max_nodes, CountLimit)
    assert isinstance(policy.documents.max_input_bytes, AddressableByteLimit)
    assert isinstance(policy.request.maximum_elapsed, MaximumElapsed)
    assert isinstance(policy.map.limits.max_concurrency, Budget)
    assert isinstance(policy.search.max_retained_content_bytes, AddressableByteLimit)
    wire = json.loads(policy.to_json())
    assert isinstance(wire["documents"]["max_nodes"], int)
    restored = Policy.model_validate_json(policy.to_json())
    assert restored.documents.max_nodes == policy.documents.max_nodes


def test_ranges_and_coordinates_use_rust_constructor_invariants() -> None:
    assert ByteRange.try_new(3, 3).start == 3
    assert TextRange.try_new(1, 2).end == 2
    assert ExpandedNamePathSegment.try_new("urn:test", "item", 1).local_name == "item"
    assert TreeCoordinate.try_new((1, 2), ByteRange.try_new(0, 4)).child_path == (1, 2)
    assert JsonCoordinate.try_new("/items/0~1name").as_pointer() == "/items/0~1name"
    epoch = DocumentEpoch.try_new(2)
    node = DomNodeId.try_new(3)
    dom = DomCoordinate.new(epoch, node)
    assert dom.document_epoch == epoch
    assert (
        JsonLocation(kind="json", coordinate=JsonCoordinate.try_new("/items/0")).kind
        == "json"
    )
    assert (
        AccessibilityLocation(
            kind="accessibility",
            coordinate=AccessibilityCoordinate.try_new(epoch, "ax-1"),
        ).coordinate.node_id
        == "ax-1"
    )
    decoded = DecodedTextCoordinate.new(
        ByteRange.try_new(0, 2), TextRange.try_new(0, 1)
    )
    assert (
        DecodedTextLocation(kind="decoded_text", coordinate=decoded).coordinate
        == decoded
    )

    invalid = (
        lambda: ByteRange.try_new(4, 3),
        lambda: TextRange.try_new(4, 3),
        lambda: ExpandedNamePathSegment.try_new(None, "", 1),
        lambda: ExpandedNamePathSegment.try_new(None, "item", 0),
        lambda: TreeCoordinate.try_new(()),
        lambda: TreeCoordinate.try_new((1, 0)),
        lambda: TreeCoordinate.with_expanded_name_path((1,), None, ()),
        lambda: JsonCoordinate.try_new("/bad~2escape"),
        lambda: DomNodeId.try_new(0),
        lambda: DomCoordinate.new(DocumentEpoch.try_new(0), node),
        lambda: AccessibilityCoordinate.try_new(epoch, " \t"),
    )
    for create in invalid:
        with pytest.raises((LocatorError, DocumentError)):
            create()


def test_finding_and_locate_result_constructors_validate_cross_field_invariants() -> (
    None
):
    document_id = DocumentId.try_new("doc")
    other_document_id = DocumentId.try_new("other")
    output_id = OutputId.try_new("node")
    dom = DomCoordinate.new(DocumentEpoch.try_new(3), DomNodeId.try_new(4))
    coordinate = RenderedDomLocation(kind="rendered_dom", coordinate=dom)
    reference = NodeReference.new(document_id, coordinate)
    projected = NodeValue(kind="node", value=reference)
    finding = Finding.try_new(
        document_id, output_id, 1, coordinate, projected, Complete(status="complete")
    )
    assert finding.document_id == document_id
    assert finding.value == reference
    with pytest.raises(LocatorError):
        Finding.try_new(
            other_document_id,
            output_id,
            1,
            coordinate,
            projected,
            Complete(status="complete"),
        )

    later = Finding.try_new(
        document_id,
        output_id,
        2,
        coordinate,
        TextValue(kind="text", value="second"),
        Complete(status="complete"),
    )
    located = LocateResult.try_new(document_id, (finding, later))
    assert located.document_id == document_id
    assert [item.order for item in located.findings] == [1, 2]
    with pytest.raises(LocatorError):
        LocateResult.try_new(document_id, (later, finding))
    with pytest.raises(LocatorError):
        LocateResult.try_new(other_document_id, (finding,))

    region = RegionLineage.new(
        RegionId.try_new("parent"),
        1,
        coordinate,
    )
    child = Finding.try_new(
        document_id,
        output_id,
        3,
        coordinate,
        TextValue(kind="text", value="child"),
        Complete(status="complete"),
        parent_region=region,
    )
    with pytest.raises(LocatorError):
        LocateResult.try_new_with_regions(document_id, (), ())
    with pytest.raises(LocatorError):
        LocateResult.try_new_with_regions(document_id, (), (child,))
    with pytest.raises(LocatorError):
        LocateResult.try_new_with_regions(document_id, (region, region), (child,))


def test_direct_pydantic_scalar_fields_retain_rust_validation() -> None:
    with pytest.raises(ValidationError):
        ys.documents.DocumentProfile.rendered_dom(0)
    with pytest.raises(ValidationError):
        ys.locators.Output(id=" ", locator=ys.css("h1").text())
    with pytest.raises(LocatorError):
        ByteRange(start=5, end=2)
