#![allow(clippy::expect_used, clippy::panic_in_result_fn)]

use std::{error::Error, fs, path::Path};

use crate::internal::types::{
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
        .expect("Yosoi SDK must be inside the workspace crates directory");
    let owners = [
        (
            "pub struct ByteCount(",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
        (
            "pub struct ByteLimit(",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
        (
            "pub struct EventCount(",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
        (
            "pub struct CaptureOffset(",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
        (
            "pub enum LossExtent",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
        (
            "pub enum LimitEnforcement",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
        (
            "pub enum BudgetScope",
            "crates/yosoi/src/internal/types/quantities.rs",
        ),
    ];
    let roots = [
        "crates/yosoi/src/internal/types",
        "crates/yosoi/src/internal/web_capture",
        "crates/yosoi/src/internal/browser",
    ];

    for (declaration, expected_owner) in owners {
        let mut matches = Vec::new();
        for root in roots {
            collect_declarations(workspace, root, declaration, &mut matches);
        }
        assert_eq!(matches, [expected_owner], "declaration {declaration:?}");
    }

    let canonical_browser =
        fs::read_to_string(workspace.join("crates/yosoi/src/internal/types/browser.rs"))
            .expect("canonical browser vocabulary must be readable");
    let web_browser = fs::read_to_string(
        workspace.join("crates/yosoi/src/internal/web_capture/environment/browser.rs"),
    )
    .expect("Web Capture browser environment must be readable");
    let provider_environment =
        fs::read_to_string(workspace.join("crates/yosoi/src/internal/browser/environment.rs"))
            .expect("browser provider environment must be readable");
    assert!(canonical_browser.contains("pub struct Viewport {"));
    assert!(!web_browser.contains("pub struct Viewport {"));
    assert!(!provider_environment.contains("pub struct EffectiveViewport {"));
}

#[test]
fn shared_types_module_stays_dependency_light() -> Result<(), Box<dyn Error>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/internal/types");
    let mut source = String::new();
    append_production_sources(&root, &mut source)?;

    for forbidden in [
        "crate::internal::archive",
        "crate::internal::browser",
        "crate::internal::direct_http",
        "crate::internal::documents",
        "crate::internal::engine",
        "crate::internal::extractor",
        "crate::internal::map",
        "crate::internal::policy",
        "crate::internal::web_capture",
        "use chromiumoxide::",
        "use tokio::",
        "use wreq::",
    ] {
        assert!(
            !source.contains(forbidden),
            "shared types module imports forbidden dependency {forbidden}"
        );
    }
    Ok(())
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
            if path.file_name().and_then(|name| name.to_str()) == Some("integration_tests") {
                continue;
            }
            let relative = path
                .strip_prefix(workspace)
                .expect("source path must remain inside workspace")
                .to_string_lossy()
                .into_owned();
            collect_declarations(workspace, &relative, declaration, matches);
        } else if path.extension().and_then(|value| value.to_str()) == Some("rs")
            && path.file_name().and_then(|name| name.to_str()) != Some("integration_tests.rs")
            && path.file_name().and_then(|name| name.to_str()) != Some("tests.rs")
            && !path
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.ends_with("_tests.rs"))
        {
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

fn append_production_sources(root: &Path, source: &mut String) -> Result<(), Box<dyn Error>> {
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            if path.file_name().and_then(|name| name.to_str()) != Some("integration_tests") {
                append_production_sources(&path, source)?;
            }
        } else if path.extension().and_then(|extension| extension.to_str()) == Some("rs") {
            let file_name = path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or_default();
            if file_name != "integration_tests.rs"
                && file_name != "tests.rs"
                && !file_name.ends_with("_tests.rs")
            {
                source.push_str(&fs::read_to_string(path)?);
                source.push('\n');
            }
        }
    }
    Ok(())
}
