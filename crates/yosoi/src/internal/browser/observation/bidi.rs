//! A receiver-only native terminal scope; no synthetic CDP crash/diagnostics.

use super::{
    ByteLimit, Instant, MeasuredCount, MeasurementUnavailableReason, ObservationAccounting,
    ObservationCountAccounting, ObservationOptions, ObservationProgress, ObservationReport,
    ObservationScope, ObservationTermination, Result, StopRequest, SystemTime, VoidCrawlError,
    broadcast, duration_micros, oneshot, unix_millis,
};
use crate::internal::browser::bidi::{session::Page, transport::BidiError};
use tokio_util::sync::CancellationToken;

impl ObservationScope {
    pub(in crate::internal::browser) async fn arm_bidi(
        page: Page,
        options: ObservationOptions,
    ) -> Result<Self> {
        let options = options.validate()?;
        if options.collect_network || options.collect_console || options.collect_exceptions {
            return Err(VoidCrawlError::UnsupportedCapability {
                operation: "native observation collectors",
            });
        }
        page.ensure_owned()
            .await
            .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let mut events = page
            .session
            .connection
            .subscribe()
            .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let started = Instant::now();
        let deadline =
            started
                .checked_add(options.max_duration)
                .ok_or(VoidCrawlError::InvalidInput {
                    operation: "observation",
                    reason: "deadline overflow",
                })?;
        let started_at_unix_ms = unix_millis(SystemTime::now());
        let diagnostic_byte_limit =
            ByteLimit::try_from(options.max_diagnostic_bytes).map_err(|_| {
                VoidCrawlError::InvalidInput {
                    operation: "observation",
                    reason: "invalid byte bound",
                }
            })?;
        let (stop, mut stopping) = oneshot::channel();
        let (progress_tx, progress) = broadcast::channel(1);
        let worker = tokio::spawn(async move {
            let cancellation = CancellationToken::new();
            let termination = loop {
                tokio::select! {
                    biased;
                    stop = &mut stopping => break match stop {
                        Ok(StopRequest::Finished) => ObservationTermination::Finished,
                        Ok(StopRequest::Cancelled) | Err(_) => ObservationTermination::Cancelled,
                        Ok(StopRequest::Interrupted) => ObservationTermination::Interrupted,
                    },
                    event = events.next(&cancellation, deadline) => match event {
                        Ok(event) if event.method == "browsingContext.contextDestroyed"
                            && event.params.get("context").and_then(serde_json::Value::as_str) == Some(page.context.as_str()) => break ObservationTermination::ProviderDisconnected,
                        Ok(_) => {},
                        Err(BidiError::Deadline) => break ObservationTermination::DeadlineReached,
                        Err(_) => break ObservationTermination::ProviderDisconnected,
                    }
                }
            };
            let elapsed_micros = duration_micros(started.elapsed());
            let _ = progress_tx.send(ObservationProgress {
                armed_at: started,
                last_event_offset_micros: elapsed_micros,
                last_event_at: Instant::now(),
                relevant_in_flight: 0,
                has_admitted_event: false,
                has_lost_events: termination == ObservationTermination::ProviderDisconnected,
                renderer_crashed: false,
                termination: Some(termination),
            });
            let not_collected = MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::NotCollected,
            };
            let counts = || ObservationCountAccounting {
                admitted: not_collected,
                retained: not_collected,
                dropped: not_collected,
            };
            Ok(ObservationReport {
                started_at_unix_ms,
                elapsed_micros,
                termination,
                events: Vec::new(),
                diagnostics: Vec::new(),
                diagnostic_bytes_retained: 0,
                diagnostic_bytes_dropped: 0,
                diagnostic_byte_limit,
                accounting: ObservationAccounting {
                    events: counts(),
                    runtime_events: counts(),
                    runtime_bytes: counts(),
                    in_flight_requests: not_collected,
                },
                cleanup_complete: true,
            })
        });
        Ok(Self {
            stop: Some(stop),
            worker: Some(worker),
            progress,
            latest_progress: None,
            armed_at: started,
            collects_network: false,
        })
    }
}
