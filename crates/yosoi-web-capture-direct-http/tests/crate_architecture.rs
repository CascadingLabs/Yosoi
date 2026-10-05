use std::{fs, process::Command};

#[test]
fn copied_complete_wire_fixture_matches_foundation_canonical_fixture() {
    assert_eq!(
        include_bytes!("fixtures/web-capture/complete-v1.json"),
        include_bytes!("../../yosoi-web-capture/tests/fixtures/web-capture/complete-v1.json"),
        "producer fixture drifted from the foundation's canonical fixture"
    );
}

#[test]
fn producer_depends_inward_on_foundation_and_owns_transport() {
    let manifest = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"))
        .expect("test fixture manifest must be readable");
    assert!(manifest.contains("yosoi-web-capture.workspace = true"));
    assert!(manifest.contains("wreq.workspace = true"));
    assert!(!manifest.contains("yosoi-web-capture-browser"));
}

#[test]
fn default_dependency_graph_excludes_browser_engine_packages() {
    let output = Command::new("cargo")
        .args([
            "tree",
            "--locked",
            "--offline",
            "--package",
            "yosoi-web-capture-direct-http",
            "--no-default-features",
            "--edges",
            "normal",
            "--prefix",
            "none",
        ])
        .output()
        .expect("cargo tree must be available");
    assert!(output.status.success(), "cargo tree failed");
    let tree = String::from_utf8(output.stdout).expect("cargo tree output must be UTF-8");
    for forbidden in ["void_crawl_core", "chromiumoxide"] {
        assert!(
            !tree.lines().any(|line| line.starts_with(forbidden)),
            "Direct HTTP default dependency graph contains {forbidden}:\n{tree}"
        );
    }
}
