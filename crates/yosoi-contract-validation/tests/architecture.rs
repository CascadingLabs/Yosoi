#![allow(clippy::panic_in_result_fn)] // Assertions intentionally enforce architecture boundaries.

use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

#[test]
fn validation_has_no_acquisition_or_query_dependencies() -> Result<(), Box<dyn Error>> {
    let manifest = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml"))?;
    for forbidden in [
        "yosoi-web-capture",
        "void_crawl",
        "chromiumoxide",
        "yosoi-policy",
        "tokio",
        "wreq",
        "regex",
    ] {
        assert!(
            !manifest.contains(forbidden),
            "Contract validation must not depend on {forbidden}"
        );
    }
    Ok(())
}

#[test]
fn generated_validation_hooks_are_not_in_the_public_prelude() -> Result<(), Box<dyn Error>> {
    let facade = Path::new(env!("CARGO_MANIFEST_DIR")).join("../yosoi/src/lib.rs");
    let source = fs::read_to_string(facade)?;
    let prelude = source
        .rsplit_once("pub mod prelude {")
        .and_then(|(_, remainder)| remainder.split_once("\n}\n\n#[doc(hidden)]"))
        .map(|(prelude, _)| prelude)
        .ok_or("could not isolate yosoi prelude source")?;
    assert!(!prelude.contains("RuntimeContractValue"));
    assert!(!prelude.contains("ValidateContract"));
    assert!(!prelude.contains("read_required"));
    assert!(!source.contains("ValidateContract"));
    Ok(())
}

#[test]
fn extracted_has_no_public_callback_constructor() -> Result<(), Box<dyn Error>> {
    let validation = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let derive = validation.join("../../yosoi-contracts-derive/src");
    for root in [&validation, &derive] {
        for path in rust_sources(root)? {
            let source = fs::read_to_string(&path)?;
            for forbidden in ["__from_generated", "CandidateValidator", "ValidateContract"] {
                assert!(
                    !source.contains(forbidden),
                    "Contract validation source {} must not expose {forbidden}",
                    path.display()
                );
            }
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
