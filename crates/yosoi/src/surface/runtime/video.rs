//! Video is a read-only source behind the same JSON-lines front end as live web.
use super::{AgentSurface, Operation, Request, Result, Trace, recording::Recording};
use crate::{
    Archive,
    automation_record::AutomationRecord,
    surface::{
        Budget,
        model::{self, ReadOperation, ReadRequest, SurfaceRead},
        video::{DecodedFrame, FrameArchiveRef, VideoArchiveRef, VideoPolicy, VideoSurface},
    },
};
use serde_json::{Value, json};
use std::{
    fs, io,
    path::{Path, PathBuf},
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
    pub(super) async fn close(&mut self) -> Result<()> {
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
pub async fn replay_loaded(
    archive: &Archive,
    record: &AutomationRecord,
    repeat: usize,
    query: Option<&str>,
    output: Option<&Path>,
) -> Result<Value> {
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
        .collect::<Result<Vec<_>>>()?;
    if let Some(directory) = output {
        fs::create_dir_all(directory)?;
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
                    fs::write(path, &frame.png)?;
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
