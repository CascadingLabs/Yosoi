//! Explicitly versioned, frozen network windows remain separate from source JSON.
use sha2::Digest;
use std::{error::Error, process::Command};
use yosoi::{
    Archive, Document,
    surface::{
        DocumentPolicies, DocumentPolicy, NetworkCoverage, NetworkObservationPolicy,
        NetworkRetention, NetworkWindow, Surface, browser::WebSurface, model::SourceId,
    },
};

fn window() -> NetworkWindow {
    NetworkWindow {
        schema: "yosoi.network.v1".into(),
        schema_version: 1,
        session_id: "session-1".into(),
        tab_id: "tab-1".into(),
        subscription_id: "subscription-1".into(),
        window_id: "subscription-1:1".into(),
        first_sequence: None,
        last_sequence: None,
        started_at_unix_us: 1,
        ended_at_unix_us: 2,
        events: Vec::new(),
        in_flight_at_start: Vec::new(),
        in_flight: Vec::new(),
        gaps: Vec::new(),
        coverage: NetworkCoverage {
            complete: false,
            reason: "page_target_cdp_window".into(),
            overflow: false,
            dropped_events: 0,
            disconnected: false,
            expired: false,
            instrumentation_escalated: true,
            network_was_previously_enabled: false,
            late_events: 0,
            filtered_events: 0,
            starts_not_observed: 0,
            omitted_payload_links: 0,
            start_boundary_unknown: true,
            end_boundary_in_flight: false,
        },
        retention: NetworkRetention {
            max_duration_ms: 300_000,
            max_events: 2_048,
            max_buffered_events: 256,
            max_event_bytes: 2 * 1024 * 1024,
            max_windows: 32,
            retain_url_path: false,
            retain_url_query: false,
            retained_header_names: Vec::new(),
            retain_bodies: false,
            max_response_bodies: 16,
            max_body_bytes: 1024 * 1024,
            max_total_body_bytes: 8 * 1024 * 1024,
            provider_resource_buffer_bytes: surface::NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES,
            provider_total_buffer_bytes: surface::NETWORK_PROVIDER_TOTAL_BUFFER_BYTES,
            allowed_origins: Vec::new(),
            allowed_methods: Vec::new(),
        },
        payloads: Vec::new(),
    }
}

#[test]
fn ordinary_json_with_network_looking_fields_stays_ordinary_json() -> Result<(), Box<dyn Error>> {
    let policies = DocumentPolicies {
        json: DocumentPolicy {
            max_bytes: 4096,
            ..DocumentPolicy::default()
        },
        network: DocumentPolicy {
            max_bytes: 1,
            ..DocumentPolicy::default()
        },
        ..DocumentPolicies::default()
    };
    let ordinary = Document::json(
        "ordinary-json",
        br#"{"schema":"yosoi.network.v1","events":[{"request":"not-a-window"}]}"#.to_vec(),
    )?;
    let ordinary_index = Surface::with_policy(&ordinary, &policies)?;
    assert!(!ordinary_index.is_network_observation());
    assert!(ordinary_index.coverage().complete);
    assert!(NetworkWindow::from_document(&ordinary).is_err());
    assert!(
        WebSurface::with_policy(
            ordinary_index,
            SourceId::new("ordinary-json")?,
            policies.json,
        )
        .is_err()
    );

    let typed = window().to_document("network-window")?;
    let typed_policies = DocumentPolicies::default();
    let network_index = Surface::with_policy(&typed, &typed_policies)?;
    assert!(network_index.is_network_observation());
    assert!(!network_index.coverage().complete);
    let network = WebSurface::with_policy(
        network_index,
        SourceId::new("native-network")?,
        typed_policies.network,
    )?;
    assert_eq!(network.descriptor().representation, "yosoi.web.network.v1");
    assert_eq!(
        network.observation().coverage.reason.as_deref(),
        Some("page_target_cdp_window")
    );
    let defaults = NetworkObservationPolicy::default().retention();
    assert!(!defaults.retain_url_path);
    assert!(!defaults.retain_url_query);
    assert!(!defaults.retain_bodies);
    assert_eq!(defaults.provider_resource_buffer_bytes, 1);
    let opted_in = NetworkObservationPolicy {
        retain_bodies: true,
        header_allowlist: vec![
            "authorization".into(),
            "x-api-token".into(),
            "accept".into(),
        ],
        ..NetworkObservationPolicy::default()
    }
    .retention();
    assert_eq!(opted_in.retained_header_names, ["accept"]);
    assert_eq!(opted_in.provider_resource_buffer_bytes, 1024 * 1024);
    Ok(())
}

#[tokio::test]
async fn cli_restores_network_payloads_from_portable_outcomes_without_a_browser()
-> Result<(), Box<dyn Error>> {
    let temporary = tempfile::tempdir()?;
    let archive = Archive::open(temporary.path().join("archive")).await?;
    let payload_id = "network-payload-json-1";
    let payload = Document::json(payload_id, br#"{"offline":true}"#.to_vec())?;
    let payload_sha = format!("{:x}", sha2::Sha256::digest(payload.bytes()));
    let mut outcome = surface::Outcome::new("network-offline", surface::ArchiveLimits::default())?;
    outcome = outcome.with_source(surface::ArchivedSource::new(payload_id, &payload, None))?;
    let window = NetworkWindow {
        schema: surface::NETWORK_OBSERVATION_SCHEMA.into(),
        schema_version: 1,
        session_id: "session-offline".into(),
        tab_id: "tab-offline".into(),
        subscription_id: "subscription-offline".into(),
        window_id: "subscription-offline:1".into(),
        first_sequence: Some(1),
        last_sequence: Some(1),
        started_at_unix_us: 1,
        ended_at_unix_us: 2,
        events: vec![surface::NetworkEvent {
            sequence: 1,
            request_id: "request-1".into(),
            request_start_observed: true,
            hop: 0,
            observed_at_unix_us: 1,
            provider_time_us: Some(1),
            provider_clock: Some(surface::NetworkProviderClock::CdpMonotonic),
            frame_id: None,
            loader_id: None,
            kind: surface::NetworkEventKind::ResponseReceived {
                url: "http://fixture.test/api".into(),
                status: Some(200),
                declared_media_type: Some("application/json; charset=utf-8".into()),
                browser_effective_mime: Some("application/json".into()),
                browser_effective_charset: Some("utf-8".into()),
                content_encoding: None,
                headers: Vec::new(),
            },
        }],
        in_flight_at_start: Vec::new(),
        in_flight: Vec::new(),
        gaps: Vec::new(),
        coverage: NetworkCoverage {
            complete: false,
            reason: "page_target_cdp_window_is_not_browser_wide_or_atomic".into(),
            overflow: false,
            dropped_events: 0,
            disconnected: false,
            expired: false,
            instrumentation_escalated: false,
            network_was_previously_enabled: true,
            late_events: 0,
            filtered_events: 0,
            starts_not_observed: 0,
            omitted_payload_links: 0,
            start_boundary_unknown: true,
            end_boundary_in_flight: false,
        },
        retention: NetworkObservationPolicy::default().retention(),
        payloads: vec![surface::NetworkPayloadRef {
            id: payload_id.into(),
            request_id: "request-1".into(),
            hop: 0,
            response_sequence: 1,
            response_window_id: "subscription-offline:1".into(),
            body_capture_at_unix_us: Some(2),
            state: surface::NetworkPayloadState::Retained,
            document_kind: Some(surface::NetworkPayloadKind::Json),
            projection_basis: Some(surface::NetworkProjectionBasis::RequestsDeclared),
            declared_media_type: Some("application/json; charset=utf-8".into()),
            browser_effective_mime: Some("application/json".into()),
            browser_effective_charset: Some("utf-8".into()),
            detected_media_type: Some("application/json".into()),
            content_encoding: None,
            byte_provenance: surface::NetworkByteProvenance::CdpDecodedResponseBody,
            provider_base64_encoded: false,
            provider_reported_body_bytes: Some(u64::try_from(payload.bytes().len())?),
            text_utf8_normalized: true,
            retained_bytes: u64::try_from(payload.bytes().len())?,
            sha256: Some(payload_sha),
            document_id: Some(payload_id.into()),
            reason: None,
        }],
    };
    let window_document = window.to_document("network-window-offline")?;
    let window_surface = Surface::with_policy(&window_document, &DocumentPolicies::default())?;
    outcome = outcome.with_source(surface::ArchivedSource::new(
        "network-window-1",
        &window_document,
        Some(&window_surface),
    ))?;
    let outcome_ref = archive.write(&outcome).await?;
    let portable = temporary.path().join("network.yosoi");
    archive.export_file(&outcome_ref, &portable).await?;
    let output = temporary.path().join("body.json");
    let result = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args([
            "surface",
            "payload",
            "--record",
            portable
                .to_str()
                .ok_or_else(|| io::Error::other("portable path is not UTF-8"))?,
            "--id",
            payload_id,
            "--file",
            output
                .to_str()
                .ok_or_else(|| io::Error::other("payload path is not UTF-8"))?,
        ])
        .output()?;
    if !result.status.success() {
        return Err(io::Error::other(String::from_utf8_lossy(&result.stderr).into_owned()).into());
    }
    assert_eq!(std::fs::read(output)?, payload.bytes());
    let _restored = archive.read(&outcome_ref).await?;
    Ok(())
}
