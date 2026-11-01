//! Event-driven waiting and GUID-bound file finalization.

use super::{CaptureState, DownloadCaptureError, NativeDownloadResult};
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::{
    browser::{DownloadProgressState, EventDownloadWillBegin},
    page::{FrameTree, GetFrameTreeParams},
};
use crate::internal::browser::vendor::chromiumoxide::listeners::EventDelivery;
use crate::internal::media_documents::MAX_SOURCE_BYTES;
use futures_util::{FutureExt, StreamExt};
use std::{
    collections::{HashMap, HashSet},
    path::{Path, PathBuf},
    sync::{Arc, atomic::Ordering},
};
use tokio::{fs, io::AsyncReadExt, time::sleep_until};
use tokio_util::sync::CancellationToken;

pub(super) async fn monitor(
    mut state: CaptureState,
    cancellation: CancellationToken,
) -> Result<NativeDownloadResult, DownloadCaptureError> {
    let result = tokio::select! {
        biased;
        () = cancellation.cancelled() => Err(DownloadCaptureError::Cancelled),
        result = state.wait_inner() => result,
    };
    let cleanup = state.cleanup(result.is_err()).await;
    match cleanup {
        Ok(()) => result,
        Err(error) => Err(error),
    }
}

impl CaptureState {
    pub(super) async fn wait_inner(
        &mut self,
    ) -> Result<NativeDownloadResult, DownloadCaptureError> {
        loop {
            if self.watcher_failed.load(Ordering::Acquire) {
                return Err(DownloadCaptureError::Incomplete);
            }
            if let Some(result) = self.completed_file().await? {
                return Ok(result);
            }
            tokio::select! {
                    () = sleep_until(self.deadline) => return Err(DownloadCaptureError::Timeout),
                    delivery = self.will_begin.next() => {
                        match delivery {
                        Some(EventDelivery::Event(event)) => {
                            if !self.record_download_begin(&event).await? {
                                    return Err(DownloadCaptureError::Incomplete);
                                }
                            }
            Some(EventDelivery::Lagged { .. }) | None => {
                                self.unrelated_download = true;
                                return Err(DownloadCaptureError::Incomplete);
                            }
                        }
                    }
                    delivery = self.progress.next(), if self.guid.is_some() && !self.terminal => {
                        match delivery {
                            Some(EventDelivery::Event(event)) if self.guid.as_deref() == Some(event.guid.as_str()) => {
                                if exceeds_limit(event.received_bytes, self.max_bytes)
                                    || exceeds_limit(event.total_bytes, self.max_bytes)
                                {
                                    self.guid = Some(event.guid.clone());
                                    return Err(DownloadCaptureError::TooLarge { maximum: self.max_bytes });
                                }
                                match event.state {
                                    DownloadProgressState::Completed => self.terminal = true,
                                    DownloadProgressState::Canceled => {
                                        self.terminal = true;
                                        return Err(DownloadCaptureError::Cancelled);
                                    }
                                    DownloadProgressState::InProgress => {}
                                }
                            }
                            Some(EventDelivery::Event(_)) => {}
                            Some(EventDelivery::Lagged { .. }) | None => return Err(DownloadCaptureError::Incomplete),
                        }
                    }
                    event = self.file_events.recv(), if self.guid.is_some() => {
                        if event.is_none() {
                            return Err(DownloadCaptureError::Incomplete);
                        }
                    }
                }
        }
    }

    async fn completed_file(&self) -> Result<Option<NativeDownloadResult>, DownloadCaptureError> {
        let Some(guid) = self.guid.as_deref() else {
            return Ok(None);
        };
        let directory = self
            .directory
            .as_ref()
            .ok_or(DownloadCaptureError::Incomplete)?;
        let path = directory.path().join(guid);
        if fs::try_exists(&partial_path(&path))
            .await
            .map_err(|_| DownloadCaptureError::FileRead)?
        {
            return Ok(None);
        }
        if !fs::try_exists(&path)
            .await
            .map_err(|_| DownloadCaptureError::FileRead)?
        {
            return Ok(None);
        }
        let metadata = fs::metadata(&path)
            .await
            .map_err(|_| DownloadCaptureError::FileRead)?;
        if metadata.len() > self.max_bytes {
            return Err(DownloadCaptureError::TooLarge {
                maximum: self.max_bytes,
            });
        }
        let read_cap = self
            .max_bytes
            .checked_add(1)
            .ok_or(DownloadCaptureError::FileRead)?;
        let file = fs::File::open(&path)
            .await
            .map_err(|_| DownloadCaptureError::FileRead)?;
        let mut bytes = Vec::new();
        file.take(read_cap)
            .read_to_end(&mut bytes)
            .await
            .map_err(|_| DownloadCaptureError::FileRead)?;
        if u64::try_from(bytes.len()).map_err(|_| DownloadCaptureError::FileRead)? > self.max_bytes
        {
            return Err(DownloadCaptureError::TooLarge {
                maximum: self.max_bytes,
            });
        }
        Ok(Some(NativeDownloadResult {
            bytes,
            filename: self
                .filename
                .clone()
                .unwrap_or_else(|| "download".to_owned()),
            guid: guid.to_owned(),
            source: self.source.clone(),
        }))
    }

    async fn record_download_begin(
        &mut self,
        event: &EventDownloadWillBegin,
    ) -> Result<bool, DownloadCaptureError> {
        let frame_id = event.frame_id.inner();
        if !self.frame_contexts.contains_key(frame_id) {
            self.refresh_frame_contexts().await;
        }
        let Some(event_context) = self.frame_contexts.get(frame_id) else {
            self.unrelated_download = true;
            return Ok(false);
        };
        if event_context != &self.context_key {
            return Ok(true);
        }
        if self.guid.as_deref() == Some(event.guid.as_str()) {
            return Ok(true);
        }
        if self.guid.is_none() && self.frame_ids.contains(frame_id) && valid_guid(&event.guid) {
            self.guid = Some(event.guid.clone());
            self.filename = Some(safe_filename(&event.suggested_filename));
            if let Some(error) = source_url_error(&event.url) {
                return Err(error);
            }
            self.source = (!event.url.is_empty()).then(|| event.url.clone());
            Ok(true)
        } else {
            self.unrelated_download = true;
            Ok(false)
        }
    }

    async fn refresh_frame_contexts(&mut self) {
        let browser = Arc::clone(&self.browser);
        let mut browser = browser.lock().await;
        let Ok(targets) = browser.fetch_targets().await else {
            return;
        };
        for target in targets.iter().filter(|target| target.r#type == "page") {
            let context = target
                .browser_context_id
                .as_ref()
                .map(|context| context.inner().clone());
            if let Ok(page) = browser.get_page(target.target_id.clone()).await
                && let Ok(frame_tree) = page.execute(GetFrameTreeParams::default()).await
            {
                let current_target = target.target_id.inner() == &self.target_id;
                if current_target
                    && self
                        .frame_ids
                        .contains(frame_tree.result.frame_tree.frame.id.inner())
                {
                    collect_frame_ids(&frame_tree.result.frame_tree, &mut self.frame_ids);
                }
                collect_frame_contexts(
                    &frame_tree.result.frame_tree,
                    context.as_deref(),
                    &mut self.frame_contexts,
                );
            }
        }
    }
}

pub(super) async fn drain_download_begins(state: &mut CaptureState) {
    for _ in 0..256 {
        match state.will_begin.next().now_or_never() {
            Some(Some(EventDelivery::Event(event))) => {
                let _ = state.record_download_begin(&event).await;
            }
            Some(Some(EventDelivery::Lagged { .. }) | None) => {
                state.unrelated_download = true;
                break;
            }
            None => return,
        }
    }
    state.unrelated_download = true;
}

pub(super) fn collect_frame_ids(tree: &FrameTree, output: &mut HashSet<String>) {
    output.insert(tree.frame.id.inner().clone());
    if let Some(children) = &tree.child_frames {
        for child in children {
            collect_frame_ids(child, output);
        }
    }
}

pub(super) fn collect_frame_contexts(
    tree: &FrameTree,
    context_id: Option<&str>,
    output: &mut HashMap<String, Option<String>>,
) {
    output.insert(tree.frame.id.inner().clone(), context_id.map(str::to_owned));
    if let Some(children) = &tree.child_frames {
        for child in children {
            collect_frame_contexts(child, context_id, output);
        }
    }
}

fn partial_path(path: &Path) -> PathBuf {
    let mut partial = path.as_os_str().to_os_string();
    partial.push(".crdownload");
    PathBuf::from(partial)
}

fn exceeds_limit(value: f64, max_bytes: u64) -> bool {
    if !value.is_finite() || value < 0.0 {
        return false;
    }
    let Ok(maximum) = u32::try_from(max_bytes) else {
        return true;
    };
    value > f64::from(maximum)
}

fn valid_guid(guid: &str) -> bool {
    !guid.is_empty()
        && guid.len() <= 128
        && guid
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn safe_filename(value: &str) -> String {
    if value.is_empty() || value.len() > 1024 {
        "download".to_owned()
    } else {
        value.to_owned()
    }
}

fn source_url_error(value: &str) -> Option<DownloadCaptureError> {
    (value.len() > MAX_SOURCE_BYTES).then_some(DownloadCaptureError::MetadataTooLong {
        maximum: MAX_SOURCE_BYTES,
        observed: value.len(),
    })
}

#[cfg(test)]
mod tests {
    use super::{DownloadCaptureError, MAX_SOURCE_BYTES, source_url_error};

    #[test]
    fn overlong_source_is_rejected_before_payload_materialization() {
        let url = format!("https://example.test/{}", "x".repeat(MAX_SOURCE_BYTES));
        assert!(matches!(
            source_url_error(&url),
            Some(DownloadCaptureError::MetadataTooLong { maximum, observed })
                if maximum == MAX_SOURCE_BYTES && observed == url.len()
        ));
        assert!(source_url_error("https://example.test/file").is_none());
    }
}
