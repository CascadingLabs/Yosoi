#![cfg(feature = "browser")]
#![allow(
    clippy::expect_used,
    clippy::panic,
    clippy::unwrap_used,
    reason = "deterministic browser integration harness assertions"
)]

#[path = "browser_runtime/capture_attempt_lifecycle.rs"]
mod capture_attempt_lifecycle;
#[path = "browser_runtime/cas328_evidence.rs"]
mod cas328_evidence;
use super::browser_fixture_harness::harness as fixture;
#[path = "browser_runtime/smoke.rs"]
mod smoke;
