#![allow(
    clippy::indexing_slicing,
    reason = "shared fixture construction mutates a checked-in Web Capture document"
)]

#[path = "capture_round_trip/support.rs"]
mod capture_support;

use std::env;
use std::error::Error;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use tempfile::tempdir;
use tokio::runtime::Builder;
use yosoi_archive::{
    Archive, ArchiveError, ArchivedDocumentInput, DocumentArchiveRef, EvaluationRunArchiveRef,
    EvaluationRunError, EvaluationRunRecord,
};
use yosoi_contracts::{
    CONTRACT_SCHEMA_VERSION, Cardinality, ContractId, ContractSchema, FieldId, FieldSchema,
    RecordScope,
};
use yosoi_documents::{Document, Plan, output, text_literal};
use yosoi_policy::Policy;

const CHILD_ROLE: &str = "YOSOI_EVALUATION_ARCHIVE_CHILD_ROLE";
const CHILD_ROOT: &str = "YOSOI_EVALUATION_ARCHIVE_CHILD_ROOT";
const CHILD_REFERENCE: &str = "YOSOI_EVALUATION_ARCHIVE_CHILD_REFERENCE";

fn locator_plan() -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output(
        "title",
        text_literal("Example product")?.text(),
    )?])?)
}

fn contract_schema() -> Result<ContractSchema, Box<dyn Error>> {
    Ok(ContractSchema::try_new(
        CONTRACT_SCHEMA_VERSION,
        ContractId::try_new("product")?,
        "One product record",
        RecordScope::Page,
        vec![FieldSchema::try_new(
            FieldId::try_new("title")?,
            "Human-readable product title",
            Cardinality::ExactlyOne,
            "string",
        )?],
    )?)
}

fn normalized_document() -> Result<Document, Box<dyn Error>> {
    Ok(Document::text(
        "normalized-product",
        b"Example product\nUSD 12.00".to_vec(),
    )?)
}

async fn write_evaluation_fixture(
    archive: &Archive,
) -> Result<EvaluationRunArchiveRef, Box<dyn Error>> {
    let capture = capture_support::mixed_bundle()?;
    let source_artifact = capture_support::source_references(capture.capture())
        .first()
        .copied()
        .ok_or("mixed Capture fixture omitted retained source")?;
    let plan = locator_plan()?;
    let schema = contract_schema()?;
    let document = normalized_document()?;
    let capture_ref = archive.write(&capture).await?;
    let policy_ref = archive.write(&Policy::default()).await?;
    let plan_ref = archive.write(&plan).await?;
    let schema_ref = archive.write(&schema).await?;
    let document_ref = archive.write(&document).await?;
    let run = EvaluationRunRecord::try_new(
        capture_ref,
        policy_ref,
        plan_ref,
        Some(schema_ref),
        vec![ArchivedDocumentInput::new(
            document_ref,
            Some(source_artifact),
        )],
    )?;
    Ok(archive.write(&run).await?)
}

async fn verify_offline_evaluation(
    archive: &Archive,
    reference: &EvaluationRunArchiveRef,
) -> Result<(), Box<dyn Error>> {
    let run = archive.read(reference).await?;
    let input = run
        .documents()
        .first()
        .ok_or("EvaluationRun lost its Document")?;
    let document = archive.read(input.document()).await?;
    let plan = archive.read(run.plan()).await?;
    let policy = archive.read(run.policy()).await?;
    let schema_ref = run
        .contract_schema()
        .ok_or("EvaluationRun lost its ContractSchema")?;
    let schema = archive.read(schema_ref).await?;
    let _capture = archive.read(run.capture()).await?;

    if document != normalized_document()? || plan != locator_plan()? || policy != Policy::default()
    {
        return Err("offline EvaluationRun reopened different typed inputs".into());
    }
    if document.locate(&plan) != normalized_document()?.locate(&locator_plan()?) {
        return Err("offline locator outcome differs from the immediate outcome".into());
    }
    if schema.identity()? != contract_schema()?.identity()? {
        return Err("offline ContractSchema identity differs from the archived definition".into());
    }
    Ok(())
}

#[tokio::test]
async fn evaluation_run_reopens_ordered_documents_and_definitions() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let reference = write_evaluation_fixture(&archive).await?;
    drop(archive);

    let reopened = Archive::open(&root).await?;
    verify_offline_evaluation(&reopened, &reference).await
}

#[tokio::test]
async fn document_payload_is_exact_and_digest_verified() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let document = normalized_document()?;
    let reference = archive.write(&document).await?;
    let payload = document_payload_path(&root, &reference);
    if fs::read(&payload)? != document.bytes() {
        return Err("Document Archive changed exact normalized bytes".into());
    }
    fs::write(&payload, vec![b'x'; document.bytes().len()])?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::DocumentPayloadDigestMismatch { .. })
    ) {
        return Err("same-length Document corruption did not fail digest verification".into());
    }
    Ok(())
}

#[tokio::test]
async fn evaluation_run_rejects_invalid_shape_and_unresolved_provenance()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let capture = capture_support::mixed_bundle()?;
    let source_references = capture_support::source_references(capture.capture());
    let unavailable = source_references
        .iter()
        .find(|reference| reference.as_untyped().artifact_id().get() == 5)
        .copied()
        .ok_or("mixed Capture fixture omitted unavailable source")?;
    let capture_ref = archive.write(&capture).await?;
    let policy_ref = archive.write(&Policy::default()).await?;
    let plan_ref = archive.write(&locator_plan()?).await?;
    let document_ref = archive.write(&normalized_document()?).await?;

    if EvaluationRunRecord::try_new(
        capture_ref.clone(),
        policy_ref.clone(),
        plan_ref.clone(),
        None,
        Vec::new(),
    ) != Err(EvaluationRunError::NoDocuments)
    {
        return Err("empty EvaluationRun document order was accepted".into());
    }
    let duplicated = ArchivedDocumentInput::new(document_ref, None);
    if !matches!(
        EvaluationRunRecord::try_new(
            capture_ref.clone(),
            policy_ref.clone(),
            plan_ref.clone(),
            None,
            vec![duplicated.clone(), duplicated],
        ),
        Err(EvaluationRunError::DuplicateDocument { .. })
    ) {
        return Err("duplicate EvaluationRun Document was accepted".into());
    }
    let missing_document: DocumentArchiveRef =
        "document:v1:123e4567-e89b-42d3-a456-426614174000".parse()?;
    let missing_run = EvaluationRunRecord::try_new(
        capture_ref.clone(),
        policy_ref.clone(),
        plan_ref.clone(),
        None,
        vec![ArchivedDocumentInput::new(missing_document, None)],
    )?;
    if !matches!(
        archive.write(&missing_run).await,
        Err(ArchiveError::RecordNotFound {
            kind: "document",
            ..
        })
    ) {
        return Err("EvaluationRun with a missing Document was published".into());
    }
    let unavailable_run = EvaluationRunRecord::try_new(
        capture_ref,
        policy_ref,
        plan_ref,
        None,
        vec![ArchivedDocumentInput::new(
            archive.write(&normalized_document()?).await?,
            Some(unavailable),
        )],
    )?;
    if !matches!(
        archive.write(&unavailable_run).await,
        Err(ArchiveError::EvaluationSourcePayloadUnavailable { .. })
    ) {
        return Err("unretained source artifact provenance was accepted".into());
    }
    Ok(())
}

#[test]
fn evaluation_run_crosses_real_process_boundaries() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let reference = temporary.path().join("evaluation-run-ref.txt");
    run_child("subprocess_evaluation_writer", "write", &root, &reference)?;
    run_child("subprocess_evaluation_reader", "read", &root, &reference)
}

fn run_child(
    test_name: &str,
    role: &str,
    root: &Path,
    reference: &Path,
) -> Result<(), Box<dyn Error>> {
    let status = Command::new(env::current_exe()?)
        .args(["--ignored", "--exact", test_name, "--nocapture"])
        .env(CHILD_ROLE, role)
        .env(CHILD_ROOT, root)
        .env(CHILD_REFERENCE, reference)
        .status()?;
    if !status.success() {
        return Err(format!("Evaluation Archive child {role} failed with {status}").into());
    }
    Ok(())
}

#[test]
#[ignore = "invoked by evaluation_run_crosses_real_process_boundaries"]
fn subprocess_evaluation_writer() -> Result<(), Box<dyn Error>> {
    require_role("write")?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let root = required_os(CHILD_ROOT)?;
    let reference = runtime.block_on(async {
        let archive = Archive::open(root).await?;
        write_evaluation_fixture(&archive).await
    })?;
    fs::write(required_os(CHILD_REFERENCE)?, reference.to_string())?;
    Ok(())
}

#[test]
#[ignore = "invoked by evaluation_run_crosses_real_process_boundaries"]
fn subprocess_evaluation_reader() -> Result<(), Box<dyn Error>> {
    require_role("read")?;
    let reference: EvaluationRunArchiveRef =
        fs::read_to_string(required_os(CHILD_REFERENCE)?)?.parse()?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let root = required_os(CHILD_ROOT)?;
    runtime.block_on(async {
        let archive = Archive::open(root).await?;
        verify_offline_evaluation(&archive, &reference).await
    })
}

fn document_payload_path(root: &Path, reference: &DocumentArchiveRef) -> PathBuf {
    let key = reference.logical_key();
    let shard = key.chars().take(2).collect::<String>();
    root.join("archive/v1/documents")
        .join(shard)
        .join(key)
        .join("payload.bin")
}

fn require_role(expected: &str) -> Result<(), Box<dyn Error>> {
    let observed = env::var(CHILD_ROLE)?;
    if observed != expected {
        return Err(format!("expected child role {expected}, found {observed}").into());
    }
    Ok(())
}

fn required_os(name: &str) -> Result<OsString, Box<dyn Error>> {
    env::var_os(name).ok_or_else(|| format!("missing child environment {name}").into())
}
