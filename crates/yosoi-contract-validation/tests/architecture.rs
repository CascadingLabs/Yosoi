//! Keep the domain independent of acquisition and execution machinery.
#![allow(clippy::panic_in_result_fn)] // A failed dependency assertion reports a regression.

use std::{error::Error, fs, iter, path::Path};

#[test]
fn production_dependencies_preserve_domain_isolation() -> Result<(), Box<dyn Error>> {
    let source = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml"))?;
    let manifest: toml::Value = toml::from_str(&source)?;
    let dependencies = iter::once(&manifest)
        .chain(
            manifest
                .get("target")
                .and_then(toml::Value::as_table)
                .into_iter()
                .flat_map(|targets| targets.values()),
        )
        .filter_map(|table| table.get("dependencies").and_then(toml::Value::as_table));
    let forbidden = [
        "yosoi-web-capture",
        "void_crawl_core",
        "chromiumoxide",
        "yosoi-policy",
        "tokio",
        "wreq",
        "regex",
    ];
    for (name, declaration) in dependencies.flat_map(|table| table.iter()) {
        let package = declaration
            .get("package")
            .and_then(toml::Value::as_str)
            .unwrap_or(name);
        assert!(
            !forbidden.contains(&package),
            "domain must not depend on {package}"
        );
    }
    Ok(())
}
