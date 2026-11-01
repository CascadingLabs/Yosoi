//! Immutable local-video observations, lazy frame reads, and time-addressed references.
//!
//! FFprobe reads metadata; FFmpeg materializes individual frames with one worker.
//! Timeline navigation never grants browser/device control and does not imply OCR,
//! transcription, audio inspection, or that unsampled frames have been observed.
pub mod archive;
mod frame;
mod process;
mod source;
mod time;
mod timeline;
mod types;
use crate::{
    documents::VideoDocument,
    surface::model::{self, AddressToken, Descriptor, Observation},
};
use std::{collections::VecDeque, path::PathBuf, sync::Arc};
use tempfile::TempDir;
use tokio::sync::Mutex;
pub use types::{DecodedFrame, FrameInfo, VideoError, VideoMetadata, VideoPolicy};

#[derive(Debug)]
struct Data {
    source_document: Option<VideoDocument>,
    _snapshot: Arc<TempDir>,
    path: PathBuf,
    metadata: VideoMetadata,
    policy: VideoPolicy,
    descriptor: Descriptor,
    observation: Observation,
    root: model::Reference,
    cache: Mutex<VecDeque<(u64, DecodedFrame)>>,
    ffmpeg: PathBuf,
}
/// A frozen local source with a lazy timeline and read-only frame capabilities.
#[derive(Clone, Debug)]
pub struct VideoSurface {
    data: Arc<Data>,
}
impl VideoSurface {
    /// Borrows the original typed source when prepared from a VideoDocument.
    /// Legacy path/envelope sources remain distinguishable until explicitly migrated.
    pub fn source_document(&self) -> Option<&VideoDocument> {
        self.data.source_document.as_ref()
    }
    /// Borrows demuxer metadata and its clock origin; this is not decoded frame evidence.
    pub fn metadata(&self) -> &VideoMetadata {
        &self.data.metadata
    }
    /// Borrows the effective processing limits, without exposing live authority.
    pub fn policy(&self) -> &VideoPolicy {
        &self.data.policy
    }
    /// Issues a request for the first frame at or after a stream-relative position.
    /// A position in the final frame tail may have no later frame; materialization then fails explicitly.
    pub fn at(&self, position_us: u64) -> Result<model::Reference, VideoError> {
        if position_us >= self.data.metadata.duration_us {
            return Err(VideoError::Invalid(
                "frame position is outside the video".into(),
            ));
        }
        Ok(model::Reference {
            observation: self.data.observation.id.clone(),
            address: AddressToken::new(format!("f:{position_us}"))?,
        })
    }
}

mod session;
pub use session::VideoSession;
