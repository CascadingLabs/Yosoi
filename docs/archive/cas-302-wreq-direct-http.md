# CAS-302 Direct HTTP dependency and transport boundary

## Dependency decision

The production transport is pinned exactly to stable `wreq = 0.16.1`. Repository bootstrap also pins `cargo-deny = 0.19.0`, matching the checked-in `deny.toml` schema used for workspace dependency enforcement. The crate declares Rust 1.98 and Apache-2.0, matching this workspace's Rust 1.98 MSRV and license policy. Defaults are disabled; the explicit features are `tokio-rt`, `stream`, and `webpki-roots`. `tokio-rt` supplies wreq's supported Tokio runtime, network, and filesystem integration; `stream` preserves the response body as an asynchronous handoff for CAS-303; `webpki-roots` supplies compiled trust roots. Redirect following and gzip, Brotli, deflate, and Zstandard decompression are also disabled explicitly on every client.

The adapter producer is `com.cascadinglabs.yosoi.wreq-direct-http` at the `yosoi-web-capture` crate version. Execution identity records the dependency separately as crate `wreq`, version `0.16.1`; the resolved specification producer must match the adapter producer, not the dependency version.

Workspace declarations set `default-features = false` for Tokio and tokio-util. The direct production request is Tokio `macros`, `rt`, and `time`, plus tokio-util `rt`; wreq's explicit `tokio-rt` feature also requests Tokio `rt`, `net`, and `fs`, and its `stream` feature requests tokio-util. Cargo feature unification therefore makes the production graph's effective Tokio feature set broader than the direct workspace request. Test builds additionally request Tokio `io-util` and `net`. These are dependency feature requests, not claims that Cargo can subtract features selected transitively.

The dev-only `tokio-rustls = 0.26.4` declaration disables defaults and selects `ring`. The crate is dual `MIT OR Apache-2.0` licensed; its selected transitive graph is covered separately by the repository license allowlist. Its embedded DER certificate and key drive an in-process HTTPS fixture; wreq 0.16.1's `CertStore` API installs the fixture certificate in a crate-private test client without putting trust material in the stable specification.

## Classification and secret boundary

wreq 0.16.1 exposes `is_dns`, `is_tls`, `is_connect`, `is_timeout`, and `is_builder`. The adapter maps these predicates directly without provider-message matching. `is_tls` identifies wreq's typed TLS configuration error class; certificate or handshake rejection can remain a connection-class error in wreq and is preserved as such rather than reclassified from display text. Deterministic tests cover both paths. Before retaining a wreq error as the standard source the adapter calls `without_uri()` so the preserved source cannot expose the request URL.

The response-head model retains only status, protocol, URL values behind non-serializing accessors, and bounded allowlisted Content-Type/Content-Encoding observations. Content-Length is parsed to a typed value. Location, cookies, authorization, arbitrary headers, and bodies are never copied. Debug output redacts URLs, opaque bodies, and the contents of `ObservedHeaderValue::Value`. wreq's built-in redirect traversal and automatic content decoding remain disabled. The CAS-304 executor performs explicit GET-only traversal for 301/302/303/307/308 under one deadline; 300/305 are final responses. Followed redirect bodies are dropped unread, while the last unread response is preserved on redirect failure. See `docs/archive/cas-304-direct-http-redirects.md`. Final content-coded bodies are handed off unchanged.

## CAS-325 crate ownership

The concrete `wreq` adapter now lives in `yosoi-web-capture-direct-http`, whose producer version is that crate's version. It depends one way on the provider-neutral `yosoi-web-capture` foundation, which in turn depends on `yosoi-types`. Existing imports of transport, response, redirect, and Direct HTTP specification APIs move to `yosoi_web_capture_direct_http`. This is an intentional pre-release breaking migration; the foundation provides no compatibility reexports.
