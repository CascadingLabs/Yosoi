//! Archive locator and Contract results as immutable data.

use std::{env, error::Error, io};

use yosoi_dev_support::internal::engine::prelude as ys;
use yosoi_dev_support::internal::engine::{locator, request};

#[derive(ys::Contract)]
#[ys(crate = "yosoi_dev_support::internal::engine")]
#[ys(id = "author", description = "One author result")]
struct Author {
    #[ys(
        description = "Author display name",
        locator = locator::text_literal("John Doe").text()
    )]
    name: String,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let target = env::args().nth(1).ok_or_else(|| {
        io::Error::other(
            "usage: archive_evaluation_results <plain-text-http(s)-url> [archive-root]",
        )
    })?;
    let root = env::args_os().nth(2).unwrap_or_else(|| ".yosoi".into());
    let archive = ys::Archive::open(root).await?;
    let archived = request::new(target).send_archived(&archive).await?;
    let request_run: ys::RequestRunRecord = archive.read(archived.request_run_ref()).await?;
    let (capture, input) = match produced_document(&request_run) {
        Ok(produced) => produced,
        Err(error) => {
            println!("Archived request has no evaluator-ready Document: {error}");
            return Ok(());
        }
    };
    let document = ys::Document::from_archived(archive.read(input.document()).await?);

    let plan_ref = archive.write(Author::plan()?).await?;
    let schema_ref = archive.write(Author::schema()?).await?;
    let evaluation = ys::EvaluationRunRecord::try_new(
        capture,
        archived.policy_ref().clone(),
        plan_ref,
        Some(schema_ref.clone()),
        vec![input.clone()],
    )?;
    let evaluation_ref = archive.write(&evaluation).await?;
    let located = Author::locate(&document)?;
    let locator_ref = archive
        .write(&ys::LocatorRunRecord::new(
            evaluation_ref,
            input.document().clone(),
            located.clone(),
        ))
        .await?;
    let outcome = Author::extract(&located).validate();
    let contract_ref = archive
        .write(&ys::ContractRunRecord::new(
            locator_ref.clone(),
            schema_ref,
            &outcome,
        )?)
        .await?;

    println!("Locator result: {locator_ref}");
    println!("Contract result: {contract_ref}");
    print_author(&archive.read(&contract_ref).await?)?;
    Ok(())
}

fn produced_document(
    run: &ys::RequestRunRecord,
) -> Result<(ys::CaptureArchiveRef, ys::ArchivedDocumentInput), io::Error> {
    let attempt = run
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("RequestRun has no attempt"))?;
    let ys::RequestAttemptOutcome::Completed {
        capture, documents, ..
    } = attempt.outcome()
    else {
        return Err(io::Error::other("request attempt did not complete"));
    };
    let outcome = documents
        .first()
        .ok_or_else(|| io::Error::other("request attempt has no Document"))?;
    let ys::RequestDocumentOutcome::Produced { document } = outcome.outcome() else {
        return Err(io::Error::other("request did not produce a Document"));
    };
    Ok((capture.clone(), document.clone()))
}

fn print_author(result: &ys::ContractRunRecord) -> Result<(), io::Error> {
    let authors: Vec<Author> = result
        .values()
        .map_err(|error| io::Error::other(error.to_string()))?;
    let Some(author) = authors.first() else {
        println!("Archived Contract has no validated author values");
        return Ok(());
    };
    println!("Archived author: {}", author.name);
    Ok(())
}
