#[path = "integration_tests/support/oopif_fixture.rs"]
mod oopif_fixture;

mod active_navigation;
mod ax_tree;
mod browser_acquisition_conformance;
mod byte_control;
mod captcha_capture;
mod captcha_runtime_loaded;
mod cdp_minimal;
mod context_isolation;
mod document_snapshot;
#[cfg(feature = "scanner")]
mod download;
mod download_events;
mod emulation;
mod environment_snapshot;
mod integration;
mod managed_profile_registry;
mod navigation_capture;
mod observation_scope;
mod public_cdp_surface;
mod recording;
#[cfg(feature = "scanner")]
mod scanner;
mod selector_bbox;
mod stealth_ua;
mod visual_snapshot;
