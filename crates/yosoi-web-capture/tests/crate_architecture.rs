use std::{fs, path::Path, process::Command};

use serde_json::Value;

const RETIRED_VOIDCRAWL_ADAPTER: &str = "yosoi-web-capture-voidcrawl";

#[test]
fn foundation_manifest_has_no_direct_http_transport_dependencies() {
    let output = Command::new("cargo")
        .args(["metadata", "--no-deps", "--format-version", "1"])
        .output()
        .expect("cargo metadata must be available");
    assert!(output.status.success(), "cargo metadata failed");
    let metadata: Value = serde_json::from_slice(&output.stdout).expect("valid cargo metadata");
    let package = metadata["packages"]
        .as_array()
        .and_then(|packages| {
            packages
                .iter()
                .find(|package| package["name"].as_str() == Some("yosoi-web-capture"))
        })
        .expect("foundation package must be present");
    let dependencies = package["dependencies"]
        .as_array()
        .expect("foundation dependencies must be an array");
    for forbidden in [
        "wreq",
        "async-compression",
        "futures-util",
        "tokio-util",
        "tokio-rustls",
    ] {
        assert!(
            !dependencies.iter().any(|dependency| {
                dependency["name"].as_str() == Some(forbidden)
                    && dependency["kind"].is_null()
                    && !dependency["optional"].as_bool().unwrap_or(false)
            }),
            "foundation production dependencies contain {forbidden}"
        );
    }
}

#[test]
fn retired_voidcrawl_adapter_cannot_reenter_the_workspace() {
    let workspace_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root must contain crates");
    assert!(
        !workspace_root
            .join("crates")
            .join(RETIRED_VOIDCRAWL_ADAPTER)
            .exists(),
        "the retired adapter directory must not return"
    );

    let output = Command::new("cargo")
        .args(["metadata", "--no-deps", "--format-version", "1"])
        .output()
        .expect("cargo metadata must be available");
    assert!(output.status.success(), "cargo metadata failed");
    let metadata: Value = serde_json::from_slice(&output.stdout).expect("valid cargo metadata");
    let packages = metadata["packages"]
        .as_array()
        .expect("workspace packages must be an array");
    assert!(
        !packages
            .iter()
            .any(|package| package["name"].as_str() == Some(RETIRED_VOIDCRAWL_ADAPTER)),
        "the retired adapter must not be a workspace package"
    );

    for manifest in ["Cargo.toml", "Cargo.lock"] {
        let contents = fs::read_to_string(workspace_root.join(manifest))
            .expect("workspace manifest state must be readable");
        assert!(
            !contents.contains(RETIRED_VOIDCRAWL_ADAPTER),
            "{manifest} must not reference the retired adapter"
        );
    }
}
