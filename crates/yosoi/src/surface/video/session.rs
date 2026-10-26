//! Read-only stateful exploration; decoding and archive storage belong to video.
use super::{DecodedFrame, VideoPolicy, VideoSurface};
use crate::surface::{
    ArchivePolicy, ArchiveReceipt, Budget, ExecutionError, SurfaceConnection, SurfacePolicy,
    archive::Recording,
    connection::{AgentSurface, Connection, Operation, Request, Result, Trace, connection},
    model::{self, ReadOperation, ReadRequest, SurfaceRead},
};
use serde_json::{Value, json};
use std::{
    fmt::{self, Debug, Formatter},
    fs, io,
    path::{Path, PathBuf},
    result::Result as StdResult,
};
pub(super) struct VideoDriver {
    surface: VideoSurface,
    attached: bool,
    focus: model::Reference,
    trace: Trace,
    recording: Option<Recording>,
    recording_fault: bool,
}
impl VideoDriver {
    pub(super) async fn finish(&mut self) -> Result<()> {
        self.attached = false;
        if let Some(recording) = self.recording.as_mut() {
            recording.close_video().await?;
        }
        Ok(())
    }
    fn describe(&self) -> Value {
        json!({"descriptor":self.surface.descriptor(),"observation":self.surface.observation(),"root":self.surface.root_reference()})
    }
    fn status(&self) -> Value {
        json!({"descriptor":self.surface.descriptor(),"observation":self.surface.observation(),"metadata":self.surface.metadata(),"root":self.surface.root_reference(),"cursor":{"attached":self.attached,"mode":if self.attached{"reader"}else{"detached"},"focus":self.focus},"recording":self.recording.as_ref().map_or_else(||json!({"mode":"off"}),Recording::status),"recording_fault":self.recording_fault})
    }
    fn validate(&self, reference: &model::Reference) -> Result<()> {
        self.surface.read(&ReadRequest {
            operation: ReadOperation::Inspect {
                reference: reference.clone(),
            },
            budget: Budget::default(),
            continuation: None,
        })?;
        Ok(())
    }
    async fn pixels(&mut self, frame: DecodedFrame) -> Result<Value> {
        let name = format!("frame-{}.png", frame.info.png_sha256);
        let path = self.trace.output.join(name);
        fs::write(&path, &frame.png)?;
        if let Some(recording) = self.recording.as_mut() {
            let saved = async {
                let saved = frame.write_to(recording.archive()).await?;
                recording
                    .evidence("surface.video.frame", serde_json::to_value(saved)?)
                    .await
            }
            .await;
            if let Err(error) = saved {
                self.recording_fault = true;
                self.attached = false;
                return Err(error);
            }
        }
        self.focus = frame.info.reference.clone();
        Ok(json!({"frame":frame.info,"artifact":{"path":path,"media_type":"image/png"}}))
    }
}
impl AgentSurface for VideoDriver {
    fn outcome(&self) -> Option<ArchiveReceipt> {
        self.recording.as_ref().and_then(Recording::receipt)
    }
    async fn close(mut self) -> (Option<ArchiveReceipt>, Result<()>) {
        let result = Self::finish(&mut self).await;
        (self.recording.as_ref().and_then(Recording::receipt), result)
    }

    fn ready(&mut self) -> Result<Value> {
        let page = self.surface.read(&ReadRequest {
            operation: ReadOperation::Overview,
            budget: Budget::default(),
            continuation: None,
        })?;
        self.trace.read("surface.open", &page)?;
        Ok(
            json!({"event":"ready","sdk":"ys::surface","representation":self.surface.descriptor().representation,"state":self.status(),"protocol":"JSON lines; describe/read/focus_evidence shared with web; seek/frame/crop are read capabilities; no hot authority"}),
        )
    }
    async fn command(&mut self, request: &Request) -> Result<Value> {
        match &request.operation{
            Operation::Describe=>Ok(self.describe()),
            Operation::Status=>Ok(self.status()),
            Operation::Attach=>{self.attached=true;Ok(self.status())},
            Operation::Detach=>{self.attached=false;Ok(self.status())},
            Operation::Read{request:read}=>{let mut read=read.clone();read.budget.bytes=read.budget.bytes.min(request.budget.saturating_sub(256));Ok(serde_json::to_value(self.surface.read(&read)?)?)},
            Operation::FocusEvidence{reference}=>{self.validate(reference)?;self.focus=reference.clone();Ok(self.status())},
            Operation::Seek{position_us}=>{self.focus=self.surface.at(*position_us)?;Ok(json!({"focus":self.focus,"controllable":false,"meaning":"read cursor moved; immutable source was not changed"}))},
            Operation::Frame{reference}=>{
                if self.recording_fault{return Err(io::Error::other("recording failed; pixel materialization blocked").into());}
                let frame=self.surface.frame(reference).await?;self.pixels(frame).await
            },
            Operation::Crop{reference,rect}=>{
                if self.recording_fault{return Err(io::Error::other("recording failed; pixel materialization blocked").into());}
                let frame=self.surface.crop(reference,*rect).await?;self.pixels(frame).await
            },
            Operation::Close=>Ok(json!({"closing":true})),
            _=>Err(io::Error::other("capability unavailable on read-only video; use describe and the shared read protocol").into()),
        }
    }
    async fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> Result<Value> {
        if let Some(recording) = self.recording.as_mut()
            && let Err(error) = recording
                .command(serde_json::to_value(operation)?, &result)
                .await
        {
            self.recording_fault = true;
            self.attached = false;
            return Err(error);
        }
        result
    }
    fn trace(&mut self) -> &mut Trace {
        &mut self.trace
    }
}
pub(super) async fn open(
    path: &Path,
    output: PathBuf,
    archive: Option<PathBuf>,
    max_side: u32,
) -> Result<VideoDriver> {
    fs::create_dir_all(&output)?;
    let surface = VideoSurface::open(
        path,
        VideoPolicy {
            frame_max_side: max_side,
            ..VideoPolicy::default()
        },
    )
    .await?;
    let mut recording = match archive {
        Some(root) => Some(
            Recording::open_video(&root, &output, serde_json::to_value(surface.descriptor())?)
                .await?,
        ),
        None => None,
    };
    if let Some(recording) = recording.as_mut() {
        let source = surface.write_to(recording.archive()).await?;
        recording
            .evidence("surface.video.source", serde_json::to_value(source)?)
            .await?;
    }
    let focus = surface.root_reference();
    Ok(VideoDriver {
        surface,
        attached: false,
        focus,
        trace: Trace::new(&output),
        recording,
        recording_fault: false,
    })
}
/// Detached, read-only connection over frozen video evidence; close explicitly.
pub struct VideoSession {
    inner: Connection<VideoDriver>,
}
impl VideoSession {
    /// Opens a frozen source. Frame dimensions are bounded by this video's max_side.
    pub async fn open(
        path: &Path,
        policy: SurfacePolicy,
        max_side: u32,
    ) -> StdResult<Self, ExecutionError> {
        let temporary = tempfile::tempdir().map_err(|e| ExecutionError::Operation(e.into()))?;
        let output = policy
            .output
            .unwrap_or_else(|| temporary.path().join("artifacts"));
        let archive = (policy.archive == ArchivePolicy::Enabled).then(|| {
            policy
                .archive_root
                .unwrap_or_else(|| temporary.path().join("archive"))
        });
        let driver = open(path, output.clone(), archive, max_side)
            .await
            .map_err(ExecutionError::Operation)?;
        Ok(Self {
            inner: Connection::new(driver, output, temporary),
        })
    }
}
connection!(VideoSession);
