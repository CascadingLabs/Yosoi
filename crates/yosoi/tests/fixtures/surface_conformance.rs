//! Emit canonical Surface evidence for the shared Python/Rust input vectors.
use serde::Deserialize;
use serde_json::json;
use std::{env, error::Error, fs, io};
use yosoi::{
    documents::{Document, DocumentEpoch},
    surface::{Budget, Surface},
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

fn main() -> Result<(), Box<dyn Error>> {
    let path = env::args()
        .nth(1)
        .ok_or_else(|| io::Error::other("expected vector file"))?;
    let vectors: Vectors = serde_json::from_slice(&fs::read(path)?)?;
    let mut values = Vec::new();
    for case in vectors.cases {
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
        values.push(json!({"name":case.name, "metadata":{
            "identity":index.identity(),"representation":index.representation(),
            "source_bytes":index.source_bytes(),"node_count":index.node_count(),
            "coverage":index.coverage(),"root":index.root()},
            "overview":index.overview(None,Budget::default())?,"found":found,"details":details}));
    }
    println!("{}", serde_json::to_string_pretty(&values)?);
    Ok(())
}
