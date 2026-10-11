use super::{
    Arc, BrowserExecutionManagerError, CloseAction, Duration, ExecutionPageContext, Handle,
    Instant, LeaseResource, ProcessStatus, ReleaseCompletion, ReleaseProgress,
    close_process_slot_outcome, find_slot_mut, sleep_until, timeout_at, yosoi,
};

pub(super) fn cleanup_deadline(limits: yosoi::BrowserExecutionLimits) -> Instant {
    Instant::now()
        .checked_add(Duration::from_millis(
            limits.cleanup_deadline().milliseconds(),
        ))
        .unwrap_or_else(Instant::now)
}

pub(super) fn release_wait_deadline(limits: yosoi::BrowserExecutionLimits) -> Instant {
    let milliseconds = limits
        .cleanup_deadline()
        .milliseconds()
        .checked_mul(2)
        .unwrap_or_else(|| limits.cleanup_deadline().milliseconds());
    Instant::now()
        .checked_add(Duration::from_millis(milliseconds))
        .unwrap_or_else(Instant::now)
}

pub(super) enum ReleaseExecutor {
    Stable,
    Current,
}

pub(super) async fn start_release(
    resource: Arc<LeaseResource>,
    deadline: Instant,
    executor_choice: ReleaseExecutor,
) {
    let Some(manager) = resource.manager.upgrade() else {
        return;
    };
    let executor = match executor_choice {
        ReleaseExecutor::Stable => manager
            .provider_executor
            .clone()
            .unwrap_or_else(Handle::current),
        ReleaseExecutor::Current => Handle::current(),
    };
    let mut state = resource.state.lock().await;
    if state.release_result.is_some() {
        return;
    }
    state.releasing = true;
    for tab in state.tabs.values() {
        tab.navigation_closing.cancel();
    }
    if state
        .release_worker
        .as_ref()
        .is_some_and(|worker| !worker.is_finished())
    {
        return;
    }
    let worker_resource = Arc::clone(&resource);
    state.release_worker = Some(executor.spawn(async move {
        release_resource_attempt(worker_resource, deadline).await;
    }));
}

pub(super) async fn restart_release_on_current(resource: Arc<LeaseResource>, deadline: Instant) {
    let worker = {
        let mut state = resource.state.lock().await;
        if state.release_result.is_some() {
            return;
        }
        state.release_worker.take()
    };
    if let Some(worker) = worker {
        worker.abort();
        let _ = worker.await;
    }
    start_release(resource, deadline, ReleaseExecutor::Current).await;
}

pub(super) async fn release_resource_attempt(resource: Arc<LeaseResource>, deadline: Instant) {
    let pending_tab_creations = cancel_pending_tab_creations(&resource).await;
    let managed_profile_context = matches!(
        resource.state.lock().await.context.as_deref(),
        Some(ExecutionPageContext::ManagedProfile(_))
    );
    let navigation_quiet = wait_for_navigation_lanes(&resource, deadline).await;
    let context = if navigation_quiet {
        take_context_for_release(&resource, deadline).await
    } else {
        None
    };

    #[cfg(test)]
    let release_pause = match resource.manager.upgrade() {
        Some(manager) => manager.state.lock().await.release_pause.take(),
        None => None,
    };
    #[cfg(test)]
    if let Some((started, proceed)) = release_pause {
        started.notify_one();
        proceed.notified().await;
    }

    #[cfg(test)]
    let injected_context_disposition = match resource.manager.upgrade() {
        Some(manager) => manager
            .state
            .lock()
            .await
            .context_cleanup_dispositions
            .pop_front(),
        None => None,
    };
    let observed_context_disposition = match context {
        Some(context) => match context {
            ExecutionPageContext::Isolated(context) => {
                let cleanup = context.dispose_before(deadline).await;
                if cleanup.cleanup_complete {
                    yosoi::BrowserContextCleanupDisposition::Completed
                } else if Instant::now() >= deadline {
                    yosoi::BrowserContextCleanupDisposition::DeadlineExceeded
                } else {
                    yosoi::BrowserContextCleanupDisposition::Failed
                }
            }
            ExecutionPageContext::ManagedProfile(_) => {
                if resource.authorize_profile_cleanup().is_err() {
                    yosoi::BrowserContextCleanupDisposition::Failed
                } else {
                    close_managed_profile_pages(&resource, deadline).await
                }
            }
        },
        None => yosoi::BrowserContextCleanupDisposition::Failed,
    };
    #[cfg(test)]
    let context_disposition = if pending_tab_creations && managed_profile_context {
        yosoi::BrowserContextCleanupDisposition::Failed
    } else {
        injected_context_disposition.unwrap_or(observed_context_disposition)
    };
    #[cfg(not(test))]
    let context_disposition = if pending_tab_creations && managed_profile_context {
        yosoi::BrowserContextCleanupDisposition::Failed
    } else {
        observed_context_disposition
    };
    let active_tabs = resource.state.lock().await.active_tabs;
    let result =
        finish_resource_release(&resource, active_tabs, context_disposition, deadline).await;
    let mut state = resource.state.lock().await;
    state.tabs.clear();
    state.tab_creations.clear();
    state.active_tabs = 0;
    if state.release_result.is_none() {
        state.release_result = Some(result);
    }
    drop(state);
    resource.released.notify_waiters();
}

async fn close_managed_profile_pages(
    resource: &Arc<LeaseResource>,
    deadline: Instant,
) -> yosoi::BrowserContextCleanupDisposition {
    let pages = {
        let state = resource.state.lock().await;
        state
            .tabs
            .values()
            .filter(|tab| tab.open)
            .filter_map(|tab| tab.page.as_ref().map(Arc::clone))
            .collect::<Vec<_>>()
    };
    for page in pages {
        if !matches!(timeout_at(deadline, page.close()).await, Ok(Ok(()))) {
            return if Instant::now() >= deadline {
                yosoi::BrowserContextCleanupDisposition::DeadlineExceeded
            } else {
                yosoi::BrowserContextCleanupDisposition::Failed
            };
        }
    }
    yosoi::BrowserContextCleanupDisposition::Completed
}

async fn wait_for_navigation_lanes(resource: &Arc<LeaseResource>, deadline: Instant) -> bool {
    let gates = {
        let state = resource.state.lock().await;
        state
            .tabs
            .values()
            .map(|tab| Arc::clone(&tab.navigation_gate))
            .collect::<Vec<_>>()
    };
    let mut guards = Vec::with_capacity(gates.len());
    for gate in gates {
        let Ok(guard) = timeout_at(deadline, gate.lock_owned()).await else {
            return false;
        };
        guards.push(guard);
    }
    drop(guards);
    true
}

pub(super) async fn cancel_pending_tab_creations(resource: &Arc<LeaseResource>) -> bool {
    let (had_pending_creations, workers) = {
        let mut state = resource.state.lock().await;
        let had_pending_creations = !state.tab_creations.is_empty();
        let workers = state
            .tab_creations
            .drain()
            .filter_map(|(_, creation)| creation.worker)
            .collect::<Vec<_>>();
        drop(state);
        (had_pending_creations, workers)
    };
    for worker in &workers {
        worker.abort();
    }
    for worker in workers {
        let _ = worker.await;
    }
    resource.released.notify_waiters();
    had_pending_creations
}

pub(super) async fn take_context_for_release(
    resource: &Arc<LeaseResource>,
    deadline: Instant,
) -> Option<ExecutionPageContext> {
    loop {
        let notified = resource.released.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let context = resource.state.lock().await.context.take()?;
        match Arc::try_unwrap(context) {
            Ok(context) => return Some(context),
            Err(context) => {
                if Instant::now() >= deadline {
                    return None;
                }
                resource.state.lock().await.context = Some(context);
            }
        }
        tokio::select! {
            () = sleep_until(deadline) => {
                let context = resource.state.lock().await.context.take();
                drop(context);
                return None;
            }
            () = &mut notified => {}
        }
    }
}

#[allow(
    clippy::significant_drop_tightening,
    reason = "lease and manager accounting commit atomically before provider close"
)]
pub(super) async fn finish_resource_release(
    resource: &Arc<LeaseResource>,
    active_tabs: u32,
    context_disposition: yosoi::BrowserContextCleanupDisposition,
    deadline: Instant,
) -> Result<ReleaseCompletion, BrowserExecutionManagerError> {
    let Some(manager) = resource.manager.upgrade() else {
        return Err(BrowserExecutionManagerError::ManagerClosing);
    };
    let progress = {
        let mut lease_state = resource.state.lock().await;
        if let Some(progress) = lease_state.release_progress.clone() {
            progress
        } else {
            let mut manager_state = manager.state.lock().await;
            manager_state.active_contexts = manager_state
                .active_contexts
                .checked_sub(1)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            manager_state.active_tabs = manager_state
                .active_tabs
                .checked_sub(active_tabs)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            manager_state
                .resources
                .remove(&resource.admission.execution().execution());
            let manager_closing = manager_state.closing;
            let slot = find_slot_mut(
                &mut manager_state.slots,
                resource.slot_id,
                resource.generation,
            )
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            slot.active_contexts = slot
                .active_contexts
                .checked_sub(1)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            // Already-admitted concurrent contexts may finish after this slot
            // reaches its recycle threshold. Preserve that exact factual count;
            // draining prevents any further admissions to the generation.
            slot.completed_contexts = slot
                .completed_contexts
                .checked_add(1)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            if manager_closing
                || context_disposition != yosoi::BrowserContextCleanupDisposition::Completed
                || slot.completed_contexts >= manager.limits.recycle_threshold().get()
            {
                slot.status = ProcessStatus::Draining;
            }
            let (process_action, retained_process_disposition) =
                if slot.status == ProcessStatus::Draining && slot.active_contexts == 0 {
                    let session = slot.session.clone();
                    slot.status = if session.is_some() {
                        ProcessStatus::Closing
                    } else {
                        ProcessStatus::Vacant
                    };
                    (
                        session.map(|session| CloseAction {
                            slot_id: slot.id,
                            generation: slot.generation,
                            session,
                        }),
                        yosoi::BrowserProcessCleanupDisposition::NotRequired,
                    )
                } else {
                    let disposition = if slot.status == ProcessStatus::Ready {
                        yosoi::BrowserProcessCleanupDisposition::WarmRetained
                    } else {
                        yosoi::BrowserProcessCleanupDisposition::NotRequired
                    };
                    (None, disposition)
                };
            let progress = ReleaseProgress {
                context_disposition,
                process_action,
                retained_process_disposition,
                completed_contexts_in_generation: slot.completed_contexts,
            };
            lease_state.release_progress = Some(progress.clone());
            progress
        }
    };
    manager.changed.notify_waiters();
    let process_disposition = match progress.process_action.clone() {
        Some(close) => close_process_slot_outcome(&manager, close, deadline)
            .await
            .disposition(),
        None => progress.retained_process_disposition,
    };
    Ok(ReleaseCompletion {
        cleanup: yosoi::BrowserExecutionCleanupReceipt::new(
            resource.admission.clone(),
            progress.context_disposition,
            process_disposition,
        ),
        completed_contexts_in_generation: progress.completed_contexts_in_generation,
    })
}

pub(super) async fn wait_for_release(
    resource: &Arc<LeaseResource>,
) -> Result<yosoi::BrowserExecutionCleanupReceipt, BrowserExecutionManagerError> {
    loop {
        let notified = resource.released.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let result = resource.state.lock().await.release_result.clone();
        if let Some(result) = result {
            return result.map(|completion| completion.cleanup);
        }
        notified.await;
    }
}

pub(super) async fn wait_for_release_before(
    resource: &Arc<LeaseResource>,
    deadline: Instant,
) -> Result<yosoi::BrowserExecutionCleanupReceipt, BrowserExecutionManagerError> {
    tokio::select! {
        result = wait_for_release(resource) => result,
        () = sleep_until(deadline) => Err(BrowserExecutionManagerError::ContextCleanupDeadline),
    }
}
