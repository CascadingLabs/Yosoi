//! Source policy for VoidCrawl's public boundary around Chromiumoxide handles.
#![allow(clippy::expect_used, clippy::panic)]

use std::{fs, path::Path};

const RAW_HANDLE_TYPES: &[&str] = &[
    "chromiumoxide::Page",
    "chromiumoxide::page::Page",
    "CdpPage",
    "SessionId",
    "TargetId",
];

fn collect_rust_sources(root: &Path, sources: &mut Vec<String>) {
    for entry in fs::read_dir(root).expect("VoidCrawl source directory must be readable") {
        let path = entry
            .expect("source directory entry must be readable")
            .path();
        if path.is_dir() {
            collect_rust_sources(&path, sources);
        } else if path.extension().and_then(|extension| extension.to_str()) == Some("rs") {
            sources.push(
                fs::read_to_string(&path).expect("VoidCrawl Rust source file must be readable"),
            );
        }
    }
}

fn public_function_signatures(source: &str) -> Vec<String> {
    let mut lines = source.lines();
    let mut signatures = Vec::new();

    while let Some(line) = lines.next() {
        let line = line.trim_start();
        if ![
            "pub fn ",
            "pub async fn ",
            "pub const fn ",
            "pub async const fn ",
            "pub unsafe fn ",
            "pub async unsafe fn ",
        ]
        .iter()
        .any(|prefix| line.starts_with(prefix))
        {
            continue;
        }

        let mut signature = line.to_owned();
        while !signature.contains('{') && !signature.contains(';') {
            let Some(line) = lines.next() else {
                break;
            };
            signature.push(' ');
            signature.push_str(line.trim());
        }
        signatures.push(signature);
    }

    signatures
}

fn public_type_declarations(source: &str) -> Vec<String> {
    let mut lines = source.lines();
    let mut declarations = Vec::new();

    while let Some(line) = lines.next() {
        let line = line.trim_start();
        if !line.starts_with("pub use ") && !line.starts_with("pub type ") {
            continue;
        }

        let mut declaration = line.to_owned();
        while !declaration.contains(';') {
            let Some(line) = lines.next() else {
                break;
            };
            declaration.push(' ');
            declaration.push_str(line.trim());
        }
        declarations.push(declaration);
    }

    declarations
}

#[test]
fn public_api_does_not_return_raw_chromiumoxide_handles() {
    let source_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut source_files = Vec::new();
    collect_rust_sources(&source_root, &mut source_files);

    for source in &source_files {
        for declaration in public_type_declarations(source) {
            for raw_handle in RAW_HANDLE_TYPES {
                assert!(
                    !declaration.contains(*raw_handle),
                    "public re-export or alias exposes raw controller handle {raw_handle}: {declaration}"
                );
            }
        }

        for signature in public_function_signatures(source) {
            let Some((_, return_type)) = signature.split_once("->") else {
                continue;
            };
            for raw_handle in RAW_HANDLE_TYPES {
                assert!(
                    !return_type.contains(*raw_handle),
                    "public function returns raw controller handle {raw_handle}: {signature}"
                );
            }
            assert!(
                !signature.contains("fn target_id("),
                "raw CDP target ids must not be returned by the public API: {signature}"
            );
            assert!(
                !signature.contains("fn attach_page("),
                "raw CDP target ids must not be accepted by the public API: {signature}"
            );
        }
    }

    let page_source =
        fs::read_to_string(source_root.join("page.rs")).expect("Page source must be readable");
    assert!(
        page_source.contains("pub(crate) const fn cdp(&self) -> &CdpPage"),
        "internal controller use must remain behind the crate-private cdp accessor"
    );
    assert!(
        !public_function_signatures(&page_source)
            .iter()
            .any(|signature| {
                signature.contains("fn inner(") || signature.contains("fn target_id(")
            }),
        "the raw Page and target-id escapes must stay private"
    );
}
