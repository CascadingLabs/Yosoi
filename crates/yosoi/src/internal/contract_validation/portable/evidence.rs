use crate::internal::contracts::FieldId;
use crate::internal::documents::Finding;
use serde::{Deserialize, Serialize};

/// Exact located evidence retained for one Contract candidate field.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PortableCandidateField {
    id: FieldId,
    evidence: Vec<Finding>,
}

impl PortableCandidateField {
    pub const fn new(id: FieldId, evidence: Vec<Finding>) -> Self {
        Self { id, evidence }
    }

    pub const fn id(&self) -> &FieldId {
        &self.id
    }

    pub fn evidence(&self) -> &[Finding] {
        &self.evidence
    }
}
