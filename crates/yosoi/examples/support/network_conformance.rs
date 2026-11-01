//! Deterministic, typed offline network evidence; no browser or request is run.

use serde_json::{Value, json};
use std::{error::Error, io};
use yosoi::{
    Surface,
    documents::{Document, FileDocument},
    surface::{
        NetworkObservationPolicy, NetworkPayload, NetworkPayloadRef, NetworkPayloadValue,
        NetworkWindow, Outcome, SurfaceError,
    },
};

pub fn event(sequence: u64, request: &str, hop: u32, kind: Value) -> Value {
    json!({"sequence":sequence,"request_id":request,"request_start_observed":request!="late-request","hop":hop,
        "observed_at_unix_us":1_000_100,"provider_time_us":500,"provider_clock":"cdp_monotonic",
        "frame_id":"frame-fixture","loader_id":"loader-fixture","kind":kind})
}

pub fn window(
    policy: &NetworkObservationPolicy,
    payloads: &[NetworkPayloadRef],
) -> Result<NetworkWindow, Box<dyn Error>> {
    let request = |url: &str| json!({"kind":"request_started","url":url,"method":"GET","resource_type":"Fetch","headers":[{"name":"x-request-id","value":"public-fixture"}]});
    let response = |url: &str, media: &str| json!({"kind":"response_received","url":url,"status":200,"declared_media_type":media,"browser_effective_mime":media,"browser_effective_charset":"utf-8","content_encoding":"gzip","headers":[{"name":"x-request-id","value":"public-fixture"}]});
    let done = json!({"kind":"finished","encoded_data_length":42});
    let events = vec![
        event(
            1,
            "request-html",
            0,
            request("https://fixture.invalid/start"),
        ),
        event(
            2,
            "request-html",
            0,
            json!({"kind":"redirect","from_url":"https://fixture.invalid/start","to_url":"https://fixture.invalid/page","status":302,"headers":[]}),
        ),
        event(
            3,
            "request-html",
            1,
            request("https://fixture.invalid/page"),
        ),
        event(
            4,
            "request-html",
            1,
            response("https://fixture.invalid/page", "text/html"),
        ),
        event(5, "request-html", 1, done.clone()),
        event(
            6,
            "request-json",
            0,
            request("https://fixture.invalid/data"),
        ),
        event(
            7,
            "request-json",
            0,
            response("https://fixture.invalid/data", "application/problem+json"),
        ),
        event(8, "request-json", 0, done.clone()),
        event(
            9,
            "request-file",
            0,
            request("https://fixture.invalid/file"),
        ),
        event(
            10,
            "request-file",
            0,
            response("https://fixture.invalid/file", "application/octet-stream"),
        ),
        event(11, "request-file", 0, done.clone()),
        event(
            12,
            "in-flight",
            0,
            request("https://fixture.invalid/pending"),
        ),
        event(13, "late-request", 0, done),
    ];
    let value = json!({"schema":"yosoi.network.v1","schema_version":1,"session_id":"session-fixture","tab_id":"tab-fixture","subscription_id":"subscription-fixture","window_id":"window-fixture",
        "first_sequence":1,"last_sequence":13,"started_at_unix_us":1_000_000,"ended_at_unix_us":2_000_000,
        "events":events,"in_flight_at_start":[{"request_id":"prior-flight","hop":0,"url":"https://fixture.invalid/prior","method":"GET","response_seen":true}],
        "in_flight":[{"request_id":"in-flight","hop":0,"url":"https://fixture.invalid/pending","method":"GET","response_seen":false}],
        "gaps":[{"after_sequence":11,"reason":"bounded producer queue gap","dropped_events":2}],
        "coverage":{"complete":false,"reason":"bounded fixture is not browser-wide evidence","overflow":true,"dropped_events":2,"disconnected":false,"expired":false,"instrumentation_escalated":false,"network_was_previously_enabled":true,"late_events":1,"filtered_events":1,"starts_not_observed":1,"omitted_payload_links":0,"start_boundary_unknown":true,"end_boundary_in_flight":true},
        "retention":policy.retention(),"payloads":payloads});
    let window: NetworkWindow = serde_json::from_value(value)?;
    window.validate()?;
    Ok(window)
}

pub fn reference(
    id: &str,
    request: &str,
    hop: u32,
    sequence: u64,
    kind: &str,
    bytes: &[u8],
) -> Result<NetworkPayloadRef, Box<dyn Error>> {
    use sha2::{Digest, Sha256};
    let (media, basis, state, base64) = match kind {
        "html" => (
            "text/html; charset=utf-8",
            "requests_declared",
            "retained",
            false,
        ),
        "json" => (
            "application/problem+json",
            "requests_structured_suffix",
            "retained",
            false,
        ),
        "file" => (
            "application/octet-stream",
            "opaque_bytes",
            "truncated",
            true,
        ),
        _ => return Err(io::Error::other("unknown authored network payload kind").into()),
    };
    Ok(serde_json::from_value(
        json!({"id":id,"request_id":request,"hop":hop,"response_sequence":sequence,"response_window_id":"window-fixture","body_capture_at_unix_us":2_000_050,
        "state":state,"document_kind":kind,"projection_basis":basis,"declared_media_type":media,"browser_effective_mime":media,"browser_effective_charset":if base64 {None} else {Some("utf-8")},"detected_media_type":null,"content_encoding":"gzip","byte_provenance":"cdp_decoded_response_body","provider_base64_encoded":base64,"provider_reported_body_bytes":bytes.len(),"text_utf8_normalized":!base64,"retained_bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes)),"document_id":id,"reason":if base64 {Some("bounded prefix")} else {None}}),
    )?)
}

pub fn document(value: &Document) -> Value {
    json!({"class":"Document","id":value.id(),"bytes":value.bytes(),"profile":{
        "representation":value.profile().representation(),"source_format":value.profile().source_format(),"schema":value.profile().schema(),"epoch":value.profile().epoch()}})
}

pub fn payload(value: &NetworkPayload) -> Value {
    let body = match &value.value {
        NetworkPayloadValue::Document(value) => document(value),
        NetworkPayloadValue::File(value) => {
            json!({"class":match value.as_ref() {FileDocument::Image(_)=>"ImageDocument",FileDocument::Video(_)=>"VideoDocument",FileDocument::Audio(_)=>"AudioDocument",FileDocument::Binary(_)=>"BinaryDocument"},"id":value.id(),"bytes":value.bytes(),"metadata":value.metadata(),"sha256":value.sha256()})
        }
    };
    json!({"class":"NetworkPayload","reference":value.reference,"bytes":value.bytes(),"value":body})
}

pub fn surface(value: &Surface) -> Result<Value, Box<dyn Error>> {
    Ok(
        json!({"identity":value.identity(),"representation":value.representation(),"coverage":value.coverage(),"overview":value.overview(None,yosoi::surface::Budget::default())?}),
    )
}

pub fn outcome_arguments(value: &Outcome) -> Value {
    let mut sources: Vec<_> = value
        .sources
        .iter()
        .map(|source| source.key.clone())
        .collect();
    sources.sort();
    json!({"id":value.record.id(),"source_keys":sources,"limits":value.limits})
}

pub fn case(name: &str, path: &str, arguments: Value, observed: Value) -> Value {
    json!({"name":name,"rustPath":path,"input":arguments,"rust":observed})
}

pub fn error(
    name: &str,
    path: &str,
    operation: &str,
    arguments: Value,
    result: Result<(), SurfaceError>,
) -> Result<Value, Box<dyn Error>> {
    let failure = match result {
        Err(value) => value,
        Ok(()) => return Err(io::Error::other(format!("{name} unexpectedly succeeded")).into()),
    };
    let (variant, details) = match &failure {
        SurfaceError::Invalid(message) => ("Invalid", json!({"message":message})),
        SurfaceError::Limit(limit) => ("Limit", json!({"limit":limit})),
        SurfaceError::Unknown => ("Unknown", json!({})),
        other => {
            return Err(
                io::Error::other(format!("unhandled network fixture error: {other}")).into(),
            );
        }
    };
    Ok(
        json!({"name":name,"rustPath":path,"operation":operation,"input":arguments,"rust":{"rejected":true},"rustFailure":{"rust_type":"yosoi::surface::SurfaceError","variant":variant,"details":details,"message":failure.to_string()}}),
    )
}
