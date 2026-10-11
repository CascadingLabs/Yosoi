#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail pipeline tests.

use crate::internal::engine::prelude as ys;
use std::error::Error;
use std::ptr;

const PRODUCT_ROOT: ys::PinnedLocator = ys::locator::css("article.product");
const PRODUCT_NAME: ys::PinnedOutputLocator = ys::locator::css("h2").text();
const PRODUCT_PRICE: ys::PinnedOutputLocator = ys::locator::css("span.price").text();
const PRODUCT_SUBTITLE: ys::PinnedOutputLocator = ys::locator::css("span.subtitle").text();
const PRODUCT_CATEGORY: ys::PinnedOutputLocator = ys::locator::css("span.category").text();

#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(
    id = "product",
    description = "One catalog product",
    root = ys::locator::css("article.product")
)]
struct Product {
    #[ys(
        description = "Product name",
        locator = ys::locator::css("h2").text()
    )]
    name: String,
    #[ys(
        description = "Current USD price",
        locator = ys::locator::css("span.price").text()
    )]
    price: ys::Money,
    #[ys(
        description = "Optional supporting copy",
        locator = ys::locator::css("span.subtitle").text()
    )]
    subtitle: Option<String>,
    #[ys(
        description = "Product categories",
        locator = ys::locator::css("span.category").text()
    )]
    categories: Vec<String>,
}

#[allow(dead_code)]
#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(
    id = "product",
    description = "One catalog product",
    root = PRODUCT_ROOT
)]
struct ReferencedProduct {
    #[ys(description = "Product name", locator = PRODUCT_NAME)]
    name: String,
    #[ys(description = "Current USD price", locator = PRODUCT_PRICE)]
    price: ys::Money,
    #[ys(description = "Optional supporting copy", locator = PRODUCT_SUBTITLE)]
    subtitle: Option<String>,
    #[ys(description = "Product categories", locator = PRODUCT_CATEGORY)]
    categories: Vec<String>,
}

#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(id = "page_summary", description = "One page summary")]
struct PageSummary {
    #[ys(
        description = "Page title",
        locator = ys::locator::text_literal("Catalog").text()
    )]
    title: String,
    #[ys(
        description = "Optional page description",
        locator = ys::locator::text_literal("Description").text()
    )]
    description: Option<String>,
}

#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(id = "link", description = "One link in a result list", root = ys::locator::css("li"))]
struct Link {
    #[ys(description = "The destination", locator = ys::locator::css("a[href]").attribute("href"))]
    href: String,
    #[ys(description = "The visible label", locator = ys::locator::css("a[href]").text())]
    label: String,
}

#[allow(dead_code)]
#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(
    id = "bad_root",
    description = "Malformed pinned root",
    root = ys::locator::css("")
)]
struct BadRoot {
    #[ys(
        description = "Value beneath the malformed root",
        locator = ys::locator::css("span").text()
    )]
    value: String,
}

#[allow(dead_code)]
#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(id = "bad_field", description = "Malformed pinned page field")]
struct BadField {
    #[ys(
        description = "Malformed page output",
        locator = ys::locator::css("").text()
    )]
    value: String,
}

#[allow(dead_code)]
#[derive(ys::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(
    id = "xml_product",
    description = "One XML product",
    root = ys::locator::css("product")
)]
struct XmlProduct {
    #[ys(
        description = "XML product name",
        locator = ys::locator::css("name").text()
    )]
    name: String,
}

#[test]
fn real_html_plan_locates_extracts_and_validates_products() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog.html",
        br#"
        <main>
          <article class="product">
            <h2>Tea</h2><span class="price">$4.50</span>
            <span class="category">drinks</span><span class="category">pantry</span>
          </article>
          <article class="product">
            <h2>Coffee</h2><span class="price">$8.25</span>
            <span class="category">drinks</span>
          </article>
        </main>
        "#
        .to_vec(),
    )?;
    assert!(ptr::eq(Product::plan()?, Product::plan()?));
    assert_eq!(Product::schema()?.scope(), ys::RecordScope::Repeated);
    assert!(Product::root_locator().is_some());
    let located = Product::locate(&document)?;
    assert!(matches!(located, ys::LocateOutcome::Matched { .. }));
    let products = Product::extract(&located).validate().require_all()?;
    assert_eq!(products.len(), 2);
    assert_eq!(
        products.first().map(|product| product.name.as_str()),
        Some("Tea")
    );
    assert_eq!(
        products.first().map(|product| product.price.minor_units()),
        Some(450)
    );
    assert_eq!(
        products
            .first()
            .and_then(|product| product.subtitle.as_deref()),
        None
    );
    assert_eq!(
        products
            .first()
            .map(|product| product.categories.as_slice()),
        Some(["drinks".to_owned(), "pantry".to_owned()].as_slice())
    );
    assert_eq!(
        products.get(1).map(|product| product.name.as_str()),
        Some("Coffee")
    );
    Ok(())
}

#[test]
fn pinned_contract_reads_link_attribute_with_its_row() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "links.html",
        b"<ul><li><a href='https://a.example/'>A</a></li><li><a href='https://b.example/'>B</a></li></ul>".to_vec(),
    )?;
    let links = Link::extract(&Link::locate(&document)?)
        .validate()
        .require_all()?;
    assert_eq!(links.len(), 2);
    assert_eq!(
        links.first().map(|link| link.href.as_str()),
        Some("https://a.example/")
    );
    assert_eq!(links.get(1).map(|link| link.label.as_str()), Some("B"));
    Ok(())
}

#[test]
fn repeated_root_membership_survives_missing_field_outputs() -> Result<(), Box<dyn Error>> {
    let no_root = ys::Document::html("none.html", b"<main></main>".to_vec())?;
    assert!(matches!(
        Product::locate(&no_root)?,
        ys::LocateOutcome::NoMatch { .. }
    ));

    let empty_root = ys::Document::html(
        "empty.html",
        b"<main><article class='product'></article></main>".to_vec(),
    )?;
    let located = Product::locate(&empty_root)?;
    let ys::LocateOutcome::Matched { result } = &located else {
        return Err("expected the empty product root to remain matched".into());
    };
    assert_eq!(result.regions().len(), 1);
    assert_eq!(result.findings().len(), 0);
    let extracted = Product::extract(&located);
    let candidate = extracted
        .candidates()
        .first()
        .ok_or("missing empty-root candidate")?;
    assert!(candidate.name.is_absent());
    assert!(candidate.price.is_absent());
    assert!(candidate.subtitle.is_absent());
    assert_eq!(candidate.categories.values().len(), 0);
    let ys::ContractOutcome::Evaluated {
        records, issues, ..
    } = extracted.validate()
    else {
        return Err("expected empty root to produce validation issues".into());
    };
    assert_eq!(records.len(), 0);
    assert_eq!(issues.len(), 1);
    assert_eq!(
        issues.first().map(|issue| issue
            .fields
            .iter()
            .map(|field| field.field.as_str())
            .collect::<Vec<_>>()),
        Some(vec!["name", "price"])
    );

    let required_only = ys::Document::html(
        "required.html",
        b"<article class='product'><h2>Tea</h2><span class='price'>$4.50</span></article>".to_vec(),
    )?;
    let products = Product::extract(&Product::locate(&required_only)?)
        .validate()
        .require_all()?;
    let product = products.first().ok_or("missing required-only product")?;
    assert_eq!(product.name, "Tea");
    assert_eq!(product.subtitle, None);
    assert_eq!(product.categories, Vec::<String>::new());
    Ok(())
}

#[test]
fn xml_repeated_root_survives_when_every_field_misses() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::xml("products.xml", b"<products><product/></products>".to_vec())?;
    let located = XmlProduct::locate(&document)?;
    let ys::LocateOutcome::Matched { result } = &located else {
        return Err("expected empty XML product root to remain matched".into());
    };
    assert_eq!(result.regions().len(), 1);
    assert_eq!(result.findings().len(), 0);
    let ys::ContractOutcome::Evaluated {
        records, issues, ..
    } = XmlProduct::extract(&located).validate()
    else {
        return Err("expected XML root validation outcome".into());
    };
    assert_eq!(records.len(), 0);
    assert_eq!(issues.len(), 1);
    assert_eq!(
        issues
            .first()
            .and_then(|issue| issue.fields.first())
            .map(|field| field.field.as_str()),
        Some("name")
    );
    Ok(())
}

#[test]
fn malformed_pinned_locators_fail_before_location() -> Result<(), Box<dyn Error>> {
    assert_eq!(BadRoot::schema()?.scope(), ys::RecordScope::Repeated);
    assert!(matches!(
        BadRoot::plan(),
        Err(ys::ContractLocatorError::Query(
            ys::QueryError::EmptyExpression
        ))
    ));
    assert!(matches!(
        BadRoot::plan(),
        Err(ys::ContractLocatorError::Query(
            ys::QueryError::EmptyExpression
        ))
    ));
    assert_eq!(BadField::schema()?.scope(), ys::RecordScope::Page);
    assert!(matches!(
        BadField::plan(),
        Err(ys::ContractLocatorError::Query(
            ys::QueryError::EmptyExpression
        ))
    ));
    assert!(matches!(
        BadField::plan(),
        Err(ys::ContractLocatorError::Query(
            ys::QueryError::EmptyExpression
        ))
    ));
    Ok(())
}

#[test]
fn pinned_plan_cache_is_stable_under_repeated_access() -> Result<(), Box<dyn Error>> {
    let expected = Product::plan()?;
    assert_eq!(expected, ReferencedProduct::plan()?);
    for _ in 0..10_000 {
        if !ptr::eq(expected, Product::plan()?) {
            return Err("pinned Contract plan cache returned a different allocation".into());
        }
    }
    Ok(())
}

#[test]
fn real_text_plan_validates_a_page_contract() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::text("summary.txt", b"Catalog".to_vec())?;
    assert_eq!(PageSummary::schema()?.scope(), ys::RecordScope::Page);
    assert!(PageSummary::root_locator().is_none());
    let summaries = PageSummary::extract(&PageSummary::locate(&document)?)
        .validate()
        .require_all()?;
    assert_eq!(summaries.len(), 1);
    assert_eq!(
        summaries.first().map(|summary| summary.title.as_str()),
        Some("Catalog")
    );
    assert_eq!(
        summaries
            .first()
            .and_then(|summary| summary.description.as_deref()),
        None
    );
    Ok(())
}
