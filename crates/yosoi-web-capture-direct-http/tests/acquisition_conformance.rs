#![allow(
    dead_code,
    clippy::indexing_slicing,
    clippy::unwrap_used,
    reason = "deterministic conformance fixture assertions"
)]

use std::{fs, path::Path};

#[test]
fn physical_provider_neutral_modules_do_not_depend_on_providers() {
    let producer_root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let root = producer_root.join("../yosoi-web-capture/src");
    let neutral = [
        "bounded_acquisition.rs",
        "bundle.rs",
        "capture.rs",
        "wire.rs",
        "artifact/mod.rs",
        "artifact/family.rs",
        "observation/mod.rs",
    ];
    let forbidden = [
        "crate::direct_http",
        "direct_http::",
        "direct_http_spec",
        "direct_http_orchestration",
        "wreq",
        "PendingDirectHttpResponse",
        "DirectHttpResponseFacts",
        "VoidCrawl",
        "browser::",
    ];
    for relative in neutral {
        let source = fs::read_to_string(root.join(relative)).unwrap();
        for dependency in forbidden {
            assert!(
                !source.contains(dependency),
                "neutral module {relative} contains forbidden dependency {dependency}"
            );
        }
    }
    let adapter = fs::read_to_string(producer_root.join("src/lifecycle.rs")).unwrap();
    assert!(adapter.contains("BoundedAcquisitionLifecycle"));
    assert!(adapter.contains("ResolvedDirectHttpCaptureSpec"));
}
