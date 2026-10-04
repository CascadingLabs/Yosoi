use super::*;

#[tokio::test]
#[allow(clippy::expect_used, reason = "test")]
async fn caller_wait_budget_preserves_a_deadline_report() {
    let limits = ResponseCaptureLimits::default();
    let (cancel, cancel_rx) = oneshot::channel();
    let worker = tokio::spawn(async move {
        let _ = cancel_rx.await;
        capture_report(
            HashMap::new(),
            0,
            0,
            limits,
            ResponseCaptureTermination::Cancelled,
        )
    });
    let capture = ResponseCapture {
        cancel: Some(cancel),
        worker: Some(worker),
        patterns: vec!["test".into()],
        timeout: Duration::from_secs(1),
    };
    let report = capture
        .wait_report_for(Duration::ZERO)
        .await
        .expect("deadline report");
    assert_eq!(
        report.termination,
        ResponseCaptureTermination::DeadlineReached
    );
    assert!(matches!(
        report.aggregate_bytes.additional_loss(),
        MeasuredBrowserBytes::Unavailable { .. }
    ));
}
