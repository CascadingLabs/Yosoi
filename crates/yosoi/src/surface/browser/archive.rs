//! Browser archive procedures resolve saved intentions against fresh evidence.
pub(super) use crate::surface::archive::Recording;
mod repeating;
use crate::surface::{ExecutionError, connection::Result};
pub(super) use repeating::resolve;
use serde_json::Value;
use std::path::Path;
use std::result::Result as StdResult;
/// Repeats a sealed browser recipe with new references and a fresh source each time.
/// Emits completed iterations as they finish, retaining earlier progress on failure.
pub async fn repeat(
    path: &Path,
    count: usize,
    headless: bool,
    output: &Path,
    on_iteration: impl FnMut(Value),
) -> StdResult<(), ExecutionError> {
    repeating::run(path, count, headless, output, on_iteration)
        .await
        .map_err(ExecutionError::Operation)
}

use crate::{
    Archive,
    automation_record::{AutomationRecord, Observation, OperationStatus},
    documents::Document,
    surface::{Surface, archive::Capture},
};
use serde_json::json;
use uuid::Uuid;
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
}
