#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "validated loopback corpus"
)]
#[path = "direct_http_corpus/common.rs"]
mod common;
use super::direct_http_corpus_fixture as corpus;
#[path = "direct_http_corpus/corpus.rs"]
mod corpus_tests;
#[path = "direct_http_corpus/edge_cases.rs"]
mod edge_cases;
use crate::internal::test_support::direct_http_fixture as fixture;
