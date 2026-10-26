//! Emit canonical Surface evidence for the shared Python/Rust input vectors.
use serde::Deserialize;
use serde_json::json;
use std::{env, error::Error, fs, io};
use yosoi::{
    Archive,
    documents::{Document, DocumentEpoch},
    surface::{ArchiveLimits, ArchivedSource, Budget, Limits, Outcome, SessionPolicy, Surface},
};

#[derive(Deserialize)]
struct Vectors {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    name: String,
    format: String,
    content: String,
    query: String,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let path = env::args()
        .nth(1)
        .ok_or_else(|| io::Error::other("expected vector file"))?;
    let vectors: Vectors = serde_json::from_slice(&fs::read(path)?)?;
    let mut values = Vec::new();
    let scratch = tempfile::tempdir()?;
    for (number, case) in vectors.cases.into_iter().enumerate() {
        let bytes = case.content.into_bytes();
        let document = match case.format.as_str() {
            "html" => Document::html(case.name.clone(), bytes)?,
            "xml" => Document::xml(case.name.clone(), bytes)?,
            "json" => Document::json(case.name.clone(), bytes)?,
            "text" => Document::text(case.name.clone(), bytes)?,
            "rendered_dom" => {
                Document::rendered_dom(case.name.clone(), DocumentEpoch::try_from(7)?, bytes)?
            }
            "accessibility_tree" => {
                Document::accessibility_tree(case.name.clone(), DocumentEpoch::try_from(7)?, bytes)?
            }
            _ => return Err(io::Error::other("unsupported vector format").into()),
        };
        let index = Surface::new(&document)?;
        let found = index.find(&case.query, None, Budget::default())?;
        let details = found
            .entries
            .iter()
            .map(|entry| index.inspect(&entry.reference, None, Budget::default()))
            .collect::<Result<Vec<_>, _>>()?;
        let source = ArchivedSource::capture("source", &index)?;
        let direct = ArchivedSource::new("source", &document, Some(&index));
        if source != direct || source.restore(64 * 1024 * 1024)? != document {
            return Err(io::Error::other("retained source differs from original document").into());
        }
        let retained = source.restore_surface(Limits::default())?;
        let outcome = Outcome::new(case.name.clone(), ArchiveLimits::default())?
            .with_source(source.clone())?;
        outcome.validate()?;
        let archive = Archive::open(scratch.path().join(format!("original-{number}"))).await?;
        let reference = archive.write(&outcome).await?;
        let file = scratch.path().join(format!("case-{number}.yosoi"));
        archive.export_file(&reference, &file).await?;
        let fresh = Archive::open(scratch.path().join(format!("fresh-{number}"))).await?;
        let imported = fresh.import_file(file).await?;
        let loaded = fresh.read(&imported).await?;
        let archived = json!({"source":source,"record_id":loaded.record.id(),"version":loaded.version,"sealed":loaded.sealed,"complete":loaded.complete,"limits":loaded.limits,"retained_capture":retained.identity(),"file_capture":loaded.surface("source",Limits::default())?.identity(),"policy":SessionPolicy::default()});
        values.push(json!({"name":case.name, "metadata":{
            "identity":index.identity(),"representation":index.representation(),
            "source_bytes":index.source_bytes(),"node_count":index.node_count(),
            "coverage":index.coverage(),"root":index.root()},
            "overview":index.overview(None,Budget::default())?,"found":found,"details":details,"archive":archived}));
    }
    println!("{}", serde_json::to_string_pretty(&values)?);
    Ok(())
}
