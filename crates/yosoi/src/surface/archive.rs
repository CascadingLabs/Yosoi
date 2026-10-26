//! Surface recording uses existing immutable Documents and AutomationRecords.
use super::connection::Result;
use crate::{
    Archive,
    archive::DocumentArchiveRef,
    automation_record::{
        AutomationRecord, AutomationRecordRef, Observation, OperationReceipt, OperationStatus,
    },
    surface::{Budget, Limits, Surface},
    view::View,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::result::Result as StdResult;
use std::{
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
};

/// Reference to retained evidence; reopening never grants live authority.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchiveReceipt {
    /// Persisted receipt format.
    pub schema: String,
    /// Directory containing immutable archive values.
    pub archive: PathBuf,
    /// Exact retained operation record.
    pub record: AutomationRecordRef,
}
#[derive(Debug)]
pub(super) struct Recording {
    pub(super) archive: Archive,
    pub(super) record: AutomationRecord,
    pub(super) output: PathBuf,
    pub(super) handle: Option<ArchiveReceipt>,
    pub(super) sequence: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Capture {
    pub schema: String,
    pub document: DocumentArchiveRef,
    pub surface: String,
    pub normalized_strings: Value,
}
impl Recording {
    pub(super) fn receipt(&self) -> Option<ArchiveReceipt> {
        self.handle.clone()
    }

    pub(super) fn push(
        &mut self,
        kind: &str,
        status: OperationStatus,
        result: Value,
        observation: Option<Observation>,
        error: Option<String>,
    ) -> Result<()> {
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("record sequence exhausted"))?;
        self.record.push_operation(OperationReceipt {
            id: format!("{}:{}", self.record.id(), self.sequence),
            kind: kind.into(),
            status,
            result: Some(result),
            observation,
            error,
        })?;
        Ok(())
    }

    pub async fn command(&mut self, command: Value, result: &Result<Value>) -> Result<()> {
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
                OperationStatus::Rejected,
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
    pub async fn checkpoint(&mut self) -> Result<ArchiveReceipt> {
        let handle = ArchiveReceipt {
            schema: "yosoi.surface.record-handle.v1".into(),
            archive: self.archive.root().to_owned(),
            record: self.record.write_to(&self.archive).await?,
        };
        let mut temporary = tempfile::NamedTempFile::new_in(&self.output)?;
        temporary.write_all(&serde_json::to_vec_pretty(&handle)?)?;
        temporary.as_file().sync_all()?;
        temporary.persist(self.output.join("record.json"))?;
        self.handle = Some(handle.clone());
        Ok(handle)
    }

    pub fn status(&self) -> Value {
        json!({"mode":"archive","archive":self.archive.root(),"handle_file":self.output.join("record.json"),"handle":self.handle})
    }
}
pub(super) async fn load(path: &Path) -> Result<(Archive, AutomationRecord)> {
    if fs::metadata(path)?.len() > 64 * 1024 {
        return Err(io::Error::other("record handle exceeds 64 KiB").into());
    }
    let bytes = fs::read(path)?;
    if bytes.len() > 64 * 1024 {
        return Err(io::Error::other("record handle exceeds 64 KiB").into());
    }
    let handle: ArchiveReceipt = serde_json::from_slice(&bytes)?;
    if handle.schema != "yosoi.surface.record-handle.v1" {
        return Err(io::Error::other("unsupported surface record handle").into());
    }
    if !handle.archive.is_dir() {
        return Err(io::Error::other("recorded Archive directory is unavailable").into());
    }
    let archive = Archive::open(&handle.archive).await?;
    let record = AutomationRecord::read_from(&archive, &handle.record).await?;
    Ok((archive, record))
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
    let (archive, record) = load(path).await?;
    if record
        .operations()
        .iter()
        .any(|op| op.kind == "surface.video.source")
    {
        return super::video::archive::replay_loaded(&archive, &record, repeat, query, output)
            .await;
    }
    let captures = capture_descriptors(&record)?;
    if captures.is_empty() {
        return Err(io::Error::other("record has no captured surfaces").into());
    }
    let mut last = None;
    for _ in 0..repeat {
        for capture in &captures {
            let document = archive.read_document(&capture.document).await?;
            let surface = Surface::with_limits(
                &document,
                Limits {
                    input_bytes: 32 * 1024 * 1024,
                    ..Limits::default()
                },
            )?;
            if surface.identity() != capture.surface {
                return Err(io::Error::other(
                    "restored surface identity differs from recorded identity",
                )
                .into());
            }
            last = Some(surface);
        }
        for observation in record.observations() {
            View::from_observation(observation, 20)?;
        }
    }
    let last = last.ok_or_else(|| io::Error::other("last surface absent"))?;
    let matches = query
        .map(|q| {
            last.find(
                q,
                None,
                Budget {
                    bytes: 2048,
                    items: 5,
                },
            )
        })
        .transpose()?;
    let mut actions: Vec<_> = record
        .operations()
        .iter()
        .filter(|op| {
            op.kind == "surface.command"
                && op
                    .result
                    .as_ref()
                    .and_then(|v| v.get("outcome"))
                    .and_then(|v| v.get("receipt"))
                    .is_some()
        })
        .map(|op| json!({"id":op.id,"status":op.status}))
        .collect();
    let actions_omitted = actions.len().saturating_sub(8);
    actions.truncate(8);
    Ok(
        json!({"mode":"offline","browser_started":false,"controllable":false,"record":record.id(),"iterations":repeat,"captures":captures.len(),"offline_views":record.observations().len(),"last_capture":last.identity(),"last_url":record.observations().last().and_then(|observation|observation.url.as_ref()),"actions":actions,"actions_omitted":actions_omitted,"matches":matches}),
    )
}

/// Reconstructs retained evidence offline without starting a browser or decoder.
pub async fn replay(
    path: &Path,
    repeat: usize,
    query: Option<&str>,
    output: Option<&Path>,
) -> StdResult<Value, super::ExecutionError> {
    replay_raw(path, repeat, query, output)
        .await
        .map_err(super::ExecutionError::Operation)
}
