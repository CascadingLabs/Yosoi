use std::{
    future::Future,
    pin::Pin,
    result::Result as StdResult,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use chromiumoxide::{
    cdp::browser_protocol::page::{
        EventFrameNavigated, EventFrameStoppedLoading, EventLifecycleEvent,
        EventNavigatedWithinDocument, FrameId, NavigateReturns, StopLoadingParams,
    },
    error::CdpError,
    listeners::{EventDelivery, EventStream},
};
use futures::StreamExt;
use tokio::{
    sync::oneshot,
    time::{self, Instant},
};

use super::progress::ProgressEmitter;
use super::{
    NavigationFailureReason, NavigationProgressKind, NavigationReport, NavigationState,
    NavigationStop, NavigationTermination,
};
use crate::internal::browser::{
    VoidCrawlError,
    page::{CdpDocumentIdentity, DocumentIdentityState},
};

pub(super) struct NavigationStreams {
    pub(super) committed: EventStream<EventFrameNavigated>,
    pub(super) same_document: EventStream<EventNavigatedWithinDocument>,
    pub(super) lifecycle: EventStream<EventLifecycleEvent>,
    pub(super) stopped: EventStream<EventFrameStoppedLoading>,
}

pub(super) struct NavigationWorker {
    pub(super) page: chromiumoxide::Page,
    pub(super) identity: Arc<DocumentIdentityState>,
    pub(super) state: Arc<NavigationState>,
    pub(super) page_closed: Arc<AtomicBool>,
    pub(super) browser_closing: Arc<AtomicBool>,
    pub(super) frame_id: FrameId,
    pub(super) deadline: Instant,
    pub(super) cleanup_timeout: Duration,
    pub(super) streams: NavigationStreams,
    pub(super) emitter: ProgressEmitter,
    pub(super) cancel: oneshot::Receiver<NavigationStop>,
    pub(super) command: Pin<Box<dyn Future<Output = StdResult<NavigateReturns, CdpError>> + Send>>,
    pub(super) terminal: oneshot::Sender<NavigationReport>,
}

impl NavigationWorker {
    #[allow(
        clippy::cognitive_complexity,
        reason = "the lifecycle reactor keeps event and terminal precedence visible"
    )]
    pub(super) async fn run(mut self) {
        let deadline = self.deadline;
        let command = tokio::select! {
            biased;
            stop = &mut self.cancel => Err(match stop {
                Ok(NavigationStop::ReadinessSatisfied) => NavigationTermination::Failed {
                    reason: NavigationFailureReason::ProviderFailure,
                },
                Ok(NavigationStop::Cancelled) | Err(_) => NavigationTermination::Cancelled,
            }),
            () = time::sleep_until(deadline) => Err(NavigationTermination::DeadlineReached),
            result = &mut self.command => classify_command_result(result, &self.frame_id, self.page_closed.load(Ordering::Acquire), self.browser_closing.load(Ordering::Acquire)),
        };
        let expected_loader = match command {
            Ok(expected_loader) => {
                self.emitter.emit(NavigationProgressKind::CommandAccepted);
                expected_loader
            }
            Err(termination) => {
                let stopping = matches!(
                    termination,
                    NavigationTermination::Cancelled | NavigationTermination::DeadlineReached
                );
                if stopping {
                    let _ = self.stop_loading().await;
                }
                let cleanup_complete = !stopping;
                let uncertain = stopping
                    || matches!(
                        termination,
                        NavigationTermination::BrowserClosed
                            | NavigationTermination::Failed {
                                reason: NavigationFailureReason::DocumentIdentityMismatch
                                    | NavigationFailureReason::ProviderFailure
                                    | NavigationFailureReason::EventStreamClosed
                                    | NavigationFailureReason::DocumentIdentityUnavailable
                            }
                    );
                self.state.finish(uncertain);
                let _ = self.terminal.send(NavigationReport {
                    termination,
                    progress: self.emitter.report(),
                    provider_events_dropped: self.emitter.provider_report(),
                    cleanup_complete,
                    same_document: false,
                });
                return;
            }
        };
        let mut committed = false;
        let mut pending_same_document = false;
        let mut pending_dom_content_loaded = false;
        let mut pending_load = false;
        let mut pending_stopped = false;
        let mut same_document = false;
        let mut uncertain = false;
        let mut readiness_satisfied = false;
        let termination = loop {
            tokio::select! {
                biased;
                stop = &mut self.cancel => match stop {
                    Ok(NavigationStop::ReadinessSatisfied) => {
                        readiness_satisfied = true;
                        break NavigationTermination::Completed;
                    }
                    Ok(NavigationStop::Cancelled) | Err(_) => {
                        break NavigationTermination::Cancelled;
                    }
                },
                () = time::sleep_until(deadline) => break NavigationTermination::DeadlineReached,
                delivery = self.streams.committed.next() => {
                    let Some(delivery) = delivery else { break self.closed_termination(); };
                    match delivery {
                        EventDelivery::Lagged { dropped } => { self.emitter.provider_lagged(dropped); uncertain = true; break NavigationTermination::Failed { reason: NavigationFailureReason::EventStreamClosed }; }
                        EventDelivery::Event(event) => {
                            if event.frame.id != self.frame_id || event.frame.parent_id.is_some() || expected_loader.as_deref() != Some(event.frame.loader_id.inner()) { continue; }
                            let identity = CdpDocumentIdentity::from_frame(&event.frame);
                            if self.identity.observe_top_document(&identity, true).is_err() { uncertain = true; break NavigationTermination::Failed { reason: NavigationFailureReason::DocumentIdentityUnavailable }; }
                            if committed { continue; }
                            committed = true;
                            self.emitter.emit(NavigationProgressKind::DocumentCommitted);
                            if pending_same_document { self.emitter.emit(NavigationProgressKind::SameDocumentNavigation); }
                            if pending_dom_content_loaded { self.emitter.emit(NavigationProgressKind::DomContentLoaded); }
                            if pending_stopped { self.emitter.emit(NavigationProgressKind::FrameStopped); }
                            if pending_load { self.emitter.emit(NavigationProgressKind::Load); break NavigationTermination::Completed; }
                        }
                    }
                }
                delivery = self.streams.same_document.next() => {
                    let Some(delivery) = delivery else { break self.closed_termination(); };
                    match delivery {
                        EventDelivery::Lagged { dropped } => { self.emitter.provider_lagged(dropped); uncertain = true; break NavigationTermination::Failed { reason: NavigationFailureReason::EventStreamClosed }; }
                        EventDelivery::Event(event) if event.frame_id == self.frame_id => {
                            if expected_loader.is_none() { self.emitter.emit(NavigationProgressKind::SameDocumentNavigation); same_document = true; break NavigationTermination::Completed; }
                            if committed { self.emitter.emit(NavigationProgressKind::SameDocumentNavigation); } else { pending_same_document = true; }
                        }
                        EventDelivery::Event(_) => {}
                    }
                }
                delivery = self.streams.lifecycle.next() => {
                    let Some(delivery) = delivery else { break self.closed_termination(); };
                    match delivery {
                        EventDelivery::Lagged { dropped } => { self.emitter.provider_lagged(dropped); uncertain = true; break NavigationTermination::Failed { reason: NavigationFailureReason::EventStreamClosed }; }
                        EventDelivery::Event(event) if event.frame_id == self.frame_id && expected_loader.as_deref() == Some(event.loader_id.inner()) => match event.name.as_str() {
                            "DOMContentLoaded" if committed => self.emitter.emit(NavigationProgressKind::DomContentLoaded),
                            "DOMContentLoaded" => pending_dom_content_loaded = true,
                            "load" if committed => { self.emitter.emit(NavigationProgressKind::Load); break NavigationTermination::Completed; }
                            "load" => pending_load = true,
                            _ => {}
                        },
                        EventDelivery::Event(_) => {}
                    }
                }
                delivery = self.streams.stopped.next() => {
                    let Some(delivery) = delivery else { break self.closed_termination(); };
                    match delivery {
                        EventDelivery::Lagged { dropped } => { self.emitter.provider_lagged(dropped); uncertain = true; break NavigationTermination::Failed { reason: NavigationFailureReason::EventStreamClosed }; }
                        EventDelivery::Event(event) if event.frame_id == self.frame_id => if committed { self.emitter.emit(NavigationProgressKind::FrameStopped); } else { pending_stopped = true; },
                        EventDelivery::Event(_) => {}
                    }
                }
            }
        };
        let stopping = readiness_satisfied
            || matches!(
                termination,
                NavigationTermination::Cancelled | NavigationTermination::DeadlineReached
            );
        let stop_loading_complete = if stopping {
            self.stop_loading().await
        } else {
            true
        };
        let cleanup_complete = if readiness_satisfied {
            stop_loading_complete
        } else {
            !stopping
        };
        if readiness_satisfied {
            uncertain = !stop_loading_complete;
        } else if stopping {
            uncertain = true;
        }
        if matches!(
            termination,
            NavigationTermination::BrowserClosed
                | NavigationTermination::Failed {
                    reason: NavigationFailureReason::EventStreamClosed
                        | NavigationFailureReason::ProviderFailure
                        | NavigationFailureReason::DocumentIdentityMismatch
                        | NavigationFailureReason::DocumentIdentityUnavailable
                }
        ) {
            uncertain = true;
        }
        self.state.finish(uncertain);
        let _ = self.terminal.send(NavigationReport {
            termination,
            progress: self.emitter.report(),
            provider_events_dropped: self.emitter.provider_report(),
            cleanup_complete,
            same_document,
        });
    }

    fn closed_termination(&self) -> NavigationTermination {
        if self.page_closed.load(Ordering::Acquire) {
            NavigationTermination::PageClosed
        } else {
            NavigationTermination::BrowserClosed
        }
    }

    async fn stop_loading(&mut self) -> bool {
        let Some(deadline) = Instant::now().checked_add(self.cleanup_timeout) else {
            return false;
        };
        if !matches!(
            time::timeout_at(deadline, self.page.execute(StopLoadingParams::default())).await,
            Ok(Ok(_))
        ) {
            return false;
        }
        loop {
            match time::timeout_at(deadline, self.streams.stopped.next()).await {
                Ok(Some(EventDelivery::Lagged { dropped })) => {
                    self.emitter.provider_lagged(dropped);
                }
                Ok(Some(EventDelivery::Event(event))) if event.frame_id == self.frame_id => {
                    return true;
                }
                Ok(Some(EventDelivery::Event(_))) => {}
                Ok(None) | Err(_) => return false,
            }
        }
    }
}

fn classify_command_result(
    result: StdResult<NavigateReturns, CdpError>,
    frame_id: &FrameId,
    page_closed: bool,
    browser_closing: bool,
) -> StdResult<Option<String>, NavigationTermination> {
    if page_closed {
        return Err(NavigationTermination::PageClosed);
    }
    if browser_closing {
        return Err(NavigationTermination::BrowserClosed);
    }
    let result = result.map_err(|_| NavigationTermination::Failed {
        reason: NavigationFailureReason::ProviderFailure,
    })?;
    if &result.frame_id != frame_id {
        return Err(NavigationTermination::Failed {
            reason: NavigationFailureReason::DocumentIdentityMismatch,
        });
    }
    if result.error_text.is_some() {
        return Err(NavigationTermination::Failed {
            reason: NavigationFailureReason::CommandRejected,
        });
    }
    if result.is_download == Some(true) {
        return Err(NavigationTermination::Failed {
            reason: NavigationFailureReason::BecameDownload,
        });
    }
    Ok(result.loader_id.map(|value| value.inner().clone()))
}

pub(super) fn provider_error(error: &CdpError) -> VoidCrawlError {
    VoidCrawlError::NavigationFailed(error.to_string())
}
