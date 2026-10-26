//! Protocol-private watch ownership behind common observation values.

use super::super::{DocumentEpoch, DocumentScope, ObservationChange, Result};

#[derive(Debug)]
pub enum ObservationWatch {
    Chrome(Box<super::super::ObservationWatch>),
    #[cfg(feature = "browser-bidi")]
    Bidi(super::super::bidi::watch::ObservationWatch),
}

impl ObservationWatch {
    pub fn start_scope(&self) -> &DocumentScope {
        match self {
            Self::Chrome(watch) => watch.start_scope(),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(watch) => watch.start_scope(),
        }
    }
    pub fn frame_id(&self) -> &str {
        match self {
            Self::Chrome(watch) => watch.frame_id(),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(watch) => watch.frame_id(),
        }
    }
    pub fn loader_id(&self) -> Option<&str> {
        match self {
            Self::Chrome(watch) => Some(watch.loader_id()),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(_) => None,
        }
    }
    pub fn document_epoch(&self) -> DocumentEpoch {
        self.start_scope().epoch
    }
    pub async fn next(&mut self) -> Result<ObservationChange> {
        match self {
            Self::Chrome(watch) => watch.next().await,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(watch) => watch.next().await,
        }
    }
    pub async fn settle(&mut self) -> Result<()> {
        match self {
            Self::Chrome(watch) => watch.settle().await,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(watch) => watch.settle().await,
        }
    }
}
