//! Compile fixture proving the Contract derive respects a renamed dependency.

use ys::contracts::{ContractSchema, ContractSchemaError};
use ys::prelude as sdk;

const PRODUCT_ROOT: sdk::PinnedLocator = sdk::locator::css("article.product");
const PRODUCT_NAME: sdk::PinnedOutputLocator = sdk::locator::css("h2").text();

#[derive(Debug, sdk::Contract)]
#[ys(
    id = "renamed_product",
    description = "Renamed dependency fixture",
    root = PRODUCT_ROOT
)]
pub struct RenamedProduct {
    #[ys(description = "Product name", locator = PRODUCT_NAME)]
    pub name: String,
}

pub fn schema() -> Result<&'static ContractSchema, ContractSchemaError> {
    RenamedProduct::schema()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::error::Error;

    #[test]
    fn renamed_facade_extracts_and_validates() -> Result<(), Box<dyn Error>> {
        let document = sdk::Document::html(
            "renamed-fixture.html",
            b"<article class='product'><h2>Tea</h2></article>".to_vec(),
        )?;
        let located = RenamedProduct::locate(&document)?;
        let records = RenamedProduct::extract(&located).validate().require_all()?;
        match records.as_slice() {
            [product] if product.name == "Tea" => Ok(()),
            _ => Err("renamed facade did not construct the matched record".into()),
        }
    }
}
