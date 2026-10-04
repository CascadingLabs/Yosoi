//! Execute one explicit archived request and reopen its durable request record.

use std::{env, error::Error, io};

use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let target = env::args()
        .nth(1)
        .ok_or_else(|| io::Error::other("usage: archive_request <http(s)-url> [archive-root]"))?;
    let root = env::args_os().nth(2).unwrap_or_else(|| ".yosoi".into());
    let archive = ys::Archive::open(root).await?;

    let archived = ys::request::new(target).send_archived(&archive).await?;
    println!("Policy: {}", archived.policy_ref());
    println!("Request run: {}", archived.request_run_ref());

    let run: ys::RequestRunRecord = archive.read(archived.request_run_ref()).await?;
    println!(
        "Reopened request {} at {} with {} attempt(s)",
        run.request_id(),
        run.target_origin(),
        run.attempts().len()
    );
    let produced = run
        .attempts()
        .iter()
        .flat_map(|attempt| match attempt.outcome() {
            ys::RequestAttemptOutcome::Completed { documents, .. } => documents.as_slice(),
            ys::RequestAttemptOutcome::Failed { .. }
            | ys::RequestAttemptOutcome::NotStarted { .. } => &[],
        })
        .find_map(|record| match record.outcome() {
            ys::RequestDocumentOutcome::Produced { document } => Some(document),
            ys::RequestDocumentOutcome::Partial { .. }
            | ys::RequestDocumentOutcome::Unavailable { .. }
            | ys::RequestDocumentOutcome::Unprojectable { .. } => None,
        });
    if let Some(input) = produced {
        let document = ys::Document::from_archived(archive.read(input.document()).await?);
        println!(
            "Reopened Document {} ({:?}, {} bytes)",
            document.id(),
            document.class(),
            document.byte_len()
        );
    }
    Ok(())
}
