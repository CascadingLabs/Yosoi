//! Capture once, then reload the same portable evidence in any later process.
use std::{env, error::Error, io, path::PathBuf};
use yosoi::{
    Archive,
    documents::Document,
    surface::{ArchivePolicy, Budget, Limits, Session, SessionPolicy, Surface},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let mode = args
        .next()
        .ok_or_else(|| io::Error::other("usage: surface_archive capture|reload FILE STORE"))?;
    let file = PathBuf::from(
        args.next()
            .ok_or_else(|| io::Error::other("missing portable file path"))?,
    );
    let store = args
        .next()
        .ok_or_else(|| io::Error::other("missing local Archive path"))?;
    let archive = Archive::open(store).await?;
    let reference = match mode.as_str() {
        "capture" => {
            let document = Document::html(
                "versions",
                b"<main><h1>Documentation</h1><button>v0.1.0</button></main>".to_vec(),
            )?;
            let session = Session::new(
                Surface::new(&document)?,
                SessionPolicy {
                    archive: ArchivePolicy::Enabled,
                    ..SessionPolicy::default()
                },
            )?;
            let cursor = session.cursor()?;
            let page = cursor.find("v0.1.0", None, Budget::default())?;
            let entry = page
                .entries
                .first()
                .ok_or_else(|| io::Error::other("version missing"))?;
            cursor.inspect(&entry.reference, None, Budget::default())?;
            cursor.close()?;
            let outcome = session
                .close()?
                .ok_or_else(|| io::Error::other("archive policy is off"))?;
            let reference = archive.write(&outcome).await?;
            archive.export_file(&reference, &file).await?;
            reference
        }
        "reload" => archive.import_file(&file).await?,
        _ => return Err(io::Error::other("mode must be capture or reload").into()),
    };
    let saved = archive.read(&reference).await?;
    let source = saved
        .sources
        .first()
        .ok_or_else(|| io::Error::other("source missing"))?;
    let restored = saved.surface(&source.key, Limits::default())?;
    let page = restored.find("v0.1.0", None, Budget::default())?;
    println!(
        "{}",
        serde_json::json!({"file":file,"capture":restored.identity(),"sealed":saved.sealed,"complete":saved.complete,"operations":saved.record.operations().len(),"matches":page})
    );
    Ok(())
}
