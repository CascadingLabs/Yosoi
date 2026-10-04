#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

pub(super) fn empty_steps(plan: &ProfileWarmPlan) -> Vec<ProfileWarmStepReceipt> {
    plan.steps()
        .iter()
        .map(|step| ProfileWarmStepReceipt::not_attempted(step.id()))
        .collect()
}

pub(super) async fn execute_warm_plan(
    scheduler: &BrowserNavigationScheduler,
    plan: &ProfileWarmPlan,
    cancellation: &CancellationToken,
    overall_deadline: Instant,
) -> Result<(Vec<ProfileWarmStepReceipt>, ProfileWarmTerminalReason), ProfileWarmServiceError> {
    let mut steps = empty_steps(plan);
    let mut reason = ProfileWarmTerminalReason::Completed;
    let linked_cancellation = cancellation.child_token();
    let session = tokio::select! {
        biased;
        () = cancellation.cancelled() => {
            reason = ProfileWarmTerminalReason::CallerCancelled;
            linked_cancellation.cancel();
            None
        }
        () = sleep_until(overall_deadline) => {
            reason = ProfileWarmTerminalReason::DeadlineExceeded;
            linked_cancellation.cancel();
            None
        }
        result = scheduler.acquire_session(&linked_cancellation) => match result {
            Ok(session) => Some(session),
            Err(BrowserNavigationSchedulerError::ManagerUnavailable) => {
                reason = ProfileWarmTerminalReason::ProviderDisconnected;
                None
            }
            Err(_) => {
                reason = ProfileWarmTerminalReason::StagingFailed;
                None
            }
        }
    };
    let Some(session) = session else {
        return Ok((steps, reason));
    };

    let tab = session.initial_tab().clone();
    for (index, step) in plan.steps().iter().enumerate() {
        let nav_deadline = Instant::now()
            .checked_add(Duration::from_millis(
                plan.bounds().navigation_milliseconds(),
            ))
            .map(|deadline| deadline.min(overall_deadline));
        let Some(nav_deadline) = nav_deadline else {
            reason = ProfileWarmTerminalReason::DeadlineExceeded;
            break;
        };
        let scheduled = tokio::select! {
            biased;
            () = cancellation.cancelled() => {
                reason = ProfileWarmTerminalReason::CallerCancelled;
                linked_cancellation.cancel();
                break;
            }
            () = sleep_until(overall_deadline) => {
                reason = ProfileWarmTerminalReason::DeadlineExceeded;
                linked_cancellation.cancel();
                break;
            }
            () = sleep_until(nav_deadline) => {
                reason = ProfileWarmTerminalReason::DeadlineExceeded;
                linked_cancellation.cancel();
                break;
            }
            result = scheduler.schedule(
                &tab,
                BrowserNavigationCommand::new(step.target().clone(), plan.readiness()),
                &linked_cancellation,
            ) => result,
        };
        let Ok(handle) = scheduled else {
            reason = ProfileWarmTerminalReason::ProviderDisconnected;
            break;
        };
        let mut terminal_task = tokio::spawn(async move { handle.wait().await });
        let terminal = tokio::select! {
            biased;
            result = &mut terminal_task => result.ok().and_then(Result::ok),
            () = cancellation.cancelled() => {
                reason = ProfileWarmTerminalReason::CallerCancelled;
                linked_cancellation.cancel();
                (&mut terminal_task).await.ok().and_then(Result::ok)
            }
            () = sleep_until(overall_deadline) => {
                reason = ProfileWarmTerminalReason::DeadlineExceeded;
                linked_cancellation.cancel();
                (&mut terminal_task).await.ok().and_then(Result::ok)
            }
            () = sleep_until(nav_deadline) => {
                reason = ProfileWarmTerminalReason::DeadlineExceeded;
                linked_cancellation.cancel();
                (&mut terminal_task).await.ok().and_then(Result::ok)
            }
        };
        let Some(terminal) = terminal else {
            reason = ProfileWarmTerminalReason::ProviderDisconnected;
            break;
        };
        let outcome = terminal.outcome();
        let requested_readiness = terminal.requested_readiness();
        let reached_readiness = terminal.reached_readiness();
        let receipt = ProfileWarmStepReceipt::navigation(step.id(), terminal)
            .map_err(|_| ProfileWarmServiceError::ReceiptInvariant)?;
        let Some(slot) = steps.get_mut(index) else {
            return Err(ProfileWarmServiceError::ReceiptInvariant);
        };
        *slot = receipt;
        if reason != ProfileWarmTerminalReason::Completed {
            break;
        }
        if outcome != BrowserNavigationOutcome::Completed
            || requested_readiness != plan.readiness()
            || !readiness_reached(plan.readiness(), reached_readiness)
        {
            reason = if outcome == BrowserNavigationOutcome::Completed {
                ProfileWarmTerminalReason::ProviderDisconnected
            } else {
                ProfileWarmTerminalReason::NavigationFailed
            };
            break;
        }
    }
    let _ = session.release().await;
    Ok((steps, reason))
}

pub(super) const fn readiness_reached(
    readiness: BrowserNavigationReadinessCheckpoint,
    reached: Option<BrowserNavigationProgressKind>,
) -> bool {
    matches!(
        (readiness, reached),
        (
            BrowserNavigationReadinessCheckpoint::CommandAccepted,
            Some(BrowserNavigationProgressKind::CommandAccepted)
        ) | (
            BrowserNavigationReadinessCheckpoint::DocumentCommitted,
            Some(BrowserNavigationProgressKind::DocumentCommitted)
        ) | (
            BrowserNavigationReadinessCheckpoint::DomContentLoaded,
            Some(BrowserNavigationProgressKind::DomContentLoaded)
        ) | (
            BrowserNavigationReadinessCheckpoint::Load,
            Some(BrowserNavigationProgressKind::Load)
        ) | (
            BrowserNavigationReadinessCheckpoint::ControllerCompleted,
            Some(BrowserNavigationProgressKind::ControllerCompleted)
        )
    )
}
