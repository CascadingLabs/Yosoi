use super::{
    Arc, BrowserExecutionManager, BrowserExecutionManagerError, CancellationToken,
    ExecutionPageContext, HashMap, Instant, LeaseResource, LeaseState, Mutex, NonZeroU64, Notify,
    ReleaseExecutor, Reservation, RuntimeBrowserLease, RuntimeBrowserTabLease, TabEntry,
    cleanup_deadline, mpsc, rollback_creation_inner, sleep_until, start_release, timeout_at,
    wait_for_release, yosoi,
};

mod queue;

impl BrowserExecutionManager {
    /// Acquires one fresh context for an unrelated standalone capture.
    pub async fn acquire_independent(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<RuntimeBrowserLease, BrowserExecutionManagerError> {
        if self.inner.managed_profile.is_some() {
            return Err(BrowserExecutionManagerError::ManagedProfileRequiresSessionScope);
        }
        self.acquire(yosoi::BrowserExecutionScope::Independent, cancellation)
            .await
    }

    /// Acquires one fresh context whose tabs intentionally share session-local state.
    pub async fn acquire_session(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<RuntimeBrowserLease, BrowserExecutionManagerError> {
        self.acquire(yosoi::BrowserExecutionScope::SessionGroup, cancellation)
            .await
    }

    async fn acquire(
        &self,
        scope: yosoi::BrowserExecutionScope,
        cancellation: &CancellationToken,
    ) -> Result<RuntimeBrowserLease, BrowserExecutionManagerError> {
        let reservation = self.reserve_fifo(cancellation).await?;
        let manager = self.clone();
        let caller_cancellation = cancellation.clone();
        let (result_sender, mut result_receiver) = mpsc::channel(1);

        // Provider creation and any cleanup it requires are manager-owned, not
        // caller-future-owned. Dropping or aborting the caller closes the
        // receiver and cancels creation, but the worker keeps polling until its
        // explicit bounded cleanup has relinquished every provider handle.
        tokio::spawn(async move {
            let worker_cancellation = CancellationToken::new();
            let creation = manager.create_reserved(scope, reservation, &worker_cancellation);
            tokio::pin!(creation);
            let result = tokio::select! {
                biased;
                () = caller_cancellation.cancelled() => {
                    worker_cancellation.cancel();
                    creation.await
                }
                () = result_sender.closed() => {
                    worker_cancellation.cancel();
                    creation.await
                }
                result = &mut creation => result,
            };
            if let Err(undelivered) = result_sender.send(result).await
                && let Ok(lease) = undelivered.0
            {
                let _ = lease.release().await;
            }
        });

        result_receiver
            .recv()
            .await
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?
    }

    #[allow(
        clippy::cognitive_complexity,
        reason = "creation keeps provider ownership, cancellation, and rollback order explicit"
    )]
    async fn create_reserved(
        &self,
        scope: yosoi::BrowserExecutionScope,
        reservation: Reservation,
        cancellation: &CancellationToken,
    ) -> Result<RuntimeBrowserLease, BrowserExecutionManagerError> {
        let profile_launch = match self
            .inner
            .managed_profile
            .as_ref()
            .map(|profile| profile.acquire_before_launch(&self.inner))
            .transpose()
        {
            Ok(profile_launch) => profile_launch,
            Err(error) => {
                rollback_creation_inner(&self.inner, &reservation, false).await;
                return Err(error);
            }
        };
        let Some(generation) = NonZeroU64::new(reservation.generation) else {
            rollback_creation_inner(&self.inner, &reservation, true).await;
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };
        let generation = yosoi::BrowserProcessGeneration::new(generation);
        let execution = yosoi::BrowserExecutionLease::new(
            yosoi::BrowserProcessSlotLease::new(self.inner.id, reservation.slot_id, generation),
            yosoi::BrowserExecutionId::random(),
        );
        let context_lease = yosoi::BrowserContextLease::new(
            execution.clone(),
            yosoi::BrowserContextLeaseId::random(),
        );
        let session_lease = yosoi::BrowserSessionLease::new(
            context_lease.clone(),
            yosoi::BrowserSessionLeaseId::random(),
        );
        let tab_id = yosoi::BrowserTabLeaseId::random();
        let tab_lease = yosoi::BrowserTabLease::new(session_lease.clone(), tab_id);
        let Ok(admission) = yosoi::BrowserExecutionAdmissionReceipt::new(
            scope,
            execution,
            context_lease,
            session_lease,
            tab_lease,
        ) else {
            rollback_creation_inner(&self.inner, &reservation, true).await;
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };

        let session = match &reservation.session {
            Some(session) => Arc::clone(session),
            None => match self.launch_reserved_process(&reservation).await {
                Ok(session) => session,
                Err(error) => {
                    rollback_creation_inner(
                        &self.inner,
                        &reservation,
                        self.inner.managed_profile.is_some(),
                    )
                    .await;
                    return Err(error);
                }
            },
        };

        if let (Some(profile), Some(profile_launch)) =
            (&self.inner.managed_profile, &profile_launch)
            && let Err(error) = profile.authorize_admission(profile_launch.generation)
        {
            rollback_creation_inner(&self.inner, &reservation, true).await;
            return Err(error);
        }

        if cancellation.is_cancelled() {
            rollback_creation_inner(&self.inner, &reservation, false).await;
            return Err(BrowserExecutionManagerError::CallerCancelled);
        }
        if self.inner.closing.is_cancelled() {
            rollback_creation_inner(&self.inner, &reservation, false).await;
            return Err(BrowserExecutionManagerError::ManagerClosing);
        }

        let (context, initial_page) = if let Some(profile_launch) = &profile_launch {
            let Ok(managed_context) = session.managed_profile_context() else {
                rollback_creation_inner(&self.inner, &reservation, true).await;
                return Err(BrowserExecutionManagerError::ProviderUnavailable);
            };
            let page_result = {
                let creation = managed_context.new_page();
                tokio::pin!(creation);
                let result = tokio::select! {
                    biased;
                    () = cancellation.cancelled() => Err(BrowserExecutionManagerError::CallerCancelled),
                    () = self.inner.closing.cancelled() => Err(BrowserExecutionManagerError::ManagerClosing),
                    () = sleep_until(Instant::from_std(profile_launch.deadline)) => Err(BrowserExecutionManagerError::ManagedProfileExpired),
                    result = &mut creation => result.map_err(|_| BrowserExecutionManagerError::ProviderUnavailable),
                };
                match result {
                    Ok(page) => Ok(Arc::new(page)),
                    Err(error) => {
                        let deadline = cleanup_deadline(self.inner.limits);
                        let close_failed = match timeout_at(deadline, &mut creation).await {
                            Ok(Ok(page)) => {
                                !matches!(timeout_at(deadline, page.close()).await, Ok(Ok(())))
                            }
                            Ok(Err(_)) | Err(_) => true,
                        };
                        Err((error, close_failed))
                    }
                }
            };
            let page = match page_result {
                Ok(page) => page,
                Err((error, close_failed)) => {
                    rollback_creation_inner(&self.inner, &reservation, close_failed).await;
                    return Err(error);
                }
            };
            if let Some(profile) = &self.inner.managed_profile
                && let Err(error) = profile.authorize_admission(profile_launch.generation)
            {
                let deadline = cleanup_deadline(self.inner.limits);
                let close_failed = !matches!(timeout_at(deadline, page.close()).await, Ok(Ok(())));
                rollback_creation_inner(&self.inner, &reservation, close_failed).await;
                return Err(error);
            }
            (
                Arc::new(ExecutionPageContext::ManagedProfile(managed_context)),
                page,
            )
        } else {
            let context = session.new_isolated_context();
            tokio::pin!(context);
            let creation = tokio::select! {
                biased;
                () = cancellation.cancelled() => Err(BrowserExecutionManagerError::CallerCancelled),
                () = self.inner.closing.cancelled() => Err(BrowserExecutionManagerError::ManagerClosing),
                result = &mut context => Ok(result),
            };
            let context = match creation {
                Ok(Ok(context)) => context,
                Ok(Err(_)) => {
                    rollback_creation_inner(&self.inner, &reservation, true).await;
                    return Err(BrowserExecutionManagerError::ProviderUnavailable);
                }
                Err(error) => {
                    let deadline = cleanup_deadline(self.inner.limits);
                    let poisoned = match timeout_at(deadline, &mut context).await {
                        Ok(Ok(context)) => !context.dispose_before(deadline).await.cleanup_complete,
                        Ok(Err(_)) | Err(_) => true,
                    };
                    rollback_creation_inner(&self.inner, &reservation, poisoned).await;
                    return Err(error);
                }
            };
            let initial_page = context.page_handle();
            (
                Arc::new(ExecutionPageContext::Isolated(context)),
                initial_page,
            )
        };
        #[cfg(test)]
        let context_creation_pause = self.inner.state.lock().await.context_creation_pause.clone();
        #[cfg(test)]
        if let Some((started, proceed)) = context_creation_pause {
            started.notify_one();
            proceed.notified().await;
        }
        let interrupted = if cancellation.is_cancelled() {
            Some(BrowserExecutionManagerError::CallerCancelled)
        } else if self.inner.closing.is_cancelled() {
            Some(BrowserExecutionManagerError::ManagerClosing)
        } else {
            None
        };
        if let Some(error) = interrupted {
            let deadline = cleanup_deadline(self.inner.limits);
            let cleanup_complete = match Arc::try_unwrap(context) {
                Ok(ExecutionPageContext::Isolated(context)) => {
                    context.dispose_before(deadline).await.cleanup_complete
                }
                Ok(ExecutionPageContext::ManagedProfile(_)) => {
                    matches!(timeout_at(deadline, initial_page.close()).await, Ok(Ok(())))
                }
                Err(_) => false,
            };
            rollback_creation_inner(&self.inner, &reservation, !cleanup_complete).await;
            return Err(error);
        }

        let mut tabs = HashMap::new();
        tabs.insert(
            tab_id,
            TabEntry {
                page: Some(initial_page),
                open: true,
                closing: false,
                navigation_gate: Arc::new(Mutex::new(())),
                navigation_closing: CancellationToken::new(),
            },
        );
        let resource = Arc::new(LeaseResource {
            manager: Arc::downgrade(&self.inner),
            admission,
            slot_id: reservation.slot_id,
            generation: reservation.generation,
            profile_generation: profile_launch.map(|profile| profile.generation),
            state: Mutex::new(LeaseState {
                context: Some(context),
                tabs,
                tab_creations: HashMap::new(),
                active_tabs: 1,
                releasing: false,
                release_worker: None,
                release_progress: None,
                release_result: None,
            }),
            released: Notify::new(),
        });

        let mut state = self.inner.state.lock().await;
        let still_owned = state.creations.remove(&reservation.creation_id).is_some();
        let remaining_creations = state.in_flight_creations.checked_sub(1);
        if !still_owned || remaining_creations.is_none() {
            drop(state);
            start_release(
                Arc::clone(&resource),
                cleanup_deadline(self.inner.limits),
                ReleaseExecutor::Stable,
            )
            .await;
            let _ = wait_for_release(&resource).await;
            self.inner.changed.notify_waiters();
            return Err(if self.inner.closing.is_cancelled() {
                BrowserExecutionManagerError::ManagerClosing
            } else {
                BrowserExecutionManagerError::InternalInvariant
            });
        }
        let Some(remaining_creations) = remaining_creations else {
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };
        state.in_flight_creations = remaining_creations;
        if state.closing {
            drop(state);
            start_release(
                Arc::clone(&resource),
                cleanup_deadline(self.inner.limits),
                ReleaseExecutor::Stable,
            )
            .await;
            let _ = wait_for_release(&resource).await;
            self.inner.changed.notify_waiters();
            return Err(BrowserExecutionManagerError::ManagerClosing);
        }
        state.resources.insert(
            resource.admission.execution().execution(),
            Arc::clone(&resource),
        );
        drop(state);
        self.inner.changed.notify_waiters();

        Ok(RuntimeBrowserLease {
            initial_tab: RuntimeBrowserTabLease {
                id: tab_id,
                resource: Arc::downgrade(&resource),
            },
            resource,
        })
    }
}
