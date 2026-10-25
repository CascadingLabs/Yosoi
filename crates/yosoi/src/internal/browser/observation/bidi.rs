//! Native network and log events normalized into bounded shared observations.

use super::{
    BrowserBudgetScope, BrowserByteBudget, BrowserByteDomain, BrowserByteSpec, BrowserLimitScope,
    HashSet, Instant, MeasuredCount, MeasurementUnavailableReason, ObservationAccounting,
    ObservationCountAccounting, ObservationEventKind, ObservationOptions, ObservationProgress,
    ObservationReport, ObservationScope, ObservationTermination, RawDiagnostic, RawSignal,
    RequestTransition, Result, RetainOutcome, RuntimeDiagnosticKind, StopRequest, SystemTime,
    VoidCrawlError, broadcast, duration_micros, instant_at_offset, oneshot, retain_signal,
    unix_millis,
};
use crate::browser::BrowserEngine;
use crate::internal::browser::{
    bidi::{
        session::{Page, SessionError},
        transport::{BidiError, BidiEvent},
    },
    controller::map_bidi,
};
use serde_json::Value;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

impl ObservationScope {
    pub(in crate::internal::browser) async fn arm_bidi(
        page: Page,
        options: ObservationOptions,
    ) -> Result<Self> {
        let options = options.validate()?;
        page.ensure_owned().await.map_err(map_bidi)?;
        let started = Instant::now();
        let deadline =
            started
                .checked_add(options.max_duration)
                .ok_or(VoidCrawlError::InvalidInput {
                    operation: "observation",
                    reason: "deadline overflow",
                })?;
        let token = CancellationToken::new();
        // Moli 1.1.19 omits top-level document network events in isolated
        // contexts. Its subresource events remain useful, but cannot prove
        // a complete in-flight count or network quiet settlement.
        let complete_network = page.session.config.engine != BrowserEngine::Moli;
        let complete_runtime =
            page.session.config.engine != BrowserEngine::Moli || !options.collect_exceptions;
        let collect_runtime = options.collect_console || options.collect_exceptions;
        let mut events = page
            .arm_observation_events(options.collect_network, collect_runtime, &token, deadline)
            .await
            .map_err(map_bidi)?;
        let started_at_unix_ms = unix_millis(SystemTime::now());
        let diagnostic_byte_limit =
            options
                .diagnostic_limit()
                .map_err(|_| VoidCrawlError::InvalidInput {
                    operation: "observation",
                    reason: "invalid byte bound",
                })?;
        let (stop, mut stopping) = oneshot::channel();
        let (progress_tx, progress) = broadcast::channel(options.max_events.clamp(1, 2048));
        let worker = tokio::spawn(async move {
            let mut retained = Vec::new();
            let mut runtime_admitted = 0usize;
            let mut missing_text = 0usize;
            let mut in_flight = HashSet::new();
            let mut diagnostics = Vec::new();
            let mut diagnostic_bytes_retained = 0;
            let mut diagnostic_bytes_dropped = 0;
            let mut budget = BrowserByteBudget::new(BrowserByteSpec::new(
                BrowserByteDomain::RuntimeDiagnosticUtf8,
                diagnostic_byte_limit,
                BrowserLimitScope::RetentionAfterProviderMaterialization,
                BrowserBudgetScope::CaptureAggregate,
            ));
            let mut update = ObservationProgress {
                armed_at: started,
                last_event_offset_micros: 0,
                last_event_at: started,
                relevant_in_flight: 0,
                has_admitted_event: false,
                has_lost_events: false,
                renderer_crashed: false,
                termination: None,
            };
            let _ = progress_tx.send(update);
            let termination = loop {
                let event = tokio::select! {
                    biased;
                    event = events.next(&token, deadline) => match event {
                        Ok(event) => event,
                        Err(SessionError::Transport(BidiError::Deadline)) => break ObservationTermination::DeadlineReached,
                        Err(_) => break ObservationTermination::ProviderDisconnected,
                    },
                    stop = &mut stopping => break match stop {
                        Ok(StopRequest::Finished) => ObservationTermination::Finished,
                        Ok(StopRequest::Cancelled) | Err(_) => ObservationTermination::Cancelled,
                        Ok(StopRequest::Interrupted) => ObservationTermination::Interrupted,
                    },
                };
                if event.method == "browsingContext.contextDestroyed"
                    && event.params.get("context").and_then(Value::as_str)
                        == Some(page.context.as_str())
                {
                    break ObservationTermination::ProviderDisconnected;
                }
                let signal = if event.method == "log.entryAdded" {
                    match runtime_signal(&event, options) {
                        Ok(Some((signal, unavailable))) => {
                            let Some(count) = runtime_admitted.checked_add(1) else {
                                break ObservationTermination::EventLimitReached;
                            };
                            runtime_admitted = count;
                            if unavailable {
                                let Some(count) = missing_text.checked_add(1) else {
                                    break ObservationTermination::EventLimitReached;
                                };
                                missing_text = count;
                            }
                            signal
                        }
                        Ok(None) => continue,
                        Err(_) => break ObservationTermination::ProviderDisconnected,
                    }
                } else {
                    let Some(signal) = network_signal(&event) else {
                        continue;
                    };
                    signal
                };
                match retain_signal(
                    signal,
                    &mut retained,
                    &mut in_flight,
                    options.max_events,
                    duration_micros(started.elapsed()),
                    &mut diagnostics,
                    &mut diagnostic_bytes_retained,
                    &mut diagnostic_bytes_dropped,
                    options.max_diagnostic_bytes,
                    &mut budget,
                ) {
                    RetainOutcome::Continue => {}
                    RetainOutcome::EventLimitReached => {
                        break ObservationTermination::EventLimitReached;
                    }
                    RetainOutcome::StreamClosed => {
                        break ObservationTermination::ProviderDisconnected;
                    }
                }
                update.last_event_offset_micros =
                    retained.last().map_or(0, |event| event.offset_micros);
                update.last_event_at = instant_at_offset(started, update.last_event_offset_micros);
                update.relevant_in_flight = in_flight.len();
                update.has_admitted_event = !retained.is_empty();
                let _ = progress_tx.send(update);
            };
            update.last_event_offset_micros =
                retained.last().map_or(0, |event| event.offset_micros);
            update.last_event_at = instant_at_offset(started, update.last_event_offset_micros);
            update.relevant_in_flight = in_flight.len();
            update.has_admitted_event = !retained.is_empty();
            update.termination = Some(termination);
            update.has_lost_events = matches!(
                termination,
                ObservationTermination::ProviderDisconnected
                    | ObservationTermination::EventLimitReached
            );
            let _ = progress_tx.send(update);
            let cleanup_complete = match Instant::now().checked_add(Duration::from_secs(5)) {
                Some(deadline) => events.close(&token, deadline).await.is_ok(),
                None => false,
            };
            let not_collected = MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::NotCollected,
            };
            let unknown = MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::ProviderDidNotReport,
            };
            let known = |count: usize| {
                u64::try_from(count).map_or(unknown, |value| MeasuredCount::Known { value })
            };
            let no_counts = ObservationCountAccounting {
                admitted: not_collected,
                retained: not_collected,
                dropped: not_collected,
            };
            Ok(ObservationReport {
                started_at_unix_ms,
                elapsed_micros: duration_micros(started.elapsed()),
                termination,
                accounting: ObservationAccounting {
                    events: if options.collect_network || collect_runtime {
                        ObservationCountAccounting {
                            admitted: known(retained.len()),
                            retained: known(retained.len()),
                            dropped: unknown,
                        }
                    } else {
                        no_counts
                    },
                    runtime_events: if collect_runtime {
                        ObservationCountAccounting {
                            admitted: known(runtime_admitted),
                            retained: known(diagnostics.len()),
                            dropped: if termination == ObservationTermination::Finished
                                && complete_runtime
                            {
                                known(missing_text)
                            } else {
                                unknown
                            },
                        }
                    } else {
                        no_counts
                    },
                    runtime_bytes: if collect_runtime {
                        ObservationCountAccounting {
                            admitted: diagnostic_bytes_retained
                                .checked_add(diagnostic_bytes_dropped)
                                .map_or(unknown, known),
                            retained: known(diagnostic_bytes_retained),
                            dropped: if missing_text == 0 && complete_runtime {
                                known(diagnostic_bytes_dropped)
                            } else {
                                unknown
                            },
                        }
                    } else {
                        no_counts
                    },
                    in_flight_requests: if options.collect_network
                        && complete_network
                        && !update.has_lost_events
                    {
                        known(in_flight.len())
                    } else if options.collect_network {
                        unknown
                    } else {
                        not_collected
                    },
                },
                events: retained,
                diagnostics,
                diagnostic_bytes_retained,
                diagnostic_bytes_dropped,
                diagnostic_byte_limit,
                cleanup_complete,
            })
        });
        Ok(Self {
            stop: Some(stop),
            worker: Some(worker),
            progress,
            latest_progress: None,
            armed_at: started,
            collects_network: options.collect_network && complete_network,
        })
    }
}

fn network_signal(event: &BidiEvent) -> Option<RawSignal> {
    let request = event
        .params
        .get("request")?
        .get("request")?
        .as_str()?
        .to_owned();
    let (kind, transition) = match event.method.as_str() {
        "network.beforeRequestSent" => (
            if event
                .params
                .get("navigation")
                .and_then(Value::as_str)
                .is_some()
            {
                ObservationEventKind::DocumentRequestStarted
            } else {
                ObservationEventKind::ResourceRequestStarted
            },
            Some(RequestTransition::Started(request)),
        ),
        "network.responseStarted" => (ObservationEventKind::ResponseReceived, None),
        "network.responseCompleted" => (
            ObservationEventKind::RequestFinished,
            Some(RequestTransition::Finished(request)),
        ),
        "network.fetchError" => (
            ObservationEventKind::RequestFailed,
            Some(RequestTransition::Finished(request)),
        ),
        _ => return None,
    };
    Some(RawSignal::Event {
        kind,
        request: transition,
        diagnostic: None,
    })
}

fn runtime_signal(
    event: &BidiEvent,
    options: ObservationOptions,
) -> Result<Option<(RawSignal, bool)>> {
    let (kind, diagnostic_kind) = match event.params.get("type").and_then(Value::as_str) {
        Some("console") if options.collect_console => {
            let method = event.params.get("method").and_then(Value::as_str);
            let level = match method {
                Some("warn") => "warning",
                Some("group") => "startGroup",
                Some("groupCollapsed") => "startGroupCollapsed",
                Some("groupEnd") => "endGroup",
                Some(
                    value @ ("log" | "debug" | "info" | "error" | "dir" | "dirxml" | "table"
                    | "trace" | "clear" | "assert" | "profile" | "profileEnd" | "count"
                    | "timeEnd"),
                ) => value,
                _ => match event.params.get("level").and_then(Value::as_str) {
                    Some("warn") => "warning",
                    Some(level @ ("debug" | "info" | "error")) => level,
                    _ => {
                        return Err(VoidCrawlError::PageError(
                            "native log level unavailable".to_owned(),
                        ));
                    }
                },
            };
            (
                ObservationEventKind::ConsoleApiCalled,
                RuntimeDiagnosticKind::Console {
                    level: level.to_owned(),
                },
            )
        }
        Some("javascript") if options.collect_exceptions => (
            ObservationEventKind::RuntimeExceptionThrown,
            RuntimeDiagnosticKind::Exception,
        ),
        _ => return Ok(None),
    };
    // A nullable protocol text is not an empty message. Keep its lifecycle
    // marker, count the omitted diagnostic, and preserve unknown byte loss.
    let text = event.params.get("text").and_then(Value::as_str);
    let diagnostic = text.map(|text| RawDiagnostic {
        kind: diagnostic_kind,
        text: text.to_owned(),
    });
    Ok(Some((
        RawSignal::Event {
            kind,
            request: None,
            diagnostic,
        },
        text.is_none(),
    )))
}

#[cfg(test)]
mod tests;
