use std::{
    collections::{HashMap, VecDeque},
    future::Future,
};

use tokio::{
    task::{Id as TaskId, JoinSet},
    time::{Instant, sleep_until},
};
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum SchedulerStopReason {
    Cancelled,
    DeadlineReached,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum SchedulerTermination {
    Completed,
    Cancelled,
    DeadlineReached,
}

pub(super) struct ScheduledJob<J> {
    pub(super) slot: usize,
    pub(super) uses_browser: bool,
    pub(super) payload: J,
}

pub(super) struct SchedulerResult<T> {
    pub(super) slots: Vec<Option<T>>,
    pub(super) not_started: Vec<Option<SchedulerStopReason>>,
    pub(super) termination: SchedulerTermination,
}

pub(super) async fn run_scheduler<J, T, F, Fut>(
    jobs: VecDeque<ScheduledJob<J>>,
    slots: Vec<Option<T>>,
    max_in_flight: usize,
    max_browser_in_flight: usize,
    deadline: Instant,
    caller_cancellation: &CancellationToken,
    worker: F,
) -> SchedulerResult<T>
where
    J: Send + 'static,
    T: Send + 'static,
    F: Fn(J, CancellationToken) -> Fut + Clone + Send + Sync + 'static,
    Fut: Future<Output = T> + Send + 'static,
{
    let slot_count = slots.len();
    let mut result = SchedulerResult {
        slots,
        not_started: vec![None; slot_count],
        termination: SchedulerTermination::Completed,
    };
    let mut queued = jobs;
    let mut running = JoinSet::new();
    let mut active = HashMap::<TaskId, bool>::new();
    let operation_cancellation = caller_cancellation.child_token();
    let mut stop_reason = None;

    loop {
        if stop_reason.is_none() {
            if caller_cancellation.is_cancelled() {
                stop_reason = Some(SchedulerStopReason::Cancelled);
            } else if Instant::now() >= deadline {
                stop_reason = Some(SchedulerStopReason::DeadlineReached);
            }
            if let Some(reason) = stop_reason {
                operation_cancellation.cancel();
                mark_queued_not_started(&mut queued, &mut result, reason);
            }
        }

        if stop_reason.is_none() {
            while running.len() < max_in_flight {
                if caller_cancellation.is_cancelled() {
                    stop_reason = Some(SchedulerStopReason::Cancelled);
                    operation_cancellation.cancel();
                    mark_queued_not_started(
                        &mut queued,
                        &mut result,
                        SchedulerStopReason::Cancelled,
                    );
                    break;
                }
                if Instant::now() >= deadline {
                    stop_reason = Some(SchedulerStopReason::DeadlineReached);
                    operation_cancellation.cancel();
                    mark_queued_not_started(
                        &mut queued,
                        &mut result,
                        SchedulerStopReason::DeadlineReached,
                    );
                    break;
                }
                let browser_count = active.values().filter(|is_browser| **is_browser).count();
                let eligible = queued
                    .iter()
                    .position(|job| !job.uses_browser || browser_count < max_browser_in_flight);
                let Some(eligible) = eligible else {
                    break;
                };
                let Some(job) = queued.remove(eligible) else {
                    break;
                };
                let token = operation_cancellation.child_token();
                let run_worker = worker.clone();
                let slot = job.slot;
                let uses_browser = job.uses_browser;
                let abort_handle = running.spawn(async move {
                    let value = run_worker(job.payload, token).await;
                    (slot, uses_browser, value)
                });
                active.insert(abort_handle.id(), uses_browser);
            }
        }

        if running.is_empty() {
            if stop_reason.is_none() && !queued.is_empty() {
                // A nonzero browser limit and no active jobs make every queued
                // job eligible; this branch only protects against bad bounds.
                mark_queued_not_started(
                    &mut queued,
                    &mut result,
                    SchedulerStopReason::DeadlineReached,
                );
                stop_reason = Some(SchedulerStopReason::DeadlineReached);
                result.termination = SchedulerTermination::DeadlineReached;
            }
            break;
        }

        // Do not abort a started Request while cancellation settles. Each
        // child profile has a positive maximum_elapsed; Direct HTTP uses that
        // attempt deadline, and browser capture reserves its bounded cleanup
        // grace after the attempt deadline. Joining lets those paths finish.
        tokio::select! {
            biased;
            () = caller_cancellation.cancelled(), if stop_reason.is_none() => {
                stop_reason = Some(SchedulerStopReason::Cancelled);
                result.termination = SchedulerTermination::Cancelled;
                operation_cancellation.cancel();
                mark_queued_not_started(&mut queued, &mut result, SchedulerStopReason::Cancelled);
            }
            () = sleep_until(deadline), if stop_reason.is_none() => {
                stop_reason = Some(SchedulerStopReason::DeadlineReached);
                result.termination = SchedulerTermination::DeadlineReached;
                operation_cancellation.cancel();
                mark_queued_not_started(&mut queued, &mut result, SchedulerStopReason::DeadlineReached);
            }
            joined = running.join_next_with_id() => {
                match joined {
                    Some(Ok((task_id, (slot, _uses_browser, value)))) => {
                        active.remove(&task_id);
                        if let Some(destination) = result.slots.get_mut(slot) {
                            *destination = Some(value);
                        }
                    }
                    Some(Err(error)) => {
                        active.remove(&error.id());
                    }
                    None => {}
                }
            }
        }
    }

    if let Some(reason) = stop_reason {
        result.termination = match reason {
            SchedulerStopReason::Cancelled => SchedulerTermination::Cancelled,
            SchedulerStopReason::DeadlineReached => SchedulerTermination::DeadlineReached,
        };
    }
    result
}

fn mark_queued_not_started<J, T>(
    queued: &mut VecDeque<ScheduledJob<J>>,
    result: &mut SchedulerResult<T>,
    reason: SchedulerStopReason,
) {
    while let Some(job) = queued.pop_front() {
        if let Some(slot) = result.not_started.get_mut(job.slot) {
            *slot = Some(reason);
        }
    }
}
