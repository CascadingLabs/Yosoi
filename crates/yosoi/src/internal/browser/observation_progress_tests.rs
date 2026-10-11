use super::*;

#[tokio::test(start_paused = true)]
async fn quiet_progress_deadline_does_not_succeed_with_excess_in_flight() {
    let started = Instant::now();
    let (sender, mut receiver) = broadcast::channel(2);
    sender
        .send(ObservationProgress {
            armed_at: started,
            last_event_offset_micros: 0,
            last_event_at: started,
            relevant_in_flight: 1,
            has_admitted_event: true,
            has_lost_events: false,
            renderer_crashed: false,
            termination: None,
        })
        .expect("receiver remains live");
    let deadline = started + Duration::from_millis(20);
    let waiter = tokio::spawn(async move {
        wait_for_quiet_progress(&mut receiver, None, Duration::from_millis(5), 0, deadline).await
    });
    time::advance(Duration::from_millis(20)).await;
    assert_eq!(
        waiter.await.expect("wait task"),
        Err(QuietWaitError::DeadlineReached)
    );
    drop(sender);
}

#[tokio::test(start_paused = true)]
async fn cached_checkpoint_can_start_a_later_quiet_wait() {
    let started = Instant::now();
    let (_sender, mut receiver) = broadcast::channel(1);
    let initial = ObservationProgress {
        armed_at: started,
        last_event_offset_micros: 1,
        last_event_at: started,
        relevant_in_flight: 0,
        has_admitted_event: true,
        has_lost_events: false,
        renderer_crashed: false,
        termination: None,
    };
    let waiter = tokio::spawn(async move {
        wait_for_quiet_progress(
            &mut receiver,
            Some(initial),
            Duration::from_millis(5),
            0,
            started + Duration::from_secs(1),
        )
        .await
    });
    time::advance(Duration::from_millis(5)).await;
    assert!(waiter.await.expect("wait task").is_ok());
}

#[tokio::test]
async fn lagged_progress_and_terminal_progress_cannot_claim_quiet() {
    let started = Instant::now();
    let (sender, mut receiver) = broadcast::channel(1);
    for offset in [1_u64, 2] {
        sender
            .send(ObservationProgress {
                armed_at: started,
                last_event_offset_micros: offset,
                last_event_at: started,
                relevant_in_flight: 0,
                has_admitted_event: true,
                has_lost_events: false,
                renderer_crashed: false,
                termination: None,
            })
            .expect("receiver remains live");
    }
    assert_eq!(
        wait_for_quiet_progress(
            &mut receiver,
            None,
            Duration::from_millis(1),
            0,
            started + Duration::from_secs(1),
        )
        .await,
        Err(QuietWaitError::ProgressLost)
    );

    let (_sender, mut receiver) = broadcast::channel(1);
    assert_eq!(
        wait_for_quiet_progress(
            &mut receiver,
            Some(ObservationProgress {
                armed_at: started,
                last_event_offset_micros: 1,
                last_event_at: started,
                relevant_in_flight: 0,
                has_admitted_event: true,
                has_lost_events: false,
                renderer_crashed: false,
                termination: Some(ObservationTermination::ProviderDisconnected),
            }),
            Duration::from_millis(1),
            0,
            started + Duration::from_secs(1),
        )
        .await,
        Err(QuietWaitError::ObservationTerminated(
            ObservationTermination::ProviderDisconnected
        ))
    );
}

#[tokio::test]
async fn renderer_crash_progress_is_terminal() {
    let started = Instant::now();
    let (_sender, mut receiver) = broadcast::channel(1);
    let progress = ObservationProgress {
        armed_at: started,
        last_event_offset_micros: 0,
        last_event_at: started,
        relevant_in_flight: 0,
        has_admitted_event: false,
        has_lost_events: false,
        renderer_crashed: true,
        termination: None,
    };

    assert_eq!(
        wait_for_quiet_progress(
            &mut receiver,
            Some(progress),
            Duration::from_millis(1),
            0,
            started + Duration::from_secs(1),
        )
        .await,
        Err(QuietWaitError::RendererCrashed)
    );
}

#[test]
fn report_serialization_contains_no_payload_or_runtime_handle_fields() {
    let report = ObservationReport {
        started_at_unix_ms: Some(1),
        elapsed_micros: 2,
        termination: ObservationTermination::Finished,
        events: vec![ObservationEvent {
            sequence: 0,
            offset_micros: 1,
            kind: ObservationEventKind::RuntimeExceptionThrown,
        }],
        diagnostics: vec![RuntimeDiagnostic {
            event_sequence: 0,
            kind: RuntimeDiagnosticKind::Exception,
            retained_bytes: 6,
            complete_bytes: 6,
            truncated: false,
            text: ProtectedDiagnosticText(Arc::from(b"secret".as_slice())),
        }],
        diagnostic_bytes_retained: 6,
        diagnostic_bytes_dropped: 0,
        diagnostic_byte_limit: ByteLimit::one(),
        accounting: ObservationAccounting {
            events: ObservationCountAccounting {
                admitted: MeasuredCount::Known { value: 1 },
                retained: MeasuredCount::Known { value: 1 },
                dropped: MeasuredCount::Unavailable {
                    reason: MeasurementUnavailableReason::ProviderDidNotReport,
                },
            },
            runtime_events: ObservationCountAccounting {
                admitted: MeasuredCount::Known { value: 1 },
                retained: MeasuredCount::Known { value: 1 },
                dropped: MeasuredCount::Known { value: 0 },
            },
            runtime_bytes: ObservationCountAccounting {
                admitted: MeasuredCount::Known { value: 6 },
                retained: MeasuredCount::Known { value: 6 },
                dropped: MeasuredCount::Known { value: 0 },
            },
            in_flight_requests: MeasuredCount::Known { value: 0 },
        },
        cleanup_complete: true,
    };
    let serialized = serde_json::to_string(&report).expect("serialize report");
    for forbidden in [
        "url",
        "message",
        "exception_text",
        "request_id",
        "headers",
        "body",
        "ws_url",
        "profile_path",
        "secret",
    ] {
        assert!(!serialized.contains(forbidden), "report leaked {forbidden}");
    }
}
