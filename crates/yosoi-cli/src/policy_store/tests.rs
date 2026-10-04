#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail focused store tests.

use std::{error::Error, fs};

use serde_json::{Map, Value, json};
use tempfile::tempdir;
use yosoi::{
    Policy,
    policy::{PageDiscovery, search::Provider},
};

use super::{
    MAX_CLI_VERSIONS, MAX_PROFILES_PER_VERSION, MAX_STORE_BYTES, PolicyStore, PolicyStoreError,
};

#[test]
fn missing_store_uses_binary_defaults_without_writing() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let store = PolicyStore::load_from(&path)?;

    assert_eq!(store.current()?, Policy::default());
    assert!(!path.exists());
    Ok(())
}

#[test]
fn sparse_current_profile_inherits_other_binary_defaults() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let mut versions = Map::new();
    versions.insert(
        env!("CARGO_PKG_VERSION").to_owned(),
        json!({
            "active_profile": "daily",
            "profiles": {"daily": {"request": {"maximum_elapsed": 15_000_000}}}
        }),
    );
    fs::write(
        &path,
        serde_json::to_vec(&json!({"format_version": 1, "cli_versions": versions}))?,
    )?;

    let store = PolicyStore::load_from(&path)?;
    let resolved = store.current()?;
    let defaults = Policy::default();
    assert_eq!(store.active_profile(), Some("daily"));
    assert_ne!(
        resolved.request.maximum_elapsed,
        defaults.request.maximum_elapsed
    );
    assert_eq!(resolved.page, defaults.page);
    assert_eq!(resolved.documents, defaults.documents);
    assert_eq!(resolved.locators, defaults.locators);
    assert_eq!(resolved.tuning, defaults.tuning);
    assert_eq!(resolved.map, defaults.map);
    Ok(())
}

#[test]
fn current_profile_can_replace_complete_map_policy() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let mut authored_map = serde_json::to_value(Policy::default().map)?;
    authored_map["pages"] = json!("disabled");
    let mut versions = Map::new();
    versions.insert(
        env!("CARGO_PKG_VERSION").to_owned(),
        json!({"active_profile": "bounded", "profiles": {"bounded": {"map": authored_map}}}),
    );
    fs::write(
        &path,
        serde_json::to_vec(&json!({"format_version": 1, "cli_versions": versions}))?,
    )?;

    let policy = PolicyStore::load_from(&path)?.current()?;
    assert_eq!(policy.map.pages, PageDiscovery::Disabled);
    assert_eq!(policy.request, Policy::default().request);
    Ok(())
}

#[test]
fn sparse_search_profile_supplies_ordered_providers_and_inherits_other_search_bounds()
-> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let mut versions = Map::new();
    versions.insert(
        env!("CARGO_PKG_VERSION").to_owned(),
        json!({
            "active_profile": "web",
            "profiles": {
                "web": {
                    "search": {
                        "providers": [
                            {"provider": "bing", "profile": {"kind": "current"}},
                            {"provider": "brave", "profile": {"kind": "current"}}
                        ],
                        "max_in_flight": 3,
                        "max_results_per_provider": 4,
                        "max_total_results": 9
                    }
                }
            }
        }),
    );
    fs::write(
        &path,
        serde_json::to_vec(&json!({"format_version": 1, "cli_versions": versions}))?,
    )?;

    let store = PolicyStore::load_from(&path)?;
    let resolved = store.current()?;
    let providers = resolved.search.providers();
    assert_eq!(providers.len(), 2);
    assert_eq!(
        providers.first().ok_or("first provider missing")?.provider,
        Provider::Bing
    );
    assert_eq!(
        providers.get(1).ok_or("second provider missing")?.provider,
        Provider::Brave
    );
    assert_eq!(resolved.search.max_in_flight().get(), 3);
    assert_eq!(resolved.search.max_results_per_provider().get(), 4);
    assert_eq!(resolved.search.max_total_results().get(), 9);
    assert_eq!(
        resolved.search.max_browser_in_flight(),
        Policy::default().search.max_browser_in_flight()
    );
    Ok(())
}

#[test]
fn other_cli_version_is_ignored_and_file_is_untouched() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let original = b"{\"format_version\":1,\"cli_versions\":{\"0.0.7\":{\"future_field\":true}}}";
    fs::write(&path, original)?;

    let store = PolicyStore::load_from(&path)?;
    assert_eq!(store.current()?, Policy::default());
    assert_eq!(fs::read(path)?, original);
    Ok(())
}

#[test]
fn rejects_store_file_larger_than_limit() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    fs::write(&path, vec![b' '; MAX_STORE_BYTES + 1])?;

    assert!(matches!(
        PolicyStore::load_from(&path),
        Err(PolicyStoreError::TooLarge { .. })
    ));
    Ok(())
}

#[test]
fn rejects_profile_count_above_limit() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let profiles: Map<String, Value> = (0..=MAX_PROFILES_PER_VERSION)
        .map(|index| (format!("profile-{index}"), json!({})))
        .collect();
    fs::write(
        &path,
        serde_json::to_vec(&json!({
            "format_version": 1,
            "cli_versions": {"0.0.7": {"profiles": profiles}}
        }))?,
    )?;

    assert!(matches!(
        PolicyStore::load_from(&path),
        Err(PolicyStoreError::TooManyProfiles { .. })
    ));
    Ok(())
}

#[test]
fn rejects_cli_version_count_above_limit() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("policies.json");
    let versions: Map<String, Value> = (0..=MAX_CLI_VERSIONS)
        .map(|index| (format!("0.0.{index}"), json!({})))
        .collect();
    fs::write(
        &path,
        serde_json::to_vec(&json!({
            "format_version": 1,
            "cli_versions": versions
        }))?,
    )?;

    assert!(matches!(
        PolicyStore::load_from(&path),
        Err(PolicyStoreError::TooManyVersions(_))
    ));
    Ok(())
}
