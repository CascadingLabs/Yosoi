#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "deterministic loopback corpus assertions"
)]
#[path = "support/direct_http_fixture.rs"]
mod fixture;
#[path = "direct_http_outcome_corpus/lifecycle.rs"]
mod lifecycle;
#[path = "direct_http_outcome_corpus/policy_replay.rs"]
mod policy_replay;
#[path = "direct_http_outcome_corpus/support.rs"]
mod support;
