use super::capture_round_trip_support as capture_support;
use crate::internal::archive as internal_archive;

use std::{
    error::Error,
    fs,
    path::{Path, PathBuf},
};

use crate::internal::archive::{
    Archive, ArchiveError, ArchivedDocumentInput, EvaluationRunRecord, LocatorRunArchiveRef,
    LocatorRunRecord, LocatorRunRecordError,
};
use crate::internal::documents::{
    Document, DocumentId, IncompleteEvidence, LocateFailure, LocateOutcome, Plan, ProjectedValue,
    output, text_literal,
};
use crate::internal::policy::Policy;
use tempfile::tempdir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn author_document(id: &str) -> TestResult<Document> {
    Ok(Document::text(id, b"Author: John Doe".to_vec())?)
}

fn author_plan() -> TestResult<Plan> {
    Ok(Plan::new([output(
        "author",
        text_literal("John Doe")?.text(),
    )?])?)
}

async fn evaluation_fixture(
    archive: &Archive,
) -> TestResult<(
    internal_archive::EvaluationRunArchiveRef,
    internal_archive::DocumentArchiveRef,
)> {
    let capture = capture_support::mixed_bundle()?;
    let plan = author_plan()?;
    let document = author_document("author-document")?;
    let capture_ref = archive.write(&capture).await?;
    let policy_ref = archive.write(&Policy::default()).await?;
    let plan_ref = archive.write(&plan).await?;
    let document_ref = archive.write(&document).await?;
    let evaluation = EvaluationRunRecord::try_new(
        capture_ref,
        policy_ref,
        plan_ref,
        None,
        vec![ArchivedDocumentInput::new(document_ref.clone(), None)],
    )?;
    let evaluation_ref = archive.write(&evaluation).await?;
    Ok((evaluation_ref, document_ref))
}

#[tokio::test]
async fn locator_run_reopens_exact_author_value_and_provenance() -> TestResult {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let (evaluation_ref, document_ref) = evaluation_fixture(&archive).await?;
    let outcome = author_document("author-document")?.locate(&author_plan()?);
    let record = LocatorRunRecord::new(evaluation_ref, document_ref, outcome.clone());
    if format!("{record:?}").contains("John Doe") {
        return Err("LocatorRun Debug exposed archived output values".into());
    }
    let reference = archive.write(&record).await?;
    require_locator_run_ref(&reference);
    let text = reference.to_string();
    drop(archive);

    let archive = Archive::open(&root).await?;
    let parsed: LocatorRunArchiveRef = text.parse()?;
    let reopened = archive.read(&parsed).await?;
    if reopened != record || reopened.outcome() != &outcome {
        return Err("LocatorRun changed across Archive reopen".into());
    }
    let LocateOutcome::Matched { result } = reopened.outcome() else {
        return Err("archived author locator did not retain its matched state".into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or("archived author locator omitted its finding")?;
    if finding.output_id().as_str() != "author"
        || finding.value() != &ProjectedValue::Text("John Doe".to_owned())
    {
        return Err("archived author finding lost its output or John Doe value".into());
    }
    Ok(())
}

#[tokio::test]
async fn locator_run_rejects_foreign_and_mismatched_documents() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (evaluation_ref, document_ref) = evaluation_fixture(&archive).await?;
    let foreign_ref = archive.write(&author_document("foreign-document")?).await?;
    let foreign = LocatorRunRecord::new(
        evaluation_ref.clone(),
        foreign_ref,
        author_document("foreign-document")?.locate(&author_plan()?),
    );
    if !matches!(
        archive.write(&foreign).await,
        Err(ArchiveError::InvalidLocatorRun(
            LocatorRunRecordError::DocumentNotInEvaluation
        ))
    ) {
        return Err("LocatorRun accepted a Document outside its EvaluationRun".into());
    }

    let mismatched = LocatorRunRecord::new(
        evaluation_ref,
        document_ref,
        LocateOutcome::NoMatch {
            document_id: DocumentId::try_new("other-document")?,
        },
    );
    if !matches!(
        archive.write(&mismatched).await,
        Err(ArchiveError::InvalidLocatorRun(
            LocatorRunRecordError::OutcomeDocumentMismatch { .. }
        ))
    ) {
        return Err("LocatorRun accepted an outcome for another Document".into());
    }
    Ok(())
}

#[tokio::test]
async fn locator_run_preserves_every_terminal_outcome_variant() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (evaluation_ref, document_ref) = evaluation_fixture(&archive).await?;
    let document = archive.read(&document_ref).await?;
    let outcomes = [
        LocateOutcome::NoMatch {
            document_id: document.id().clone(),
        },
        LocateOutcome::Indeterminate {
            document_id: document.id().clone(),
            completeness: IncompleteEvidence::Unknown {
                reason_code: "test.incomplete".to_owned(),
            },
            reason_code: "test.indeterminate".to_owned(),
        },
        LocateOutcome::Failed {
            failure: LocateFailure::ParseFailed {
                code: "test.parse".to_owned(),
            },
        },
    ];
    for outcome in outcomes {
        let record = LocatorRunRecord::new(
            evaluation_ref.clone(),
            document_ref.clone(),
            outcome.clone(),
        );
        let reference = archive.write(&record).await?;
        if archive.read(&reference).await?.outcome() != &outcome {
            return Err("LocatorRun changed a terminal outcome variant".into());
        }
    }
    Ok(())
}

#[tokio::test]
async fn future_locator_run_schema_fails_before_value_decode() -> TestResult {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let (evaluation_ref, document_ref) = evaluation_fixture(&archive).await?;
    let record = LocatorRunRecord::new(
        evaluation_ref,
        document_ref,
        author_document("author-document")?.locate(&author_plan()?),
    );
    let reference = archive.write(&record).await?;
    let path = record_path(&root, reference.logical_key());
    let mut json: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    let object = json.as_object_mut().ok_or("record must be an object")?;
    object.insert("schema_version".to_owned(), serde_json::json!(2));
    object.insert("value".to_owned(), serde_json::json!({"invalid": true}));
    fs::write(path, serde_json::to_vec(&json)?)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::MigrationRequired {
            kind: "locator-run",
            found_schema: 2,
            supported_schema: 1,
            ..
        })
    ) {
        return Err("future LocatorRun schema decoded as the current record".into());
    }
    Ok(())
}

const fn require_locator_run_ref(_reference: &LocatorRunArchiveRef) {}

fn record_path(root: &Path, key: &str) -> PathBuf {
    let shard: String = key.chars().take(2).collect();
    root.join("archive/v1/records/locator-run")
        .join(shard)
        .join(format!("{key}.json"))
}
