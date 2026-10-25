//! Surface recording uses existing immutable Documents and AutomationRecords.
use super::connection::Result;
use super::{ExecutionError, SurfacePolicy};
use crate::{
    Archive,
    archive::DocumentArchiveRef,
    automation_record::{
        AutomationRecord, AutomationRecordRef, Observation, OperationReceipt, OperationStatus,
    },
    surface::{ArchiveLimits, ArchivedSource, Outcome, OutcomeRef, Surface},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::result::Result as StdResult;
use std::{
    fs,
    io::{self, Read, Write},
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Handle {
    pub(super) schema: String,
    pub(super) archive: PathBuf,
    pub(super) record: AutomationRecordRef,
    #[serde(default)]
    pub(super) outcome: Option<OutcomeRef>,
}
#[derive(Debug)]
pub(super) struct Recording {
    pub(super) archive: Archive,
    pub(super) outcome: Outcome,
    pub(super) output: PathBuf,
    pub(super) handle: Option<Handle>,
    pub(super) sequence: u64,
    pub(super) pending: Option<Value>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Capture {
    pub(super) schema: String,
    pub(super) document: DocumentArchiveRef,
    pub(super) surface: String,
    pub(super) normalized_strings: Value,
}
impl Recording {
    pub(super) const fn fault(&mut self) {
        self.outcome.complete = false;
    }
    pub(super) fn outcome(&self) -> Outcome {
        self.outcome.clone()
    }
    pub(super) const fn set_limits(&mut self, limits: ArchiveLimits) {
        self.outcome.limits = limits;
    }

    pub(super) async fn dispatch(&mut self, command: Value) -> Result<()> {
        if self.pending.is_some() {
            return Err(io::Error::other(
                "an earlier dispatch remains unresolved; close and inspect its outcome",
            )
            .into());
        }
        self.push("surface.dispatch", OperationStatus::Unknown, json!({"command":command,"note":"effect prepared; possible dispatch remains unknown until a matching receipt"}),None,None)?;
        self.pending = Some(command);
        self.checkpoint().await?;
        Ok(())
    }
    pub(super) async fn failure(&mut self, error: &str) -> Result<()> {
        self.push(
            "surface.failure",
            OperationStatus::Unknown,
            json!({"stage":"rerun"}),
            None,
            Some(error.chars().take(1024).collect()),
        )?;
        self.checkpoint().await?;
        Ok(())
    }
    pub(super) fn abandon_pending(&mut self) -> Result<()> {
        if let Some(command) = self.pending.take() {
            self.push("surface.command",OperationStatus::Unknown,json!({"command":command,"outcome":{"receipt":{"status":"Unconfirmed"}},"note":"command interrupted after possible dispatch"}),None,None)?;
        }
        Ok(())
    }
    pub(super) fn push(
        &mut self,
        kind: &str,
        status: OperationStatus,
        result: Value,
        observation: Option<Observation>,
        error: Option<String>,
    ) -> Result<()> {
        if self.outcome.record.operations().len() >= self.outcome.limits.operations {
            self.outcome.complete = false;
            return Err(io::Error::other(
                "archive operation limit exhausted; outcome is incomplete",
            )
            .into());
        }
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("record sequence exhausted"))?;
        let result = self.outcome.record.push_operation(OperationReceipt {
            id: format!("{}:{}", self.outcome.record.id(), self.sequence),
            kind: kind.into(),
            status,
            result: Some(result),
            observation,
            error,
        });
        if result.is_err() {
            self.outcome.complete = false;
        }
        result?;
        Ok(())
    }

    pub(super) async fn command(&mut self, command: Value, result: &Result<Value>) -> Result<()> {
        if self.pending.as_ref() == Some(&command) {
            self.pending = None;
        } else {
            self.abandon_pending()?;
        }
        let (status, outcome, error) = match result {
            Ok(value) => {
                let status = match value
                    .get("receipt")
                    .and_then(|r| r.get("status"))
                    .and_then(Value::as_str)
                {
                    Some("Rejected") => OperationStatus::Rejected,
                    Some("Unconfirmed") => OperationStatus::Unknown,
                    _ => OperationStatus::Observed,
                };
                (status, value.clone(), None)
            }
            Err(error) => (
                if matches!(
                    command.get("op").and_then(Value::as_str),
                    Some("click" | "fill" | "key" | "scroll" | "navigate")
                ) {
                    OperationStatus::Unknown
                } else {
                    OperationStatus::Rejected
                },
                Value::Null,
                Some(error.to_string().chars().take(1024).collect()),
            ),
        };
        self.push(
            "surface.command",
            status,
            json!({"command":command,"outcome":outcome}),
            None,
            error,
        )?;
        self.checkpoint().await?;
        Ok(())
    }
    pub(super) async fn checkpoint(&mut self) -> Result<Handle> {
        let handle = Handle {
            schema: "yosoi.surface.record-handle.v1".into(),
            archive: self.archive.root().to_owned(),
            record: self.outcome.record.write_to(&self.archive).await?,
            outcome: Some(self.archive.write(&self.outcome).await?),
        };
        let mut temporary = tempfile::NamedTempFile::new_in(&self.output)?;
        temporary.write_all(&serde_json::to_vec_pretty(&handle)?)?;
        temporary.as_file().sync_all()?;
        temporary.persist(self.output.join("record.json"))?;
        self.handle = Some(handle.clone());
        Ok(handle)
    }

    pub(super) async fn finalize(&mut self) -> Result<()> {
        self.outcome.sealed = true;
        let handle = self.checkpoint().await?;
        let reference = handle
            .outcome
            .as_ref()
            .ok_or_else(|| io::Error::other("outcome handle missing"))?;
        self.archive
            .export_file(reference, self.output.join("surface.yosoi"))
            .await?;
        Ok(())
    }
    pub(super) fn status(&self) -> Value {
        json!({"mode":"archive","archive":self.archive.root(),"portable_file":self.output.join("surface.yosoi"),"handle_file":self.output.join("record.json"),"handle":self.handle})
    }
}
pub(super) struct Loaded {
    pub(super) archive: Archive,
    pub(super) record: AutomationRecord,
    pub(super) outcome: Option<Outcome>,
    // Own the imported store until all replay/rerun consumers have finished.
    _temporary: Option<tempfile::TempDir>,
}

pub(super) async fn load(path: &Path) -> Result<Loaded> {
    let mut prefix = [0_u8; 13];
    let mut file = fs::File::open(path)?;
    let portable = match file.read_exact(&mut prefix) {
        Ok(()) => &prefix == b"YOSOI-SURFACE",
        Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => false,
        Err(error) => return Err(error.into()),
    };
    if portable {
        let temporary = tempfile::tempdir()?;
        let archive = Archive::open(temporary.path()).await?;
        let reference = archive.import_file(path).await?;
        let outcome = archive.read(&reference).await?;
        return Ok(Loaded {
            archive,
            record: outcome.record.clone(),
            outcome: Some(outcome),
            _temporary: Some(temporary),
        });
    }
    if fs::metadata(path)?.len() > 64 * 1024 {
        return Err(io::Error::other("record handle exceeds 64 KiB").into());
    }
    let bytes = fs::read(path)?;
    if bytes.len() > 64 * 1024 {
        return Err(io::Error::other("record handle exceeds 64 KiB").into());
    }
    let handle: Handle = serde_json::from_slice(&bytes)?;
    if handle.schema != "yosoi.surface.record-handle.v1" {
        return Err(io::Error::other("unsupported surface record handle").into());
    }
    if !handle.archive.is_dir() {
        return Err(io::Error::other("recorded Archive directory is unavailable").into());
    }
    let archive = Archive::open(&handle.archive).await?;
    let record = AutomationRecord::read_from(&archive, &handle.record).await?;
    let outcome = if let Some(reference) = handle.outcome {
        Some(archive.read(&reference).await?)
    } else {
        None
    };
    Ok(Loaded {
        archive,
        record,
        outcome,
        _temporary: None,
    })
}

pub(super) async fn export_raw(path: &Path, output: &Path) -> Result<()> {
    let loaded = load(path).await?;
    if let Some(outcome) = &loaded.outcome {
        let reference = loaded.archive.write(outcome).await?;
        loaded.archive.export_file(&reference, output).await?;
        return Ok(());
    }
    let mut outcome = Outcome::new(loaded.record.id(), ArchiveLimits::default())?;
    outcome.record = loaded.record;
    for receipt in outcome.record.operations() {
        if matches!(
            receipt.kind.as_str(),
            "surface.capture" | "surface.video.source" | "surface.video.frame"
        ) {
            let key = receipt
                .result
                .as_ref()
                .and_then(|value| value.get("document"))
                .and_then(Value::as_str)
                .ok_or_else(|| io::Error::other("missing evidence document"))?;
            let reference: DocumentArchiveRef = key.parse()?;
            let document = loaded.archive.read_document(&reference).await?;
            let identity = if receipt.kind == "surface.capture" {
                Some(Surface::new(&document)?)
            } else {
                None
            };
            outcome
                .sources
                .push(ArchivedSource::new(key, &document, identity.as_ref()));
        }
    }
    // Legacy captures can refer to the same exact immutable occurrence.
    outcome
        .sources
        .sort_by(|left, right| left.key.cmp(&right.key));
    outcome
        .sources
        .dedup_by(|left, right| left.key == right.key);
    outcome.sealed = outcome
        .record
        .operations()
        .iter()
        .any(|receipt| receipt.kind == "surface.closed");
    let reference = loaded.archive.write(&outcome).await?;
    loaded.archive.export_file(&reference, output).await?;
    Ok(())
}
pub(super) fn capture_descriptors(record: &AutomationRecord) -> Result<Vec<Capture>> {
    record
        .operations()
        .iter()
        .filter(|op| op.kind == "surface.capture")
        .map(|op| {
            let value = op
                .result
                .clone()
                .ok_or_else(|| io::Error::other("capture descriptor missing"))?;
            let capture: Capture = serde_json::from_value(value)?;
            if capture.schema != "yosoi.surface.capture.v1" {
                return Err(io::Error::other("unsupported archived surface capture").into());
            }
            Ok(capture)
        })
        .collect()
}
pub(super) async fn replay_raw(
    path: &Path,
    repeat: usize,
    query: Option<&str>,
    output: Option<&Path>,
) -> Result<Value> {
    if !(1..=100).contains(&repeat) {
        return Err(io::Error::other("repeat must be 1..100").into());
    }
    let loaded = load(path).await?;
    if loaded.outcome.as_ref().is_some_and(|value| !value.complete) {
        return Err(io::Error::other("portable outcome is incomplete; inspect it through the SDK instead of claiming complete replay").into());
    }
    if loaded
        .record
        .operations()
        .iter()
        .any(|op| op.kind == "surface.video.source")
    {
        #[cfg(feature = "surface-video")]
        {
            return super::video::archive::replay_loaded(
                &loaded.archive,
                &loaded.record,
                repeat,
                query,
                output,
            )
            .await;
        }
        #[cfg(not(feature = "surface-video"))]
        {
            return Err(io::Error::other("video replay requires surface-video").into());
        }
    }
    super::browser::archive::replay_loaded(&loaded, repeat, query).await
}
/// Verifies and reconstructs saved observations without starting source processes.
/// Saved video pixels require neither a browser nor a decoder.
pub async fn replay(
    path: impl AsRef<Path>,
    repeat: usize,
    query: Option<&str>,
    output: Option<&Path>,
) -> StdResult<Value, ExecutionError> {
    replay_raw(path.as_ref(), repeat, query, output)
        .await
        .map_err(ExecutionError::Operation)
}
/// Exports a persisted handle or portable outcome into one immutable flat file.
pub async fn export(
    path: impl AsRef<Path>,
    output: impl AsRef<Path>,
) -> StdResult<(), ExecutionError> {
    export_raw(path.as_ref(), output.as_ref())
        .await
        .map_err(ExecutionError::Operation)
}
#[cfg(feature = "browser")]
impl Outcome {
    /// Reruns a confirmed browser procedure with fresh evidence and default isolated headless sessions.
    /// Each attempt retains its own outcome, including failed or incomplete executions.
    pub async fn rerun(
        &self,
        policy: SurfacePolicy,
        count: usize,
    ) -> StdResult<Vec<Self>, ExecutionError> {
        super::browser::archive::rerun(self, policy, count, true).await
    }
}

#[cfg(test)]
mod tests {
    use super::{OperationStatus, Recording, Result, load};
    use serde_json::json;
    use std::io;
    #[tokio::test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Regression assertions; fixture errors propagate."
    )]
    async fn interrupted_dispatch_is_archivable_and_cannot_disappear_at_close() -> Result<()> {
        let root = tempfile::tempdir()?;
        let mut recording = Recording::open(
            &root.path().join("archive"),
            root.path(),
            "https://example.invalid/",
        )
        .await?;
        let command = json!({"op":"click","reference":{"capture":"old","node":0}});
        recording.dispatch(command.clone()).await?;
        assert!(recording.dispatch(command.clone()).await.is_err());
        assert!(
            recording
                .outcome()
                .record
                .operations()
                .iter()
                .any(|receipt| receipt.kind == "surface.dispatch"
                    && receipt.status == OperationStatus::Unknown)
        );
        recording.failure("target became ambiguous").await?;
        recording.close(&Ok(())).await?;
        let loaded = load(&root.path().join("surface.yosoi")).await?;
        assert!(
            loaded
                .record
                .operations()
                .iter()
                .any(|receipt| receipt.error.as_deref() == Some("target became ambiguous"))
        );
        let interrupted = loaded
            .record
            .operations()
            .iter()
            .find(|receipt| receipt.kind == "surface.command")
            .ok_or_else(|| io::Error::other("interrupted command absent"))?;
        assert_eq!(interrupted.status, OperationStatus::Unknown);
        assert_eq!(
            interrupted
                .result
                .as_ref()
                .and_then(|value| value.get("command")),
            Some(&command)
        );
        Ok(())
    }
}
