//! Portable files must survive removal of the original store and session.
// The existing local Archive format is certified only on Unix.
#![cfg(unix)]
use serde::Deserialize;
use std::{error::Error, fs, io, result::Result as StdResult};
use yosoi::automation_record::OperationStatus;
use yosoi::{
    Archive,
    documents::{Document, DocumentEpoch},
    surface::{ArchiveLimits, ArchivePolicy, Budget, Limits, Session, SessionPolicy, Surface},
};

type Result<T = ()> = StdResult<T, Box<dyn Error>>;

fn policy() -> SessionPolicy {
    SessionPolicy {
        archive: ArchivePolicy::Enabled,
        captures: 1,
        ..SessionPolicy::default()
    }
}
fn prepared(content: &str) -> Result<Surface> {
    Ok(Surface::new(&Document::html(
        "fixture",
        content.as_bytes().to_vec(),
    )?)?)
}

#[derive(Deserialize)]
struct Cases {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    name: String,
    format: String,
    content: String,
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Behavioral regression assertions; setup errors propagate."
)]
async fn all_six_profiles_restore_from_a_moved_file_without_original_store() -> Result {
    let cases: Cases =
        serde_json::from_str(include_str!("../../../python/parity/surface-vectors.json"))?;
    let root = tempfile::tempdir()?;
    for case in cases.cases {
        let epoch = DocumentEpoch::try_from(7)?;
        let document = match case.format.as_str() {
            "html" => Document::html(&case.name, case.content.into_bytes())?,
            "xml" => Document::xml(&case.name, case.content.into_bytes())?,
            "json" => Document::json(&case.name, case.content.into_bytes())?,
            "text" => Document::text(&case.name, case.content.into_bytes())?,
            "rendered_dom" => Document::rendered_dom(&case.name, epoch, case.content.into_bytes())?,
            "accessibility_tree" => {
                Document::accessibility_tree(&case.name, epoch, case.content.into_bytes())?
            }
            _ => return Err(io::Error::other("unknown fixture").into()),
        };
        let surface = Surface::new(&document)?;
        let identity = surface.identity().to_owned();
        let session = Session::new(surface.clone(), policy())?;
        let cursor = session.cursor()?;
        let found = cursor.find("lamp", None, Budget::default())?;
        let target = found
            .entries
            .first()
            .ok_or_else(|| io::Error::other("missing lamp"))?
            .reference
            .clone();
        let expected = cursor.inspect(&target, None, Budget::default())?.content;
        session.attach()?;
        session.publish(prepared("<p>second capture evicts live history</p>")?)?;
        let outcome = session
            .close()?
            .ok_or_else(|| io::Error::other("missing policy outcome"))?;
        assert!(outcome.sealed && outcome.complete);
        assert_eq!(outcome.sources.len(), 2);
        assert_eq!(
            outcome
                .record
                .operations()
                .iter()
                .filter(|receipt| receipt.kind == "surface.read")
                .count(),
            2
        );
        assert!(session.attach().is_err());
        drop((document, surface, cursor, session));
        let original = root.path().join(format!("original-{}", case.name));
        let archive = Archive::open(&original).await?;
        let reference = archive.write(&outcome).await?;
        let source_file = root.path().join(format!("{}.yosoi", case.name));
        archive.export_file(&reference, &source_file).await?;
        assert!(archive.export_file(&reference, &source_file).await.is_err());
        drop((archive, outcome, reference));
        fs::remove_dir_all(original)?;
        let moved = root.path().join(format!("moved-{}.yosoi", case.name));
        fs::rename(source_file, &moved)?;
        let fresh = Archive::open(root.path().join(format!("fresh-{}", case.name))).await?;
        let reference = fresh.import_file(&moved).await?;
        let saved = fresh.read(&reference).await?;
        let restored = saved.surface(&identity, Limits::default())?;
        assert_eq!(restored.identity(), identity);
        assert_eq!(
            restored.inspect(&target, None, Budget::default())?.content,
            expected
        );
        let reader = Session::new(restored, SessionPolicy::default())?;
        assert!(reader.hot_owner()?.is_none());
    }
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Behavioral regression assertions; setup errors propagate."
)]
async fn corrupt_truncated_and_unknown_version_files_are_rejected() -> Result {
    use sha2::{Digest, Sha256};
    let root = tempfile::tempdir()?;
    let archive = Archive::open(root.path().join("store")).await?;
    let session = Session::new(prepared("<button>Go</button>")?, policy())?;
    let outcome = session
        .close()?
        .ok_or_else(|| io::Error::other("outcome absent"))?;
    let reference = archive.write(&outcome).await?;
    let good = root.path().join("good.yosoi");
    archive.export_file(&reference, &good).await?;
    let bytes = fs::read(&good)?;
    let mut future: serde_json::Value = serde_json::from_slice(
        bytes
            .get(48..)
            .ok_or_else(|| io::Error::other("payload missing"))?,
    )?;
    future
        .as_object_mut()
        .ok_or_else(|| io::Error::other("outcome missing"))?
        .insert("version".into(), serde_json::json!(2));
    let payload = serde_json::to_vec(&future)?;
    let mut future_file = bytes
        .get(..16)
        .ok_or_else(|| io::Error::other("header missing"))?
        .to_vec();
    future_file.extend_from_slice(&Sha256::digest(&payload));
    future_file.extend_from_slice(&payload);
    let mut changed = bytes.clone();
    *changed
        .last_mut()
        .ok_or_else(|| io::Error::other("empty file"))? ^= 1;
    let mut unknown = bytes.clone();
    *unknown
        .get_mut(15)
        .ok_or_else(|| io::Error::other("missing header"))? = 2;
    for (name, data) in [
        ("outcome-schema", future_file),
        ("corrupt", changed),
        ("version", unknown),
        ("truncated", bytes.into_iter().take(50).collect()),
    ] {
        let path = root.path().join(name);
        fs::write(&path, data)?;
        assert!(archive.import_file(path).await.is_err());
    }
    let oversized = root.path().join("oversized");
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&oversized)?
        .set_len(256 * 1024 * 1024 + 49)?;
    assert!(archive.import_file(oversized).await.is_err());
    assert!(
        !fs::read_dir(root.path())?
            .filter_map(StdResult::ok)
            .any(|entry| entry
                .file_name()
                .to_string_lossy()
                .starts_with(".yosoi-export-"))
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Behavioral regression assertions; setup errors propagate."
)]
fn limits_policy_off_and_abandoned_effects_preserve_the_truth() -> Result {
    let index = prepared("<button>Go</button>")?;
    assert!(
        Session::new(index.clone(), SessionPolicy::default())?
            .outcome()?
            .is_none()
    );
    let session = Session::new(index.clone(), policy())?;
    let cursor = session.cursor()?;
    session.attach()?;
    cursor.promote()?;
    let target = index
        .find("Go", None, Budget::default())?
        .entries
        .first()
        .ok_or_else(|| io::Error::other("target absent"))?
        .reference
        .clone();
    cursor.focus(&target)?;
    let mut lease = cursor.begin_action()?;
    lease.mark_dispatched()?;
    drop(lease);
    let outcome = session
        .close()?
        .ok_or_else(|| io::Error::other("outcome absent"))?;
    assert!(
        outcome
            .record
            .operations()
            .iter()
            .any(|receipt| receipt.kind == "surface.action"
                && receipt.status == OperationStatus::Unknown)
    );
    let limited = Session::new(
        index,
        SessionPolicy {
            archive_limits: ArchiveLimits {
                observations: 1,
                ..ArchiveLimits::default()
            },
            ..policy()
        },
    )?;
    limited.attach()?;
    assert!(limited.publish(prepared("<p>changed</p>")?).is_err());
    let partial = limited
        .close()?
        .ok_or_else(|| io::Error::other("outcome absent"))?;
    assert!(!partial.complete);
    partial.validate()?;
    Ok(())
}

#[cfg(any(feature = "browser", feature = "surface-images"))]
#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Behavioral regression assertions; setup errors propagate."
)]
async fn combined_document_and_image_restore_the_same_pixels_and_references() -> Result {
    use image::{DynamicImage, ImageFormat, Rgba, RgbaImage};
    let image = DynamicImage::ImageRgba8(RgbaImage::from_pixel(64, 64, Rgba([17, 91, 203, 255])));
    let mut encoded = io::Cursor::new(Vec::new());
    image.write_to(&mut encoded, ImageFormat::Png)?;
    let pixels = Surface::from_image(encoded.get_ref(), 32, Limits::default())?;
    let combined = Surface::combine(
        "document plus screenshot",
        vec![
            ("document".into(), prepared("<h1>Version</h1>")?),
            ("screenshot".into(), pixels.clone()),
        ],
        Limits::default(),
    )?;
    let projected = combined.project("screenshot", &pixels.root())?;
    let expected = combined.crop(&projected, 4096)?.png().to_vec();
    let identity = combined.identity().to_owned();
    let session = Session::new(combined, policy())?;
    let outcome = session
        .close()?
        .ok_or_else(|| io::Error::other("outcome absent"))?;
    let root = tempfile::tempdir()?;
    let archive = Archive::open(root.path().join("store")).await?;
    let reference = archive.write(&outcome).await?;
    archive
        .export_file(&reference, root.path().join("image.yosoi"))
        .await?;
    let fresh = Archive::open(root.path().join("fresh")).await?;
    let reference = fresh.import_file(root.path().join("image.yosoi")).await?;
    let saved = fresh.read(&reference).await?;
    let restored = saved.surface(&identity, Limits::default())?;
    assert_eq!(restored.identity(), identity);
    assert_eq!(restored.crop(&projected, 4096)?.png(), expected);
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Behavioral regression assertions; setup errors propagate."
)]
async fn normal_write_rehomes_dependency_references_and_keeps_compiled_plans() -> Result {
    use yosoi::{
        automation_record::{AutomationRecord, OperationReceipt, OperationStatus},
        locators::{Plan, output, tree_text_contains},
        surface::{ArchivedSource, Outcome},
    };
    let root = tempfile::tempdir()?;
    let original = root.path().join("original");
    let archive = Archive::open(&original).await?;
    let document = Document::html("fixture", b"<h1>Version</h1>".to_vec())?;
    let surface = Surface::new(&document)?;
    let source = archive.write_document(&document).await?;
    let mut outcome = Outcome::new("closure", ArchiveLimits::default())?;
    outcome = outcome.with_source(ArchivedSource::new(
        source.to_string(),
        &document,
        Some(&surface),
    ))?;
    outcome.record = AutomationRecord::new(
        "closure",
        Vec::new(),
        vec![OperationReceipt {
            browser: None,
            id: "capture-1".into(),
            kind: "surface.capture".into(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({"document":source,"surface":surface.identity()})),
            observation: None,
            error: None,
        }],
    )?;
    let plan = Plan::new([output("version", tree_text_contains("Version")?.text())?])?;
    outcome.plans.push(plan.clone());
    let fresh = Archive::open(root.path().join("fresh")).await?;
    let saved = fresh.write(&outcome).await?;
    drop(archive);
    fs::remove_dir_all(original)?;
    let loaded = fresh.read(&saved).await?;
    assert_eq!(loaded.plans, vec![plan]);
    let retained = loaded
        .sources
        .first()
        .ok_or_else(|| io::Error::other("missing source"))?;
    assert_eq!(retained.key, source.to_string());
    let reference = retained
        .document_archive
        .as_ref()
        .ok_or_else(|| io::Error::other("rehomed Document reference missing"))?;
    assert_ne!(reference, &source);
    assert_eq!(fresh.read_document(reference).await?, document);
    let rehomed_key = reference.to_string();
    assert_eq!(
        loaded
            .surface(&source.to_string(), Limits::default())?
            .identity(),
        surface.identity()
    );
    assert_eq!(
        loaded.surface(&rehomed_key, Limits::default())?.identity(),
        surface.identity()
    );
    assert_eq!(
        loaded
            .record
            .operations()
            .first()
            .and_then(|receipt| receipt.result.as_ref())
            .and_then(|result| result.get("document"))
            .and_then(serde_json::Value::as_str),
        Some(rehomed_key.as_str())
    );
    let mut missing = loaded;
    missing.sources.clear();
    assert!(fresh.write(&missing).await.is_err());
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "The regression verifies logical keys stay stable while known Archive references are rehomed."
)]
async fn normal_write_preserves_logical_source_keys_when_rehoming_references() -> Result {
    use yosoi::{
        automation_record::{AutomationRecord, OperationReceipt, OperationStatus},
        surface::{ArchivedSource, Outcome},
    };

    let root = tempfile::tempdir()?;
    let original_path = root.path().join("original");
    let original = Archive::open(&original_path).await?;
    let document = Document::html("logical-page", b"<h1>Version</h1>".to_vec())?;
    let surface = Surface::new(&document)?;
    let original_reference = original.write_document(&document).await?;
    let mut source = ArchivedSource::new("homepage", &document, Some(&surface));
    source.document_archive = Some(original_reference.clone());
    let mut outcome = Outcome::new("logical-key", ArchiveLimits::default())?.with_source(source)?;
    outcome.record = AutomationRecord::new(
        "logical-key",
        Vec::new(),
        vec![OperationReceipt {
            browser: None,
            id: "capture-1".into(),
            kind: "surface.capture".into(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({
                "document": original_reference.to_string(),
                "surface": surface.identity(),
            })),
            observation: None,
            error: None,
        }],
    )?;

    let label_document = Document::text("logical-archive-label", b"logical payload".to_vec())?;
    let reference_shaped_label = original.write_document(&label_document).await?.to_string();
    outcome = outcome.with_source(ArchivedSource::new(
        reference_shaped_label.clone(),
        &label_document,
        None,
    ))?;

    let fresh = Archive::open(root.path().join("fresh")).await?;
    let saved = fresh.write(&outcome).await?;
    drop(original);
    fs::remove_dir_all(original_path)?;
    let loaded = fresh.read(&saved).await?;
    let retained = loaded
        .sources
        .first()
        .ok_or_else(|| io::Error::other("logical source missing"))?;
    assert_eq!(retained.key, "homepage");
    let fresh_reference = retained
        .document_archive
        .as_ref()
        .ok_or_else(|| io::Error::other("rehomed Archive reference missing"))?;
    assert_ne!(fresh_reference, &original_reference);
    let fresh_reference = fresh_reference.to_string();
    assert_eq!(
        loaded
            .record
            .operations()
            .first()
            .and_then(|receipt| receipt.result.as_ref())
            .and_then(|result| result.get("document"))
            .and_then(serde_json::Value::as_str),
        Some(fresh_reference.as_str())
    );
    assert_eq!(
        loaded.surface("homepage", Limits::default())?.identity(),
        surface.identity()
    );
    assert_eq!(
        loaded.source_document("homepage", ArchiveLimits::default().bytes)?,
        document
    );
    assert_eq!(
        loaded.source_document(&fresh_reference, ArchiveLimits::default().bytes)?,
        document
    );
    assert_eq!(
        loaded
            .surface(&fresh_reference, Limits::default())?
            .identity(),
        surface.identity()
    );
    let label_source = loaded
        .sources
        .iter()
        .find(|source| source.key == reference_shaped_label)
        .ok_or_else(|| io::Error::other("reference-shaped logical label was rewritten"))?;
    assert_eq!(label_source.restore(1024)?, label_document);
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "The regression verifies typed-file Archive references are rehomed and remain lookup keys."
)]
async fn normal_write_keeps_typed_file_keys_and_rehomes_storage_references() -> Result {
    use yosoi::{
        archive::FileDocumentArchiveRef,
        documents::{FileDocument, VideoDocument},
        surface::{ArchivedSource, Outcome},
    };

    const MP4_SIGNATURE: [u8; 12] = [0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2'];
    let root = tempfile::tempdir()?;
    let original_path = root.path().join("original");
    let original = Archive::open(&original_path).await?;
    let video = VideoDocument::from_bytes("typed-video", MP4_SIGNATURE.to_vec())?;
    let original_reference = FileDocumentArchiveRef::Video(original.write(&video).await?);
    let mut source = ArchivedSource::new_file_document(
        original_reference.to_string(),
        &FileDocument::Video(video.clone()),
        None,
    );
    source.file_archive = Some(original_reference.clone());
    let outcome = Outcome::new("typed-file-key", ArchiveLimits::default())?.with_source(source)?;

    let fresh = Archive::open(root.path().join("fresh")).await?;
    let saved = fresh.write(&outcome).await?;
    drop(original);
    fs::remove_dir_all(original_path)?;
    let loaded = fresh.read(&saved).await?;
    let retained = loaded
        .sources
        .first()
        .ok_or_else(|| io::Error::other("typed file source missing"))?;
    let fresh_reference = retained
        .file_archive
        .as_ref()
        .ok_or_else(|| io::Error::other("rehomed typed-file Archive reference missing"))?;
    assert_ne!(fresh_reference, &original_reference);
    assert_eq!(retained.key, original_reference.to_string());
    assert_eq!(
        loaded.source_file_document(&retained.key, ArchiveLimits::default().bytes)?,
        FileDocument::Video(video.clone())
    );
    assert_eq!(
        loaded
            .source_file_document(&fresh_reference.to_string(), ArchiveLimits::default().bytes)?,
        FileDocument::Video(video)
    );
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "The regression verifies exact logical-key lookup outranks another source's Archive reference."
)]
async fn exact_logical_source_key_wins_over_archive_reference_collision() -> Result {
    use yosoi::surface::{ArchivedSource, Outcome};

    let root = tempfile::tempdir()?;
    let archive = Archive::open(root.path()).await?;
    let stored_document = Document::html("stored-document", b"<h1>Stored</h1>".to_vec())?;
    let stored_reference = archive.write_document(&stored_document).await?;
    let stored_surface = Surface::new(&stored_document)?;
    let logical_document = Document::html("logical-document", b"<h1>Logical</h1>".to_vec())?;
    let logical_surface = Surface::new(&logical_document)?;

    let stored_source = ArchivedSource::new("stored", &stored_document, Some(&stored_surface));
    let mut stored_source = stored_source;
    stored_source.document_archive = Some(stored_reference.clone());
    let logical_source = ArchivedSource::new(
        stored_reference.to_string(),
        &logical_document,
        Some(&logical_surface),
    );
    let outcome = Outcome::new("archive-key-collision", ArchiveLimits::default())?
        .with_source(stored_source)?
        .with_source(logical_source)?;

    assert_eq!(
        outcome
            .source_document(
                &stored_reference.to_string(),
                ArchiveLimits::default().bytes
            )?
            .bytes(),
        logical_document.bytes()
    );
    assert_eq!(
        outcome
            .surface(&stored_reference.to_string(), Limits::default())?
            .identity(),
        logical_surface.identity()
    );
    assert_eq!(
        outcome
            .surface(logical_surface.identity(), Limits::default())?
            .identity(),
        logical_surface.identity()
    );
    assert_eq!(
        outcome.surface("stored", Limits::default())?.identity(),
        stored_surface.identity()
    );
    Ok(())
}
