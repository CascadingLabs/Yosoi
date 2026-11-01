#![allow(
    clippy::panic_in_result_fn,
    reason = "Assertions intentionally fail behavioral tests."
)]

use crate::registry::Registry;

use std::error::Error;

use crate::policy::respectfulness::{Cooldown, Group, RateBudget, Respectfulness, Unmatched};

use super::{LimitReason, RespectfulnessError, Runtime, canonical_url, retry_after_at};

type TestResult = Result<(), Box<dyn Error>>;

fn group(id: &str) -> Group {
    Group {
        concurrency: Some(1),
        ..Group::new(id, [r"^https?://(?:[a-z]+\.)?example\.com/"])
    }
}

#[test]
fn regex_groups_share_subdomain_capacity_and_release_it() -> TestResult {
    {
        let directory = tempfile::tempdir()?;
        let registry = Registry::jsonl(directory.path().join("state.jsonl"))?;
        let policy = Respectfulness::new(vec![group("domain")])?;
        let first = Runtime::new(policy.clone(), registry.clone())?;
        let second = Runtime::new(
            policy,
            Registry::jsonl(directory.path().join("state.jsonl"))?,
        )?;
        let permit = first.reserve_at("https://www.example.com/one", 1000, 2000)?;
        assert!(matches!(
            second.reserve_at("https://api.example.com/two", 1001, 2001),
            Err(RespectfulnessError::Limited {
                reason: LimitReason::Concurrency,
                ..
            })
        ));
        permit.finish_at(1010, Some(200), None, false)?;
        second
            .reserve_at("https://api.example.com/two", 1011, 2001)?
            .finish_at(1012, Some(200), None, false)?;
    }
    Ok(())
}

#[test]
fn overlapping_constraints_reserve_all_or_none() -> TestResult {
    let directory = tempfile::tempdir()?;
    let registry = Registry::jsonl(directory.path().join("registry.jsonl"))?;
    let blocked = Group {
        blocked: true,
        ..group("blocked")
    };
    let runtime = Runtime::new(
        Respectfulness::new(vec![group("capacity"), blocked])?,
        registry.clone(),
    )?;
    let original = registry.snapshot()?;
    assert!(matches!(
        runtime.reserve_at("https://example.com/", 1000, 2000),
        Err(RespectfulnessError::Limited {
            reason: LimitReason::Blocked,
            ..
        })
    ));
    assert_eq!(registry.snapshot()?, original);
    Ok(())
}

#[test]
fn rate_budget_counts_starts_and_spacing_survives_release() -> TestResult {
    let g = Group {
        spacing_ms: Some(100),
        budgets: vec![RateBudget {
            requests: 2,
            window_ms: 1000,
        }],
        ..group("rate")
    };
    let directory = tempfile::tempdir()?;
    let runtime = Runtime::new(
        Respectfulness::new(vec![g])?,
        Registry::jsonl(directory.path().join("registry.jsonl"))?,
    )?;
    runtime
        .reserve_at("http://example.com/", 1000, 5000)?
        .finish_at(1001, Some(200), None, false)?;
    assert!(matches!(
        runtime.reserve_at("http://example.com/", 1099, 5000),
        Err(RespectfulnessError::Limited {
            reason: LimitReason::Spacing,
            next_eligible_at_ms: Some(1100),
            ..
        })
    ));
    runtime
        .reserve_at("http://example.com/", 1100, 5000)?
        .finish_at(1101, Some(200), None, false)?;
    assert!(matches!(
        runtime.reserve_at("http://example.com/", 1300, 5000),
        Err(RespectfulnessError::Limited {
            reason: LimitReason::RateBudget,
            next_eligible_at_ms: Some(2000),
            ..
        })
    ));
    runtime
        .reserve_at("http://example.com/", 2000, 5000)?
        .finish_at(2001, Some(200), None, false)?;
    Ok(())
}

#[test]
fn response_cooldown_honors_retry_after_without_penalizing_empty_success() -> TestResult {
    let g = Group {
        cooldown: Some(Cooldown {
            statuses: vec![429, 503],
            fallback_ms: 500,
            transport_errors: true,
        }),
        ..group("feedback")
    };
    let directory = tempfile::tempdir()?;
    let runtime = Runtime::new(
        Respectfulness::new(vec![g])?,
        Registry::jsonl(directory.path().join("registry.jsonl"))?,
    )?;
    runtime
        .reserve_at("https://example.com/", 1000, 10000)?
        .finish_at(1001, Some(200), None, false)?;
    runtime
        .reserve_at("https://example.com/", 1002, 10000)?
        .finish_at(1003, Some(429), Some("2"), false)?;
    assert!(matches!(
        runtime.reserve_at("https://example.com/", 2000, 10000),
        Err(RespectfulnessError::Limited {
            reason: LimitReason::Cooldown,
            next_eligible_at_ms: Some(3003),
            ..
        })
    ));
    runtime
        .reserve_at("https://example.com/", 3003, 10000)?
        .finish_at(3004, Some(200), None, false)?;
    assert_eq!(
        retry_after_at("Thu, 01 Jan 1970 00:00:03 GMT", 1000),
        Some(3000)
    );
    assert_eq!(retry_after_at("0", 1000), Some(1000));
    assert_eq!(retry_after_at("invalid", 1000), None);
    Ok(())
}

#[test]
fn expired_crash_lease_recovers_but_configuration_cannot_silently_reset() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("state.jsonl");
    let policy = Respectfulness::new(vec![group("persistent")])?;
    let first = Runtime::new(policy.clone(), Registry::jsonl(&path)?)?;
    drop(first.reserve_at("https://example.com/", 1000, 2000)?);
    drop(first);
    let second = Runtime::new(policy, Registry::jsonl(&path)?)?;
    assert!(matches!(
        second.reserve_at("https://example.com/", 1999, 3000),
        Err(RespectfulnessError::Limited { .. })
    ));
    second
        .reserve_at("https://example.com/", 2000, 3000)?
        .finish_at(2001, Some(200), None, false)?;
    let changed = Runtime::new(
        Respectfulness::new(vec![Group {
            concurrency: Some(2),
            ..group("persistent")
        }])?,
        Registry::jsonl(path)?,
    )?;
    assert!(matches!(
        changed.reserve_at("https://example.com/", 2100, 3000),
        Err(RespectfulnessError::ConfigurationMismatch { .. })
    ));
    Ok(())
}

#[test]
fn canonical_matching_and_unmatched_behavior_are_explicit() -> TestResult {
    assert_eq!(
        canonical_url("https://EXAMPLE.com.:443/search?q=one#fragment")?,
        "https://example.com/search?q=one"
    );
    assert!(canonical_url("https://user:secret@example.com/").is_err());
    let mut policy = Respectfulness::new(vec![group("one")])?;
    policy.unmatched = Unmatched::Reject;
    let directory = tempfile::tempdir()?;
    let runtime = Runtime::new(
        policy,
        Registry::jsonl(directory.path().join("registry.jsonl"))?,
    )?;
    assert_eq!(
        runtime
            .reserve_at("https://other.example/", 1000, 2000)
            .err(),
        Some(RespectfulnessError::Unmatched)
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn policy_selected_file_records_reservation_owner_and_release() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("traffic.jsonl");
    let mut policy = Respectfulness::new(vec![group("owner")])?;
    policy.registry_path = Some(path.clone());
    let registry = super::resolve_registry(&policy, None).await?;
    let runtime = Runtime::new(policy, registry.clone())?;
    let permit = runtime.reserve_at("https://example.com/private?token=secret", 1000, 2000)?;
    permit.finish_at(1001, Some(200), None, false)?;
    let text = std::fs::read_to_string(&path)?;
    assert!(!text.contains("secret"));
    let transactions = text
        .lines()
        .skip(1)
        .map(
            |line| -> Result<crate::registry::Transaction, Box<dyn Error>> {
                let record: serde_json::Value = serde_json::from_str(line)?;
                Ok(serde_json::from_value(
                    record.get("transaction").ok_or("missing envelope")?.clone(),
                )?)
            },
        )
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(transactions.len(), 2);
    let admission = transactions.first().ok_or("missing admission")?;
    let release = transactions.last().ok_or("missing release")?;
    assert_eq!(admission.caller, *registry.caller());
    assert_eq!(release.caller, admission.caller);
    assert_eq!(admission.context.operation, "respectfulness.reserve");
    assert_eq!(release.context.operation, "respectfulness.release");
    assert_eq!(release.context.reservation, admission.context.reservation);
    assert_eq!(
        admission.context.resources,
        vec!["respectfulness/v1/group/owner"]
    );
    assert_eq!(
        admission
            .context
            .reservation
            .as_ref()
            .ok_or("missing lease")?
            .expires_at
            .timestamp_millis(),
        2000
    );
    Ok(())
}
