//! Native lifecycle events feed the shared navigation owner and progress types.

use super::progress::ProgressEmitter;
use super::{
    ActiveNavigation, ActiveNavigationOptions, NavigationFailureReason, NavigationProgressKind,
    NavigationReport, NavigationStartGuard, NavigationStop, NavigationTermination,
};
use crate::browser::BrowserEngine;
use crate::internal::browser::bidi::{
    session::Page,
    transport::{BidiConnection, BidiError},
};
use crate::internal::browser::controller::map_bidi;
use crate::internal::browser::{
    MeasuredCount, MeasurementUnavailableReason, Result, VoidCrawlError,
};
use futures_util::FutureExt as _;
use serde_json::{Value, json};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use tokio::{
    sync::{mpsc, oneshot},
    task::JoinHandle,
    time::{Instant, sleep_until, timeout_at},
};
use tokio_util::sync::CancellationToken;

struct Pump(JoinHandle<()>);
impl Drop for Pump {
    fn drop(&mut self) {
        self.0.abort();
    }
}

struct FenceOnDrop {
    connection: BidiConnection,
    armed: bool,
}
impl Drop for FenceOnDrop {
    fn drop(&mut self) {
        if self.armed {
            self.connection.fence();
        }
    }
}

impl Page {
    pub async fn stop_loading(&self, token: &CancellationToken, deadline: Instant) -> Result<()> {
        self.stop_loading_native(token, deadline)
            .await
            .map_err(map_bidi)
    }

    pub async fn start_navigation(
        &self,
        url: &str,
        options: ActiveNavigationOptions,
    ) -> Result<ActiveNavigation> {
        self.ensure_owned().await.map_err(map_bidi)?;
        if self.session.config.engine == BrowserEngine::Moli {
            // 1.1.19 can return a navigation ID from a different loader after
            // Fetch activity. URL-only correlation cannot replace this identity.
            return Err(VoidCrawlError::UnsupportedCapability {
                operation: "Moli active-navigation identity",
            });
        }
        let options = options.validate()?;
        self.navigation_state.begin()?;
        let mut start_guard = NavigationStartGuard::new(Arc::clone(&self.navigation_state));
        let started = Instant::now();
        let deadline =
            started
                .checked_add(options.max_duration())
                .ok_or(VoidCrawlError::InvalidInput {
                    operation: "start_navigation",
                    reason: "deadline overflow",
                })?;
        let token = CancellationToken::new();
        let mut events = self
            .session
            .connection
            .subscribe()
            .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let (sender, mut receiver) = mpsc::channel(options.provider_event_capacity().get());
        let lost = Arc::new(AtomicBool::new(false));
        let pump_lost = Arc::clone(&lost);
        let context = self.context.clone();
        let mut pump = Pump(tokio::spawn(async move {
            loop {
                match events.next(&CancellationToken::new(), deadline).await {
                    Ok(event)
                        if event.method.starts_with("browsingContext.")
                            && event.params.get("context").and_then(Value::as_str)
                                == Some(context.as_str()) =>
                    {
                        if sender.try_send(event).is_err() {
                            pump_lost.store(true, Ordering::Release);
                            break;
                        }
                    }
                    Ok(_) => {}
                    Err(BidiError::Deadline) => break,
                    Err(_) => {
                        pump_lost.store(true, Ordering::Release);
                        break;
                    }
                }
            }
        }));
        self.session
            .synchronize_events(&token, deadline)
            .await
            .map_err(map_bidi)?;
        self.ensure_owned().await.map_err(map_bidi)?;
        let connection = self.session.connection.clone();
        let context = self.context.clone();
        let requested_url = url.to_owned();
        let mut command = Box::pin(async move {
            connection
                .command(
                    "browsingContext.navigate",
                    json!({"context":context,"url":requested_url,"wait":"none"}),
                    &token,
                    deadline,
                )
                .await
        });
        // The transport enqueues synchronously before its first suspension.
        // Poll once before exposing the owner: cancellation must never enqueue
        // a previously unpolled navigate after its stop command.
        let immediate_reply = command.as_mut().now_or_never();
        let (progress_sender, progress) = mpsc::channel(options.progress_capacity().get());
        let (terminal_sender, terminal) = oneshot::channel();
        let (cancel, mut stopping) = oneshot::channel();
        let state = Arc::clone(&self.navigation_state);
        let page = self.clone();
        let fence = FenceOnDrop {
            connection: page.session.connection.clone(),
            armed: true,
        };
        let worker = tokio::spawn(async move {
            let mut fence = fence;
            let mut emitter = ProgressEmitter::new(progress_sender, started);
            // Firefox can withhold even a wait:none reply until commitment.
            // Keep that one command alive while exposing cancellation to the
            // owner; never drop/replay it to stop an uncommitted navigation.
            let mut early = None;
            let reply_result = if immediate_reply.is_some() {
                immediate_reply
            } else {
                tokio::select! {
                    biased;
                    _ = &mut stopping => { early = Some(NavigationTermination::Cancelled); None },
                    () = sleep_until(deadline) => { early = Some(NavigationTermination::DeadlineReached); None },
                    result = &mut command => Some(result),
                }
            };
            let command_complete = reply_result.is_some();
            let reply = reply_result.and_then(|result| {
                result
                    .map_err(|_| {
                        early = Some(NavigationTermination::Failed {
                            reason: NavigationFailureReason::ProviderFailure,
                        });
                    })
                    .ok()
            });
            let navigation = reply
                .as_ref()
                .and_then(|value| value.get("navigation"))
                .and_then(Value::as_str)
                .map(str::to_owned);
            let expected_url = reply
                .as_ref()
                .and_then(|value| value.get("url"))
                .and_then(Value::as_str)
                .map(str::to_owned);
            let malformed_reply = reply.is_some() && expected_url.is_none();
            if malformed_reply {
                early = Some(NavigationTermination::Failed {
                    reason: NavigationFailureReason::ProviderFailure,
                });
            }
            if reply.is_some() {
                emitter.emit(NavigationProgressKind::CommandAccepted);
            }
            let mut committed = false;
            let mut same_document = false;
            let mut stop_loading = early.is_some();
            let mut readiness = false;
            let termination = if let Some(termination) = early {
                termination
            } else {
                loop {
                    tokio::select! {
                        biased;
                        stop = &mut stopping => {
                            stop_loading = true;
                            readiness = matches!(stop, Ok(NavigationStop::ReadinessSatisfied));
                            break if readiness {NavigationTermination::Completed} else {NavigationTermination::Cancelled};
                        },
                        () = sleep_until(deadline) => {stop_loading=true; break NavigationTermination::DeadlineReached;},
                        event = receiver.recv() => {
                            let Some(event) = event else {
                                break if Instant::now() >= deadline { stop_loading=true; NavigationTermination::DeadlineReached }
                                    else { NavigationTermination::Failed {reason:NavigationFailureReason::EventStreamClosed} };
                            };
                            if event.method == "browsingContext.contextDestroyed" {break NavigationTermination::PageClosed;}
                            let matches = match &navigation {
                                Some(id) => event.params.get("navigation").and_then(Value::as_str) == Some(id.as_str()),
                                // A null navigation ID identifies only a same-document
                                // transition, never an unrelated load at the same URL.
                                None => matches!(event.method.as_str(), "browsingContext.fragmentNavigated" | "browsingContext.historyUpdated")
                                    && event.params.get("url").and_then(Value::as_str) == expected_url.as_deref(),
                            };
                            if !matches {continue;}
                            match event.method.as_str() {
                                "browsingContext.navigationCommitted" => { committed=true; emitter.emit(NavigationProgressKind::DocumentCommitted); },
                                "browsingContext.domContentLoaded" => {
                                    if !committed {emitter.emit(NavigationProgressKind::DocumentCommitted); committed=true;}
                                    emitter.emit(NavigationProgressKind::DomContentLoaded);
                                },
                                "browsingContext.load" => { emitter.emit(NavigationProgressKind::Load); break NavigationTermination::Completed; },
                                "browsingContext.fragmentNavigated" | "browsingContext.historyUpdated" => {same_document=true; emitter.emit(NavigationProgressKind::SameDocumentNavigation); break NavigationTermination::Completed;},
                                "browsingContext.downloadWillBegin" => break NavigationTermination::Failed {reason:NavigationFailureReason::BecameDownload},
                                "browsingContext.navigationAborted" | "browsingContext.navigationFailed" => break NavigationTermination::Failed {reason:NavigationFailureReason::ProviderFailure},
                                _ => {},
                            }
                        }
                    }
                }
            };
            let mut cleanup_complete = !lost.load(Ordering::Acquire) && !malformed_reply;
            if stop_loading {
                cleanup_complete = match Instant::now().checked_add(options.cleanup_timeout()) {
                    Some(deadline) => {
                        let stopped = page.stop_loading(&CancellationToken::new(), deadline).await;
                        #[cfg(test)]
                        eprintln!(
                            "navigation cleanup stop={stopped:?} lost={} malformed={malformed_reply}",
                            lost.load(Ordering::Acquire)
                        );
                        stopped.is_ok() && cleanup_complete
                    }
                    None => false,
                };
            }
            if !command_complete {
                // Settle the original navigate reply after the acknowledged
                // stop. A protocol rejection (e.g. NS_BINDING_ABORTED) is a
                // settled command; a timeout/disconnect is uncertain cleanup.
                let settled = match Instant::now().checked_add(options.cleanup_timeout()) {
                    Some(until) => {
                        let reply = timeout_at(until, &mut command).await;
                        #[cfg(test)]
                        eprintln!("navigation cleanup original command={reply:?}");
                        matches!(reply, Ok(Ok(_) | Err(BidiError::Protocol { .. })))
                    }
                    None => false,
                };
                cleanup_complete = cleanup_complete && settled;
            }
            if readiness && !committed && !same_document {
                cleanup_complete = false;
            }
            pump.0.abort();
            let _ = (&mut pump.0).await;
            let report = NavigationReport {
                termination,
                progress: emitter.report(),
                provider_events_dropped: if lost.load(Ordering::Acquire) {
                    MeasuredCount::Unavailable {
                        reason: MeasurementUnavailableReason::ProviderDidNotReport,
                    }
                } else {
                    MeasuredCount::Known { value: 0 }
                },
                cleanup_complete,
                same_document,
            };
            state.finish(!cleanup_complete);
            fence.armed = !cleanup_complete;
            let _ = terminal_sender.send(report);
        });
        start_guard.disarm();
        Ok(ActiveNavigation {
            state: Arc::clone(&self.navigation_state),
            progress,
            terminal,
            cancel: Some(cancel),
            worker: Some(worker),
        })
    }
}
