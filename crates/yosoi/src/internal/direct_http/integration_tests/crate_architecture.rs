//! Source-level checks for the Direct HTTP provider boundary.

use std::{fs, path::Path, process::Command};

#[test]
fn copied_complete_wire_fixture_matches_foundation_canonical_fixture() {
    assert_eq!(
        include_bytes!("fixtures/web-capture/complete-v1.json"),
        include_bytes!("../../web_capture/integration_tests/fixtures/web-capture/complete-v1.json"),
        "Direct HTTP fixture drifted from Web Capture's canonical fixture"
    );
}

#[test]
fn direct_http_owns_transport_and_depends_inward_on_web_capture() {
    let sdk_root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let direct_http = sdk_root.join("src/internal/direct_http");
    let web_capture = sdk_root.join("src/internal/web_capture");
    let executor = fs::read_to_string(direct_http.join("executor.rs"))
        .expect("Direct HTTP executor source must be readable");
    let module = fs::read_to_string(direct_http.join("mod.rs"))
        .expect("Direct HTTP module source must be readable");
    let foundation = fs::read_to_string(web_capture.join("mod.rs"))
        .expect("Web Capture module source must be readable");

    assert!(module.contains("crate::internal::web_capture"));
    assert!(executor.contains("wreq::"));
    assert!(!foundation.contains("crate::internal::direct_http"));
    assert!(!foundation.contains("wreq::"));
}

#[test]
fn default_sdk_dependency_graph_excludes_browser_engine_packages() {
    let output = Command::new("cargo")
        .args([
            "tree",
            "--locked",
            "--offline",
            "--package",
            "yosoi",
            "--no-default-features",
            "--edges",
            "normal",
            "--prefix",
            "none",
        ])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .expect("cargo tree must be available");
    assert!(output.status.success(), "cargo tree failed");
    let tree = String::from_utf8(output.stdout).expect("cargo tree output must be UTF-8");
    for forbidden in ["yosoi-chromiumoxide", "chromiumoxide"] {
        assert!(
            !tree.lines().any(|line| line.starts_with(forbidden)),
            "default SDK dependency graph contains {forbidden}:\n{tree}"
        );
    }
}
