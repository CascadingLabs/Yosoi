//! Recorded video evidence and offline portable replay.
use super::{
    Archive, DecodedFrame, DocumentArchiveRef, FrameArchiveRef, VideoArchiveRef, VideoSurface,
};
use tokio::fs;

use crate::automation_record::{AutomationRecord, OperationStatus};
use crate::surface::{
    ArchiveLimits, ArchivedSource, Budget, Outcome,
    archive::Recording,
    connection::Result as SourceResult,
    model::{ReadOperation, ReadRequest},
};
use serde_json::{Value, json};
use std::{io, path::Path};
use uuid::Uuid;
impl Recording {
    pub async fn open_video(root: &Path, output: &Path, descriptor: Value) -> SourceResult<Self> {
        let archive = Archive::open(root).await?;
        let mut recording = Self {
            archive,
            outcome: Outcome::new(
                format!("surface-{}", Uuid::new_v4()),
                ArchiveLimits::default(),
            )?,
            output: output.to_owned(),
            handle: None,
            sequence: 0,
            pending: None,
        };
        recording.push("surface.video.run",OperationStatus::Observed,json!({"schema":"yosoi.surface.video-run.v1","descriptor":descriptor,"recording_policy":{"mode":"archive","source_and_pixels":true}}),None,None)?;
        Ok(recording)
    }
    pub const fn archive(&self) -> &Archive {
        &self.archive
    }
    pub async fn evidence(&mut self, kind: &str, value: Value) -> SourceResult<()> {
        if matches!(kind, "surface.video.source" | "surface.video.frame") {
            let key = value
                .get("document")
                .and_then(Value::as_str)
                .ok_or_else(|| io::Error::other("evidence document missing"))?;
            let reference: DocumentArchiveRef = key.parse()?;
            let document = self.archive.read_document(&reference).await?;
            self.outcome
                .retain(ArchivedSource::new(key, &document, None))?;
        }
        self.push(kind, OperationStatus::Observed, value, None, None)?;
        self.checkpoint().await?;
        Ok(())
    }
    pub async fn close_video(&mut self) -> SourceResult<()> {
        let receipt = self.push(
            "surface.closed",
            OperationStatus::Observed,
            json!({"resources_released":true,"browser_started":false}),
            None,
            None,
        );
        self.finalize().await?;
        receipt?;
        Ok(())
    }
}
pub(in crate::surface) async fn replay_loaded(
    archive: &Archive,
    record: &AutomationRecord,
    repeat: usize,
    query: Option<&str>,
    output: Option<&Path>,
) -> SourceResult<Value> {
    if query.is_some() {
        return Err(io::Error::other(
            "video does not advertise text search; use saved frame evidence",
        )
        .into());
    }
    let source = record
        .operations()
        .iter()
        .find(|op| op.kind == "surface.video.source")
        .and_then(|op| op.result.as_ref())
        .ok_or_else(|| io::Error::other("archived video source reference absent"))?;
    let reference: VideoArchiveRef = serde_json::from_value(source.clone())?;
    let frames = record
        .operations()
        .iter()
        .filter(|op| op.kind == "surface.video.frame")
        .map(|op| {
            serde_json::from_value::<FrameArchiveRef>(
                op.result
                    .clone()
                    .ok_or_else(|| io::Error::other("frame reference absent"))?,
            )
            .map_err(Into::into)
        })
        .collect::<SourceResult<Vec<_>>>()?;
    if let Some(directory) = output {
        fs::create_dir_all(directory).await?;
    }
    let mut summaries = Vec::new();
    let mut observation = None;
    for iteration in 0..repeat {
        let video = VideoSurface::read_from(archive, &reference).await?;
        video.read(&ReadRequest {
            operation: ReadOperation::Overview,
            budget: Budget::default(),
            continuation: None,
        })?;
        for (index, reference) in frames.iter().enumerate() {
            let frame = DecodedFrame::read_from(archive, reference).await?;
            if frame.info.reference.observation != video.observation().id {
                return Err(io::Error::other(
                    "frame belongs to a different archived video observation",
                )
                .into());
            }
            if iteration == 0 {
                let path = output.map(|directory| {
                    directory.join(format!("frame-{}.png", frame.info.png_sha256))
                });
                if let Some(path) = &path {
                    fs::write(path, &frame.png).await?;
                }
                if index < 8 {
                    summaries.push(json!({"frame":frame.info,"path":path}));
                }
            }
        }
        observation = Some(video.observation().clone());
    }
    Ok(
        json!({"mode":"offline","representation":"yosoi.video.timeline.v1","controllable":false,"browser_started":false,"decoder_started":false,"record":record.id(),"iterations":repeat,"observation":observation,"frames_verified":frames.len(),"frames":summaries,"frames_omitted":frames.len().saturating_sub(8)}),
    )
}
