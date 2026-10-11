#[path = "integration_tests/capture_bundle/support.rs"]
mod capture_bundle_support;

mod acquisition_completion;
mod acquisition_conformance;
mod browser_capture_contract;
mod browser_challenge_evaluation;
mod browser_contract_matrix;
mod browser_execution_domain;
mod browser_finalization;
mod browser_fixture_harness;
#[cfg(feature = "browser")]
mod browser_navigation_scheduler;
mod browser_profile_lifecycle_domain;
mod browser_profile_warm_domain;
mod browser_runtime;
mod capture_bundle;
mod capture_environments;
mod capture_model;
mod centralized_errors;
mod crate_architecture;
mod observation_windows;
mod property_hardening;
mod source_representation;
mod web_artifacts;
mod web_capture_wire;
