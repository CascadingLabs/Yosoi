#![allow(
    clippy::indexing_slicing,
    clippy::panic,
    clippy::panic_in_result_fn,
    reason = "tests assert fixed ordered matches and fail loudly on broken setup"
)]

use crate::internal::documents as internal_documents;
use std::{collections::BTreeMap, error::Error};

use crate::internal::documents::{
    ByteRange, DecodedTextCoordinate, DecodedTextDocument, Document, DocumentClass, LocateFailure,
    LocateOutcome, NativeCoordinate, OutputPlan, Plan, ProjectedValue, QueryError, ResourceBudget,
    ResourceBudgetValues, ResourceLimit, TextRange, output, regex, text_literal,
};

fn limits(
    max_input_bytes: u64,
    max_query_bytes: u64,
    max_matches: u64,
    max_captures: u64,
    max_output_bytes: u64,
) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes: 1_000_000,
        max_selector_visits: 10_000_000,
        max_query_bytes,
        max_query_steps: 32,
        max_regions: 8,
        max_matches,
        max_captures,
        max_depth: 32,
        max_output_bytes,
    })?)
}

fn text_plan(value: OutputPlan) -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output("matches", value)?])?)
}

fn text_document(text: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::text("text-fixture", text.as_bytes().to_vec())?)
}

fn byte_document(bytes: Vec<u8>) -> Result<Document, Box<dyn Error>> {
    Ok(Document::text("text-fixture", bytes)?)
}

fn matched(outcome: &LocateOutcome) -> &[internal_documents::Finding] {
    match outcome {
        LocateOutcome::Matched { result } => result.findings(),
        _ => panic!("expected matched outcome, got {outcome:?}"),
    }
}

fn decoded_coordinate(finding: &internal_documents::Finding) -> DecodedTextCoordinate {
    match finding.coordinate() {
        NativeCoordinate::DecodedText(coordinate) => *coordinate,
        other => panic!("expected decoded-text coordinate, got {other:?}"),
    }
}

#[test]
fn literal_matching_is_exact_case_sensitive_and_non_overlapping() -> Result<(), Box<dyn Error>> {
    let document = text_document("banana banana ANA")?;
    let query = text_literal("ana")?;
    let plan = text_plan(query.text())?;

    let outcome = document.locate(&plan);
    let findings = matched(&outcome);
    assert_eq!(findings.len(), 2);
    assert_eq!(findings[0].value(), &ProjectedValue::Text("ana".to_owned()));
    assert_eq!(findings[1].value(), &ProjectedValue::Text("ana".to_owned()));
    assert_eq!(
        decoded_coordinate(&findings[0]).byte_range(),
        ByteRange::try_new(1, 4)?
    );
    assert_eq!(
        decoded_coordinate(&findings[0]).scalar_range(),
        TextRange::try_new(1, 4)?
    );
    assert_eq!(
        decoded_coordinate(&findings[1]).byte_range(),
        ByteRange::try_new(8, 11)?
    );
    assert_eq!(text_literal(""), Err(QueryError::EmptyExpression));

    let uppercase = text_plan(text_literal("ANA")?.text())?;
    assert!(matches!(
        document.locate(&uppercase),
        LocateOutcome::Matched { .. }
    ));
    assert_eq!(matched(&document.locate(&uppercase)).len(), 1);
    Ok(())
}

#[test]
fn unicode_ranges_count_scalars_and_preserve_exact_utf8_bytes() -> Result<(), Box<dyn Error>> {
    let document = text_document("😀e\u{301}é\u{feff}")?;
    let plan = text_plan(text_literal("é")?.text())?;

    let outcome = document.locate(&plan);
    let findings = matched(&outcome);
    assert_eq!(findings.len(), 1);
    let coordinate = decoded_coordinate(&findings[0]);
    assert_eq!(coordinate.byte_range(), ByteRange::try_new(7, 9)?);
    assert_eq!(coordinate.scalar_range(), TextRange::try_new(3, 4)?);
    assert_eq!(findings[0].value(), &ProjectedValue::Text("é".to_owned()));

    let decomposed = text_plan(text_literal("e\u{301}")?.text())?;
    assert_eq!(matched(&document.locate(&decomposed)).len(), 1);
    let bom = text_plan(text_literal("\u{feff}")?.text())?;
    assert_eq!(
        decoded_coordinate(&matched(&document.locate(&bom))[0]).scalar_range(),
        TextRange::try_new(4, 5)?
    );
    Ok(())
}

#[test]
fn regex_is_case_sensitive_by_default_and_materializes_only_requested_captures()
-> Result<(), Box<dyn Error>> {
    let document = text_document("Order #1001 and order #2002")?;
    let query = regex(r"(?P<word>Order) #(?P<id>\d+)")?;
    let plan = text_plan(query.captures(["id"])?)?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome);
    assert_eq!(findings.len(), 1);
    assert_eq!(
        findings[0].value(),
        &ProjectedValue::TextWithCaptures {
            text: "Order #1001".to_owned(),
            captures: BTreeMap::from([("id".to_owned(), "1001".to_owned())]),
        }
    );
    assert_eq!(
        decoded_coordinate(&findings[0]).byte_range(),
        ByteRange::try_new(0, 11)?
    );

    let plain = text_plan(regex(r"(?P<id>\d+)")?.text())?;
    assert_eq!(
        matched(&document.locate(&plain))[0].value(),
        &ProjectedValue::Text("1001".to_owned())
    );

    let explicit_case = text_plan(regex(r"(?i)ORDER")?.text())?;
    assert_eq!(matched(&document.locate(&explicit_case)).len(), 2);

    assert!(matches!(
        regex(r"(?P<id>\d+)")?.captures(["missing"]),
        Err(QueryError::UnknownCaptureName { name }) if name == "missing"
    ));

    let valid_capture_plan = text_plan(regex(r"(?P<id>\d+)")?.captures(["id"])?)?;
    let mut wire = serde_json::to_value(&valid_capture_plan)?;
    let capture_name = wire
        .pointer_mut("/outputs/0/projection/value/names/0")
        .ok_or("serialized capture name is missing")?;
    *capture_name = serde_json::Value::String("missing".to_owned());
    assert!(serde_json::from_value::<Plan>(wire).is_err());
    Ok(())
}

#[test]
fn invalid_utf8_and_unsupported_backtracking_features_are_explicit() -> Result<(), Box<dyn Error>> {
    let limits = limits(1_024, 128, 32, 32, 1_024)?;
    let invalid = byte_document(vec![b'a', 0xff, b'b'])?;
    let parse = DecodedTextDocument::parse(&invalid, limits);
    assert!(matches!(
        parse,
        Err(internal_documents::DecodedTextParseError::InvalidUtf8 { byte_offset: 1 })
    ));
    let invalid_plan = text_plan(text_literal("a")?.text())?;
    assert!(matches!(
        invalid.locate(&invalid_plan),
        LocateOutcome::Failed {
            failure: LocateFailure::ParseFailed { ref code }
        } if code == "invalid_utf8"
    ));

    assert!(matches!(
        regex("(?=a)"),
        Err(internal_documents::QueryError::InvalidRegexSyntax)
    ));
    Ok(())
}

#[test]
fn empty_text_and_zero_width_regex_matches_have_empty_half_open_ranges()
-> Result<(), Box<dyn Error>> {
    let empty = byte_document(Vec::new())?;
    assert_eq!(empty.class(), DocumentClass::SourceText);
    let empty_regex = text_plan(regex("")?.text())?;
    let empty_outcome = empty.locate(&empty_regex);
    let findings = matched(&empty_outcome);
    assert_eq!(findings.len(), 1);
    let coordinate = decoded_coordinate(&findings[0]);
    assert_eq!(coordinate.byte_range(), ByteRange::try_new(0, 0)?);
    assert_eq!(coordinate.scalar_range(), TextRange::try_new(0, 0)?);
    assert_eq!(findings[0].value(), &ProjectedValue::Text(String::new()));

    let source = text_document("a🙂")?;
    let all_boundaries = text_plan(regex("")?.text())?;
    let outcome = source.locate(&all_boundaries);
    let findings = matched(&outcome);
    assert_eq!(findings.len(), 3);
    assert_eq!(
        decoded_coordinate(&findings[0]).byte_range(),
        ByteRange::try_new(0, 0)?
    );
    assert_eq!(
        decoded_coordinate(&findings[1]).byte_range(),
        ByteRange::try_new(1, 1)?
    );
    assert_eq!(
        decoded_coordinate(&findings[1]).scalar_range(),
        TextRange::try_new(1, 1)?
    );
    assert_eq!(
        decoded_coordinate(&findings[2]).byte_range(),
        ByteRange::try_new(5, 5)?
    );
    assert_eq!(
        decoded_coordinate(&findings[2]).scalar_range(),
        TextRange::try_new(2, 2)?
    );
    Ok(())
}

#[test]
fn input_match_capture_and_output_limits_are_enforced() -> Result<(), Box<dyn Error>> {
    let document = text_document("aa aa")?;
    let tiny_match_limits = limits(1_024, 128, 1, 8, 1_024)?;
    let match_plan = text_plan(text_literal("aa")?.text())?;
    assert!(matches!(
        document.locate_with_budget(&match_plan, tiny_match_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 1,
                observed: 2,
            }
        }
    ));

    let tiny_capture_limits = limits(1_024, 128, 8, 1, 1_024)?;
    let capture_plan = text_plan(regex(r"(?P<id>a)")?.captures(["id"])?)?;
    assert!(matches!(
        document.locate_with_budget(&capture_plan, tiny_capture_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Captures,
                maximum: 1,
                observed: 2,
            }
        }
    ));

    let tiny_output_limits = limits(1_024, 128, 8, 8, 2)?;
    let output_plan = text_plan(text_literal("aa")?.text())?;
    assert!(matches!(
        document.locate_with_budget(&output_plan, tiny_output_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: 2,
                observed: 4,
            }
        }
    ));

    let tiny_input_limits = limits(2, 128, 8, 8, 1_024)?;
    let input_plan = text_plan(text_literal("a")?.text())?;
    assert!(matches!(
        document.locate_with_budget(&input_plan, tiny_input_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum: 2,
                observed: 5,
            }
        }
    ));
    Ok(())
}
