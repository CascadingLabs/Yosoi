#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;
use crate::browser_runtime::profile_fork::facts::{
    child_contracts_for_request, failure_reason_for_domain, failure_receipt,
    map_contract_store_error, map_lease_error, provider_failure_facts,
};

impl ManagedProfileForkService {
    /// Copies and registers every requested child while the source profile lock
    /// and fence remain held. Provider failures are normalized to secret-safe
    /// receipts; they never contain filesystem paths or raw provider text.
    #[allow(
        clippy::cognitive_complexity,
        reason = "coordinates provider copy, rollback, child-contract activation, and receipts"
    )]
    pub fn fork(
        &self,
        source: &ManagedProfileForkSourceLease,
        request: &BrowserProfileForkRequest,
    ) -> Result<ManagedProfileForkOutcome, BrowserProfileForkServiceError> {
        if source.receipt() != request.source_lease()
            || source.receipt().profile_id() != request.checkpoint().source_profile_id()
            || source.fence.generation() != request.checkpoint().source_generation()
        {
            return Err(BrowserProfileForkServiceError::SourceLeaseMismatch);
        }

        let lifecycle_record = self
            .lifecycle
            .record(source.receipt().profile_id())
            .map_err(|_| BrowserProfileForkServiceError::LifecycleStoreUnavailable)?
            .ok_or(BrowserProfileForkServiceError::SourceUnavailable)?;
        if lifecycle_record.next()
            != (BrowserProfileLifecycleState::Leased {
                generation: source.receipt().generation(),
            })
            || lifecycle_record.latest_generation() != Some(source.receipt().generation())
        {
            return Err(BrowserProfileForkServiceError::SourceUnavailable);
        }

        let wall_started: DateTime<Utc> = SystemTime::now().into();
        if let Err(error) = source
            .fence
            .authorize(source.fence.generation(), Instant::now())
        {
            let reason = match error {
                BrowserProfileLeaseError::Expired => {
                    BrowserProfileForkFailureReason::SourceLeaseExpired
                }
                _ => BrowserProfileForkFailureReason::StaleSourceGeneration,
            };
            return Ok(ManagedProfileForkOutcome::Failed(failure_receipt(
                request,
                reason,
                None,
                0,
                None,
                true,
                wall_started,
            )?));
        }
        if let Err(error) = request.authorize_source(&self.generations, &wall_started) {
            if error == BrowserProfileForkError::RequestNotYetActive {
                return Err(BrowserProfileForkServiceError::RequestNotYetActive);
            }
            return Ok(ManagedProfileForkOutcome::Failed(failure_receipt(
                request,
                failure_reason_for_domain(error),
                None,
                0,
                None,
                true,
                wall_started,
            )?));
        }

        // This ticket enforces per-request copied-byte quotas. Cumulative
        // lineage-wide budgets are deferred because they require accounting
        // across future forks and are not part of this substrate contract.
        let reserved_contracts =
            child_contracts_for_request(request, BrowserProfileChildContractState::Reserved);
        if let Err(error) = self.child_contract_store.reserve(&reserved_contracts) {
            if error == BrowserProfileChildContractStoreError::Conflict {
                return Ok(ManagedProfileForkOutcome::Failed(failure_receipt(
                    request,
                    BrowserProfileForkFailureReason::ChildConflict,
                    None,
                    0,
                    None,
                    true,
                    SystemTime::now().into(),
                )?));
            }
            return Err(map_contract_store_error(error));
        }

        let mut staged_children = Vec::with_capacity(request.children().len());
        for child in request.children() {
            if self
                .lifecycle
                .stage_profile(child.profile_id(), SystemTime::now().into())
                .is_err()
            {
                let cleanup_succeeded = self
                    .child_contract_store
                    .remove_reservations(request.children())
                    .is_ok();
                let lifecycle_succeeded = self.settle_child_lifecycle(
                    &staged_children,
                    BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
                );
                if !cleanup_succeeded || !lifecycle_succeeded {
                    return Err(BrowserProfileForkServiceError::LifecycleStoreUnavailable);
                }
                return Err(BrowserProfileForkServiceError::LifecycleStoreUnavailable);
            }
            staged_children.push(child.clone());
        }

        let child_ids = request
            .children()
            .iter()
            .map(|child| child.profile_id().as_str().to_owned())
            .collect::<Vec<_>>();
        let batch = match self.registry.fork_managed_profile(
            &source.provider_lease,
            &child_ids,
            request.limits().aggregate_byte_quota(),
        ) {
            Ok(batch) => batch,
            Err(error) => {
                let provider_facts = provider_failure_facts(&error);
                let store_cleanup_succeeded = self
                    .finish_reservations(request.children(), provider_facts.cleanup_succeeded());
                let lifecycle_cleanup_succeeded = self.settle_child_lifecycle(
                    &staged_children,
                    if provider_facts.cleanup_succeeded() {
                        BrowserProfileLifecycleEvent::ProvisionFailed
                    } else {
                        BrowserProfileLifecycleEvent::ForkChildUncertain
                    },
                );
                let cleanup_succeeded = provider_facts.cleanup_succeeded()
                    && store_cleanup_succeeded
                    && lifecycle_cleanup_succeeded;
                let facts = BrowserProfileForkFailureFacts::new(
                    if cleanup_succeeded {
                        provider_facts.reason()
                    } else {
                        BrowserProfileForkFailureReason::CleanupIncomplete
                    },
                    provider_facts.child_index(),
                    provider_facts.copied_bytes(),
                    provider_facts.attempted_bytes(),
                    cleanup_succeeded,
                );
                let receipt = BrowserProfileForkFailureReceipt::from_failure_facts(
                    request,
                    facts,
                    &SystemTime::now().into(),
                )
                .map_err(BrowserProfileForkServiceError::InvalidDomainReceipt)?;
                return Ok(ManagedProfileForkOutcome::Failed(receipt));
            }
        };

        let child_profiles_match = batch.children.len() == request.children().len()
            && batch
                .children
                .iter()
                .zip(request.children())
                .all(|(actual, expected)| actual.profile.id == expected.profile_id().as_str());
        let source_profile_matches =
            batch.source_id == request.checkpoint().source_profile_id().as_str();
        let finished_at: DateTime<Utc> = SystemTime::now().into();
        let fence_status = source
            .fence
            .authorize(source.fence.generation(), Instant::now())
            .map_err(map_lease_error);
        let request_status = request.authorize_source(&self.generations, &finished_at);
        let still_authorized = fence_status.is_ok() && request_status.is_ok();
        if !child_profiles_match || !source_profile_matches || !still_authorized {
            let provider_cleanup_succeeded = self.rollback_children(request.children());
            let store_cleanup_succeeded =
                self.finish_reservations(request.children(), provider_cleanup_succeeded);
            let lifecycle_cleanup_succeeded = self.settle_child_lifecycle(
                &staged_children,
                if provider_cleanup_succeeded {
                    BrowserProfileLifecycleEvent::ProvisionFailed
                } else {
                    BrowserProfileLifecycleEvent::ForkChildUncertain
                },
            );
            let cleanup_succeeded = provider_cleanup_succeeded
                && store_cleanup_succeeded
                && lifecycle_cleanup_succeeded;
            let reason = if still_authorized {
                BrowserProfileForkFailureReason::RegistrationFailed
            } else if let Err(error) = fence_status {
                if error == BrowserProfileForkServiceError::FenceUnavailable {
                    BrowserProfileForkFailureReason::SourceLeaseExpired
                } else {
                    BrowserProfileForkFailureReason::StaleSourceGeneration
                }
            } else if let Err(error) = request_status {
                failure_reason_for_domain(error)
            } else {
                BrowserProfileForkFailureReason::StaleSourceGeneration
            };
            return Ok(ManagedProfileForkOutcome::Failed(failure_receipt(
                request,
                if cleanup_succeeded {
                    reason
                } else {
                    BrowserProfileForkFailureReason::CleanupIncomplete
                },
                None,
                batch.copied_bytes,
                None,
                cleanup_succeeded,
                finished_at,
            )?));
        }

        let child_profile_ids = request
            .children()
            .iter()
            .map(|child| child.profile_id().clone())
            .collect();
        let success_facts = BrowserProfileForkSuccessFacts::new(
            request.checkpoint().source_profile_id().clone(),
            child_profile_ids,
            batch.copied_bytes,
        );
        let receipt = match BrowserProfileForkReceipt::from_success_facts(
            request,
            success_facts,
            &self.generations,
            &finished_at,
        ) {
            Ok(receipt) => receipt,
            Err(error) => {
                let provider_cleanup_succeeded = self.rollback_children(request.children());
                let store_cleanup_succeeded =
                    self.finish_reservations(request.children(), provider_cleanup_succeeded);
                let lifecycle_cleanup_succeeded = self.settle_child_lifecycle(
                    &staged_children,
                    if provider_cleanup_succeeded {
                        BrowserProfileLifecycleEvent::ProvisionFailed
                    } else {
                        BrowserProfileLifecycleEvent::ForkChildUncertain
                    },
                );
                let cleanup_succeeded = provider_cleanup_succeeded
                    && store_cleanup_succeeded
                    && lifecycle_cleanup_succeeded;
                return Ok(ManagedProfileForkOutcome::Failed(failure_receipt(
                    request,
                    if cleanup_succeeded {
                        failure_reason_for_domain(error)
                    } else {
                        BrowserProfileForkFailureReason::CleanupIncomplete
                    },
                    None,
                    batch.copied_bytes,
                    None,
                    cleanup_succeeded,
                    finished_at,
                )?));
            }
        };

        if let Err(error) = self.child_contract_store.commit(receipt.children()) {
            let provider_cleanup_succeeded = self.rollback_children(receipt.children());
            let store_cleanup_succeeded =
                self.finish_reservations(receipt.children(), provider_cleanup_succeeded);
            let lifecycle_cleanup_succeeded = self.settle_child_lifecycle(
                receipt.children(),
                if provider_cleanup_succeeded {
                    BrowserProfileLifecycleEvent::ProvisionFailed
                } else {
                    BrowserProfileLifecycleEvent::ForkChildUncertain
                },
            );
            let cleanup_succeeded = provider_cleanup_succeeded
                && store_cleanup_succeeded
                && lifecycle_cleanup_succeeded;
            let reason = if cleanup_succeeded {
                BrowserProfileForkFailureReason::RegistrationFailed
            } else {
                BrowserProfileForkFailureReason::CleanupIncomplete
            };
            if error == BrowserProfileChildContractStoreError::InvalidStore {
                return Err(BrowserProfileForkServiceError::ContractRegistryUnavailable);
            }
            return Ok(ManagedProfileForkOutcome::Failed(failure_receipt(
                request,
                reason,
                None,
                receipt.copied_bytes(),
                None,
                cleanup_succeeded,
                SystemTime::now().into(),
            )?));
        }
        if !self.settle_child_lifecycle(
            receipt.children(),
            BrowserProfileLifecycleEvent::ForkChildAvailable,
        ) {
            let provider_cleanup_succeeded = self.rollback_children(receipt.children());
            let lifecycle_quarantined = self.settle_child_lifecycle(
                receipt.children(),
                BrowserProfileLifecycleEvent::ForkChildUncertain,
            );
            if !provider_cleanup_succeeded || !lifecycle_quarantined {
                return Err(BrowserProfileForkServiceError::LifecycleStoreUnavailable);
            }
            return Err(BrowserProfileForkServiceError::LifecycleStoreUnavailable);
        }
        Ok(ManagedProfileForkOutcome::Completed(receipt))
    }

    fn rollback_children(&self, children: &[BrowserProfileChildIdentity]) -> bool {
        let mut complete = true;
        for child in children {
            if !self
                .registry
                .delete_profile(child.profile_id().as_str())
                .unwrap_or(false)
            {
                complete = false;
            }
        }
        complete
    }

    fn finish_reservations(
        &self,
        children: &[BrowserProfileChildIdentity],
        provider_cleanup_succeeded: bool,
    ) -> bool {
        if provider_cleanup_succeeded {
            self.child_contract_store
                .remove_reservations(children)
                .is_ok()
        } else {
            false
        }
    }

    fn settle_child_lifecycle(
        &self,
        children: &[BrowserProfileChildIdentity],
        event: BrowserProfileLifecycleEvent,
    ) -> bool {
        let mut complete = true;
        for child in children {
            if self
                .lifecycle
                .transition(child.profile_id(), SystemTime::now().into(), event)
                .is_err()
            {
                complete = false;
            }
        }
        complete
    }
}
