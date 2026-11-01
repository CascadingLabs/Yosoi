//! Explicitly versioned, frozen network windows remain separate from source JSON.
use std::error::Error;
use yosoi::{
    Document,
    surface::{
        DocumentPolicies, DocumentPolicy, NetworkCoverage, NetworkRetention, NetworkWindow,
        NetworkObservationPolicy, Surface, browser::WebSurface, model::SourceId,
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
            max_buffered_events: 256,
            retain_url_path: false,
            retain_url_query: false,
            retained_header_names: Vec::new(),
            retain_bodies: false,
            provider_resource_buffer_bytes: 1,
            provider_total_buffer_bytes: 1,
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
    assert!(WebSurface::with_policy(
        ordinary_index,
        SourceId::new("ordinary-json")?,
        policies.json,
    )
    .is_err());

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
        header_allowlist: vec!["authorization".into(), "accept".into()],
        ..NetworkObservationPolicy::default()
    }
    .retention();
    assert_eq!(opted_in.retained_header_names, ["accept"]);
    assert_eq!(opted_in.provider_resource_buffer_bytes, 1024 * 1024);
    Ok(())
}
