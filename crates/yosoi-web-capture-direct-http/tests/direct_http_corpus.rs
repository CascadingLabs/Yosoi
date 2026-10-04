#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "validated loopback corpus"
)]
#[path = "direct_http_corpus/common.rs"]
mod common;
#[path = "support/direct_http_corpus.rs"]
mod corpus;
#[path = "direct_http_corpus/corpus.rs"]
mod corpus_tests;
#[path = "direct_http_corpus/edge_cases.rs"]
mod edge_cases;
#[path = "support/direct_http_fixture.rs"]
mod fixture;
