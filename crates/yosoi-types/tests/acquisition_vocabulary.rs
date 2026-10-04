#![allow(clippy::expect_used)]

use std::{fs, path::Path};

use yosoi_types::{
    BudgetScope, ByteCount, ByteLimit, CaptureDeadline, CaptureOffset, EventCount, FlatMeasured,
    LimitEnforcement, LossExtent, Measured, Viewport,
};

#[test]
fn relocated_primitives_keep_their_established_wire_forms() {
    let values = [
        (serde_json::to_string(&ByteCount::new(7)), "7"),
        (serde_json::to_string(&EventCount::new(8)), "8"),
        (
            serde_json::to_string(&CaptureOffset::from_microseconds(9)),
            "9",
        ),
        (
            serde_json::to_string(&Measured::<ByteCount, &str>::Known(ByteCount::new(5))),
            r#"{"status":"known","value":5}"#,
        ),
        (
            serde_json::to_string(&FlatMeasured::<u64, &str>::Known { value: 5 }),
            r#"{"status":"known","value":5}"#,
        ),
        (
            serde_json::to_string(&Measured::<u64, &str>::Unavailable { reason: "provider" }),
            r#"{"status":"unavailable","value":{"reason":"provider"}}"#,
        ),
        (
            serde_json::to_string(&FlatMeasured::<u64, &str>::Unavailable { reason: "provider" }),
            r#"{"status":"unavailable","reason":"provider"}"#,
        ),
        (
            serde_json::to_string(&LossExtent::Known(3)),
            r#"{"Known":3}"#,
        ),
        (
            serde_json::to_string(&LimitEnforcement::RetentionAfterProviderMaterialization),
            r#""RetentionAfterProviderMaterialization""#,
        ),
        (
            serde_json::to_string(&BudgetScope::CaptureAggregate),
            r#""CaptureAggregate""#,
        ),
    ];
    for (actual, expected) in values {
        assert_eq!(actual.expect("fixture must serialize"), expected);
    }
}

#[test]
fn positive_and_platform_sized_values_are_checked() {
    assert!(ByteLimit::try_from(0_u64).is_err());
    assert!(CaptureDeadline::try_from(0_u64).is_err());
    assert_eq!(
        ByteCount::try_from_usize(usize::MAX).is_ok(),
        u64::try_from(usize::MAX).is_ok()
    );
    assert!(Viewport::try_from_pixels(0, 1).is_err());
    assert!(Viewport::try_from_pixels(1, 0).is_err());
}

#[test]
fn acquisition_primitive_declarations_have_one_foundation_owner() {
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("yosoi-types must be inside the workspace crates directory");
    let owners = [
        (
            "pub struct ByteCount(",
            "crates/yosoi-types/src/quantities.rs",
        ),
        (
            "pub struct ByteLimit(",
            "crates/yosoi-types/src/quantities.rs",
        ),
        (
            "pub struct EventCount(",
            "crates/yosoi-types/src/quantities.rs",
        ),
        (
            "pub struct CaptureOffset(",
            "crates/yosoi-types/src/quantities.rs",
        ),
        (
            "pub enum LossExtent",
            "crates/yosoi-types/src/quantities.rs",
        ),
        (
            "pub enum LimitEnforcement",
            "crates/yosoi-types/src/quantities.rs",
        ),
        (
            "pub enum BudgetScope",
            "crates/yosoi-types/src/quantities.rs",
        ),
    ];
    let roots = [
        "crates/yosoi-types/src",
        "crates/yosoi-web-capture/src",
        "crates/voidcrawl/src",
    ];

    for (declaration, expected_owner) in owners {
        let mut matches = Vec::new();
        for root in roots {
            collect_declarations(workspace, root, declaration, &mut matches);
        }
        assert_eq!(matches, [expected_owner], "declaration {declaration:?}");
    }

    let canonical_browser = fs::read_to_string(workspace.join("crates/yosoi-types/src/browser.rs"))
        .expect("canonical browser vocabulary must be readable");
    let web_browser =
        fs::read_to_string(workspace.join("crates/yosoi-web-capture/src/environment/browser.rs"))
            .expect("Web Capture browser environment must be readable");
    let provider_environment =
        fs::read_to_string(workspace.join("crates/voidcrawl/src/environment.rs"))
            .expect("VoidCrawl environment must be readable");
    assert!(canonical_browser.contains("pub struct Viewport {"));
    assert!(!web_browser.contains("pub struct Viewport {"));
    assert!(!provider_environment.contains("pub struct EffectiveViewport {"));
}

#[test]
fn foundation_manifest_cannot_acquire_transport_or_browser_dependencies() {
    let manifest = include_str!("../Cargo.toml");
    for forbidden in [
        "chromiumoxide",
        "void_crawl_core",
        "yosoi-web-capture",
        "wreq",
        "tokio",
    ] {
        assert!(
            !manifest.lines().any(|line| {
                let line = line.trim_start();
                line.starts_with(forbidden)
                    && line
                        .get(forbidden.len()..)
                        .is_some_and(|suffix| suffix.starts_with(' ') || suffix.starts_with('='))
            }),
            "foundation manifest contains runtime dependency {forbidden}"
        );
    }
}

fn collect_declarations(
    workspace: &Path,
    relative_root: &str,
    declaration: &str,
    matches: &mut Vec<String>,
) {
    let root = workspace.join(relative_root);
    let entries = fs::read_dir(&root).expect("source directory must be readable");
    for entry in entries {
        let entry = entry.expect("source entry must be readable");
        let path = entry.path();
        if path.is_dir() {
            let relative = path
                .strip_prefix(workspace)
                .expect("source path must remain inside workspace")
                .to_string_lossy()
                .into_owned();
            collect_declarations(workspace, &relative, declaration, matches);
        } else if path.extension().and_then(|value| value.to_str()) == Some("rs") {
            let source = fs::read_to_string(&path).expect("source file must be readable");
            if source.contains(declaration) {
                matches.push(
                    path.strip_prefix(workspace)
                        .expect("source path must remain inside workspace")
                        .to_string_lossy()
                        .into_owned(),
                );
            }
        }
    }
}
