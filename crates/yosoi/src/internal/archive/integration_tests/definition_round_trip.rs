use std::error::Error;
use std::fmt::Debug;
use std::fs;
use std::path::{Path, PathBuf};

use crate::internal::archive::{Archive, ArchiveError, ContractSchemaArchiveRef, PlanArchiveRef};
use crate::internal::contracts::{
    CONTRACT_SCHEMA_VERSION, Cardinality, ContractId, ContractSchema, FieldId, FieldSchema,
    RecordScope,
};
use crate::internal::documents::{Plan, output, text_literal};
use tempfile::tempdir;

fn locator_plan() -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output(
        "product-title",
        text_literal("Example product")?.text(),
    )?])?)
}

fn contract_schema(description: &str) -> Result<ContractSchema, Box<dyn Error>> {
    Ok(ContractSchema::try_new(
        CONTRACT_SCHEMA_VERSION,
        ContractId::try_new("product")?,
        description,
        RecordScope::Page,
        vec![FieldSchema::try_new(
            FieldId::try_new("title")?,
            "Human-readable product title",
            Cardinality::ExactlyOne,
            "string",
        )?],
    )?)
}

#[tokio::test]
async fn plan_and_contract_schema_round_trip_as_exact_typed_snapshots() -> Result<(), Box<dyn Error>>
{
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let plan = locator_plan()?;
    let schema = contract_schema("One product record")?;

    let plan_ref = archive.write(&plan).await?;
    require_plan_ref(&plan_ref);
    let schema_ref = archive.write(&schema).await?;
    require_schema_ref(&schema_ref);

    let parsed_plan: PlanArchiveRef = plan_ref.to_string().parse()?;
    let parsed_schema: ContractSchemaArchiveRef = schema_ref.to_string().parse()?;
    ensure_equal(
        &archive.read(&parsed_plan).await?,
        &plan,
        "compiled Plan changed across Archive",
    )?;
    ensure_equal(
        &archive.read(&parsed_schema).await?,
        &schema,
        "ContractSchema changed across Archive",
    )?;
    Ok(())
}

#[tokio::test]
async fn repeated_definition_writes_create_distinct_immutable_snapshots()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let plan = locator_plan()?;
    let schema = contract_schema("One product record")?;

    let first_plan = archive.write(&plan).await?;
    let second_plan = archive.write(&plan).await?;
    if first_plan == second_plan {
        return Err("two Plan writes reused one Archive UUID".into());
    }
    let first_schema = archive.write(&schema).await?;
    let second_schema = archive.write(&schema).await?;
    if first_schema == second_schema {
        return Err("two ContractSchema writes reused one Archive UUID".into());
    }
    Ok(())
}

#[tokio::test]
async fn owning_deserializers_reject_invalid_archived_definitions() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let plan_ref = archive.write(&locator_plan()?).await?;
    let schema_ref = archive
        .write(&contract_schema("One product record")?)
        .await?;

    mutate_record(
        definition_record_path(&root, "plan", plan_ref.logical_key()),
        |record| set_array(record, "outputs", Vec::new()),
    )?;
    if !matches!(
        archive.read(&plan_ref).await,
        Err(ArchiveError::InvalidRecordValue { kind: "plan", .. })
    ) {
        return Err("invalid archived Plan bypassed its owning decoder".into());
    }

    mutate_record(
        definition_record_path(&root, "contract-schema", schema_ref.logical_key()),
        |record| set_string(record, "description", String::new()),
    )?;
    if !matches!(
        archive.read(&schema_ref).await,
        Err(ArchiveError::InvalidRecordValue {
            kind: "contract-schema",
            ..
        })
    ) {
        return Err("invalid archived ContractSchema bypassed its owning decoder".into());
    }
    Ok(())
}

#[tokio::test]
async fn each_definition_kind_rejects_a_future_record_schema_before_value_decode()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let plan_ref = archive.write(&locator_plan()?).await?;
    let schema_ref = archive
        .write(&contract_schema("One product record")?)
        .await?;

    set_future_schema(definition_record_path(
        &root,
        "plan",
        plan_ref.logical_key(),
    ))?;
    set_future_schema(definition_record_path(
        &root,
        "contract-schema",
        schema_ref.logical_key(),
    ))?;

    ensure_migration_required(&archive.read(&plan_ref).await, "plan")?;
    ensure_migration_required(&archive.read(&schema_ref).await, "contract-schema")
}

const fn require_plan_ref(_reference: &PlanArchiveRef) {}
const fn require_schema_ref(_reference: &ContractSchemaArchiveRef) {}

fn definition_record_path(root: &Path, kind: &str, key: &str) -> PathBuf {
    let shard: String = key.chars().take(2).collect();
    root.join("archive/v1/records")
        .join(kind)
        .join(shard)
        .join(format!("{key}.json"))
}

fn mutate_record(
    path: PathBuf,
    mutate: impl FnOnce(&mut serde_json::Value) -> Result<(), Box<dyn Error>>,
) -> Result<(), Box<dyn Error>> {
    let mut record: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    mutate(&mut record)?;
    fs::write(path, serde_json::to_vec(&record)?)?;
    Ok(())
}

fn value_object(
    record: &mut serde_json::Value,
) -> Result<&mut serde_json::Map<String, serde_json::Value>, Box<dyn Error>> {
    record
        .get_mut("value")
        .and_then(serde_json::Value::as_object_mut)
        .ok_or_else(|| "Archive definition value must be an object".into())
}

fn set_array(
    record: &mut serde_json::Value,
    field: &str,
    value: Vec<serde_json::Value>,
) -> Result<(), Box<dyn Error>> {
    value_object(record)?.insert(field.to_owned(), serde_json::Value::Array(value));
    Ok(())
}

fn set_string(
    record: &mut serde_json::Value,
    field: &str,
    value: String,
) -> Result<(), Box<dyn Error>> {
    value_object(record)?.insert(field.to_owned(), serde_json::Value::String(value));
    Ok(())
}

fn set_future_schema(path: PathBuf) -> Result<(), Box<dyn Error>> {
    mutate_record(path, |record| {
        let object = record
            .as_object_mut()
            .ok_or("Archive envelope must be an object")?;
        object.insert("schema_version".to_owned(), serde_json::json!(2));
        object.insert("value".to_owned(), serde_json::json!({"invalid": true}));
        Ok(())
    })
}

fn ensure_migration_required<T>(
    result: &Result<T, ArchiveError>,
    kind: &'static str,
) -> Result<(), Box<dyn Error>> {
    if !matches!(
        result,
        Err(ArchiveError::MigrationRequired {
            kind: observed,
            found_schema: 2,
            supported_schema: 1,
            ..
        }) if *observed == kind
    ) {
        return Err(format!("future {kind} schema was not rejected before value decoding").into());
    }
    Ok(())
}

fn ensure_equal<T>(actual: &T, expected: &T, message: &str) -> Result<(), Box<dyn Error>>
where
    T: Debug + PartialEq,
{
    if actual != expected {
        return Err(format!("{message}: expected {expected:?}, found {actual:?}").into());
    }
    Ok(())
}
