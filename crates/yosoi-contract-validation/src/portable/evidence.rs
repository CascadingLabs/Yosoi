use serde::{Deserialize, Serialize};
use yosoi_contracts::FieldId;
use yosoi_documents::Finding;

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
