//! Stateful, read-only exploration of a frozen video source.
use super::{DecodedFrame, VideoPolicy, VideoSurface};
use crate::surface::{
    ArchiveLimits, ArchivePolicy, Budget, ExecutionError, Outcome, SurfaceConnection,
    SurfacePolicy,
    archive::Recording,
    connection::{AgentSurface, Connection, Operation, Request, Result, Trace, connection},
    model::{self, ReadOperation, ReadRequest, SurfaceRead},
};
use serde_json::{Value, json};
use std::{
    error::Error,
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
    fn outcome(&self) -> Option<Outcome> {
        outcome(self)
    }
    async fn close(self) -> (Option<Outcome>, Result<()>) {
        close(self).await
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
    fn record_reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()> {
        match result {
            Ok(value) => {
                if matches!(operation, Operation::Read { .. }) {
                    self.trace.read_bytes = self
                        .trace
                        .read_bytes
                        .saturating_add(serde_json::to_vec(value)?.len());
                }
                self.trace.event("cli.reply", value.clone());
            }
            Err(error) => self.trace.event(
                "cli.error",
                json!({"error":error.to_string().chars().take(512).collect::<String>()}),
            ),
        }
        Ok(())
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
    limits: ArchiveLimits,
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
        recording.set_limits(limits);
        let source = surface.write_to(recording.archive()).await?;
        recording
            .evidence("surface.video.source", serde_json::to_value(source)?)
            .await?;
    }
    let focus = surface.root_reference();
    let driver = VideoDriver {
        surface,
        attached: false,
        focus,
        trace: Trace::new(&output),
        recording,
        recording_fault: false,
    };
    Ok(driver)
}
pub(super) async fn close(mut driver: VideoDriver) -> (Option<Outcome>, Result<()>) {
    driver.attached = false;
    drop(driver.surface);
    let result = if let Some(recording) = driver.recording.as_mut() {
        recording.close_video().await
    } else {
        Ok(())
    };
    (driver.recording.as_ref().map(Recording::outcome), result)
}
pub(super) fn outcome(driver: &VideoDriver) -> Option<Outcome> {
    driver.recording.as_ref().map(Recording::outcome)
}

/// Read-only video connection with its own cursor, bounded processing and archive collection.
/// It never starts a browser or acquires action authority. Await `close` for finalization.
pub struct VideoSession {
    inner: Connection<VideoDriver>,
}
impl VideoSession {
    /// Freezes a local source and opens a detached reader. `max_side` bounds decoded pixels.
    pub async fn open(
        path: impl AsRef<Path> + Send + Sync,
        policy: SurfacePolicy,
        max_side: u32,
    ) -> StdResult<Self, ExecutionError> {
        let result = async {
            policy.archive_limits.validate()?;
            let temporary = tempfile::tempdir()?;
            let output = policy
                .output
                .clone()
                .unwrap_or_else(|| temporary.path().join("artifacts"));
            let root = (policy.archive == ArchivePolicy::Enabled).then(|| {
                policy
                    .archive_root
                    .clone()
                    .unwrap_or_else(|| temporary.path().join("archive"))
            });
            let driver = open(
                path.as_ref(),
                output.clone(),
                root,
                max_side,
                policy.archive_limits,
            )
            .await?;
            Ok::<_, Box<dyn Error + Send + Sync>>(Self {
                inner: Connection::new(driver, output, temporary),
            })
        }
        .await;
        result.map_err(ExecutionError::Operation)
    }
}
connection!(VideoSession);
