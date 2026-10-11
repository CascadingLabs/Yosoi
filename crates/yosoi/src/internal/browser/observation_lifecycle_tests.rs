use std::future;

use super::*;

#[test]
fn options_reject_zero_bounds_but_allow_crash_only_scope() {
    assert!(
        ObservationOptions {
            collect_network: false,
            collect_console: false,
            collect_exceptions: false,
            ..ObservationOptions::default()
        }
        .validate()
        .is_ok()
    );
    assert!(
        ObservationOptions {
            max_events: 0,
            ..ObservationOptions::default()
        }
        .validate()
        .is_err()
    );
    assert!(
        ObservationOptions {
            max_diagnostic_bytes: 0,
            ..ObservationOptions::default()
        }
        .validate()
        .is_err()
    );
    assert!(
        ObservationOptions {
            max_duration: Duration::ZERO,
            ..ObservationOptions::default()
        }
        .validate()
        .is_err()
    );
}

struct AbortSignal(Option<oneshot::Sender<()>>);

impl Drop for AbortSignal {
    fn drop(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.send(());
        }
    }
}

fn pending_scope() -> (
    ObservationScope,
    oneshot::Receiver<()>,
    oneshot::Receiver<()>,
) {
    let (stop, _) = oneshot::channel();
    let (started_tx, started_rx) = oneshot::channel();
    let (aborted_tx, aborted_rx) = oneshot::channel();
    let worker = tokio::spawn(async move {
        let _signal = AbortSignal(Some(aborted_tx));
        let _ = started_tx.send(());
        future::pending::<Result<ObservationReport>>().await
    });
    let (_progress_tx, progress) = broadcast::channel(1);
    (
        ObservationScope {
            stop: Some(stop),
            worker: Some(worker),
            progress,
            latest_progress: None,
            armed_at: Instant::now(),
            collects_network: true,
        },
        started_rx,
        aborted_rx,
    )
}

#[tokio::test]
async fn cancelling_terminal_joins_aborts_the_owned_worker() {
    macro_rules! assert_terminal_join_aborts_worker {
        ($method:ident) => {{
            let (scope, started, aborted) = pending_scope();
            started.await.expect("worker started");
            let terminal = tokio::spawn(async move { scope.$method().await });
            tokio::task::yield_now().await;
            terminal.abort();
            let _ = terminal.await;
            tokio::time::timeout(Duration::from_secs(1), aborted)
                .await
                .expect("scope drop did not abort worker")
                .expect("worker abort signal dropped");
        }};
    }

    assert_terminal_join_aborts_worker!(wait);
    assert_terminal_join_aborts_worker!(finish);
    assert_terminal_join_aborts_worker!(cancel);
}

#[tokio::test(start_paused = true)]
async fn quiet_progress_resets_on_event_and_returns_zero_interval_accounting() {
    let started = Instant::now();
    let (sender, mut receiver) = broadcast::channel(4);
    sender
        .send(ObservationProgress {
            armed_at: started,
            last_event_offset_micros: 0,
            last_event_at: started,
            relevant_in_flight: 0,
            has_admitted_event: false,
            has_lost_events: false,
            renderer_crashed: false,
            termination: None,
        })
        .expect("receiver remains live");
    let waiter = tokio::spawn(async move {
        wait_for_quiet_progress(
            &mut receiver,
            None,
            Duration::from_millis(10),
            0,
            started + Duration::from_secs(1),
        )
        .await
    });
    time::advance(Duration::from_millis(5)).await;
    sender
        .send(ObservationProgress {
            armed_at: started,
            last_event_offset_micros: 5_000,
            last_event_at: started + Duration::from_millis(5),
            relevant_in_flight: 0,
            has_admitted_event: true,
            has_lost_events: false,
            renderer_crashed: false,
            termination: None,
        })
        .expect("waiter remains live");
    time::advance(Duration::from_millis(10)).await;
    let proof = waiter.await.expect("wait task").expect("quiet proof");
    assert_eq!(proof.quiet_since_offset_micros, 5_000);
    assert!(proof.satisfied_offset_micros >= 15_000);
    let zero = MeasuredCount::Known { value: 0 };
    assert_eq!(
        proof.event_accounting,
        ObservationCountAccounting {
            admitted: zero,
            retained: zero,
            dropped: zero
        }
    );
}
