//! Portable, content-free evidence of one Auto routing decision.
use super::SearchUnavailableReason;
use crate::internal::types::Sha256Digest;
use crate::{
    policy::{respectfulness::RespectfulnessError, search::Provider},
    registry::{Revision, Transaction},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

/// One candidate that Auto did not admit, including its concrete constraint.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutoRotationSkip {
    /// Concrete candidate from the ordered routing configuration.
    pub provider: Provider,
    /// Why this candidate was not selected or could not start.
    pub reason: SearchUnavailableReason,
    /// Authored constraint details and next eligibility, when applicable.
    pub error: Option<RespectfulnessError>,
}

/// Immutable metadata linking a Search operation to its exact cursor decision.
///
/// No query, result URL, headers, credentials or live execution authority is
/// retained. An absent transaction means no cursor or traffic state was changed.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutoRotationTrace {
    /// Logical audit schema, currently one.
    pub schema_version: u16,
    /// Search identity also exposed on the containing response.
    pub search_request_id: String,
    /// Effective authored policy identity version.
    pub policy_identity_version: u16,
    /// Effective policy SHA-256 digest, without retaining the authored query.
    pub policy_identity_sha256: String,
    /// Exact ordered candidate set used by the rotation algorithm.
    pub candidates: Vec<Provider>,
    /// Stable logical registry resource key for this ordered candidate set.
    pub registry_key: String,
    /// Stored next-candidate index before evaluation; None means uninitialized.
    pub cursor_before: Option<u64>,
    /// Stored index after the decision; unchanged when no candidate was admitted.
    pub cursor_after: Option<u64>,
    /// Exact registry identity and sequence evaluated for admission.
    pub revision_before: Revision,
    /// Committed revision, or the unchanged evaluated revision for rejection.
    pub revision_after: Revision,
    /// Actual journal envelope returned by the successful atomic commit.
    pub transaction: Option<Transaction>,
    /// Admitted concrete provider, including choices later cancelled or failed.
    pub selected_provider: Option<Provider>,
    /// Candidate reasons, retained independently of selected-provider execution.
    pub skipped: Vec<AutoRotationSkip>,
    /// Original, recovery and resolution Request identities belonging to this Search.
    pub request_ids: Vec<String>,
}

impl AutoRotationTrace {
    pub(crate) fn validate(&self) -> bool {
        let valid_id = |id: &str| Uuid::parse_str(id).is_ok();
        let count = u64::try_from(self.candidates.len()).unwrap_or(u64::MAX);
        if self.schema_version != 1
            || self.candidates.is_empty()
            || self.candidates.len() > 4096
            || !valid_id(&self.search_request_id)
            || self.policy_identity_version == 0
            || self.policy_identity_sha256.len() != 64
            || !self
                .policy_identity_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || self.cursor_before.is_some_and(|index| index >= count)
            || self.cursor_after.is_some_and(|index| index >= count)
            || self.revision_before.registry_id != self.revision_after.registry_id
            || !valid_id(&self.revision_before.registry_id)
            || self.request_ids.len() > 4096
            || self.request_ids.iter().any(|id| !valid_id(id))
            || self.registry_key.len() > 256
            || !self.registry_key.starts_with("search/auto/v1/")
            || self.candidates.iter().enumerate().any(|(index, provider)| {
                self.candidates
                    .get(..index)
                    .is_some_and(|prior| prior.contains(provider))
            })
            || self.skipped.len() > self.candidates.len()
            || self
                .skipped
                .iter()
                .any(|skip| !self.candidates.contains(&skip.provider))
        {
            return false;
        }
        let Ok(encoded) = serde_json::to_vec(&self.candidates) else {
            return false;
        };
        let digest = Sha256Digest::from_bytes(Sha256::digest(encoded).into());
        if self.registry_key != format!("search/auto/v1/{digest}")
            || self.skipped.iter().enumerate().any(|(index, skip)| {
                self.skipped
                    .get(..index)
                    .is_some_and(|prior| prior.iter().any(|value| value.provider == skip.provider))
            })
            || self
                .selected_provider
                .is_some_and(|selected| self.skipped.iter().any(|skip| skip.provider == selected))
        {
            return false;
        }
        match (&self.transaction, self.selected_provider) {
            (Some(transaction), Some(provider)) => {
                let Some(index) = self
                    .candidates
                    .iter()
                    .position(|candidate| *candidate == provider)
                else {
                    return false;
                };
                let next = index
                    .checked_add(1)
                    .filter(|next| *next < self.candidates.len())
                    .unwrap_or(0);
                self.cursor_after == u64::try_from(next).ok()
                    && self.revision_before.sequence.checked_add(1)
                        == Some(self.revision_after.sequence)
                    && transaction.sequence == self.revision_after.sequence
                    && transaction.context.operation == "search.auto.select"
                    && transaction.context.resources.contains(&self.registry_key)
                    && transaction
                        .context
                        .resources
                        .contains(&format!("search/request/{}", self.search_request_id))
            }
            (None, None) => {
                self.cursor_before == self.cursor_after
                    && self.revision_before == self.revision_after
                    && self.request_ids.is_empty()
            }
            _ => false,
        }
    }
}
