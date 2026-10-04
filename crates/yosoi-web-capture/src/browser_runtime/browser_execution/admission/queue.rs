use super::super::{
    Arc, BrowserExecutionManager, BrowserExecutionManagerError, CancellationToken, Duration,
    Instant, Ordering, QueuedRequestGuard, Reservation, ReserveDecision, close_process_slot,
    enqueue_request, remove_ticket, reserve_capacity, sleep_until,
};

impl BrowserExecutionManager {
    pub(super) async fn reserve_fifo(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<Reservation, BrowserExecutionManagerError> {
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(
                self.inner.limits.queue_wait().milliseconds(),
            ))
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        let ticket = self
            .inner
            .next_ticket
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |ticket| {
                ticket.checked_add(1)
            })
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        let mut queue_guard = QueuedRequestGuard {
            manager: Arc::downgrade(&self.inner),
            ticket,
            armed: false,
        };
        let mut queued = false;

        loop {
            let notified = self.inner.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let mut joined_queue = false;
            let decision = {
                let mut state = self.inner.state.lock().await;
                if state.closing {
                    if queued {
                        remove_ticket(&mut state.queue, ticket);
                        queue_guard.disarm();
                    }
                    return Err(BrowserExecutionManagerError::ManagerClosing);
                }
                let at_front = if queued {
                    state.queue.front().is_some_and(|front| *front == ticket)
                } else {
                    state.queue.is_empty()
                };
                let decision = if at_front {
                    // Background maintenance belongs to the manager queue. Only
                    // the front ticket may consume its one terminal failure;
                    // later waiters cannot bypass FIFO by racing `take()`.
                    if let Some(error) = state.maintenance_errors.pop_front() {
                        if queued {
                            let _ = state.queue.pop_front();
                            queue_guard.disarm();
                        }
                        ReserveDecision::MaintenanceFailed(error)
                    } else {
                        match reserve_capacity(&mut state, self.inner.limits, ticket)? {
                            ReserveDecision::Reserved(reservation) => {
                                if queued {
                                    let _ = state.queue.pop_front();
                                    queue_guard.disarm();
                                }
                                return Ok(reservation);
                            }
                            ReserveDecision::Close(action) => ReserveDecision::Close(action),
                            ReserveDecision::Wait => {
                                if !queued {
                                    enqueue_request(
                                        &mut state.queue,
                                        ticket,
                                        self.inner.limits.queue_depth().get(),
                                    )?;
                                    queued = true;
                                    joined_queue = true;
                                    queue_guard.arm();
                                }
                                ReserveDecision::Wait
                            }
                            ReserveDecision::MaintenanceFailed(error) => {
                                ReserveDecision::MaintenanceFailed(error)
                            }
                        }
                    }
                } else {
                    if !queued {
                        enqueue_request(
                            &mut state.queue,
                            ticket,
                            self.inner.limits.queue_depth().get(),
                        )?;
                        queued = true;
                        joined_queue = true;
                        queue_guard.arm();
                    }
                    ReserveDecision::Wait
                };
                drop(state);
                decision
            };
            if joined_queue {
                self.inner.changed.notify_waiters();
            }
            if let ReserveDecision::MaintenanceFailed(error) = decision {
                self.inner.changed.notify_waiters();
                return Err(error);
            }

            if let ReserveDecision::Close(action) = decision
                && let Err(error) = close_process_slot(&self.inner, action, deadline).await
            {
                self.remove_queued_ticket(ticket).await;
                queue_guard.disarm();
                return Err(error);
            }

            tokio::select! {
                biased;
                () = cancellation.cancelled() => {
                    self.remove_queued_ticket(ticket).await;
                    queue_guard.disarm();
                    return Err(BrowserExecutionManagerError::CallerCancelled);
                }
                () = self.inner.closing.cancelled() => {
                    self.remove_queued_ticket(ticket).await;
                    queue_guard.disarm();
                    return Err(BrowserExecutionManagerError::ManagerClosing);
                }
                () = sleep_until(deadline) => {
                    self.remove_queued_ticket(ticket).await;
                    queue_guard.disarm();
                    return Err(BrowserExecutionManagerError::QueueWaitDeadline);
                }
                () = &mut notified => {}
            }
        }
    }

    async fn remove_queued_ticket(&self, ticket: u64) {
        let mut state = self.inner.state.lock().await;
        remove_ticket(&mut state.queue, ticket);
        drop(state);
        self.inner.changed.notify_waiters();
    }
}
