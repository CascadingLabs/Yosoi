"""Identity parsing retains the SDK's typed error distinctions."""

import pytest

from yosoi.errors import RequestError, rust_error_details
from yosoi.identities import ActivityId, CaptureId


@pytest.mark.parametrize("identity", [ActivityId, CaptureId])
@pytest.mark.parametrize(
    ("value", "variant"),
    [
        ("invalid", "InvalidUuid"),
        ("550E8400-E29B-41D4-A716-446655440000", "NonCanonical"),
        ("550e8400-e29b-11d4-a716-446655440000", "NotRandomV4"),
    ],
)
def test_identity_parse_error_variants(identity, value, variant):
    with pytest.raises(RequestError) as caught:
        identity.from_str(value)
    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "yosoi_types::OccurrenceIdParseError"
    assert detail.variant == variant
    assert detail.details == {}
    assert detail.source_chain == ()


def test_identity_canonical_value_and_network_order_bytes():
    value = "550e8400-e29b-41d4-a716-446655440000"
    capture = CaptureId.from_str(value)
    assert capture.activity_id() == ActivityId.from_str(value)
    assert capture.as_bytes() == bytes.fromhex("550e8400e29b41d4a716446655440000")
