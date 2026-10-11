//! Keep runtime Contract validation independent of capture and policy.
#![allow(clippy::panic_in_result_fn)]

use std::{error::Error, fs, path::Path};

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

#[test]
fn validation_module_does_not_import_capture_or_policy() -> Result<(), Box<dyn Error>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/internal/contract_validation");
    let mut source = String::new();
    append_production_sources(&root, &mut source)?;

    for forbidden in [
        "crate::internal::archive",
        "crate::internal::browser",
        "crate::internal::direct_http",
        "crate::internal::engine",
        "crate::internal::map",
        "crate::internal::policy",
        "crate::internal::web_capture",
        "use chromiumoxide::",
        "use tokio::",
        "use wreq::",
    ] {
        assert!(
            !source.contains(forbidden),
            "Contract validation imports forbidden dependency {forbidden}"
        );
    }
    Ok(())
}
