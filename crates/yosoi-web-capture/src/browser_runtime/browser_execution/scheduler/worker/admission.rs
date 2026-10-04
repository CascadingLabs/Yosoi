use std::{sync::Arc, time::Duration};

use tokio::time::{Instant, sleep_until};

use crate as yosoi;

use super::{NavigationJob, SchedulerInner, internal_failure};

pub(super) async fn wait_for_admission(
    inner: &Arc<SchedulerInner>,
    job: &NavigationJob,
    submitted: Instant,
) -> Result<(), yosoi::BrowserNavigationOutcome> {
    let Some(deadline) = submitted.checked_add(Duration::from_millis(
        inner.manager.limits().queue_wait().milliseconds(),
    )) else {
        return Err(internal_failure());
    };
    loop {
        if inner.closing.is_cancelled() || inner.manager.inner.closing.is_cancelled() {
            return Err(yosoi::BrowserNavigationOutcome::ManagerShutdown);
        }
        if job.tab.closing.is_cancelled() {
            return Err(yosoi::BrowserNavigationOutcome::TabClosed);
        }
        if job.caller_cancellation.is_cancelled() || job.handle_cancellation.is_cancelled() {
            return Err(yosoi::BrowserNavigationOutcome::CancelledBeforeAdmission);
        }
        if Instant::now() >= deadline {
            return Err(yosoi::BrowserNavigationOutcome::QueueWaitDeadline);
        }
        let notified = inner.state_changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        {
            let mut state = inner.state.lock().await;
            let selected = if state.active_navigations < inner.limits.active_navigations().get() {
                select_runnable(&state)
            } else {
                None
            };
            if selected.is_some_and(|(ticket, _)| ticket == job.ticket) {
                let position = state
                    .queue
                    .iter()
                    .position(|candidate| candidate.ticket == job.ticket)
                    .ok_or_else(internal_failure)?;
                let queued = state.queue.remove(position).ok_or_else(internal_failure)?;
                if state
                    .active_tabs
                    .insert(job.tab.lease.tab(), queued.session)
                    .is_some()
                {
                    return Err(internal_failure());
                }
                state.active_navigations = state
                    .active_navigations
                    .checked_add(1)
                    .ok_or_else(internal_failure)?;
                state.last_dispatched_session = Some(queued.session);
                drop(state);
                inner.state_changed.notify_waiters();
                return Ok(());
            }
        }
        tokio::select! {
            biased;
            () = inner.closing.cancelled() => return Err(yosoi::BrowserNavigationOutcome::ManagerShutdown),
            () = inner.manager.inner.closing.cancelled() => return Err(yosoi::BrowserNavigationOutcome::ManagerShutdown),
            () = job.tab.closing.cancelled() => return Err(yosoi::BrowserNavigationOutcome::TabClosed),
            () = job.caller_cancellation.cancelled() => return Err(yosoi::BrowserNavigationOutcome::CancelledBeforeAdmission),
            () = job.handle_cancellation.cancelled() => return Err(yosoi::BrowserNavigationOutcome::CancelledBeforeAdmission),
            () = sleep_until(deadline) => return Err(yosoi::BrowserNavigationOutcome::QueueWaitDeadline),
            () = &mut notified => {}
        }
    }
}

pub(super) async fn remove_queued(inner: &Arc<SchedulerInner>, ticket: u64) {
    let mut state = inner.state.lock().await;
    let position = state
        .queue
        .iter()
        .position(|candidate| candidate.ticket == ticket);
    let removed = position.and_then(|position| state.queue.remove(position));
    if let Some(removed) = removed {
        remove_inactive_session(&mut state, removed.session);
    }
    drop(state);
    inner.state_changed.notify_waiters();
}

pub(super) async fn release_active(inner: &Arc<SchedulerInner>, tab: yosoi::BrowserTabLeaseId) {
    let mut state = inner.state.lock().await;
    if let Some(session) = state.active_tabs.remove(&tab) {
        state.active_navigations = state.active_navigations.saturating_sub(1);
        remove_inactive_session(&mut state, session);
    }
    drop(state);
    inner.state_changed.notify_waiters();
}

fn select_runnable(
    state: &super::super::SchedulerState,
) -> Option<(u64, yosoi::BrowserSessionLeaseId)> {
    let start = state
        .last_dispatched_session
        .and_then(|last| {
            state
                .session_order
                .iter()
                .position(|candidate| *candidate == last)
        })
        .and_then(|position| position.checked_add(1))
        .unwrap_or(0);
    state
        .session_order
        .iter()
        .skip(start)
        .chain(state.session_order.iter().take(start))
        .find_map(|session| {
            state
                .queue
                .iter()
                .find(|candidate| {
                    candidate.session == *session && !state.active_tabs.contains_key(&candidate.tab)
                })
                .map(|candidate| (candidate.ticket, candidate.session))
        })
}

fn remove_inactive_session(
    state: &mut super::super::SchedulerState,
    session: yosoi::BrowserSessionLeaseId,
) {
    let queued = state
        .queue
        .iter()
        .any(|candidate| candidate.session == session);
    let active = state
        .active_tabs
        .values()
        .any(|candidate| *candidate == session);
    if queued || active {
        return;
    }
    if let Some(position) = state
        .session_order
        .iter()
        .position(|candidate| *candidate == session)
    {
        state.session_order.remove(position);
    }
}
