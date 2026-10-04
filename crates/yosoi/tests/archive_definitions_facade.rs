use std::error::Error;

use tempfile::tempdir;
use yosoi::prelude as ys;

#[tokio::test]
async fn facade_archives_strict_plan_and_contract_schema_types() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = ys::Archive::open(temporary.path().join(".yosoi")).await?;
    let plan = ys::Plan::new([ys::output(
        "product-title",
        ys::text_literal("Example product")?.text(),
    )?])?;
    let schema = ys::ContractSchema::try_new(
        ys::CONTRACT_SCHEMA_VERSION,
        ys::ContractId::try_new("product")?,
        "One product record",
        ys::RecordScope::Page,
        vec![ys::FieldSchema::try_new(
            ys::FieldId::try_new("title")?,
            "Human-readable product title",
            ys::Cardinality::ExactlyOne,
            "string",
        )?],
    )?;

    let plan_ref = archive.write(&plan).await?;
    require_plan_ref(&plan_ref);
    let schema_ref = archive.write(&schema).await?;
    require_schema_ref(&schema_ref);
    if archive.read(&plan_ref).await? != plan {
        return Err("facade reopened a different Plan".into());
    }
    if archive.read(&schema_ref).await? != schema {
        return Err("facade reopened a different ContractSchema".into());
    }
    Ok(())
}

const fn require_plan_ref(_reference: &ys::PlanArchiveRef) {}
const fn require_schema_ref(_reference: &ys::ContractSchemaArchiveRef) {}
