#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

impl ManagedProfileTenancy {
    pub(in crate::browser_runtime::browser_execution) fn mark_ownership_uncertain(
        &self,
    ) -> Result<(), BrowserExecutionManagerError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)?;
        let (generation, lifecycle_leased, already_uncertain) = match &mut *state {
            ManagedProfileState::Held {
                fence,
                lifecycle_leased,
                ownership_uncertain,
                ..
            } => {
                let already_uncertain = *ownership_uncertain;
                *ownership_uncertain = true;
                (fence.generation(), *lifecycle_leased, already_uncertain)
            }
            _ => return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain),
        };
        drop(state);
        if already_uncertain {
            return Ok(());
        }
        let event = if lifecycle_leased {
            BrowserProfileLifecycleEvent::LeaseOwnershipUncertain { generation }
        } else {
            BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain
        };
        self.commit_lifecycle_event(event)
            .map(|_| ())
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
    }

    pub(in crate::browser_runtime::browser_execution) fn bind_process_generation(
        &self,
        profile_generation: yosoi::BrowserProfileLeaseGeneration,
        process_generation: u64,
    ) -> Result<(), BrowserExecutionManagerError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        match &mut *state {
            ManagedProfileState::Held {
                fence,
                process_generation: active_process_generation,
                ownership_uncertain,
                ..
            } if fence.generation() == profile_generation
                && active_process_generation.is_none()
                && !*ownership_uncertain =>
            {
                *active_process_generation = Some(process_generation);
                Ok(())
            }
            ManagedProfileState::Held {
                ownership_uncertain,
                ..
            } => {
                *ownership_uncertain = true;
                Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
            }
            _ => Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain),
        }
    }

    pub(in crate::browser_runtime::browser_execution) fn confirm_process_closed(
        &self,
        process_generation: u64,
    ) -> Result<(), BrowserExecutionManagerError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        match &mut *state {
            ManagedProfileState::Held {
                process_generation: active_process_generation,
                ownership_uncertain,
                ..
            } if *active_process_generation == Some(process_generation)
                && !*ownership_uncertain =>
            {
                *active_process_generation = None;
                *ownership_uncertain = false;
                Ok(())
            }
            ManagedProfileState::Held {
                ownership_uncertain,
                ..
            } => {
                *ownership_uncertain = true;
                Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
            }
            _ => Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain),
        }
    }

    pub(in crate::browser_runtime::browser_execution) fn current_generation(
        &self,
    ) -> Option<yosoi::BrowserProfileLeaseGeneration> {
        let state = self.state.lock().ok()?;
        match &*state {
            ManagedProfileState::Held { fence, .. } => Some(fence.generation()),
            _ => None,
        }
    }

    pub(in crate::browser_runtime::browser_execution) fn ownership_is_held(&self) -> bool {
        let Ok(state) = self.state.lock() else {
            return true;
        };
        matches!(
            &*state,
            ManagedProfileState::Staged { .. } | ManagedProfileState::Held { .. }
        )
    }
}
