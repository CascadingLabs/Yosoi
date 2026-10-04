#[path = "../../tests/capture_round_trip/support.rs"]
mod capture_support;

use std::{
    error::Error,
    fs,
    path::{Path, PathBuf},
};

use crate::{
    Archive, ArchiveError, ArchivedCandidateField, ArchivedContractField,
    ArchivedContractFieldValue, ArchivedContractOutcome, ArchivedContractValue,
    ArchivedDocumentInput, ArchivedExtractionDiagnostic, ArchivedExtractionFailure,
    ArchivedValidatedContractRecord, ArchivedValidationFailure, ContractRunArchiveRef,
    ContractRunRecord, ContractRunRecordError, EvaluationRunRecord, LocatorRunRecord,
};
use tempfile::tempdir;
use yosoi_contracts::{
    CONTRACT_SCHEMA_VERSION, Cardinality, ContractId, ContractSchema, FieldId, FieldSchema,
    RecordScope,
};
use yosoi_documents::{
    Document, Finding, IncompleteEvidence, LocateFailure, LocateOutcome, OutputId, Plan,
    ProjectedValue, output, text_literal,
};
use yosoi_policy::Policy;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

async fn archived_record(
    archive: &Archive,
    locator: crate::LocatorRunArchiveRef,
    schema_ref: crate::ContractSchemaArchiveRef,
    outcome: ArchivedContractOutcome,
) -> TestResult<ContractRunRecord> {
    let schema: ContractSchema = archive.read(&schema_ref).await?;
    Ok(ContractRunRecord::from_archived_parts(
        locator, schema_ref, schema, outcome,
    )?)
}

fn author_schema(id: &str) -> TestResult<ContractSchema> {
    Ok(ContractSchema::try_new(
        CONTRACT_SCHEMA_VERSION,
        ContractId::try_new(id)?,
        "One archived author",
        RecordScope::Page,
        vec![FieldSchema::try_new(
            FieldId::try_new("author")?,
            "Author display name",
            Cardinality::ExactlyOne,
            "string",
        )?],
    )?)
}

async fn no_match_fixture(
    archive: &Archive,
) -> TestResult<(
    crate::LocatorRunArchiveRef,
    crate::ContractSchemaArchiveRef,
    yosoi_documents::DocumentId,
)> {
    let capture = capture_support::mixed_bundle()?;
    let plan = Plan::new([output("author", text_literal("John Doe")?.text())?])?;
    let schema = author_schema("author")?;
    let document = Document::text("missing-author", b"Nobody".to_vec())?;
    let capture_ref = archive.write(&capture).await?;
    let policy_ref = archive.write(&Policy::default()).await?;
    let plan_ref = archive.write(&plan).await?;
    let schema_ref = archive.write(&schema).await?;
    let document_id = document.id().clone();
    let document_ref = archive.write(&document).await?;
    let evaluation = EvaluationRunRecord::try_new(
        capture_ref,
        policy_ref,
        plan_ref,
        Some(schema_ref.clone()),
        vec![ArchivedDocumentInput::new(document_ref.clone(), None)],
    )?;
    let evaluation_ref = archive.write(&evaluation).await?;
    let locator = LocatorRunRecord::new(evaluation_ref, document_ref, document.locate(&plan));
    let locator_ref = archive.write(&locator).await?;
    Ok((locator_ref, schema_ref, document_id))
}

async fn matched_fixture(
    archive: &Archive,
) -> TestResult<(
    crate::LocatorRunArchiveRef,
    crate::ContractSchemaArchiveRef,
    yosoi_documents::DocumentId,
)> {
    let capture = capture_support::mixed_bundle()?;
    let plan = Plan::new([output("author", text_literal("John Doe")?.text())?])?;
    let schema = author_schema("matched-author")?;
    let document = Document::text("matched-author", b"John Doe".to_vec())?;
    let capture_ref = archive.write(&capture).await?;
    let policy_ref = archive.write(&Policy::default()).await?;
    let plan_ref = archive.write(&plan).await?;
    let schema_ref = archive.write(&schema).await?;
    let document_id = document.id().clone();
    let document_ref = archive.write(&document).await?;
    let evaluation = EvaluationRunRecord::try_new(
        capture_ref,
        policy_ref,
        plan_ref,
        Some(schema_ref.clone()),
        vec![ArchivedDocumentInput::new(document_ref.clone(), None)],
    )?;
    let evaluation_ref = archive.write(&evaluation).await?;
    let locator = LocatorRunRecord::new(evaluation_ref, document_ref, document.locate(&plan));
    let locator_ref = archive.write(&locator).await?;
    Ok((locator_ref, schema_ref, document_id))
}

#[tokio::test]
async fn contract_run_round_trips_without_a_compiled_contract() -> TestResult {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let (locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let record = archived_record(
        &archive,
        locator_ref.clone(),
        schema_ref.clone(),
        ArchivedContractOutcome::NoMatch { document_id },
    )
    .await?;
    let reference = archive.write(&record).await?;
    require_contract_run_ref(&reference);
    let text = reference.to_string();
    drop(archive);

    let archive = Archive::open(&root).await?;
    let parsed: ContractRunArchiveRef = text.parse()?;
    if archive.read(&parsed).await? != record {
        return Err("ContractRun changed across Archive reopen".into());
    }
    Ok(())
}

#[tokio::test]
async fn contract_run_rejects_terminal_and_schema_mismatches() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let mismatch = archived_record(
        &archive,
        locator_ref.clone(),
        schema_ref,
        ArchivedContractOutcome::Evaluated {
            document_id,
            records: Vec::new(),
            issues: Vec::new(),
            extraction_diagnostics: Vec::new(),
        },
    )
    .await?;
    if !matches!(
        archive.write(&mismatch).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::LocatorOutcomeMismatch
        ))
    ) {
        return Err("ContractRun accepted an Evaluated result for locator NoMatch".into());
    }

    let other = author_schema("other-author")?;
    let other_schema = archive.write(&other).await?;
    let mismatch = archived_record(
        &archive,
        locator_ref,
        other_schema,
        ArchivedContractOutcome::NoMatch {
            document_id: Document::text("missing-author", b"Nobody".to_vec())?
                .id()
                .clone(),
        },
    )
    .await?;
    if !matches!(
        archive.write(&mismatch).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::ContractSchemaNotInEvaluation
        ))
    ) {
        return Err("ContractRun accepted a ContractSchema outside its EvaluationRun".into());
    }

    let (locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let wrong_snapshot = ContractRunRecord::from_archived_parts(
        locator_ref,
        schema_ref,
        author_schema("different-snapshot")?,
        ArchivedContractOutcome::NoMatch { document_id },
    )?;
    if !matches!(
        archive.write(&wrong_snapshot).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::ContractSchemaSnapshotMismatch
        ))
    ) {
        return Err("ContractRun accepted a mismatched embedded schema".into());
    }
    Ok(())
}

#[tokio::test]
async fn contract_run_rejects_archived_values_outside_the_schema() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (locator_ref, schema_ref, document_id) = matched_fixture(&archive).await?;
    let invalid_value = ArchivedValidatedContractRecord::new(
        document_id.clone(),
        None,
        vec![ArchivedContractField::new(
            FieldId::try_new("author")?,
            ArchivedContractFieldValue::ExactlyOne {
                value: ArchivedContractValue::MoneyUsd { minor_units: 1_200 },
            },
        )],
        vec![ArchivedCandidateField::new(
            FieldId::try_new("author")?,
            Vec::new(),
        )],
    );
    let mismatch = archived_record(
        &archive,
        locator_ref.clone(),
        schema_ref.clone(),
        ArchivedContractOutcome::Evaluated {
            document_id: document_id.clone(),
            records: vec![invalid_value],
            issues: Vec::new(),
            extraction_diagnostics: Vec::new(),
        },
    )
    .await?;
    if !matches!(
        archive.write(&mismatch).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::ValueTypeMismatch { .. }
        ))
    ) {
        return Err("ContractRun accepted Money for a String schema field".into());
    }

    let wrong_cardinality = ArchivedValidatedContractRecord::new(
        document_id.clone(),
        None,
        vec![ArchivedContractField::new(
            FieldId::try_new("author")?,
            ArchivedContractFieldValue::Many {
                values: vec![ArchivedContractValue::String {
                    value: "John Doe".to_owned(),
                }],
            },
        )],
        vec![ArchivedCandidateField::new(
            FieldId::try_new("author")?,
            Vec::new(),
        )],
    );
    let mismatch = archived_record(
        &archive,
        locator_ref.clone(),
        schema_ref.clone(),
        ArchivedContractOutcome::Evaluated {
            document_id: document_id.clone(),
            records: vec![wrong_cardinality],
            issues: Vec::new(),
            extraction_diagnostics: Vec::new(),
        },
    )
    .await?;
    if !matches!(
        archive.write(&mismatch).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::CardinalityMismatch { .. }
        ))
    ) {
        return Err("ContractRun accepted Many for an ExactlyOne schema field".into());
    }

    let locator: LocatorRunRecord = archive.read(&locator_ref).await?;
    let LocateOutcome::Matched { result } = locator.outcome() else {
        return Err("matched Contract fixture did not retain a match".into());
    };
    let source = result
        .findings()
        .first()
        .ok_or("matched Contract fixture omitted its finding")?;
    let forged = Finding::try_new(
        source.document_id().clone(),
        source.output_id().clone(),
        source
            .order()
            .checked_add(100)
            .ok_or("finding order overflow")?,
        source.coordinate().clone(),
        ProjectedValue::Text("forged".to_owned()),
        source.completeness().clone(),
        source.parent_region().cloned(),
    )?;
    let forged_record = ArchivedValidatedContractRecord::new(
        document_id.clone(),
        None,
        vec![ArchivedContractField::new(
            FieldId::try_new("author")?,
            ArchivedContractFieldValue::ExactlyOne {
                value: ArchivedContractValue::String {
                    value: "John Doe".to_owned(),
                },
            },
        )],
        vec![ArchivedCandidateField::new(
            FieldId::try_new("author")?,
            vec![forged],
        )],
    );
    let mismatch = archived_record(
        &archive,
        locator_ref,
        schema_ref,
        ArchivedContractOutcome::Evaluated {
            document_id,
            records: vec![forged_record],
            issues: Vec::new(),
            extraction_diagnostics: Vec::new(),
        },
    )
    .await?;
    if !matches!(
        archive.write(&mismatch).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::EvidenceNotInLocatorRun
        ))
    ) {
        return Err("ContractRun accepted evidence absent from its LocatorRun".into());
    }
    Ok(())
}

#[tokio::test]
async fn contract_run_preserves_extraction_and_validation_rejections() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (locator_ref, schema_ref, _) = matched_fixture(&archive).await?;
    let outcomes = [
        ArchivedContractOutcome::ExtractionRejected {
            failure: ArchivedExtractionFailure::GroupingIndexInvariant,
        },
        ArchivedContractOutcome::ValidationRejected {
            failure: ArchivedValidationFailure::FieldCountOverflow,
        },
    ];
    for outcome in outcomes {
        let record = archived_record(
            &archive,
            locator_ref.clone(),
            schema_ref.clone(),
            outcome.clone(),
        )
        .await?;
        let reference = archive.write(&record).await?;
        if archive.read(&reference).await?.outcome() != &outcome {
            return Err("ContractRun changed a rejection terminal state".into());
        }
    }
    Ok(())
}

#[tokio::test]
async fn contract_run_preserves_extraction_diagnostics() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (locator_ref, schema_ref, document_id) = matched_fixture(&archive).await?;
    let outcome = ArchivedContractOutcome::Evaluated {
        document_id,
        records: Vec::new(),
        issues: Vec::new(),
        extraction_diagnostics: vec![ArchivedExtractionDiagnostic::IncompatibleLineage {
            output: OutputId::try_new("author")?,
        }],
    };
    let record = archived_record(&archive, locator_ref, schema_ref, outcome.clone()).await?;
    let reference = archive.write(&record).await?;
    if archive.read(&reference).await?.outcome() != &outcome {
        return Err("ContractRun changed extraction diagnostics".into());
    }
    Ok(())
}

#[tokio::test]
async fn contract_run_preserves_indeterminate_and_locate_failed_states() -> TestResult {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let (base_locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let base_locator: LocatorRunRecord = archive.read(&base_locator_ref).await?;
    let indeterminate_locator = LocatorRunRecord::new(
        base_locator.evaluation().clone(),
        base_locator.document().clone(),
        LocateOutcome::Indeterminate {
            document_id: document_id.clone(),
            completeness: IncompleteEvidence::Unknown {
                reason_code: "test.incomplete".to_owned(),
            },
            reason_code: "test.indeterminate".to_owned(),
        },
    );
    let indeterminate_ref = archive.write(&indeterminate_locator).await?;
    let indeterminate = ArchivedContractOutcome::Indeterminate {
        document_id,
        completeness: IncompleteEvidence::Unknown {
            reason_code: "test.incomplete".to_owned(),
        },
        reason_code: "test.indeterminate".to_owned(),
    };
    let record = archived_record(
        &archive,
        indeterminate_ref,
        schema_ref.clone(),
        indeterminate.clone(),
    )
    .await?;
    let reference = archive.write(&record).await?;
    if archive.read(&reference).await?.outcome() != &indeterminate {
        return Err("ContractRun changed an Indeterminate state".into());
    }

    let failure = LocateFailure::ParseFailed {
        code: "test.parse".to_owned(),
    };
    let failed_locator = LocatorRunRecord::new(
        base_locator.evaluation().clone(),
        base_locator.document().clone(),
        LocateOutcome::Failed {
            failure: failure.clone(),
        },
    );
    let failed_ref = archive.write(&failed_locator).await?;
    let failed = ArchivedContractOutcome::LocateFailed { failure };
    let record = archived_record(&archive, failed_ref, schema_ref, failed.clone()).await?;
    let reference = archive.write(&record).await?;
    if archive.read(&reference).await?.outcome() != &failed {
        return Err("ContractRun changed a LocateFailed state".into());
    }
    Ok(())
}

#[tokio::test]
async fn future_contract_run_schema_fails_before_value_decode() -> TestResult {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let (locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let record = archived_record(
        &archive,
        locator_ref,
        schema_ref,
        ArchivedContractOutcome::NoMatch { document_id },
    )
    .await?;
    let reference = archive.write(&record).await?;
    let path = record_path(&root, reference.logical_key());
    let mut json: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    let object = json.as_object_mut().ok_or("record must be an object")?;
    object.insert("schema_version".to_owned(), serde_json::json!(3));
    object.insert("value".to_owned(), serde_json::json!({"invalid": true}));
    fs::write(path, serde_json::to_vec(&json)?)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::MigrationRequired {
            kind: "contract-run",
            found_schema: 3,
            supported_schema: 2,
            ..
        })
    ) {
        return Err("future ContractRun schema decoded as the current record".into());
    }
    Ok(())
}

#[tokio::test]
async fn old_contract_run_schema_requires_migration_before_value_decode() -> TestResult {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let (locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let record = archived_record(
        &archive,
        locator_ref,
        schema_ref,
        ArchivedContractOutcome::NoMatch { document_id },
    )
    .await?;
    let reference = archive.write(&record).await?;
    let path = record_path(&root, reference.logical_key());
    let mut json: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    let object = json.as_object_mut().ok_or("record must be an object")?;
    object.insert("schema_version".to_owned(), serde_json::json!(1));
    object.insert("value".to_owned(), serde_json::json!({"invalid": true}));
    fs::write(path, serde_json::to_vec(&json)?)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::MigrationRequired {
            kind: "contract-run",
            found_schema: 1,
            supported_schema: 2,
            ..
        })
    ) {
        return Err("old ContractRun schema decoded as the current record".into());
    }
    Ok(())
}

#[tokio::test]
async fn read_rejects_a_tampered_embedded_schema_snapshot() -> TestResult {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let (locator_ref, schema_ref, document_id) = no_match_fixture(&archive).await?;
    let record = archived_record(
        &archive,
        locator_ref,
        schema_ref,
        ArchivedContractOutcome::NoMatch { document_id },
    )
    .await?;
    let reference = archive.write(&record).await?;
    let path = record_path(&root, reference.logical_key());
    let mut json: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    let description = json
        .pointer_mut("/value/schema/description")
        .ok_or("record must contain an embedded schema description")?;
    *description = serde_json::json!("tampered schema snapshot");
    fs::write(path, serde_json::to_vec(&json)?)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::InvalidContractRun(
            ContractRunRecordError::ContractSchemaSnapshotMismatch
        ))
    ) {
        return Err("ContractRun read accepted a tampered schema snapshot".into());
    }
    Ok(())
}

const fn require_contract_run_ref(_reference: &ContractRunArchiveRef) {}

fn record_path(root: &Path, key: &str) -> PathBuf {
    let shard: String = key.chars().take(2).collect();
    root.join("archive/v1/records/contract-run")
        .join(shard)
        .join(format!("{key}.json"))
}
