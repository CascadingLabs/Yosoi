use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use super::super::{BrowserProfileId, BrowserProfileLeaseGenerationRegistry};
use super::validation::validate_receipt_bindings;
use super::{
    BrowserProfileCheckpointIdentity, BrowserProfileChildIdentity, BrowserProfileForkError,
    BrowserProfileForkRequest, BrowserProfileLineageIdentity, ResolvedBrowserProfileForkLimits,
};

/// Facts an adapter can safely derive from a successful provider fork.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserProfileForkSuccessFacts {
    source_profile_id: BrowserProfileId,
    child_profile_ids: Vec<BrowserProfileId>,
    copied_bytes: u64,
}

impl BrowserProfileForkSuccessFacts {
    pub const fn new(
        source_profile_id: BrowserProfileId,
        child_profile_ids: Vec<BrowserProfileId>,
        copied_bytes: u64,
    ) -> Self {
        Self {
            source_profile_id,
            child_profile_ids,
            copied_bytes,
        }
    }
}

/// Secret-safe successful fork receipt. Child leases are intentionally absent.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileForkReceipt {
    checkpoint: BrowserProfileCheckpointIdentity,
    lineage: BrowserProfileLineageIdentity,
    children: Vec<BrowserProfileChildIdentity>,
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: DateTime<Utc>,
    child_expires_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    copied_bytes: u64,
}

impl BrowserProfileForkReceipt {
    pub fn from_success_facts(
        request: &BrowserProfileForkRequest,
        facts: BrowserProfileForkSuccessFacts,
        generations: &BrowserProfileLeaseGenerationRegistry,
        finished_at: &DateTime<Utc>,
    ) -> Result<Self, BrowserProfileForkError> {
        request.authorize_source(generations, finished_at)?;
        let BrowserProfileForkSuccessFacts {
            source_profile_id,
            child_profile_ids,
            copied_bytes,
        } = facts;
        if &source_profile_id != request.checkpoint.source_profile_id()
            || child_profile_ids.len() != request.children.len()
            || child_profile_ids
                .into_iter()
                .zip(request.children.iter())
                .any(|(actual, expected)| actual.as_str() != expected.profile_id().as_str())
        {
            return Err(BrowserProfileForkError::SuccessFactsMismatch);
        }
        validate_receipt_bindings(
            &request.checkpoint,
            &request.lineage,
            &request.children,
            request.limits,
            &request.requested_at,
            &request.child_expires_at,
            finished_at,
            copied_bytes,
        )?;
        Ok(Self {
            checkpoint: request.checkpoint.clone(),
            lineage: request.lineage.clone(),
            children: request.children.clone(),
            limits: request.limits,
            requested_at: request.requested_at,
            child_expires_at: request.child_expires_at,
            finished_at: *finished_at,
            copied_bytes,
        })
    }

    pub const fn checkpoint(&self) -> &BrowserProfileCheckpointIdentity {
        &self.checkpoint
    }

    pub const fn lineage(&self) -> &BrowserProfileLineageIdentity {
        &self.lineage
    }

    pub fn children(&self) -> &[BrowserProfileChildIdentity] {
        &self.children
    }

    pub const fn limits(&self) -> ResolvedBrowserProfileForkLimits {
        self.limits
    }

    pub const fn child_expires_at(&self) -> &DateTime<Utc> {
        &self.child_expires_at
    }

    pub const fn finished_at(&self) -> &DateTime<Utc> {
        &self.finished_at
    }

    pub const fn copied_bytes(&self) -> u64 {
        self.copied_bytes
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileForkReceiptWire {
    checkpoint: BrowserProfileCheckpointIdentity,
    lineage: BrowserProfileLineageIdentity,
    children: Vec<BrowserProfileChildIdentity>,
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: DateTime<Utc>,
    child_expires_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    copied_bytes: u64,
}

impl TryFrom<BrowserProfileForkReceiptWire> for BrowserProfileForkReceipt {
    type Error = BrowserProfileForkError;

    fn try_from(value: BrowserProfileForkReceiptWire) -> Result<Self, Self::Error> {
        validate_receipt_bindings(
            &value.checkpoint,
            &value.lineage,
            &value.children,
            value.limits,
            &value.requested_at,
            &value.child_expires_at,
            &value.finished_at,
            value.copied_bytes,
        )?;
        Ok(Self {
            checkpoint: value.checkpoint,
            lineage: value.lineage,
            children: value.children,
            limits: value.limits,
            requested_at: value.requested_at,
            child_expires_at: value.child_expires_at,
            finished_at: value.finished_at,
            copied_bytes: value.copied_bytes,
        })
    }
}

impl<'de> Deserialize<'de> for BrowserProfileForkReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserProfileForkReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
