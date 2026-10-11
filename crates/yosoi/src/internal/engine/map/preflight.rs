//! Pure preflight shared by SDK dispatch and CLI explanations.
use crate::internal::map::admission::{Scope, normalize};
use crate::internal::policy::policy::{AcquisitionKind, DocumentRequest};
use tokio::time::Instant;
use url::Url;

use super::{MapError, MapRequest};
use crate::internal::engine::PolicySnapshot;

pub(super) struct PreparedInputs {
    pub snapshot: PolicySnapshot,
    pub seed: Url,
    pub scope: Scope,
}

impl MapRequest {
    /// Validates the seed, scope, and effective acquisition without network I/O.
    pub fn validate(&self) -> Result<(), MapError> {
        self.prepare_inputs().map(|_| ())
    }

    pub(super) fn prepare_inputs(&self) -> Result<PreparedInputs, MapError> {
        let snapshot = PolicySnapshot::from_policy(&self.policy)?;
        let seed = normalize(&self.seed, None, self.policy.map.limits.max_url_bytes.get())?;
        let scope = Scope::new(&seed, &self.policy.map)?;
        scope.admit(&seed)?;
        let acquisitions = &snapshot.effective_policy().page.acquisitions;
        if acquisitions.len() != 1
            || acquisitions.iter().any(|attempt| {
                attempt.acquisition != AcquisitionKind::DirectHttp
                    || !attempt
                        .documents
                        .contains(&DocumentRequest::ResponseDocument)
            })
        {
            return Err(MapError::UnsupportedAcquisition);
        }
        Instant::now()
            .checked_add(self.policy.map.limits.maximum_elapsed)
            .ok_or(MapError::Deadline)?;
        Ok(PreparedInputs {
            snapshot,
            seed,
            scope,
        })
    }
}
