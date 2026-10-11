use std::error::Error;

use crate::internal::engine::prelude as ys;
use tempfile::tempdir;

#[tokio::test]
async fn facade_archives_and_restores_document_without_payload_copy_on_read()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = ys::Archive::open(temporary.path().join(".yosoi")).await?;
    let document = ys::Document::text("product", b"Example product".to_vec())?;
    let plan = ys::Plan::new([ys::output(
        "title",
        ys::text_literal("Example product")?.text(),
    )?])?;
    let policy = ys::Policy::default();
    let immediate = document.bind(&policy).locate(&plan);

    let reference: ys::DocumentArchiveRef = archive.write(document.archive_value()).await?;
    let reopened = ys::Document::from_archived(archive.read(&reference).await?);
    if reopened.bind(&policy).locate(&plan) != immediate {
        return Err("archived facade Document changed its offline locator outcome".into());
    }
    Ok(())
}
