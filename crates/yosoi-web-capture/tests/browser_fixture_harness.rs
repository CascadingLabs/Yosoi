#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "fixture assertions make test failures readable"
)]

#[path = "browser_fixture/harness.rs"]
mod harness;
