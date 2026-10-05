#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail conformance tests.

use serde_json::{Value, json};
use std::sync::OnceLock;
use yosoi_contract_validation::{
    FieldIssueKind, Money, RuntimeContract, RuntimeContractOutcome, RuntimeFieldValue,
    RuntimeValue, ValidationLimits, read_many, read_optional, read_required,
};
use yosoi_contracts::{
    CONTRACT_SCHEMA_VERSION, CandidateField, CandidateInput, CandidateView, Cardinality, Contract,
    ContractId, ContractSchema, ContractSchemaError, ContractValue, FieldId, FieldSchema,
    RecordScope,
};
use yosoi_documents::{
    ByteRange, Completeness, DecodedTextCoordinate, DocumentId, Finding, LocateOutcome,
    LocateResult, NativeCoordinate, RegionId, RegionLineage, TextRange,
};
use yosoi_extractor::{ExtractionLimits, extract_contract_with_limits};

#[derive(Clone)]
struct StaticCandidate {
    document_id: DocumentId,
    name: CandidateField<String>,
    price: CandidateField<Money>,
    nickname: CandidateField<String>,
    tags: CandidateField<String>,
}

impl CandidateView for StaticCandidate {
    fn document_id(&self) -> &DocumentId {
        &self.document_id
    }

    fn region(&self) -> Option<&yosoi_documents::RegionLineage> {
        None
    }

    fn value_count(&self) -> Option<u64> {
        [
            self.name.len(),
            self.price.len(),
            self.nickname.len(),
            self.tags.len(),
        ]
        .into_iter()
        .try_fold(0_u64, |total, count| {
            total.checked_add(u64::try_from(count).ok()?)
        })
    }
}

struct StaticContract;

impl Contract for StaticContract {
    type Candidate = StaticCandidate;
    type Extracted = ();

    fn schema() -> Result<&'static ContractSchema, ContractSchemaError> {
        static SCHEMA: OnceLock<Result<ContractSchema, ContractSchemaError>> = OnceLock::new();
        SCHEMA
            .get_or_init(|| {
                ContractSchema::try_new(
                    CONTRACT_SCHEMA_VERSION,
                    ContractId::try_new("product")?,
                    "One catalog product",
                    RecordScope::Page,
                    vec![
                        FieldSchema::try_new(
                            FieldId::try_new("name")?,
                            "Product name",
                            Cardinality::ExactlyOne,
                            String::TYPE_ID,
                        )?,
                        FieldSchema::try_new(
                            FieldId::try_new("price")?,
                            "Current USD price",
                            Cardinality::ExactlyOne,
                            Money::TYPE_ID,
                        )?,
                        FieldSchema::try_new(
                            FieldId::try_new("nickname")?,
                            "Optional product label",
                            Cardinality::ZeroOrOne,
                            String::TYPE_ID,
                        )?,
                        FieldSchema::try_new(
                            FieldId::try_new("tags")?,
                            "Product tags",
                            Cardinality::Many,
                            String::TYPE_ID,
                        )?,
                    ],
                )
            })
            .as_ref()
            .map_err(Clone::clone)
    }

    fn candidate_from(input: &CandidateInput) -> Self::Candidate {
        StaticCandidate {
            document_id: input.document_id().clone(),
            name: CandidateField::from_input("name", input),
            price: CandidateField::from_input("price", input),
            nickname: CandidateField::from_input("nickname", input),
            tags: CandidateField::from_input("tags", input),
        }
    }
}

fn finding(output: &str, order: u64, text: &str, completeness: Value) -> Value {
    let start = order * 8;
    let end = start + u64::try_from(text.len()).unwrap_or(u64::MAX);
    json!({
        "document_id": "catalog-page",
        "output_id": output,
        "order": order,
        "coordinate": {
            "kind": "decoded_text",
            "coordinate": {
                "byte_range": {"start": start, "end": end},
                "scalar_range": {"start": start, "end": end}
            }
        },
        "value": {"kind": "text", "value": text},
        "completeness": completeness,
        "parent_region": null
    })
}

fn complete() -> Value {
    json!({"status": "complete"})
}

fn located(findings: Vec<Value>) -> Result<LocateOutcome, Box<dyn std::error::Error>> {
    let wire = json!({
        "status": "matched",
        "result": {
            "document_id": "catalog-page",
            "findings": findings
        }
    });
    Ok(serde_json::from_value(wire)?)
}

fn normal_findings() -> Vec<Value> {
    vec![
        finding("name", 0, "Tea", complete()),
        finding("price", 1, "$4.50", complete()),
        finding("tags", 2, "drinks", complete()),
    ]
}

#[test]
fn runtime_and_static_contracts_share_candidate_and_value_semantics()
-> Result<(), Box<dyn std::error::Error>> {
    let located = located(normal_findings())?;
    let limits = ExtractionLimits::uniform(32);
    let static_extracted = extract_contract_with_limits::<StaticContract>(&located, limits);
    let runtime = RuntimeContract::new(StaticContract::schema()?.clone())?;
    let runtime_extracted = runtime.extract(&located, limits);

    let static_candidate = static_extracted
        .candidates()
        .first()
        .ok_or_else(|| std::io::Error::other("static extraction omitted candidate"))?;
    let runtime_candidate = runtime_extracted
        .candidates()
        .first()
        .ok_or_else(|| std::io::Error::other("runtime extraction omitted candidate"))?;
    assert_eq!(
        static_candidate.document_id(),
        runtime_candidate.document_id()
    );
    assert_eq!(
        static_candidate.name.evidence(),
        runtime_candidate.findings(&FieldId::try_new("name")?)
    );
    assert_eq!(
        static_candidate.price.evidence(),
        runtime_candidate.findings(&FieldId::try_new("price")?)
    );

    let static_name = read_required(&static_candidate.name)
        .map_err(|_| std::io::Error::other("static name validation failed"))?;
    let static_price = read_required(&static_candidate.price)
        .map_err(|_| std::io::Error::other("static price validation failed"))?;
    let static_nickname = read_optional(&static_candidate.nickname)
        .map_err(|_| std::io::Error::other("static optional validation failed"))?;
    let static_tags = read_many(&static_candidate.tags)
        .map_err(|_| std::io::Error::other("static many validation failed"))?;

    let outcome = runtime_extracted.validate();
    let RuntimeContractOutcome::Evaluated {
        records,
        issues,
        extraction_diagnostics,
        ..
    } = outcome.clone()
    else {
        return Err(std::io::Error::other("runtime validation did not evaluate").into());
    };
    assert!(issues.is_empty());
    assert!(extraction_diagnostics.is_empty());
    let record = records
        .first()
        .ok_or_else(|| std::io::Error::other("runtime validation omitted record"))?;
    assert_eq!(
        record.value.get(&FieldId::try_new("name")?),
        Some(&RuntimeFieldValue::ExactlyOne {
            value: RuntimeValue::String(static_name),
        })
    );
    assert_eq!(
        record.value.get(&FieldId::try_new("price")?),
        Some(&RuntimeFieldValue::ExactlyOne {
            value: RuntimeValue::MoneyUsd(static_price),
        })
    );
    assert_eq!(
        record.value.get(&FieldId::try_new("nickname")?),
        Some(&RuntimeFieldValue::ZeroOrOne {
            value: static_nickname.map(RuntimeValue::String)
        })
    );
    assert_eq!(
        record.value.get(&FieldId::try_new("tags")?),
        Some(&RuntimeFieldValue::Many {
            values: static_tags.into_iter().map(RuntimeValue::String).collect(),
        })
    );

    let serialized = serde_json::to_value(&outcome)?;
    assert_eq!(
        serialized.get("status").and_then(Value::as_str),
        Some("evaluated")
    );
    let all = outcome.require_all()?;
    assert_eq!(all.len(), 1);
    let expected_document_id = DocumentId::try_new("catalog-page")?;
    assert_eq!(
        all.first().map(|value| value.candidate.document_id()),
        Some(&expected_document_id)
    );
    Ok(())
}

#[test]
fn runtime_contract_rejects_unsupported_scalar_types() -> Result<(), Box<dyn std::error::Error>> {
    let schema = ContractSchema::try_new(
        CONTRACT_SCHEMA_VERSION,
        ContractId::try_new("unsupported")?,
        "Unsupported scalar",
        RecordScope::Page,
        vec![FieldSchema::try_new(
            FieldId::try_new("count")?,
            "Unsupported numeric value",
            Cardinality::ExactlyOne,
            "integer",
        )?],
    )?;
    assert!(matches!(
        RuntimeContract::new(schema),
        Err(yosoi_contract_validation::RuntimeContractError::UnsupportedValueType { .. })
    ));
    Ok(())
}

#[test]
fn runtime_contract_reports_scalar_multiplicity_and_incomplete_evidence()
-> Result<(), Box<dyn std::error::Error>> {
    let multiple = located(vec![
        finding("name", 0, "Tea", complete()),
        finding("name", 1, "Coffee", complete()),
    ])?;
    let runtime = RuntimeContract::new(StaticContract::schema()?.clone())?;
    let outcome = runtime
        .extract(&multiple, ExtractionLimits::uniform(32))
        .validate();
    let RuntimeContractOutcome::Evaluated { issues, .. } = outcome else {
        return Err(std::io::Error::other("multiplicity case did not evaluate").into());
    };
    let issue = issues
        .first()
        .and_then(|record| record.fields.first())
        .ok_or_else(|| std::io::Error::other("missing multiplicity issue"))?;
    assert_eq!(issue.kind, FieldIssueKind::ExcessCandidates { observed: 2 });
    assert_eq!(issue.evidence.len(), 2);

    let partial = json!({
        "status": "partial",
        "reason_code": "source_truncated",
        "lost_items": 1
    });
    let incomplete = located(vec![finding("name", 0, "Tea", partial)])?;
    let outcome = runtime
        .extract(&incomplete, ExtractionLimits::uniform(32))
        .validate();
    let RuntimeContractOutcome::Evaluated { issues, .. } = outcome else {
        return Err(std::io::Error::other("incomplete case did not evaluate").into());
    };
    let issue = issues
        .first()
        .and_then(|record| record.fields.first())
        .ok_or_else(|| std::io::Error::other("missing incomplete-evidence issue"))?;
    assert_eq!(issue.kind, FieldIssueKind::IncompleteEvidence);
    assert_eq!(issue.evidence.len(), 1);
    assert!(matches!(
        issue.evidence.first().map(Finding::completeness),
        Some(Completeness::Partial { .. })
    ));
    Ok(())
}

#[test]
fn runtime_contract_enforces_validation_and_extraction_budgets()
-> Result<(), Box<dyn std::error::Error>> {
    let located = located(normal_findings())?;
    let runtime = RuntimeContract::new(StaticContract::schema()?.clone())?;
    let extracted = runtime.extract(&located, ExtractionLimits::uniform(32));
    let outcome = extracted.validate_with_limits(ValidationLimits {
        max_fields: 0,
        ..ValidationLimits::default()
    });
    assert!(matches!(
        outcome,
        RuntimeContractOutcome::ValidationRejected {
            failure: yosoi_contract_validation::ValidationFailure::FieldLimitExceeded {
                maximum: 0,
                observed: 4
            }
        }
    ));

    let outcome = runtime
        .extract(&located, ExtractionLimits::uniform(0))
        .validate();
    assert!(matches!(
        outcome,
        RuntimeContractOutcome::ExtractionRejected { .. }
    ));
    assert!(matches!(
        outcome.require_all(),
        Err(yosoi_contract_validation::ContractIssues::ExtractionRejected)
    ));
    Ok(())
}

#[test]
fn runtime_contract_keeps_repeated_roots_without_field_evidence()
-> Result<(), Box<dyn std::error::Error>> {
    let document_id = DocumentId::try_new("catalog-page")?;
    let coordinate = NativeCoordinate::DecodedText(DecodedTextCoordinate::new(
        ByteRange::try_new(0, 1)?,
        TextRange::try_new(0, 1)?,
    ));
    let region = RegionLineage::new(RegionId::try_new("product")?, 0, coordinate);
    let result = LocateResult::try_new_with_regions(document_id, vec![region.clone()], Vec::new())?;
    let located = LocateOutcome::Matched { result };
    let schema = ContractSchema::try_new(
        CONTRACT_SCHEMA_VERSION,
        ContractId::try_new("product")?,
        "One catalog product",
        RecordScope::Repeated,
        vec![FieldSchema::try_new(
            FieldId::try_new("name")?,
            "Product name",
            Cardinality::ExactlyOne,
            String::TYPE_ID,
        )?],
    )?;
    let runtime = RuntimeContract::new(schema)?;
    let extracted = runtime.extract(&located, ExtractionLimits::uniform(32));
    let candidate = extracted
        .candidates()
        .first()
        .ok_or_else(|| std::io::Error::other("empty repeated root was dropped"))?;
    assert_eq!(candidate.region(), Some(&region));
    assert!(candidate.fields().is_empty());
    let outcome = extracted.validate();
    let RuntimeContractOutcome::Evaluated { issues, .. } = outcome else {
        return Err(std::io::Error::other("empty repeated root did not validate").into());
    };
    assert!(matches!(
        issues
            .first()
            .and_then(|record| record.fields.first())
            .map(|issue| &issue.kind),
        Some(FieldIssueKind::MissingRequired)
    ));
    Ok(())
}
