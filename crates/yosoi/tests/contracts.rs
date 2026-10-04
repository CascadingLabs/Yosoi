#![allow(dead_code)] // Contract fixtures are inspected through generated metadata.
#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail focused contract tests.

use std::collections::BTreeMap;
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
#[ys(
    id = "product",
    description = "Different display guidance",
    root = ys::locator::css(".product")
)]
struct ProductWithDifferentDescriptions {
    #[ys(description = "Different name guidance")]
    name: String,

    #[ys(description = "Different price guidance")]
    price: ys::Money,

    #[ys(description = "Different subtitle guidance")]
    subtitle: Option<String>,

    #[ys(description = "Different category guidance")]
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

#[derive(Clone, Debug, ys::Contract)]
#[ys(id = "raw_field", description = "Contract with a raw Rust identifier")]
struct RawField {
    #[ys(description = "A field whose semantic ID omits Rust raw syntax")]
    r#type: String,
}

#[test]
fn derive_generates_pydantic_shaped_schema_and_candidate() -> Result<(), Box<dyn Error>> {
    let schema = Product::schema()?;
    assert_eq!(schema.version(), ys::CONTRACT_SCHEMA_VERSION);
    assert_eq!(schema.id().as_str(), "product");
    assert_eq!(schema.scope(), ys::RecordScope::Repeated);
    assert_eq!(schema.fields().len(), 4);
    assert_eq!(
        schema.fields().first().map(ys::FieldSchema::cardinality),
        Some(ys::Cardinality::ExactlyOne)
    );
    assert_eq!(
        schema.fields().get(2).map(ys::FieldSchema::cardinality),
        Some(ys::Cardinality::ZeroOrOne)
    );
    assert_eq!(
        schema.fields().get(3).map(ys::FieldSchema::cardinality),
        Some(ys::Cardinality::Many)
    );
    assert_eq!(
        schema.fields().get(1).map(ys::FieldSchema::value_type),
        Some("money.usd")
    );

    let input = yosoi::CandidateInput::new(
        ys::DocumentId::try_new("sentinel-document-secret")?,
        None,
        BTreeMap::new(),
    );
    assert!(!format!("{input:?}").contains("sentinel-document-secret"));
    let candidate = <Product as ys::Contract>::candidate_from(&input);
    let _: &ys::CandidateField<String> = &candidate.name;
    let _: &ys::CandidateField<ys::Money> = &candidate.price;
    let _: &ys::CandidateField<String> = &candidate.subtitle;
    let _: &ys::CandidateField<String> = &candidate.categories;
    let debug = format!("{candidate:?}");
    assert!(debug.contains("ProductCandidate"));
    assert!(debug.contains("price"));
    assert!(!debug.contains("sentinel-document-secret"));
    Ok(())
}

#[test]
fn descriptions_do_not_change_semantic_identity() -> Result<(), ys::ContractSchemaError> {
    assert_eq!(
        Product::schema()?.identity()?.to_string(),
        "5b3428f164bcfd354cf28805dc715a8cdd0307ef621f381c06e96d545a72304f"
    );
    assert_eq!(
        Product::schema()?.identity()?,
        ProductWithDifferentDescriptions::schema()?.identity()?
    );
    Ok(())
}

#[test]
fn schema_round_trips_and_revalidates() -> Result<(), Box<dyn Error>> {
    let encoded = serde_json::to_vec(Product::schema()?)?;
    let decoded: ys::ContractSchema = serde_json::from_slice(&encoded)?;
    assert_eq!(&decoded, Product::schema()?);
    assert_eq!(decoded.identity()?, Product::schema()?.identity()?);
    Ok(())
}

#[test]
fn page_scope_is_distinct() -> Result<(), ys::ContractSchemaError> {
    assert_eq!(PageSummary::schema()?.scope(), ys::RecordScope::Page);
    assert!(PageSummary::root_locator().is_none());
    assert_eq!(Product::schema()?.scope(), ys::RecordScope::Repeated);
    assert!(Product::root_locator().is_some());
    Ok(())
}

#[test]
fn raw_rust_identifiers_use_their_semantic_name() -> Result<(), ys::ContractSchemaError> {
    let schema = RawField::schema()?;
    assert_eq!(
        schema.fields().first().map(|field| field.id().as_str()),
        Some("type")
    );
    Ok(())
}

#[test]
fn schema_constructors_revalidate_hidden_ids_and_versions() -> Result<(), Box<dyn Error>> {
    assert!(matches!(
        ys::FieldSchema::try_new(
            ys::FieldId::from_derive(""),
            "Invalid field",
            ys::Cardinality::ExactlyOne,
            "string",
        ),
        Err(ys::ContractSchemaError::EmptyFieldId)
    ));
    let field = ys::FieldSchema::try_new(
        ys::FieldId::try_new("name")?,
        "Product name",
        ys::Cardinality::ExactlyOne,
        "string",
    )?;
    assert!(matches!(
        ys::ContractSchema::try_new(
            ys::CONTRACT_SCHEMA_VERSION,
            ys::ContractId::from_derive(""),
            "Invalid contract",
            ys::RecordScope::Page,
            vec![field.clone()],
        ),
        Err(ys::ContractSchemaError::EmptyContractId)
    ));
    assert!(matches!(
        ys::ContractSchema::try_new(
            ys::CONTRACT_SCHEMA_VERSION + 1,
            ys::ContractId::try_new("future")?,
            "Unsupported future contract",
            ys::RecordScope::Page,
            vec![field],
        ),
        Err(ys::ContractSchemaError::UnsupportedVersion { observed: 2 })
    ));
    Ok(())
}
