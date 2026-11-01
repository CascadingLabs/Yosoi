//! Author executable offline network-window and retained-payload parity evidence.
//!
//! No provider is started. Browser transport certification is separate from
//! these actual typed SDK, privacy-policy, navigation and Archive operations.

use serde_json::json;
use std::{
    error::Error,
    io::{self, Write},
};
use yosoi::{
    Archive, Surface,
    documents::{Document, FileDocument, FileLimits, FileMetadata, file_from_bytes},
    surface::{
        ArchiveLimits, ArchivedSource, Limits, NetworkObservationPolicy, NetworkPayload,
        NetworkWindow, Outcome,
    },
};
#[path = "support/network_conformance.rs"]
mod support;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let html = Document::html(
        "body-html",
        b"<main>Network Needle \xce\xbb</main>".to_vec(),
    )?;
    let json_body = Document::json(
        "body-json",
        br#"{"message":"Network Needle","count":3}"#.to_vec(),
    )?;
    let file = file_from_bytes(
        "body-file",
        vec![0, 1, 2, 3],
        FileMetadata::new()
            .with_declared_media_type("application/octet-stream")?
            .with_source("fixture:network-body")?,
        FileLimits::default(),
    )?;
    let policy = NetworkObservationPolicy {
        retain_bodies: true,
        retain_url_path: true,
        header_allowlist: vec![
            "X-Request-ID".into(),
            "Authorization".into(),
            "Cookie".into(),
            "Set-Cookie".into(),
            "X-API-Key".into(),
        ],
        allowed_origins: vec!["https://fixture.invalid".into()],
        allowed_methods: vec!["GET".into()],
        ..NetworkObservationPolicy::default()
    };
    policy.validate()?;
    let refs = vec![
        support::reference("body-html", "request-html", 1, 4, "html", html.bytes())?,
        support::reference("body-json", "request-json", 0, 7, "json", json_body.bytes())?,
        support::reference("body-file", "request-file", 0, 10, "file", file.bytes())?,
    ];
    let window = support::window(&policy, &refs)?;
    let document = window.to_document("network-window")?;
    let index = Surface::new(&document)?;
    let ordinary = Document::json("ordinary-json", document.bytes().to_vec())?;
    let outcome = Outcome::new("network-parity-outcome", ArchiveLimits::default())?
        .with_source(ArchivedSource::new(
            "network-window",
            &document,
            Some(&index),
        ))?
        .with_source(ArchivedSource::new("body-html", &html, None))?
        .with_source(ArchivedSource::new("body-json", &json_body, None))?
        .with_source(ArchivedSource::new_file_document("body-file", &file, None))?;
    let mut cases = vec![
        support::case(
            "policy-defaults",
            "yosoi::surface::NetworkObservationPolicy",
            json!({}),
            serde_json::to_value(NetworkObservationPolicy::default())?,
        ),
        support::case(
            "policy-retention",
            "yosoi::surface::NetworkObservationPolicy::retention",
            json!({"self":policy}),
            serde_json::to_value(policy.retention())?,
        ),
        support::case(
            "typed-window",
            "yosoi::surface::NetworkWindow::to_document",
            json!({"self":window,"id":"network-window"}),
            json!({"window":NetworkWindow::from_document(&document)?,"document":support::document(&document),"surface":support::surface(&index)?}),
        ),
        support::case(
            "ordinary-json",
            "yosoi::Surface::new",
            json!({"document":support::document(&ordinary)}),
            json!({"network":Surface::new(&ordinary)?.is_network_observation(),"surface":support::surface(&Surface::new(&ordinary)?)?}),
        ),
    ];
    for reference in &refs {
        let value = NetworkPayload::from_outcome(&outcome, reference, 1_048_576)?;
        cases.push(support::case(&format!("payload-{}",reference.id),"yosoi::surface::NetworkPayload::from_outcome",json!({"outcome":support::outcome_arguments(&outcome),"reference":reference,"maximum":1_048_576}),support::payload(&value)));
    }
    let temporary = tempfile::tempdir()?;
    let archive = Archive::open(temporary.path().join("original")).await?;
    let saved = archive.write(&outcome).await?;
    let portable = temporary.path().join("network.yosoi");
    archive.export_file(&saved, &portable).await?;
    let fresh = Archive::open(temporary.path().join("fresh")).await?;
    let imported = fresh.import_file(&portable).await?;
    let restored: Outcome = fresh.read(&imported).await?;
    let restored_payloads = refs
        .iter()
        .map(|reference| {
            NetworkPayload::from_outcome(&restored, reference, 1_048_576)
                .map(|value| support::payload(&value))
        })
        .collect::<Result<Vec<_>, _>>()?;
    cases.push(support::case("portable-outcome","yosoi::surface::Outcome::source_document",json!({"self":support::outcome_arguments(&restored),"key":"network-window","maximum":1_048_576}),json!({"class":"Outcome","record_id":restored.record.id(),"source_keys":support::outcome_arguments(&restored),"payloads":restored_payloads,"window_document":support::document(&restored.source_document("network-window",1_048_576)?),"network_surface":support::surface(&restored.surface("network-window",Limits::default())?)?,"complete":restored.complete,"sealed":restored.sealed})));
    let mut errors = Vec::new();
    errors.push(support::error(
        "ordinary-json-rejected",
        "yosoi::surface::NetworkWindow::from_document",
        "ordinary-json",
        json!({"document":support::document(&ordinary)}),
        NetworkWindow::from_document(&ordinary).map(|_| ()),
    )?);
    for (name, field, value) in [
        (
            "bad-origin",
            "allowed_origins",
            json!(["https://fixture.invalid/private?secret=1"]),
        ),
        ("bad-header", "header_allowlist", json!(["bad header"])),
        ("bad-method", "allowed_methods", json!(["\u{03bb}"])),
        ("event-bound", "max_events", json!(0)),
    ] {
        let mut raw = serde_json::to_value(&policy)?;
        let fields = raw
            .as_object_mut()
            .ok_or_else(|| io::Error::other("policy fixture not object"))?;
        fields.insert(field.into(), value);
        let invalid: NetworkObservationPolicy = serde_json::from_value(raw.clone())?;
        errors.push(support::error(
            name,
            "yosoi::surface::NetworkObservationPolicy::validate",
            "policy",
            json!({"self":raw}),
            invalid.validate(),
        )?);
    }
    let mut invalid = window.clone();
    invalid.ended_at_unix_us = 0;
    errors.push(support::error(
        "window-interval",
        "yosoi::surface::NetworkWindow::validate",
        "window",
        json!({"self":invalid}),
        invalid.validate(),
    )?);
    let mut invalid = window.clone();
    invalid
        .events
        .first_mut()
        .ok_or_else(|| io::Error::other("network fixture has no first event"))?
        .request_id
        .clear();
    errors.push(support::error(
        "empty-request-id",
        "yosoi::surface::NetworkWindow::validate",
        "window",
        json!({"self":invalid}),
        invalid.validate(),
    )?);
    let mut invalid = window.clone();
    invalid.payloads.extend(refs.clone());
    errors.push(support::error(
        "duplicate-payload",
        "yosoi::surface::NetworkWindow::validate",
        "window",
        json!({"self":invalid}),
        invalid.validate(),
    )?);
    let mut foreign = refs
        .first()
        .ok_or_else(|| io::Error::other("missing first payload"))?
        .clone();
    foreign.hop = 99;
    errors.push(support::error("foreign-membership","yosoi::surface::NetworkPayload::from_outcome","payload",json!({"outcome":support::outcome_arguments(&outcome),"reference":foreign,"maximum":1_048_576}),NetworkPayload::from_outcome(&outcome,&foreign,1_048_576).map(|_|()))?);
    let reference = refs
        .first()
        .ok_or_else(|| io::Error::other("missing first payload"))?;
    errors.push(support::error(
        "payload-byte-bound",
        "yosoi::surface::NetworkPayload::from_outcome",
        "payload",
        json!({"outcome":support::outcome_arguments(&outcome),"reference":reference,"maximum":1}),
        NetworkPayload::from_outcome(&outcome, reference, 1).map(|_| ()),
    )?);
    let missing = Outcome::new("network-missing-body", ArchiveLimits::default())?
        .with_source(ArchivedSource::new("network-window", &document, None))?;
    errors.push(support::error("missing-body","yosoi::surface::NetworkPayload::from_outcome","missing-body",json!({"outcome":support::outcome_arguments(&missing),"reference":reference,"maximum":1_048_576}),NetworkPayload::from_outcome(&missing,reference,1_048_576).map(|_|()))?);
    let limits = Limits {
        input_bytes: 1,
        ..Limits::default()
    };
    errors.push(support::error(
        "document-byte-bound",
        "yosoi::Surface::with_limits",
        "surface",
        json!({"document":support::document(&document),"limits":limits}),
        Surface::with_limits(&document, limits).map(|_| ()),
    )?);
    let output = json!({"schemaVersion":1,"kind":"yosoi-network-conformance-fixtures","input":{"policy":policy,"window":window,"bodies":[support::document(&html),support::document(&json_body),{"class":match &file{FileDocument::Binary(_)=>"BinaryDocument",_=>"unexpected"},"id":file.id(),"bytes":file.bytes(),"metadata":file.metadata(),"sha256":file.sha256()}]},"cases":cases,"errorCases":errors});
    let mut writer = io::stdout().lock();
    serde_json::to_writer(&mut writer, &output)?;
    writer.write_all(b"\n")?;
    Ok(())
}
