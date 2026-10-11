use crate::internal::policy::{EffectivePolicy, Policy, PolicyError, PolicySnapshot};
use serde::{Deserialize, Serialize};

use crate::internal::archive::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::internal::archive::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::internal::archive::{
    Archive, ArchiveError, EffectivePolicyIdentityRecord, PolicyArchiveRef,
};

const POLICY_SCHEMA_VERSION: u32 = 3;
const LEGACY_POLICY_SCHEMA_VERSION: u32 = 1;

#[derive(Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PolicyArchiveRecord {
    policy: Policy,
    effective_policy: EffectivePolicy,
    effective_identity: EffectivePolicyIdentityRecord,
}

pub struct ArchivedPolicyRecord {
    pub(in crate::internal::archive) policy: Policy,
    pub(in crate::internal::archive) effective_policy: EffectivePolicy,
    pub(in crate::internal::archive) effective_identity: EffectivePolicyIdentityRecord,
}

pub async fn read_policy_record(
    archive: &Archive,
    reference: &PolicyArchiveRef,
) -> Result<ArchivedPolicyRecord, ArchiveError> {
    if reference.format_version() != ARCHIVE_FORMAT_VERSION {
        return Err(ArchiveError::UnsupportedFormat {
            found: reference.format_version(),
            supported: ARCHIVE_FORMAT_VERSION,
        });
    }

    match archive
        .read_record::<serde_json::Value>(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            reference.key(),
        )
        .await
    {
        Ok(value) => {
            let map_robots_authored = value.pointer("/effective_policy/map/robots").is_some();
            let record: PolicyArchiveRecord = serde_json::from_value(value).map_err(|source| {
                ArchiveError::InvalidRecordValue {
                    kind: "policy",
                    source,
                }
            })?;
            record
                .policy
                .validate()
                .map_err(ArchiveError::InvalidPolicy)?;
            record
                .policy
                .validate_effective_snapshot(&record.effective_policy)
                .map_err(ArchiveError::InvalidPolicy)?;
            let computed = if map_robots_authored {
                record.effective_policy.effective_identity()
            } else {
                record
                    .effective_policy
                    .archived_v4_search_pre_robots_identity()
            }
            .map_err(ArchiveError::InvalidPolicy)?;
            let expected = EffectivePolicyIdentityRecord::from_identity(computed);
            if expected != record.effective_identity {
                return Err(ArchiveError::InvalidPolicy(
                    PolicyError::ArchivedIdentityMismatch,
                ));
            }
            Ok(ArchivedPolicyRecord {
                policy: record.policy,
                effective_policy: record.effective_policy,
                effective_identity: record.effective_identity,
            })
        }
        Err(ArchiveError::MigrationRequired {
            found_schema: LEGACY_POLICY_SCHEMA_VERSION,
            ..
        }) => {
            let value: serde_json::Value = archive
                .read_record(
                    RecordKind::Policy,
                    LEGACY_POLICY_SCHEMA_VERSION,
                    reference.key(),
                )
                .await?;
            let map_robots_authored = value
                .as_object()
                .and_then(|fields| fields.get("map"))
                .and_then(serde_json::Value::as_object)
                .map(|map| map.contains_key("robots"));
            let policy: Policy = serde_json::from_value(value).map_err(|source| {
                ArchiveError::InvalidRecordValue {
                    kind: "policy",
                    source,
                }
            })?;
            let effective_policy = policy
                .effective_policy()
                .map_err(ArchiveError::InvalidPolicy)?;
            let identity = match map_robots_authored {
                None => policy.archived_v2_identity(),
                Some(false) => policy.archived_v3_map_pre_robots_identity(),
                Some(true) => policy.archived_v3_map_identity(),
            }
            .map_err(ArchiveError::InvalidPolicy)?;
            Ok(ArchivedPolicyRecord {
                policy,
                effective_policy,
                effective_identity: EffectivePolicyIdentityRecord::from_identity(identity),
            })
        }
        Err(error) => Err(error),
    }
}

impl sealed::Value for Policy {}

impl ArchiveValue for Policy {
    type Reference = PolicyArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        let snapshot = PolicySnapshot::from_policy(value).map_err(ArchiveError::InvalidPolicy)?;
        let effective_identity = EffectivePolicyIdentityRecord::from_identity(snapshot.identity());
        let record = PolicyArchiveRecord {
            policy: value.clone(),
            effective_policy: snapshot.effective_policy().clone(),
            effective_identity,
        };
        let reference = PolicyArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::Policy,
                POLICY_SCHEMA_VERSION,
                reference.key(),
                &record,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for PolicyArchiveRef {}

impl ArchiveReference for PolicyArchiveRef {
    type Value = Policy;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        read_policy_record(archive, reference)
            .await
            .map(|record| record.policy)
    }
}
