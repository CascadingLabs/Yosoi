//! Surface recording uses existing immutable Documents and AutomationRecords.
use super::Result;
use crate::{
    Archive,
    archive::DocumentArchiveRef,
    automation_record::{
        AutomationRecord, AutomationRecordRef, Observation, OperationReceipt, OperationStatus,
    },
    documents::Document,
    surface::{Budget, Limits, Surface},
    view::View,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
};
use uuid::Uuid;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Handle {
    pub schema: String,
    pub archive: PathBuf,
    pub record: AutomationRecordRef,
}
#[derive(Debug)]
pub struct Recording {
    archive: Archive,
    record: AutomationRecord,
    output: PathBuf,
    handle: Option<Handle>,
    sequence: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capture {
    pub schema: String,
    pub document: DocumentArchiveRef,
    pub surface: String,
    pub normalized_strings: Value,
}
impl Recording {
    pub async fn open(root: &Path, output: &Path, url: &str) -> Result<Self> {
        let archive = Archive::open(root).await?;
        let mut recording = Self {
            archive,
            record: AutomationRecord::new(
                format!("surface-{}", Uuid::new_v4()),
                Vec::new(),
                Vec::new(),
            )?,
            output: output.to_owned(),
            handle: None,
            sequence: 0,
        };
        recording.push("surface.run",OperationStatus::Observed,json!({"schema":"yosoi.surface.run.v1","url":url,"recording_policy":{"mode":"archive","captures":"rendered_dom_and_html","checkpoint":"each_command"}}),None,None)?;
        Ok(recording)
    }
    pub async fn open_video(root: &Path, output: &Path, descriptor: Value) -> Result<Self> {
        let archive = Archive::open(root).await?;
        let mut recording = Self {
            archive,
            record: AutomationRecord::new(
                format!("surface-{}", Uuid::new_v4()),
                Vec::new(),
                Vec::new(),
            )?,
            output: output.to_owned(),
            handle: None,
            sequence: 0,
        };
        recording.push("surface.video.run",OperationStatus::Observed,json!({"schema":"yosoi.surface.video-run.v1","descriptor":descriptor,"recording_policy":{"mode":"archive","source_and_pixels":true}}),None,None)?;
        Ok(recording)
    }
    pub const fn archive(&self) -> &Archive {
        &self.archive
    }
    pub async fn evidence(&mut self, kind: &str, value: Value) -> Result<()> {
        self.push(kind, OperationStatus::Observed, value, None, None)?;
        self.checkpoint().await?;
        Ok(())
    }
    pub async fn close_video(&mut self) -> Result<()> {
        self.push(
            "surface.closed",
            OperationStatus::Observed,
            json!({"resources_released":true,"browser_started":false}),
            None,
            None,
        )?;
        self.checkpoint().await?;
        Ok(())
    }
    fn push(
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
    pub async fn capture(
        &mut self,
        document: &Document,
        surface: &Surface,
        snapshot: &Value,
        epoch: u64,
    ) -> Result<()> {
        let reference = self.archive.write_document(document).await?;
        let observation = Observation {
            id: format!("{}:capture:{epoch}", self.record.id()),
            session_id: self.record.id().into(),
            tab_id: "primary".into(),
            document_epoch: epoch,
            html: snapshot
                .get("html")
                .and_then(Value::as_str)
                .map(str::to_owned),
            url: snapshot
                .get("url")
                .and_then(Value::as_str)
                .map(str::to_owned),
            screenshot: None,
        };
        self.record.push_observation(observation.clone())?;
        let capture = Capture {
            schema: "yosoi.surface.capture.v1".into(),
            document: reference,
            surface: surface.identity().into(),
            normalized_strings: snapshot
                .get("normalized_strings")
                .cloned()
                .unwrap_or_else(|| json!([])),
        };
        self.push(
            "surface.capture",
            OperationStatus::Observed,
            serde_json::to_value(capture)?,
            Some(observation),
            None,
        )?;
        self.checkpoint().await?;
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
    pub async fn checkpoint(&mut self) -> Result<Handle> {
        let handle = Handle {
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
    pub async fn close(&mut self, closed: &Result<()>) -> Result<()> {
        self.push(
            "surface.closed",
            if closed.is_ok() {
                OperationStatus::Observed
            } else {
                OperationStatus::Unknown
            },
            json!({"browser_closed":closed.is_ok()}),
            None,
            closed.as_ref().err().map(ToString::to_string),
        )?;
        self.checkpoint().await?;
        Ok(())
    }
    pub fn status(&self) -> Value {
        json!({"mode":"archive","archive":self.archive.root(),"handle_file":self.output.join("record.json"),"handle":self.handle})
    }
}
pub async fn load(path: &Path) -> Result<(Archive, AutomationRecord)> {
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
    Ok((archive, record))
}
pub fn capture_descriptors(record: &AutomationRecord) -> Result<Vec<Capture>> {
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
pub async fn replay(
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
        return super::video::replay_loaded(&archive, &record, repeat, query, output).await;
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
