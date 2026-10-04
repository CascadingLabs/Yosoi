#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "deterministic loopback corpus"
)]
#[path = "support/direct_http_fixture.rs"]
mod fixture;
#[path = "direct_http_redirect_corpus/redirects.rs"]
mod redirects;
#[path = "direct_http_redirect_corpus/support.rs"]
mod support;
#[path = "direct_http_redirect_corpus/transport.rs"]
mod transport;
