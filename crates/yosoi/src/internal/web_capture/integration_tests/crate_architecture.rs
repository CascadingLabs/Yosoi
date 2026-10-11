//! Keep provider-neutral Web Capture code independent of Direct HTTP transport.
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
fn web_capture_does_not_import_direct_http_transport() -> Result<(), Box<dyn Error>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/internal/web_capture");
    let mut source = String::new();
    append_production_sources(&root, &mut source)?;

    for forbidden in [
        "crate::internal::direct_http",
        "use async_compression::",
        "use futures_util::",
        "use wreq::",
        "use tokio_rustls::",
    ] {
        assert!(
            !source.contains(forbidden),
            "Web Capture imports Direct HTTP transport dependency {forbidden}"
        );
    }
    Ok(())
}

#[test]
fn implementation_root_stays_private_to_sdk_consumers() -> Result<(), Box<dyn Error>> {
    let source = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("src/lib.rs"))?;
    assert!(source.lines().any(|line| line.trim() == "mod internal;"));
    assert!(
        !source
            .lines()
            .any(|line| line.trim_start().starts_with("pub mod internal")),
        "implementation modules must not be public SDK exports"
    );
    Ok(())
}
