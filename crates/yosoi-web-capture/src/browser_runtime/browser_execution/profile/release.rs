#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

impl ManagedProfileTenancy {
    pub(in crate::browser_runtime::browser_execution) fn close_confirmed(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
    ) -> Result<(), BrowserExecutionManagerError> {
        self.close_confirmed_at(generation, Instant::now())
    }

    #[allow(
        clippy::significant_drop_tightening,
        reason = "terminal lifecycle persistence and provider-lock release form one local authority transition"
    )]
    pub(in crate::browser_runtime::browser_execution) fn close_confirmed_at(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
        monotonic_now: Instant,
    ) -> Result<(), BrowserExecutionManagerError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        let (terminal, lifecycle_leased, expired) = match &*state {
            ManagedProfileState::Held {
                fence,
                process_generation: None,
                lifecycle_leased,
                ownership_uncertain: false,
                ..
            } if fence.generation() == generation => {
                let expired = fence.expired_at(monotonic_now);
                let outcome = if expired {
                    yosoi::BrowserProfileLeaseTerminalOutcome::ExpiredAndReleased
                } else {
                    yosoi::BrowserProfileLeaseTerminalOutcome::Released
                };
                let now: DateTime<Utc> = SystemTime::now().into();
                let finished_at = if expired {
                    now.max(*fence.receipt().expires_at())
                } else {
                    now.max(*fence.receipt().acquired_at())
                };
                let terminal = yosoi::BrowserProfileLeaseTerminalReceipt::new(
                    fence.receipt().clone(),
                    outcome,
                    finished_at,
                )
                .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
                (terminal, *lifecycle_leased, expired)
            }
            _ => return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain),
        };

        let event = if expired {
            BrowserProfileLifecycleEvent::LeaseExpired { generation }
        } else {
            BrowserProfileLifecycleEvent::LeaseReleased { generation }
        };
        let lifecycle_result = if lifecycle_leased {
            self.lifecycle
                .transition(&self.profile_id, SystemTime::now().into(), event)
        } else {
            self.lifecycle.record(&self.profile_id).and_then(|record| {
                record
                    .filter(|record| record.next() == BrowserProfileLifecycleState::Staged)
                    .ok_or(ProfileLifecycleStoreError::StaleTransition)
            })
        };
        if lifecycle_result.is_err() {
            if let ManagedProfileState::Held {
                ownership_uncertain,
                ..
            } = &mut *state
            {
                *ownership_uncertain = true;
            }
            let uncertain_event = if lifecycle_leased {
                BrowserProfileLifecycleEvent::LeaseOwnershipUncertain { generation }
            } else {
                BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain
            };
            let _uncertain_transition = self.lifecycle.transition(
                &self.profile_id,
                SystemTime::now().into(),
                uncertain_event,
            );
            return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
        }

        let previous = mem::replace(&mut *state, ManagedProfileState::Unleased);
        let registry_lease = match previous {
            ManagedProfileState::Held { registry_lease, .. } => registry_lease,
            other => {
                *state = other;
                return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
            }
        };
        let staging_release = registry_lease.release_after_confirmed_browser_close();
        *state = ManagedProfileState::Terminal {
            receipt: Some(terminal),
            staging_release: Some(staging_release),
        };
        Ok(())
    }

    #[allow(
        clippy::significant_drop_tightening,
        reason = "staged lifecycle validation and confirmed provider-lock release are one local authority transition"
    )]
    pub(in crate::browser_runtime::browser_execution) fn confirm_no_process_and_release_staged(
        &self,
    ) -> Result<(), BrowserExecutionManagerError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        match &*state {
            ManagedProfileState::Staged {
                registry_lease: Some(_),
            } => {
                let lifecycle_record = self
                    .lifecycle
                    .record(&self.profile_id)
                    .map_err(|_| BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)?;
                if lifecycle_record
                    .is_none_or(|record| record.next() != BrowserProfileLifecycleState::Staged)
                {
                    return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
                }
                let previous = mem::replace(&mut *state, ManagedProfileState::Unleased);
                if let ManagedProfileState::Staged {
                    registry_lease: Some(registry_lease),
                } = previous
                {
                    *state = ManagedProfileState::Terminal {
                        receipt: None,
                        staging_release: Some(
                            registry_lease.release_after_confirmed_browser_close(),
                        ),
                    };
                    Ok(())
                } else {
                    Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
                }
            }
            ManagedProfileState::Unleased => Ok(()),
            _ => Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain),
        }
    }

    pub(in crate::browser_runtime::browser_execution) fn take_staging_release(
        &self,
    ) -> Option<ManagedProfileLeaseRelease> {
        let mut state = self.state.lock().ok()?;
        match &mut *state {
            ManagedProfileState::Terminal {
                staging_release, ..
            } => staging_release.take(),
            _ => None,
        }
    }

    pub(in crate::browser_runtime::browser_execution) fn lease_receipt(
        &self,
    ) -> Option<yosoi::BrowserProfileLeaseReceipt> {
        let state = self.state.lock().ok()?;
        match &*state {
            ManagedProfileState::Held { fence, .. } => Some(fence.receipt().clone()),
            ManagedProfileState::Terminal {
                receipt: Some(receipt),
                ..
            } => Some(receipt.lease().clone()),
            ManagedProfileState::Unleased
            | ManagedProfileState::Staged { .. }
            | ManagedProfileState::Terminal { receipt: None, .. } => None,
        }
    }

    pub(in crate::browser_runtime::browser_execution) fn terminal_receipt(
        &self,
    ) -> Option<yosoi::BrowserProfileLeaseTerminalReceipt> {
        let state = self.state.lock().ok()?;
        match &*state {
            ManagedProfileState::Terminal {
                receipt: Some(receipt),
                ..
            } => Some(receipt.clone()),
            _ => None,
        }
    }

    pub(super) fn commit_lifecycle_event(
        &self,
        event: BrowserProfileLifecycleEvent,
    ) -> Result<yosoi::BrowserProfileLifecycleRecord, BrowserExecutionManagerError> {
        self.lifecycle
            .transition(&self.profile_id, SystemTime::now().into(), event)
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
    }
}
