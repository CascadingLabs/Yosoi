#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "deterministic loopback corpus assertions"
)]
use crate::internal::test_support::direct_http_fixture as fixture;
#[path = "direct_http_outcome_corpus/lifecycle.rs"]
mod lifecycle;
#[path = "direct_http_outcome_corpus/policy_replay.rs"]
mod policy_replay;
#[path = "direct_http_outcome_corpus/support.rs"]
mod support;
