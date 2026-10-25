//! Deliberately rerun a portable web procedure and archive each new outcome.
use std::{env, error::Error, fs, io, path::PathBuf};
use yosoi::{
    Archive,
    surface::{ArchivePolicy, ExecutionError, SurfacePolicy},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error + Send + Sync>> {
    let mut arguments = env::args().skip(1);
    let file = arguments
        .next()
        .ok_or_else(|| io::Error::other("usage: surface_archive_rerun FILE OUTPUT"))?;
    let output = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| io::Error::other("missing output directory"))?,
    );
    fs::create_dir_all(&output)?;
    let archive = Archive::open(output.join("store")).await?;
    let reference = archive.import_file(file).await?;
    let saved = archive.read(&reference).await?;
    let execution = saved
        .rerun(
            SurfacePolicy {
                archive: ArchivePolicy::Enabled,
                output: Some(output.join("executions")),
                ..SurfacePolicy::default()
            },
            1,
        )
        .await;
    let (outcomes, failure) = match execution {
        Ok(outcomes) => (outcomes, None),
        Err(ExecutionError::Execution { outcomes, source }) => (outcomes, Some(source)),
        Err(error) => return Err(error.into()),
    };
    let mut files = Vec::new();
    for (index, outcome) in outcomes.iter().enumerate() {
        let reference = archive.write(outcome).await?;
        let file = output.join(format!("outcome-{index}.yosoi"));
        archive.export_file(&reference, &file).await?;
        files.push(file);
    }
    println!(
        "{}",
        serde_json::json!({"original_run":saved.record.id(),"runs":outcomes.iter().map(|outcome|outcome.record.id()).collect::<Vec<_>>(),"files":files,"failed":failure.is_some()})
    );
    if let Some(error) = failure {
        return Err(error);
    }
    Ok(())
}
