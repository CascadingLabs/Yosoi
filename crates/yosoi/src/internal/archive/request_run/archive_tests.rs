#![allow(clippy::panic_in_result_fn)]

use crate::internal::policy::policy::Budget;
use crate::internal::policy::{
    EffectivePolicy, Policy, PolicyError,
    policy::{
        Acquisition, AcquisitionKind, DocumentRequest, Documents, MaximumElapsed, Page, Provider,
        ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile, ProviderSelection,
        Request, Search,
    },
};
use crate::internal::types::CaptureId;
use serde::Serialize;
use std::error::Error;
use tempfile::tempdir;

use super::*;
use crate::internal::archive::policy::read_policy_record;
use crate::internal::archive::{
    AuthoredDocumentSelection, EffectivePolicyIdentityRecord, PolicyArchiveRef,
    RequestAttemptRecord, RequestNotStartedReason,
};

const POLICY_SCHEMA_V1: u32 = 1;
const POLICY_SCHEMA_V3: u32 = 3;

fn not_started_attempt() -> Result<RequestAttemptRecord, Box<dyn Error>> {
    let capture_id: CaptureId = "123e4567-e89b-42d3-a456-426614174101".parse()?;
    Ok(RequestAttemptRecord::try_new(
        capture_id,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::NotStarted {
            reason: RequestNotStartedReason::Cancelled,
        },
    )?)
}

fn request_run(
    policy: PolicyArchiveRef,
    identity: EffectivePolicyIdentityRecord,
) -> Result<RequestRunRecord, Box<dyn Error>> {
    Ok(RequestRunRecord::try_new(
        "123e4567-e89b-42d3-a456-426614174100".parse()?,
        "https://example.test".parse()?,
        policy,
        identity,
        RequestRunTermination::Cancelled,
        vec![not_started_attempt()?],
    )?)
}

#[tokio::test]
async fn legacy_policy_v1_request_run_keeps_its_v2_identity() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = Policy {
        search: Search::disabled(),
        ..Policy::default()
    };
    let legacy_value: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/policy-v2-pre-map.json"))?;
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V1,
            policy_reference.key(),
            &legacy_value,
        )
        .await?;

    let archived = read_policy_record(&archive, &policy_reference).await?;
    assert_eq!(archived.effective_identity.version(), 2);
    assert_eq!(
        archived.effective_identity.digest().to_string(),
        "104fe019a7a24aad993c243290fce35da4de719d5f4eb6ae1f860b9af01dc0b6"
    );
    assert_eq!(archived.policy, policy);
    let run = request_run(policy_reference, archived.effective_identity)?;
    let reference = archive.write(&run).await?;
    let reopened: RequestRunRecord = archive.read(&reference).await?;
    assert_eq!(reopened.effective_policy(), archived.effective_identity);
    Ok(())
}

#[tokio::test]
async fn map_era_policy_v1_request_run_keeps_its_v3_identity() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let mut policy = Policy {
        search: Search::disabled(),
        ..Policy::default()
    };
    // The retained v3 fixtures authored one worker before the default became two.
    policy.map.limits.max_concurrency = Budget::new(1)?;
    let legacy_value: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/policy-v3-map-only.json"))?;
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V1,
            policy_reference.key(),
            &legacy_value,
        )
        .await?;

    let archived = read_policy_record(&archive, &policy_reference).await?;
    assert_eq!(archived.effective_identity.version(), 3);
    assert_eq!(
        archived.effective_identity.digest().to_string(),
        "ffdc6771106b42faa73336d0fa811bea669a2f1214c5672c265e8314d8b81cbb"
    );
    assert_eq!(archived.policy, policy);
    let run = request_run(policy_reference, archived.effective_identity)?;
    let reference = archive.write(&run).await?;
    let reopened: RequestRunRecord = archive.read(&reference).await?;
    assert_eq!(reopened.effective_policy(), archived.effective_identity);
    Ok(())
}

#[tokio::test]
async fn map_robots_policy_v1_request_run_keeps_its_v3_identity() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let mut policy = Policy {
        search: Search::disabled(),
        ..Policy::default()
    };
    // The retained v3 fixtures authored one worker before the default became two.
    policy.map.limits.max_concurrency = Budget::new(1)?;
    let legacy_value: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/policy-v3-map-robots.json"))?;
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V1,
            policy_reference.key(),
            &legacy_value,
        )
        .await?;

    let archived = read_policy_record(&archive, &policy_reference).await?;
    assert_eq!(archived.effective_identity.version(), 3);
    assert_eq!(
        archived.effective_identity.digest().to_string(),
        "9545dec1e905d5799729bfe3c25dc7775fa8de0cae1dd8b3e68c8cbfbc0c2c47"
    );
    assert_eq!(archived.policy, policy);
    let run = request_run(policy_reference, archived.effective_identity)?;
    let reference = archive.write(&run).await?;
    let reopened: RequestRunRecord = archive.read(&reference).await?;
    assert_eq!(reopened.effective_policy(), archived.effective_identity);
    Ok(())
}

#[tokio::test]
async fn search_v4_policy_v3_request_run_keeps_its_pre_robots_identity()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let legacy_value: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/policy-v4-search-pre-robots.json"))?;
    let policy: Policy = serde_json::from_value(legacy_value.clone())?;
    let effective = policy.effective_policy()?;
    let identity = effective.archived_v4_search_pre_robots_identity()?;
    assert_eq!(identity.version(), 4);
    assert_eq!(
        identity.digest().to_string(),
        "8cff327f06672c9b335125bc2a2f1ed8e447368cac3fe7ebc30b24408a7b824f"
    );
    let identity_record = EffectivePolicyIdentityRecord::from_identity(identity);
    let mut effective_value = serde_json::to_value(effective)?;
    let effective_map = effective_value
        .pointer_mut("/map")
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("effective Map is missing")?;
    effective_map.remove("robots");
    let record = serde_json::json!({
        "policy": legacy_value,
        "effective_policy": effective_value,
        "effective_identity": identity_record,
    });
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V3,
            policy_reference.key(),
            &record,
        )
        .await?;

    let archived = read_policy_record(&archive, &policy_reference).await?;
    assert_eq!(archived.effective_identity, identity_record);
    assert_eq!(archived.policy, policy);
    let run = request_run(policy_reference, archived.effective_identity)?;
    let reference = archive.write(&run).await?;
    let reopened: RequestRunRecord = archive.read(&reference).await?;
    assert_eq!(reopened.effective_policy(), archived.effective_identity);
    Ok(())
}

#[derive(serde::Deserialize, Eq, PartialEq, Serialize)]
struct TestPolicyArchiveRecord {
    policy: Policy,
    effective_policy: EffectivePolicy,
    effective_identity: EffectivePolicyIdentityRecord,
}

#[tokio::test]
async fn archive_rejects_mismatched_authored_and_effective_exact_profiles()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let authored_profile =
        ProviderRequestProfile::new(Page::default(), Request::default(), Documents::default())?;
    let policy = Policy {
        search: Search {
            providers: vec![ProviderSelection::exact(Provider::Brave, authored_profile)],
            ..Search::default()
        },
        ..Policy::default()
    };
    let mut effective = policy.effective_policy()?;
    let route = effective
        .search
        .providers
        .first_mut()
        .ok_or("Search provider route is missing")?;
    let unrelated_request = Request {
        maximum_elapsed: MaximumElapsed::try_from(20_000_000)?,
        ..Request::default()
    };
    route.profile = Some(ProviderRequestProfile::new(
        Page::default(),
        unrelated_request,
        Documents::default(),
    )?);
    let identity = EffectivePolicyIdentityRecord::from_identity(effective.effective_identity()?);
    let record = TestPolicyArchiveRecord {
        policy: policy.clone(),
        effective_policy: effective,
        effective_identity: identity,
    };
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V3,
            policy_reference.key(),
            &record,
        )
        .await?;

    if !matches!(
        archive.read(&policy_reference).await,
        Err(ArchiveError::InvalidPolicy(
            PolicyError::ArchivedSnapshotMismatch
        ))
    ) {
        return Err("Archive::read accepted an unrelated effective Exact profile".into());
    }
    let run = request_run(policy_reference.clone(), identity)?;
    if !matches!(
        archive.write(&run).await,
        Err(ArchiveError::InvalidPolicy(
            PolicyError::ArchivedSnapshotMismatch
        ))
    ) {
        return Err(
            "RequestRun trusted an effective profile that differed from authored Policy".into(),
        );
    }
    Ok(())
}

#[tokio::test]
async fn archive_rejects_mismatched_page_exact_documents() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
        ])?,
        ..Policy::default()
    };
    let mut effective = policy.effective_policy()?;
    effective
        .page
        .acquisitions
        .first_mut()
        .ok_or("effective Page acquisition is missing")?
        .documents
        .clear();
    let identity = EffectivePolicyIdentityRecord::from_identity(effective.effective_identity()?);
    let record = TestPolicyArchiveRecord {
        policy,
        effective_policy: effective,
        effective_identity: identity,
    };
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V3,
            policy_reference.key(),
            &record,
        )
        .await?;

    if !matches!(
        archive.read(&policy_reference).await,
        Err(ArchiveError::InvalidPolicy(
            PolicyError::ArchivedSnapshotMismatch
        ))
    ) {
        return Err("Archive::read accepted different Page Exact documents".into());
    }
    Ok(())
}

#[tokio::test]
async fn request_run_uses_the_archived_current_profile_snapshot() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = Policy {
        search: Search::new([Provider::Brave])?,
        ..Policy::default()
    };
    let mut effective = policy.effective_policy()?;
    let route = effective
        .search
        .providers
        .first_mut()
        .ok_or("Search provider route is missing")?;
    route.profile = Some(ProviderRequestProfile::new(
        Page::default(),
        Request::default(),
        Documents::default(),
    )?);
    route.defaults_status = ProviderDefaultsStatus::Certified {
        version: ProviderDefaultsVersion::try_new(7)?,
    };
    let identity = EffectivePolicyIdentityRecord::from_identity(effective.effective_identity()?);
    let record = TestPolicyArchiveRecord {
        policy: policy.clone(),
        effective_policy: effective,
        effective_identity: identity,
    };
    let policy_reference = PolicyArchiveRef::new_current();
    archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_V3,
            policy_reference.key(),
            &record,
        )
        .await?;

    let run = request_run(policy_reference, identity)?;
    archive.write(&run).await?;
    Ok(())
}
