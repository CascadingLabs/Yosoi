use std::sync::Arc;

use crate::internal::browser::vendor::chromiumoxide::{
    cdp::browser_protocol::page::NavigateParams,
    listeners::{EventListenerConfig, EventOverflowPolicy},
};
use tokio::{
    sync::{mpsc, oneshot},
    time::{self, Instant},
};

use crate::internal::browser::page::Page;
use crate::internal::browser::{Result, VoidCrawlError};

use super::progress::ProgressEmitter;
use super::worker::{NavigationStreams, NavigationWorker, provider_error};
use super::{
    ActiveNavigation, ActiveNavigationOptions, NavigationProgressKind, NavigationStartGuard,
    NavigationTermination,
};

impl Page {
    /// Navigates until the top document reaches `DOMContentLoaded`.
    ///
    /// The page-domain event stream is armed before `Page.navigate`, and the
    /// remaining load is stopped through the same owned navigation worker once
    /// the checkpoint is observed. This does not wait for network idle or the
    /// full load event.
    pub async fn navigate_until_dom_content_loaded(
        &self,
        url: &str,
        options: ActiveNavigationOptions,
    ) -> Result<()> {
        let mut navigation = self.start_navigation(url, options).await?;
        while let Some(progress) = navigation.next_progress().await? {
            if matches!(
                progress.kind,
                NavigationProgressKind::DomContentLoaded
                    | NavigationProgressKind::SameDocumentNavigation
            ) {
                let report = navigation.complete_at_readiness().await?;
                return if report.termination == NavigationTermination::Completed
                    && report.cleanup_complete
                {
                    Ok(())
                } else {
                    Err(VoidCrawlError::NavigationFailed(
                        "navigation readiness cleanup failed".to_owned(),
                    ))
                };
            }
        }
        let report = navigation.wait().await?;
        if report.termination == NavigationTermination::Completed && report.cleanup_complete {
            Ok(())
        } else {
            Err(VoidCrawlError::NavigationFailed(
                "navigation ended before DOMContentLoaded".to_owned(),
            ))
        }
    }

    pub async fn start_navigation(
        &self,
        url: &str,
        options: ActiveNavigationOptions,
    ) -> Result<ActiveNavigation> {
        self.ensure_active().await?;
        let options = options.validate()?;
        let started = Instant::now();
        let deadline =
            started
                .checked_add(options.max_duration)
                .ok_or(VoidCrawlError::InvalidInput {
                    operation: "start_navigation",
                    reason: "navigation duration exceeds the monotonic clock range",
                })?;
        self.navigation_state.begin()?;
        let mut start_guard = NavigationStartGuard::new(Arc::clone(&self.navigation_state));
        let result = time::timeout_at(
            deadline,
            self.start_navigation_inner(url, options, started, deadline),
        )
        .await
        .map_or_else(
            |_| {
                self.navigation_state.finish(true);
                Err(VoidCrawlError::NavigationSetupDeadline)
            },
            |result| {
                if result.is_err() {
                    self.navigation_state.finish(false);
                }
                result
            },
        );
        start_guard.disarm();
        result
    }

    async fn start_navigation_inner(
        &self,
        url: &str,
        options: ActiveNavigationOptions,
        started: Instant,
        deadline: Instant,
    ) -> Result<ActiveNavigation> {
        let tree = self.frame_tree().await?;
        let frame_id = tree.frame.id;
        let listener =
            EventListenerConfig::new(options.provider_event_capacity, EventOverflowPolicy::Close);
        let streams = NavigationStreams {
            committed: self
                .cdp()
                .event_listener(listener)
                .await
                .map_err(|error| provider_error(&error))?,
            same_document: self
                .cdp()
                .event_listener(listener)
                .await
                .map_err(|error| provider_error(&error))?,
            lifecycle: self
                .cdp()
                .event_listener(listener)
                .await
                .map_err(|error| provider_error(&error))?,
            stopped: self
                .cdp()
                .event_listener(listener)
                .await
                .map_err(|error| provider_error(&error))?,
        };
        let (progress_tx, progress) = mpsc::channel(options.progress_capacity.get());
        let emitter = ProgressEmitter::new(progress_tx, started);
        let (terminal_tx, terminal) = oneshot::channel();
        let (cancel_tx, cancel) = oneshot::channel();
        let command_page = self.cdp().clone();
        let requested_url = url.to_owned();
        let command = Box::pin(async move {
            command_page
                .navigate(NavigateParams::new(requested_url))
                .await
        });
        let worker = NavigationWorker {
            page: self.cdp().clone(),
            identity: Arc::clone(&self.document_identity),
            state: Arc::clone(&self.navigation_state),
            page_closed: Arc::clone(&self.closed),
            browser_closing: Arc::clone(&self.browser_closing),
            frame_id,
            deadline,
            cleanup_timeout: options.cleanup_timeout,
            streams,
            emitter,
            cancel,
            command,
            terminal: terminal_tx,
        };
        let worker = Some(tokio::spawn(worker.run()));
        Ok(ActiveNavigation {
            state: Arc::clone(&self.navigation_state),
            progress,
            terminal,
            cancel: Some(cancel_tx),
            worker,
        })
    }
}
