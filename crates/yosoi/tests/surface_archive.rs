//! Portable files must survive removal of the original store and session.
// The existing local Archive format is certified only on Unix.
#![cfg(unix)]
use serde::Deserialize;
use std::{error::Error, fs, io, result::Result as StdResult};
use yosoi::{
    Archive,
    documents::{Document, DocumentEpoch},
    surface::{ArchiveLimits, ArchivePolicy, Budget, Limits, Session, SessionPolicy, Surface},
};
use yosoi::{archive::DocumentArchiveRef, automation_record::OperationStatus};

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
    let expected = combined.crop(&projected, 4096)?.png;
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
    assert_eq!(restored.crop(&projected, 4096)?.png, expected);
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
    let reference: DocumentArchiveRef = loaded
        .sources
        .first()
        .ok_or_else(|| io::Error::other("missing source"))?
        .key
        .parse()?;
    assert_ne!(reference.to_string(), source.to_string());
    assert_eq!(fresh.read_document(&reference).await?, document);
    let mut missing = loaded;
    missing.sources.clear();
    assert!(fresh.write(&missing).await.is_err());
    Ok(())
}
