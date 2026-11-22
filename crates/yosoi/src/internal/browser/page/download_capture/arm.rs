//! Event subscription and browser-context arming.

use super::{
    CaptureState, DOWNLOAD_EVENT_CAPACITY, DownloadCaptureError, NativeDownloadCapture, wait,
};
use crate::internal::browser::vendor::chromiumoxide::{
    cdp::browser_protocol::{
        browser::{
            EventDownloadProgress, EventDownloadWillBegin, SetDownloadBehaviorBehavior,
            SetDownloadBehaviorParams,
        },
        page::GetFrameTreeParams,
    },
    listeners::{EventListenerConfig, EventOverflowPolicy},
};
use notify::{Config, RecursiveMode, Watcher};
use std::{
    collections::{HashMap, HashSet},
    num::NonZeroUsize,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{
    runtime::Handle,
    sync::{mpsc, oneshot},
    time::Instant,
};
use tokio_util::sync::CancellationToken;

use super::super::{Page, ProviderBrowserContextIdentity};

impl Page {
    /// Arms native CDP events on this owned context before a caller action.
    pub(crate) async fn start_native_download_capture(
        &self,
        max_bytes: u64,
        timeout: Duration,
    ) -> Result<NativeDownloadCapture, DownloadCaptureError> {
        if timeout.is_zero() {
            return Err(DownloadCaptureError::Timeout);
        }
        if self.attached_browser {
            return Err(DownloadCaptureError::Unsupported);
        }
        self.ensure_active()
            .await
            .map_err(|_| DownloadCaptureError::Setup)?;
        let lease = self.download_coordinator.acquire()?;
        let runtime = Handle::try_current().map_err(|_| DownloadCaptureError::Setup)?;
        let frame_tree = self
            .inner
            .execute(GetFrameTreeParams::default())
            .await
            .map_err(|_| DownloadCaptureError::Setup)?
            .result
            .frame_tree;
        let mut frame_ids = HashSet::new();
        wait::collect_frame_ids(&frame_tree, &mut frame_ids);
        if frame_ids.is_empty() {
            return Err(DownloadCaptureError::Incomplete);
        }
        let context_id = self
            .provider_context
            .as_ref()
            .map(|context: &ProviderBrowserContextIdentity| context.0.clone());
        let context_key = context_id.as_ref().map(|context| context.inner().clone());
        let mut frame_contexts = HashMap::new();
        wait::collect_frame_contexts(&frame_tree, context_key.as_deref(), &mut frame_contexts);
        {
            let mut browser = self.browser.lock().await;
            if let Ok(targets) = browser.fetch_targets().await {
                for target in targets.iter().filter(|target| target.r#type == "page") {
                    let context = target
                        .browser_context_id
                        .as_ref()
                        .map(|context| context.inner().clone());
                    if let Ok(page) = browser.get_page(target.target_id.clone()).await
                        && let Ok(frame_tree) = page.execute(GetFrameTreeParams::default()).await
                    {
                        wait::collect_frame_contexts(
                            &frame_tree.result.frame_tree,
                            context.as_deref(),
                            &mut frame_contexts,
                        );
                    }
                }
            }
        }

        let directory = tempfile::tempdir().map_err(|_| DownloadCaptureError::Setup)?;
        let (file_tx, file_events) = mpsc::channel(1);
        let watcher_failed = Arc::new(AtomicBool::new(false));
        let callback_failed = Arc::clone(&watcher_failed);
        let watcher = notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
            if event.is_err() {
                callback_failed.store(true, Ordering::Release);
            }
            let _ = file_tx.try_send(());
        })
        .map_err(|_| DownloadCaptureError::Setup)?;
        let mut watcher = watcher;
        watcher
            .configure(Config::default())
            .map_err(|_| DownloadCaptureError::Setup)?;
        watcher
            .watch(directory.path(), RecursiveMode::NonRecursive)
            .map_err(|_| DownloadCaptureError::Setup)?;

        let event_capacity =
            NonZeroUsize::new(DOWNLOAD_EVENT_CAPACITY).ok_or(DownloadCaptureError::Setup)?;
        let config = EventListenerConfig::new(event_capacity, EventOverflowPolicy::Close);
        let (will_begin, progress) = {
            let browser = self.browser.lock().await;
            let will_begin = browser
                .event_listener::<EventDownloadWillBegin>(config)
                .await
                .map_err(|_| DownloadCaptureError::Setup)?;
            let progress = browser
                .event_listener::<EventDownloadProgress>(config)
                .await
                .map_err(|_| DownloadCaptureError::Setup)?;
            (will_begin, progress)
        };

        let state = CaptureState {
            browser: Arc::clone(&self.browser),
            coordinator: Arc::clone(&self.download_coordinator),
            lease,
            runtime,
            deadline: Instant::now(),
            context_id: context_id.clone(),
            context_key,
            target_id: self.target_id(),
            frame_ids,
            frame_contexts,
            directory: Some(directory),
            watcher: Some(watcher),
            file_events,
            watcher_failed,
            will_begin,
            progress,
            max_bytes,
            guid: None,
            filename: None,
            source: None,
            unrelated_download: false,
            terminal: false,
            // Cleanup is armed before issuing a command that may partially dispatch.
            armed: true,
        };
        let mut capture = NativeDownloadCapture {
            arming: Some(state),
            result: None,
            cancellation: CancellationToken::new(),
        };
        let download_path = capture
            .arming
            .as_ref()
            .and_then(|state| state.directory.as_ref())
            .ok_or(DownloadCaptureError::Setup)?
            .path()
            .to_string_lossy()
            .into_owned();
        let mut params = SetDownloadBehaviorParams::builder()
            .behavior(SetDownloadBehaviorBehavior::AllowAndName)
            .download_path(download_path)
            .events_enabled(true);
        if let Some(context_id) = context_id {
            params = params.browser_context_id(context_id);
        }
        let params = params.build().map_err(|_| DownloadCaptureError::Setup)?;
        if self.browser.lock().await.execute(params).await.is_err() {
            let cleanup = if let Some(state) = capture.arming.as_mut() {
                state.cleanup(false).await
            } else {
                Ok(())
            };
            cleanup?;
            capture.arming.take();
            return Err(DownloadCaptureError::Setup);
        }

        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or(DownloadCaptureError::Setup)?;
        let Some(mut state) = capture.arming.take() else {
            return Err(DownloadCaptureError::Incomplete);
        };
        state.deadline = deadline;
        let cancellation = capture.cancellation.clone();
        let (result_tx, result_rx) = oneshot::channel();
        let runtime = state.runtime.clone();
        runtime.spawn(async move {
            let result = wait::monitor(state, cancellation).await;
            let _ = result_tx.send(result);
        });
        capture.result = Some(result_rx);
        Ok(capture)
    }
}
