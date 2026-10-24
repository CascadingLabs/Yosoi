//! Acquire a live HTML document, inspect bounded evidence and restore it from Archive.
use std::{env, error::Error, io};
use yosoi::{
    Archive,
    documents::DocumentRef,
    request::{self, Attempt},
    surface::{
        Budget, Surface,
        model::{ReadOperation, ReadRequest, SourceId, SurfaceRead},
        web::WebSurface,
    },
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let url = args
        .next()
        .unwrap_or_else(|| "https://qscrape.dev/eshop/html/product/obj-001/".into());
    let query = args.next().unwrap_or_else(|| "lamp".into());
    let root = args.next().unwrap_or_else(|| "surface-evidence".into());
    let response = request::new(url.clone()).send().await?;
    let document = response
        .attempts()
        .flat_map(Attempt::documents)
        .find_map(|item| item.outcome().document().map(DocumentRef::to_owned))
        .ok_or_else(|| io::Error::other("acquisition returned no retained document"))?;
    let index = Surface::new(&document)?;
    let web = WebSurface::new(index.clone(), SourceId::new(url)?)?;
    let result = web.read(&ReadRequest {
        operation: ReadOperation::Search { query },
        budget: Budget::default(),
        continuation: None,
    })?;
    let archive = Archive::open(root).await?;
    let reference = archive.write_document(&document).await?;
    let restored = Surface::new(&archive.read_document(&reference).await?)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "descriptor":web.descriptor(), "result":result, "archive_reference":reference,
            "same_observation":restored.identity()==index.identity(), "node_count":index.node_count()
        }))?
    );
    Ok(())
}
