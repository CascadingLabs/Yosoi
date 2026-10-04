#![allow(dead_code)] // Contract fixtures are exercised through generated validation code.
#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail focused validation tests.

use std::collections::BTreeMap;
use std::error::Error;
use yosoi_engine::prelude as ys;

#[derive(ys::Contract)]
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

const fn assert_extracted_type(_: &ys::Extracted<Product>) {}

fn region(ordinal: u64) -> Result<ys::RegionLineage, Box<dyn Error>> {
    Ok(ys::RegionLineage::new(
        ys::RegionId::try_new("product")?,
        ordinal,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new(format!("/products/{ordinal}"))?),
    ))
}

fn finding(
    document: &ys::DocumentId,
    output: &str,
    order: u64,
    pointer: &str,
    value: &str,
    completeness: ys::Completeness,
    region: ys::RegionLineage,
) -> Result<ys::Finding, Box<dyn Error>> {
    Ok(ys::Finding::try_new(
        document.clone(),
        ys::OutputId::try_new(output)?,
        order,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new(pointer)?),
        ys::ProjectedValue::Text(value.into()),
        completeness,
        Some(region),
    )?)
}

fn projected_finding(
    document: &ys::DocumentId,
    output: &str,
    order: u64,
    pointer: &str,
    value: ys::ProjectedValue,
    region: ys::RegionLineage,
) -> Result<ys::Finding, Box<dyn Error>> {
    Ok(ys::Finding::try_new(
        document.clone(),
        ys::OutputId::try_new(output)?,
        order,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new(pointer)?),
        value,
        ys::Completeness::Complete,
        Some(region),
    )?)
}

fn valid_located() -> Result<ys::LocateOutcome, Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let first = region(0)?;
    let second = region(1)?;
    let findings = vec![
        finding(
            &document,
            "name",
            0,
            "/products/0/name",
            "Tea",
            ys::Completeness::Complete,
            first.clone(),
        )?,
        finding(
            &document,
            "price",
            1,
            "/products/0/price",
            "$4.50",
            ys::Completeness::Complete,
            first.clone(),
        )?,
        finding(
            &document,
            "categories",
            2,
            "/products/0/categories/0",
            "drinks",
            ys::Completeness::Complete,
            first.clone(),
        )?,
        finding(
            &document,
            "categories",
            3,
            "/products/0/categories/1",
            "pantry",
            ys::Completeness::Complete,
            first,
        )?,
        finding(
            &document,
            "name",
            4,
            "/products/1/name",
            "Coffee",
            ys::Completeness::Complete,
            second.clone(),
        )?,
        finding(
            &document,
            "price",
            5,
            "/products/1/price",
            "$8.25",
            ys::Completeness::Complete,
            second.clone(),
        )?,
        finding(
            &document,
            "subtitle",
            6,
            "/products/1/subtitle",
            "Whole bean",
            ys::Completeness::Complete,
            second,
        )?,
    ];
    Ok(ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    })
}

#[path = "validation/edges.rs"]
mod edges;
#[path = "validation/limits_privacy_money.rs"]
mod limits_privacy_money;
#[path = "validation/outcomes.rs"]
mod outcomes;
#[path = "validation/records.rs"]
mod records;
