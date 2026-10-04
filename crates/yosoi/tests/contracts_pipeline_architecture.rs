#![allow(clippy::panic_in_result_fn)] // Assertions intentionally enforce SDK boundaries.

use std::error::Error;
use std::fs;
use std::path::Path;

#[test]
fn public_contract_examples_cover_inline_and_referenced_locators() -> Result<(), Box<dyn Error>> {
    let examples = Path::new(env!("CARGO_MANIFEST_DIR")).join("examples");
    let product = fs::read_to_string(examples.join("contracts_product.rs"))?;
    for required in [
        "root = ys::locator::css",
        "locator = ys::locator::css",
        "Product::locate(document)",
    ] {
        assert!(
            product.contains(required),
            "product example omits {required}"
        );
    }
    let page = fs::read_to_string(examples.join("contracts_page_summary.rs"))?;
    for required in [
        "const TITLE_LOCATOR",
        "locator = TITLE_LOCATOR",
        "PageSummary::locate(document)",
    ] {
        assert!(page.contains(required), "page example omits {required}");
    }
    for (name, source) in [("product", product), ("page", page)] {
        for forbidden in ["Plan::new", "ExtractionPlan", "repeated", "page\n"] {
            assert!(
                !source.contains(forbidden),
                "public {name} Contract example contains obsolete {forbidden}"
            );
        }
    }
    Ok(())
}

#[test]
fn contract_docs_do_not_restore_rejected_designs() -> Result<(), Box<dyn Error>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let guide = fs::read_to_string(root.join("docs/contracts-extractor.md"))?;
    for forbidden in ["public ExtractionPlan", "runtime schema builder"] {
        assert!(!guide.contains(forbidden));
    }
    Ok(())
}
