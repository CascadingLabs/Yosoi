#![allow(clippy::panic_in_result_fn)]

mod common;

use std::io;

use common::{TestResult, default_policy_json_value};
use serde_json::{Value, json};
use yosoi_policy::{
    Policy, PolicyError,
    policy::{Budget, HostScope, Map, Robots, Search, Subdomains},
};

const LEGACY_POLICY_JSON: &str = include_str!("fixtures/policy-v2-without-map.json");

#[test]
fn map_defaults_are_serialized_and_legacy_policy_gets_default_map() -> TestResult {
    let policy = Policy::default();
    assert_eq!(policy.map, Map::default());
    assert_eq!(
        policy.to_canonical_json()?,
        common::DEFAULT_POLICY_JSON.trim()
    );

    let legacy: Policy = serde_json::from_str(LEGACY_POLICY_JSON)?;
    let historical = Policy {
        search: Search::disabled(),
        ..policy
    };
    assert_eq!(legacy, historical);
    assert_eq!(legacy.map, Map::default());
    assert_eq!(legacy.to_canonical_json()?, historical.to_canonical_json()?);
    Ok(())
}

#[test]
fn map_values_change_effective_identity_and_validate_scope() -> TestResult {
    let default_identity = Policy::default().effective_identity()?;
    assert_eq!(Policy::default().map.robots, Robots::Ignore);

    let mut changed = Policy::default();
    changed.map.limits.max_url_bytes = Budget::new(8_193)?;
    assert_ne!(changed.effective_identity()?, default_identity);

    changed.map.subdomains = Subdomains::Passive;
    assert_eq!(
        changed.validate(),
        Err(PolicyError::PassiveSubdomainsRequireRegistrableDomain)
    );
    changed.map.scope.hosts = HostScope::RegistrableDomain;
    assert!(changed.validate().is_ok());
    assert_ne!(changed.effective_identity()?, default_identity);
    Ok(())
}

#[test]
fn map_robots_defaults_to_ignore_when_missing_from_existing_map_policy() -> TestResult {
    let mut document = default_policy_json_value()?;
    let map = document
        .pointer_mut("/map")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| io::Error::other("default Map policy is missing"))?;
    map.remove("robots");

    let parsed: Policy = serde_json::from_value(document)?;
    assert_eq!(parsed.map.robots, Robots::Ignore);
    assert_eq!(parsed, Policy::default());

    let mut respecting = Policy::default();
    respecting.map.robots = Robots::Respect;
    assert_ne!(
        respecting.effective_identity()?,
        Policy::default().effective_identity()?
    );
    let roundtrip: Policy = serde_json::from_str(&respecting.to_canonical_json()?)?;
    assert_eq!(roundtrip.map.robots, Robots::Respect);

    let mut invalid = default_policy_json_value()?;
    set_value(&mut invalid, "/map/robots", json!("respect_crawl_delays"))?;
    assert!(serde_json::from_value::<Policy>(invalid).is_err());
    Ok(())
}

#[test]
fn map_positive_limits_and_filter_bounds_are_checked_during_deserialization() -> TestResult {
    assert_eq!(Budget::new(0), Err(PolicyError::ZeroMapBudget));
    assert_eq!(Budget::new(7)?.get(), 7);

    for pointer in [
        "/map/limits/max_hosts",
        "/map/limits/max_urls",
        "/map/limits/max_relationships",
        "/map/limits/max_observations",
        "/map/limits/max_pending",
        "/map/limits/max_requests",
        "/map/limits/max_sitemaps",
        "/map/limits/max_response_bytes",
        "/map/limits/max_total_response_bytes",
        "/map/limits/max_retained_document_bytes",
        "/map/limits/max_concurrency",
        "/map/limits/max_url_bytes",
        "/map/limits/max_inventory_bytes",
        "/map/limits/max_parser_entries",
        "/map/limits/max_hostname_bytes",
    ] {
        let mut document = default_policy_json_value()?;
        set_value(&mut document, pointer, json!(0))?;
        assert!(
            serde_json::from_value::<Policy>(document).is_err(),
            "{pointer}"
        );
    }

    let mut zero_elapsed = default_policy_json_value()?;
    set_value(
        &mut zero_elapsed,
        "/map/limits/maximum_elapsed",
        json!({"seconds": 0, "nanoseconds": 0}),
    )?;
    assert!(serde_json::from_value::<Policy>(zero_elapsed).is_err());

    let mut invalid_elapsed = default_policy_json_value()?;
    set_value(
        &mut invalid_elapsed,
        "/map/limits/maximum_elapsed/nanoseconds",
        json!(1_000_000_000),
    )?;
    assert!(serde_json::from_value::<Policy>(invalid_elapsed).is_err());

    let mut zero_depths = default_policy_json_value()?;
    set_value(&mut zero_depths, "/map/limits/max_link_depth", json!(0))?;
    set_value(&mut zero_depths, "/map/limits/max_sitemap_depth", json!(0))?;
    let parsed: Policy = serde_json::from_value(zero_depths)?;
    assert_eq!(parsed.map.limits.max_link_depth, 0);
    assert_eq!(parsed.map.limits.max_sitemap_depth, 0);

    let mut too_many = default_policy_json_value()?;
    let keys = too_many
        .pointer_mut("/map/filters/excluded_query_keys")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| io::Error::other("default Map filter list is missing"))?;
    for index in 0..129 {
        keys.push(json!(format!("key-{index}")));
    }
    assert!(serde_json::from_value::<Policy>(too_many).is_err());

    let mut too_long = default_policy_json_value()?;
    set_value(
        &mut too_long,
        "/map/filters/excluded_path_prefixes",
        json!(["x".repeat(1_025)]),
    )?;
    assert!(serde_json::from_value::<Policy>(too_long).is_err());

    let mut empty_path_prefix = default_policy_json_value()?;
    set_value(
        &mut empty_path_prefix,
        "/map/filters/excluded_path_prefixes",
        json!([""]),
    )?;
    assert!(serde_json::from_value::<Policy>(empty_path_prefix).is_err());

    let mut empty_query_key = default_policy_json_value()?;
    set_value(
        &mut empty_query_key,
        "/map/filters/excluded_query_keys",
        json!([""]),
    )?;
    assert!(serde_json::from_value::<Policy>(empty_query_key).is_ok());
    Ok(())
}

fn set_value(document: &mut Value, pointer: &str, value: Value) -> Result<(), io::Error> {
    let destination = document.pointer_mut(pointer).ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("default policy fixture has no field at {pointer}"),
        )
    })?;
    *destination = value;
    Ok(())
}
