#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

#[allow(
    clippy::cognitive_complexity,
    clippy::too_many_arguments,
    reason = "the worker keeps provider ownership, rollback, and handoff order explicit"
)]
pub(in super::super) async fn create_additional_tab(
    resource: Arc<LeaseResource>,
    manager: Arc<ManagerInner>,
    context: Arc<ExecutionPageContext>,
    id: yosoi::BrowserTabLeaseId,
    cancellation: CancellationToken,
    mut result_sender: oneshot::Sender<
        Result<yosoi::BrowserTabLeaseId, BrowserExecutionManagerError>,
    >,
    ack_receiver: oneshot::Receiver<()>,
) {
    if let Err(error) = resource.authorize_profile_admission() {
        drop(context);
        let _ = finish_tab_creation_failure(&resource, &manager, id).await;
        let _ = result_sender.send(Err(error));
        return;
    }
    #[cfg(test)]
    let reservation_pause = manager.state.lock().await.tab_reservation_pause.take();
    #[cfg(test)]
    if let Some((started, proceed)) = reservation_pause {
        started.notify_one();
        proceed.notified().await;
    }

    let interrupted = if cancellation.is_cancelled() {
        Some(BrowserExecutionManagerError::CallerCancelled)
    } else if manager.closing.is_cancelled() {
        Some(BrowserExecutionManagerError::ManagerClosing)
    } else {
        None
    };
    if let Some(error) = interrupted {
        drop(context);
        let _ = finish_tab_creation_failure(&resource, &manager, id).await;
        let _ = result_sender.send(Err(error));
        return;
    }

    let page_result = {
        let creation = context.new_blank_page();
        tokio::pin!(creation);
        let creation_outcome = tokio::select! {
            biased;
            () = cancellation.cancelled() => Err(BrowserExecutionManagerError::CallerCancelled),
            () = manager.closing.cancelled() => Err(BrowserExecutionManagerError::ManagerClosing),
            () = result_sender.closed() => Err(BrowserExecutionManagerError::CallerCancelled),
            result = &mut creation => Ok(result),
        };
        match creation_outcome {
            Ok(Ok(page)) => Ok(Arc::new(page)),
            Ok(Err(_)) => Err((BrowserExecutionManagerError::ProviderUnavailable, true)),
            Err(error) => {
                let deadline = cleanup_deadline(manager.limits);
                let close_failed = match timeout_at(deadline, &mut creation).await {
                    Ok(Ok(page)) => {
                        let page = Arc::new(page);
                        #[cfg(test)]
                        {
                            manager.state.lock().await.last_created_tab = Some(Arc::clone(&page));
                        }
                        !matches!(timeout_at(deadline, page.close()).await, Ok(Ok(())))
                    }
                    Ok(Err(_)) => false,
                    Err(_) => true,
                };
                Err((error, close_failed))
            }
        }
    };
    let page = match page_result {
        Ok(page) => page,
        Err((error, poison)) => {
            drop(context);
            if poison {
                let _ = poison_slot(&manager, resource.slot_id, resource.generation).await;
            }
            let _ = finish_tab_creation_failure(&resource, &manager, id).await;
            let _ = result_sender.send(Err(error));
            return;
        }
    };

    #[cfg(test)]
    let creation_pause = {
        let mut state = manager.state.lock().await;
        state.last_created_tab = Some(Arc::clone(&page));
        state.tab_creation_pause.take()
    };
    #[cfg(test)]
    if let Some((started, proceed)) = creation_pause {
        started.notify_one();
        proceed.notified().await;
    }

    let interrupted = if cancellation.is_cancelled() {
        Some(BrowserExecutionManagerError::CallerCancelled)
    } else if manager.closing.is_cancelled() {
        Some(BrowserExecutionManagerError::ManagerClosing)
    } else {
        None
    };
    if let Some(error) = interrupted {
        let deadline = cleanup_deadline(manager.limits);
        let close_failed = !matches!(timeout_at(deadline, page.close()).await, Ok(Ok(())));
        drop(context);
        if close_failed {
            let _ = poison_slot(&manager, resource.slot_id, resource.generation).await;
        }
        let _ = finish_tab_creation_failure(&resource, &manager, id).await;
        let _ = result_sender.send(Err(error));
        return;
    }

    let installed = {
        let mut state = resource.state.lock().await;
        if state.releasing
            || state.release_result.is_some()
            || !state.tab_creations.contains_key(&id)
        {
            false
        } else {
            state.tabs.insert(
                id,
                TabEntry {
                    page: Some(page),
                    open: true,
                    closing: false,
                    navigation_gate: Arc::new(Mutex::new(())),
                    navigation_closing: CancellationToken::new(),
                },
            );
            true
        }
    };
    drop(context);
    resource.released.notify_waiters();
    manager.changed.notify_waiters();
    if !installed {
        // The page was moved only when installation succeeded. A concurrent
        // release otherwise owns context-wide disposal and the reserved count.
        let _ = result_sender.send(Err(BrowserExecutionManagerError::TabReleased));
        return;
    }

    // Keep the pending entry and its JoinHandle installed through handoff. If
    // the caller disappears, release and shutdown must still be able to abort
    // and join this worker until its orphaned provider page has been closed.
    if result_sender.send(Ok(id)).is_err() || ack_receiver.await.is_err() {
        let lease = RuntimeBrowserTabLease {
            id,
            resource: Arc::downgrade(&resource),
        };
        let _ = lease.close().await;
    }
    finish_tab_creation_success(&resource, &manager, id).await;
}
