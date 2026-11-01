"""Offline response references are scoped to exact typed windows in one Outcome."""

from __future__ import annotations

import hashlib

import pytest

import yosoi as ys
from yosoi import surface as sf


@pytest.fixture
def network_outcome():
    body = ys.Document.from_json("network-body", b'{"offline":true}')
    reference = sf.NetworkPayloadRef(
        id="network-body",
        request_id="request-1",
        hop=0,
        response_sequence=1,
        response_window_id="response-window",
        state="retained",
        document_kind="json",
        projection_basis="requests_declared",
        declared_media_type="application/json",
        browser_effective_mime="application/json",
        browser_effective_charset="utf-8",
        detected_media_type="application/json",
        byte_provenance="cdp_decoded_response_body",
        provider_base64_encoded=False,
        text_utf8_normalized=True,
        retained_bytes=len(body.data),
        sha256=hashlib.sha256(body.data).hexdigest(),
        document_id="network-body",
    )
    choices = sf.NetworkObservationPolicy().model_dump(exclude={"header_allowlist"})
    retention = sf.NetworkRetention(
        **choices,
        retained_header_names=(),
        provider_resource_buffer_bytes=8388608,
        provider_total_buffer_bytes=8388608,
    )
    window = sf.NetworkWindow(
        schema="yosoi.network.v1",
        schema_version=1,
        session_id="session-1",
        tab_id="tab-1",
        subscription_id="subscription-1",
        window_id="body-window",
        started_at_unix_us=1,
        ended_at_unix_us=2,
        events=(),
        in_flight_at_start=(),
        in_flight=(),
        gaps=(),
        retention=retention,
        payloads=(reference,),
        coverage=sf.NetworkCoverage(
            complete=False,
            reason="fixture_partial",
            overflow=False,
            dropped_events=0,
            disconnected=False,
            expired=False,
            instrumentation_escalated=False,
            network_was_previously_enabled=True,
            late_events=0,
            filtered_events=0,
            starts_not_observed=0,
            omitted_payload_links=0,
            start_boundary_unknown=True,
            end_boundary_in_flight=False,
        ),
    )
    body_source = sf.ArchivedSource.from_document("network-body", body)
    outcome = (
        sf.Outcome.new("network-outcome")
        .with_source(body_source)
        .with_source(
            sf.ArchivedSource.from_document(
                "network-window", window.to_document("window")
            )
        )
    )
    return outcome, reference, body, window


def test_offline_network_payload_accepts_exact_owned_reference(network_outcome):
    outcome, reference, body, _ = network_outcome
    assert outcome.network_payload(reference).value.data == body.data


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "foreign-request"),
        ("hop", 1),
        ("response_sequence", 2),
        ("response_window_id", "foreign-window"),
    ],
)
def test_offline_network_payload_rejects_modified_correlations(
    network_outcome, field, value
):
    outcome, reference, _, _ = network_outcome
    altered = reference.model_copy(update={field: value})
    with pytest.raises(sf.SurfaceError, match="not retained by this Outcome"):
        outcome.network_payload(altered)


def test_offline_network_payload_rejects_foreign_outcome_and_json_magic(
    network_outcome,
):
    _, reference, body, window = network_outcome
    foreign = sf.Outcome.new("foreign").with_source(
        sf.ArchivedSource.from_document("network-body", body)
    )
    with pytest.raises(sf.SurfaceError, match="not retained by this Outcome"):
        foreign.network_payload(reference)
    foreign_reference = reference.model_copy(update={"request_id": "foreign-request"})
    foreign_window = window.model_copy(update={"payloads": (foreign_reference,)})
    foreign = foreign.with_source(
        sf.ArchivedSource.from_document(
            "foreign-explicit-window", foreign_window.to_document("foreign-window")
        )
    )
    with pytest.raises(sf.SurfaceError, match="not retained by this Outcome"):
        foreign.network_payload(reference)
    assert foreign.network_payload(foreign_reference).value.data == body.data
    ordinary = ys.Document.from_json("ordinary-window", window.model_dump_json())
    foreign = foreign.with_source(
        sf.ArchivedSource.from_document("ordinary-window", ordinary)
    )
    with pytest.raises(sf.SurfaceError, match="not retained by this Outcome"):
        foreign.network_payload(reference)
