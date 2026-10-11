use super::{
    Arc, BrowserExecutionManagerError, CloseAction, ManagerInner, ProcessStatus, ReleaseExecutor,
    cleanup_deadline, close_process_slot, drain_navigation_scheduler, release_wait_deadline,
    restart_release_on_current, rollback_abandoned_creation, sleep_until, start_release,
    wait_for_release_before,
};

#[allow(
    clippy::cognitive_complexity,
    reason = "shutdown keeps retry and provider ownership order explicit"
)]
pub(super) async fn shutdown_inner(
    manager: Arc<ManagerInner>,
) -> Result<(), BrowserExecutionManagerError> {
    let deadline = cleanup_deadline(manager.limits);
    {
        let mut state = manager.state.lock().await;
        if state.shutdown_complete {
            return Ok(());
        }
        state.closing = true;
        state.queue.clear();
    }
    manager.closing.cancel();
    manager.changed.notify_waiters();

    let mut first_error = drain_navigation_scheduler(&manager).await.err();
    loop {
        let notified = manager.changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let in_flight = manager.state.lock().await.in_flight_creations;
        if in_flight == 0 {
            break;
        }
        tokio::select! {
            () = sleep_until(deadline) => {
                first_error = Some(BrowserExecutionManagerError::ContextCleanupDeadline);
                break;
            }
            () = &mut notified => {}
        }
    }

    // A creation worker can disappear only with its executor (for example,
    // runtime shutdown). Its reservation remains manager-owned, including any
    // launched session already installed in the slot. Reclaim counters only
    // after the bounded creation wait, then close the retained process below.
    if first_error.is_some() {
        let abandoned = {
            let state = manager.state.lock().await;
            state.creations.values().cloned().collect::<Vec<_>>()
        };
        for reservation in abandoned {
            rollback_abandoned_creation(&manager, &reservation).await;
        }
    }

    let resources = {
        let state = manager.state.lock().await;
        state.resources.values().cloned().collect::<Vec<_>>()
    };
    for resource in resources {
        let stalled = {
            let state = resource.state.lock().await;
            state.releasing && state.release_result.is_none()
        };
        let resource_deadline = cleanup_deadline(manager.limits);
        if stalled {
            restart_release_on_current(Arc::clone(&resource), resource_deadline).await;
        } else {
            start_release(
                Arc::clone(&resource),
                resource_deadline,
                ReleaseExecutor::Current,
            )
            .await;
        }
        if wait_for_release_before(&resource, release_wait_deadline(manager.limits))
            .await
            .is_err()
        {
            let retry_deadline = cleanup_deadline(manager.limits);
            restart_release_on_current(Arc::clone(&resource), retry_deadline).await;
            if let Err(error) =
                wait_for_release_before(&resource, release_wait_deadline(manager.limits)).await
                && first_error.is_none()
            {
                first_error = Some(error);
            }
        }
    }

    let actions = {
        let mut state = manager.state.lock().await;
        if first_error.is_none() {
            first_error = state.maintenance_errors.pop_front();
        }
        state
            .slots
            .iter_mut()
            .filter_map(|slot| {
                let session = slot.session.clone()?;
                slot.status = ProcessStatus::Closing;
                Some(CloseAction {
                    slot_id: slot.id,
                    generation: slot.generation,
                    session,
                })
            })
            .collect::<Vec<_>>()
    };
    for action in actions {
        if let Err(error) =
            close_process_slot(&manager, action, cleanup_deadline(manager.limits)).await
            && first_error.is_none()
        {
            first_error = Some(error);
        }
    }

    let state = manager.state.lock().await;
    let fully_closed = state.in_flight_creations == 0
        && state.active_contexts == 0
        && state.active_tabs == 0
        && state.resources.is_empty()
        && state
            .slots
            .iter()
            .all(|slot| slot.status == ProcessStatus::Vacant && slot.session.is_none());
    drop(state);

    if fully_closed && let Some(profile) = &manager.managed_profile {
        let release = profile.current_generation().map_or_else(
            || profile.confirm_no_process_and_release_staged(),
            |generation| profile.close_confirmed(generation),
        );
        if let Err(error) = release
            && first_error.is_none()
        {
            first_error = Some(error);
        }
    }

    if first_error.is_none() && fully_closed {
        manager.state.lock().await.shutdown_complete = true;
    }
    first_error.map_or_else(
        || {
            if fully_closed {
                Ok(())
            } else {
                Err(BrowserExecutionManagerError::ContextCleanupFailed)
            }
        },
        Err,
    )
}
