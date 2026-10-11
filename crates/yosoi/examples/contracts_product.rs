//! Contract with inline pinned product locators.

#![allow(dead_code)] // Public SDK example.

use std::error::Error;
use yosoi::prelude as ys;

#[derive(ys::Contract)]
#[ys(
    id = "product",
    description = "One product offered to a buyer",
    root = ys::locator::css("article.product")
)]
struct Product {
    #[ys(
        description = "The product name shown to the buyer",
        locator = ys::locator::css("h2").text()
    )]
    name: String,

    #[ys(
        description = "The currently advertised purchase price",
        locator = ys::locator::css(".price").text()
    )]
    price: ys::Money,

    #[ys(
        description = "Optional supporting copy shown with the product",
        locator = ys::locator::css(".subtitle").text()
    )]
    subtitle: Option<String>,

    #[ys(
        description = "Categories assigned to this product",
        locator = ys::locator::css(".category").text()
    )]
    categories: Vec<String>,
}

fn evaluate_products(
    document: &ys::Document,
) -> Result<ys::contracts::ContractOutcome<Product>, ys::ContractLocatorError> {
    let located = Product::locate(document)?;
    let extracted = Product::extract(&located);

    for product in extracted.candidates() {
        let _projected_prices = product.price.values();
        let _price_evidence = product.price.evidence();
    }

    Ok(extracted.validate())
}

fn main() -> Result<(), Box<dyn Error>> {
    let schema = Product::schema()?;
    let _ = schema.id();
    let _ = Product::plan()?;
    Ok(())
}
