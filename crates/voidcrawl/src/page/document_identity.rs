use chromiumoxide::cdp::browser_protocol::page::{Frame, FrameId, FrameTree, GetFrameTreeParams};
use yosoi_types::BrowserFrameId;

use super::Page;
use crate::{
    DocumentEpoch, DocumentFrameScope, DocumentScope, ProtectedUrl, Result, VoidCrawlError,
};
use std::{
    collections::HashMap,
    sync::{
        Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
};

#[derive(Debug)]
pub struct DocumentIdentityState {
    top_epoch: AtomicU64,
    top_known: AtomicBool,
    top_loader: Mutex<Option<String>>,
    frame_ids: Mutex<HashMap<String, BrowserFrameId>>,
    frame_documents: Mutex<HashMap<String, FrameDocumentIdentity>>,
}

impl DocumentIdentityState {
    pub(super) fn new(attached_browser: bool) -> Self {
        Self {
            top_epoch: AtomicU64::new(0),
            top_known: AtomicBool::new(!attached_browser),
            top_loader: Mutex::new(None),
            frame_ids: Mutex::new(HashMap::new()),
            frame_documents: Mutex::new(HashMap::new()),
        }
    }

    pub(crate) fn observe_top_document(
        &self,
        identity: &CdpDocumentIdentity,
        controlled_navigation: bool,
    ) -> Result<DocumentEpoch> {
        let mut current = self
            .top_loader
            .lock()
            .map_err(|_| VoidCrawlError::Other("document loader lock poisoned".into()))?;
        let changed = current
            .as_deref()
            .is_some_and(|loader| loader != identity.loader_id);
        let known = self.top_known.load(Ordering::Relaxed);
        let establish_or_advance = if known {
            changed || (controlled_navigation && current.is_none())
        } else {
            controlled_navigation
        };
        if establish_or_advance {
            self.top_epoch
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |epoch| {
                    epoch.checked_add(1)
                })
                .map_err(|_| VoidCrawlError::Other("document epoch exhausted".into()))?;
            self.top_known.store(true, Ordering::Relaxed);
        }
        *current = Some(identity.loader_id.clone());
        drop(current);
        if self.top_known.load(Ordering::Relaxed) {
            Ok(DocumentEpoch::Known(self.top_epoch.load(Ordering::Relaxed)))
        } else {
            Ok(DocumentEpoch::UnavailableForAttachedPage)
        }
    }

    fn browser_frame_id(&self, frame_id: &FrameId) -> Result<BrowserFrameId> {
        let mut ids = self
            .frame_ids
            .lock()
            .map_err(|_| VoidCrawlError::Other("frame identity lock poisoned".into()))?;
        if let Some(id) = ids.get(frame_id.inner()) {
            return Ok(*id);
        }
        let next = u64::try_from(ids.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .map(BrowserFrameId)
            .ok_or_else(|| VoidCrawlError::Other("frame identity space exhausted".into()))?;
        ids.insert(frame_id.inner().clone(), next);
        drop(ids);
        Ok(next)
    }

    fn frame_document_epoch(&self, identity: &CdpDocumentIdentity) -> Result<DocumentEpoch> {
        if !self.top_known.load(Ordering::Relaxed) {
            return Ok(DocumentEpoch::UnavailableForAttachedPage);
        }
        let mut documents = self
            .frame_documents
            .lock()
            .map_err(|_| VoidCrawlError::Other("frame document lock poisoned".into()))?;
        let raw_frame_id = identity.frame_id.inner();
        let epoch = match documents.get_mut(raw_frame_id) {
            Some(document) if document.loader_id == identity.loader_id => document.epoch,
            Some(document) => {
                let next = document
                    .epoch
                    .checked_add(1)
                    .ok_or_else(|| VoidCrawlError::Other("document epoch exhausted".into()))?;
                document.loader_id.clone_from(&identity.loader_id);
                document.epoch = next;
                next
            }
            None => {
                documents.insert(
                    raw_frame_id.clone(),
                    FrameDocumentIdentity {
                        loader_id: identity.loader_id.clone(),
                        epoch: 1,
                    },
                );
                1
            }
        };
        drop(documents);
        Ok(DocumentEpoch::Known(epoch))
    }
}

#[derive(Debug)]
struct FrameDocumentIdentity {
    loader_id: String,
    epoch: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CdpDocumentIdentity {
    pub(super) frame_id: FrameId,
    pub(super) loader_id: String,
    pub(super) url: String,
}

impl CdpDocumentIdentity {
    pub(crate) fn from_frame(frame: &Frame) -> Self {
        Self {
            frame_id: frame.id.clone(),
            loader_id: frame.loader_id.inner().clone(),
            url: format!(
                "{}{}",
                frame.url,
                frame.url_fragment.as_deref().unwrap_or("")
            ),
        }
    }

    pub(super) fn same_document(&self, other: &Self) -> bool {
        self.frame_id == other.frame_id && self.loader_id == other.loader_id
    }
}

pub(super) fn identity_in_tree(
    tree: &FrameTree,
    frame_id: &FrameId,
) -> Option<CdpDocumentIdentity> {
    if &tree.frame.id == frame_id {
        return Some(CdpDocumentIdentity::from_frame(&tree.frame));
    }
    tree.child_frames
        .as_deref()
        .unwrap_or_default()
        .iter()
        .find_map(|child| identity_in_tree(child, frame_id))
}

impl Page {
    pub(super) fn observe_document_identity(
        &self,
        identity: &CdpDocumentIdentity,
        controlled_navigation: bool,
    ) -> Result<DocumentEpoch> {
        self.document_identity
            .observe_top_document(identity, controlled_navigation)
    }

    pub(crate) async fn frame_tree(&self) -> Result<FrameTree> {
        self.inner
            .execute(GetFrameTreeParams::default())
            .await
            .map(|response| response.result.frame_tree)
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))
    }

    pub(super) async fn top_level_document_identity(&self) -> Result<CdpDocumentIdentity> {
        Ok(CdpDocumentIdentity::from_frame(
            &self.frame_tree().await?.frame,
        ))
    }

    pub(super) fn scope_for_identity(
        &self,
        identity: &CdpDocumentIdentity,
        controlled_navigation: bool,
    ) -> Result<DocumentScope> {
        Ok(DocumentScope {
            frame_id: self.browser_frame_id(&identity.frame_id)?,
            epoch: self.observe_document_identity(identity, controlled_navigation)?,
            frame: DocumentFrameScope::TopLevel,
            url: Some(ProtectedUrl::new(identity.url.clone())),
        })
    }

    pub(super) fn browser_frame_id(&self, frame_id: &FrameId) -> Result<BrowserFrameId> {
        self.document_identity.browser_frame_id(frame_id)
    }

    fn frame_document_epoch(&self, identity: &CdpDocumentIdentity) -> Result<DocumentEpoch> {
        self.document_identity.frame_document_epoch(identity)
    }

    pub(super) fn scope_for_frame_identity(
        &self,
        identity: &CdpDocumentIdentity,
        top: &DocumentScope,
    ) -> Result<DocumentScope> {
        Ok(DocumentScope {
            frame_id: self.browser_frame_id(&identity.frame_id)?,
            epoch: self.frame_document_epoch(identity)?,
            frame: DocumentFrameScope::Frame {
                url: Some(ProtectedUrl::new(identity.url.clone())),
            },
            url: top.url.clone(),
        })
    }

    pub(crate) async fn top_level_document_scope(&self) -> Result<DocumentScope> {
        let identity = self.top_level_document_identity().await?;
        self.scope_for_identity(&identity, false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity(frame: &str, loader: &str, url: &str) -> CdpDocumentIdentity {
        CdpDocumentIdentity {
            frame_id: FrameId::new(frame),
            loader_id: loader.to_string(),
            url: url.to_string(),
        }
    }

    #[test]
    fn identical_urls_in_distinct_frames_receive_distinct_opaque_ids() {
        let state = DocumentIdentityState::new(false);
        let first = identity("cdp-frame-a", "loader-a", "https://example.test/same");
        let second = identity("cdp-frame-b", "loader-b", "https://example.test/same");

        let first_id = state.browser_frame_id(&first.frame_id).expect("first id");
        let second_id = state.browser_frame_id(&second.frame_id).expect("second id");

        assert_ne!(first_id, second_id);
        assert_eq!(
            state.browser_frame_id(&first.frame_id).expect("stable id"),
            first_id
        );
    }

    #[test]
    fn frame_navigation_advances_epoch_without_replacing_frame_id() {
        let state = DocumentIdentityState::new(false);
        let first = identity("cdp-frame", "loader-a", "https://example.test/same");
        let replacement = identity("cdp-frame", "loader-b", "https://example.test/same");

        let frame_id = state.browser_frame_id(&first.frame_id).expect("frame id");
        assert_eq!(
            state.frame_document_epoch(&first).expect("first epoch"),
            DocumentEpoch::Known(1)
        );
        assert_eq!(
            state
                .frame_document_epoch(&replacement)
                .expect("replacement epoch"),
            DocumentEpoch::Known(2)
        );
        assert_eq!(
            state
                .browser_frame_id(&replacement.frame_id)
                .expect("stable frame id"),
            frame_id
        );
    }

    #[test]
    fn top_level_navigation_advances_epoch_when_the_url_is_unchanged() {
        let state = DocumentIdentityState::new(false);
        let first = identity("top", "loader-a", "https://example.test/same");
        let replacement = identity("top", "loader-b", "https://example.test/same");

        assert_eq!(
            state
                .observe_top_document(&first, true)
                .expect("first epoch"),
            DocumentEpoch::Known(1)
        );
        assert_eq!(
            state
                .observe_top_document(&replacement, false)
                .expect("replacement epoch"),
            DocumentEpoch::Known(2)
        );
    }

    #[test]
    fn detached_frame_identity_is_never_reassigned_to_a_replacement() {
        let state = DocumentIdentityState::new(false);
        let detached = identity(
            "cdp-frame-detached",
            "loader-a",
            "https://example.test/frame",
        );
        let replacement = identity(
            "cdp-frame-replacement",
            "loader-b",
            "https://example.test/frame",
        );

        let detached_id = state
            .browser_frame_id(&detached.frame_id)
            .expect("detached id");
        let replacement_id = state
            .browser_frame_id(&replacement.frame_id)
            .expect("replacement id");

        assert_ne!(detached_id, replacement_id);
        assert_eq!(
            state
                .browser_frame_id(&detached.frame_id)
                .expect("retired id remains reserved"),
            detached_id
        );
    }

    #[test]
    fn attached_epochs_remain_unknown_until_controlled_navigation() {
        let state = DocumentIdentityState::new(true);
        let adopted = identity("top", "adopted-loader", "https://example.test/adopted");
        let external = identity("top", "external-loader", "https://example.test/external");
        let navigated = identity("top", "controlled-loader", "https://example.test/known");
        let child = identity("child", "child-loader", "https://example.test/frame");

        assert_eq!(
            state
                .observe_top_document(&adopted, false)
                .expect("adopted epoch"),
            DocumentEpoch::UnavailableForAttachedPage
        );
        assert_eq!(
            state
                .observe_top_document(&external, false)
                .expect("externally replaced epoch"),
            DocumentEpoch::UnavailableForAttachedPage
        );
        assert_eq!(
            state
                .frame_document_epoch(&child)
                .expect("unknown child epoch"),
            DocumentEpoch::UnavailableForAttachedPage
        );
        assert_eq!(
            state
                .observe_top_document(&navigated, true)
                .expect("controlled epoch"),
            DocumentEpoch::Known(1)
        );
        assert_eq!(
            state
                .frame_document_epoch(&child)
                .expect("known child epoch"),
            DocumentEpoch::Known(1)
        );
    }
}
