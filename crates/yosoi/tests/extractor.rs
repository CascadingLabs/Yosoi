#![allow(dead_code)] // Contract fixtures are inspected through generated candidates.
#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail focused extraction tests.

use std::error::Error;
use yosoi::prelude as ys;

#[derive(Clone, Debug, ys::Contract)]
#[ys(
    id = "product",
    description = "One product offered to a buyer",
    root = ys::locator::css(".product")
)]
struct Product {
    #[ys(description = "The product name shown to the buyer")]
    name: String,

    #[ys(description = "The currently advertised purchase price")]
    price: ys::Money,

    #[ys(description = "Optional supporting copy shown with the product")]
    subtitle: Option<String>,

    #[ys(description = "Categories assigned to this product")]
    categories: Vec<String>,
}

#[derive(Clone, Debug, ys::Contract)]
#[ys(id = "page_summary", description = "Summary metadata for one document")]
struct PageSummary {
    #[ys(description = "The page title shown to a reader")]
    title: String,

    #[ys(description = "Optional page summary text")]
    description: Option<String>,
}

fn finding(
    document: &ys::DocumentId,
    output: &str,
    order: u64,
    pointer: &str,
    value: &str,
    completeness: ys::Completeness,
    region: Option<ys::RegionLineage>,
) -> Result<ys::Finding, Box<dyn Error>> {
    Ok(ys::Finding::try_new(
        document.clone(),
        ys::OutputId::try_new(output)?,
        order,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new(pointer)?),
        ys::ProjectedValue::Text(value.into()),
        completeness,
        region,
    )?)
}

fn region(id: &str, ordinal: u64, pointer: &str) -> Result<ys::RegionLineage, Box<dyn Error>> {
    Ok(ys::RegionLineage::new(
        ys::RegionId::try_new(id)?,
        ordinal,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new(pointer)?),
    ))
}

#[path = "extractor/behavior.rs"]
mod behavior;
#[path = "extractor/limits.rs"]
mod limits;
