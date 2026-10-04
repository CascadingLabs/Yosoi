#![allow(clippy::panic_in_result_fn)] // Assertions intentionally enforce architecture boundaries.

use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

#[test]
fn contract_core_has_no_runtime_or_query_dependencies() -> Result<(), Box<dyn Error>> {
    let manifest = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml"))?;
    for forbidden in [
        "yosoi-web-capture",
        "void_crawl",
        "chromiumoxide",
        "tokio",
        "wreq",
        "regex",
    ] {
        assert!(
            !manifest.contains(forbidden),
            "Contracts must not depend on {forbidden}"
        );
    }
    Ok(())
}

#[test]
fn contract_sources_contain_no_selector_authoring_surface() -> Result<(), Box<dyn Error>> {
    for path in rust_sources(&Path::new(env!("CARGO_MANIFEST_DIR")).join("src"))? {
        let source = fs::read_to_string(&path)?;
        for forbidden in ["css(", "xpath(", "json_path(", "query_selector"] {
            assert!(
                !source.contains(forbidden),
                "Contracts source {} must not expose selector authoring: {forbidden}",
                path.display()
            );
        }
    }
    Ok(())
}

fn rust_sources(root: &Path) -> Result<Vec<PathBuf>, Box<dyn Error>> {
    let mut files = Vec::new();
    collect_rust_sources(root, &mut files)?;
    files.sort();
    Ok(files)
}

fn collect_rust_sources(root: &Path, files: &mut Vec<PathBuf>) -> Result<(), Box<dyn Error>> {
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let path = entry.path();
        if entry.file_type()?.is_dir() {
            collect_rust_sources(&path, files)?;
        } else if path.extension().is_some_and(|extension| extension == "rs") {
            files.push(path);
        }
    }
    Ok(())
}
