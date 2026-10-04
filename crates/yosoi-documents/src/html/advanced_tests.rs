#![allow(
    clippy::format_collect,
    clippy::iter_on_single_items,
    clippy::panic_in_result_fn
)] // Opt-in oracle tests prioritize transparent record construction.

use std::{env, error::Error, fs, io::Error as IoError, path::PathBuf};

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::{
    Document, Finding, LocateOutcome, NativeCoordinate, Plan, ProjectedValue, ResourceBudget, css,
    output, tree_text_contains, xpath,
};

use super::{ParsedHtmlDocument, SelectorElement};

const MATRIX_JSON: &str =
    include_str!("../../../../benchmarks/fixtures/document-locators/v1/matrix.json");

#[derive(Serialize)]
struct OracleCoordinate {
    kind: &'static str,
    child_path: Vec<u32>,
    path: String,
}

#[derive(Serialize)]
struct OracleRecord {
    value: Value,
    coordinate: OracleCoordinate,
}

#[derive(Clone, Copy)]
enum OracleProjection {
    Text,
    Attribute(&'static str),
    NodeReference,
}

fn expected_case<'a>(matrix: &'a Value, id: &str) -> Result<&'a Value, Box<dyn Error>> {
    let cases = matrix
        .get("advanced_cases")
        .and_then(Value::as_array)
        .ok_or_else(|| IoError::other("advanced matrix cases are missing"))?;
    cases
        .iter()
        .find(|case| case.get("id").and_then(Value::as_str) == Some(id))
        .and_then(|case| case.get("expected"))
        .ok_or_else(|| IoError::other("locked advanced HTML oracle is missing").into())
}

fn source_tree_path(parsed: &ParsedHtmlDocument, path: &[u32]) -> Option<String> {
    let mut current: Option<usize> = None;
    for ordinal in path {
        current = if let Some(parent_index) = current {
            let child_offset = usize::try_from(ordinal.checked_sub(1)?).ok()?;
            let child_index = parsed
                .tree
                .element_children(parent_index)?
                .get(child_offset)
                .copied()?;
            if parsed
                .tree
                .element(child_index)?
                .element_sibling_ordinal()?
                != *ordinal
            {
                return None;
            }
            Some(child_index)
        } else {
            (0..parsed.tree.element_count()).find(|index| {
                parsed.tree.element(*index).is_some_and(|element| {
                    element.element_parent().is_none()
                        && element.element_sibling_ordinal() == Some(*ordinal)
                })
            })
        };
    }

    let mut path_parts = Vec::new();
    while let Some(index) = current {
        let element = parsed.tree.element(index)?;
        let tag_name = element.local_name()?;
        let tag_ordinal = if let Some(parent_index) = element.element_parent() {
            let mut same_tag_ordinal = 0_u32;
            let mut found = false;
            for sibling_index in parsed.tree.element_children(parent_index)? {
                let sibling = parsed.tree.element(*sibling_index)?;
                if sibling.local_name() == Some(tag_name) {
                    same_tag_ordinal = same_tag_ordinal.checked_add(1)?;
                }
                if *sibling_index == index {
                    found = true;
                    break;
                }
            }
            if !found || same_tag_ordinal == 0 {
                return None;
            }
            same_tag_ordinal
        } else {
            1
        };
        path_parts.push(format!("/{tag_name}[{tag_ordinal}]"));
        current = element.element_parent();
    }
    path_parts.reverse();
    Some(path_parts.concat())
}

fn oracle_record(
    parsed: &ParsedHtmlDocument,
    finding: &Finding,
    projection: OracleProjection,
) -> Result<OracleRecord, Box<dyn Error>> {
    let NativeCoordinate::SourceTree(coordinate) = finding.coordinate() else {
        return Err(IoError::other("HTML finding has a non-tree coordinate").into());
    };
    let path = source_tree_path(parsed, coordinate.child_path())
        .ok_or_else(|| IoError::other("HTML coordinate cannot resolve to a parser node"))?;
    let value = match (projection, finding.value()) {
        (OracleProjection::Text, ProjectedValue::Text(value)) => Value::String(value.clone()),
        (OracleProjection::Attribute(expected_name), ProjectedValue::Attribute { name, value })
            if name == expected_name =>
        {
            Value::String(value.clone())
        }
        (OracleProjection::NodeReference, ProjectedValue::Node(reference))
            if reference.document_id() == finding.document_id()
                && reference.coordinate() == finding.coordinate() =>
        {
            Value::Object(
                [("path".to_owned(), Value::String(path.clone()))]
                    .into_iter()
                    .collect(),
            )
        }
        _ => return Err(IoError::other("HTML projection does not match its oracle").into()),
    };
    Ok(OracleRecord {
        value,
        coordinate: OracleCoordinate {
            kind: "source_tree_path",
            child_path: coordinate.child_path().to_vec(),
            path,
        },
    })
}

fn assert_locked_case(
    document: &Document,
    parsed: &ParsedHtmlDocument,
    plan: &Plan,
    expected: &Value,
    projection: OracleProjection,
) -> Result<(), Box<dyn Error>> {
    let limits = ResourceBudget::conservative();
    let retained = parsed.locate_with_budget(plan, limits);
    assert_eq!(document.locate_with_budget(plan, limits), retained);
    let result = match retained {
        LocateOutcome::Matched { result } => result,
        outcome => {
            return Err(
                IoError::other(format!("expected advanced HTML matches, got {outcome:?}")).into(),
            );
        }
    };
    let expected_count = expected
        .get("match_count")
        .and_then(Value::as_u64)
        .ok_or_else(|| IoError::other("advanced oracle match count is missing"))?;
    assert_eq!(result.findings().len(), usize::try_from(expected_count)?);
    let records = result
        .findings()
        .iter()
        .map(|finding| oracle_record(parsed, finding, projection))
        .collect::<Result<Vec<_>, _>>()?;
    let digest = Sha256::digest(serde_json::to_vec(&records)?);
    let digest = digest
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let expected_digest = expected
        .get("records_sha256")
        .and_then(Value::as_str)
        .ok_or_else(|| IoError::other("advanced oracle digest is missing"))?;
    assert_eq!(digest, expected_digest);

    let first_sample = expected
        .get("first")
        .and_then(Value::as_array)
        .and_then(|samples| samples.first())
        .ok_or_else(|| IoError::other("advanced oracle first sample is missing"))?;
    let last_sample = expected
        .get("last")
        .and_then(Value::as_array)
        .and_then(|samples| samples.last())
        .ok_or_else(|| IoError::other("advanced oracle last sample is missing"))?;
    assert_eq!(
        serde_json::to_value(
            records
                .first()
                .ok_or_else(|| { IoError::other("advanced HTML result has no first record") })?
        )?,
        *first_sample
    );
    assert_eq!(
        serde_json::to_value(
            records
                .last()
                .ok_or_else(|| { IoError::other("advanced HTML result has no last record") })?
        )?,
        *last_sample
    );
    Ok(())
}

#[test]
#[ignore = "requires the offline advanced HTML corpus materialized locally"]
fn advanced_whatwg_html_matches_locked_lxml_oracles() -> Result<(), Box<dyn Error>> {
    let advanced_root = env::var_os("YOSOI_DOCUMENT_LOCATOR_ADVANCED_ROOT")
        .map(PathBuf::from)
        .ok_or_else(|| IoError::other("advanced corpus root environment variable is required"))?;
    let document = Document::html(
        "advanced-whatwg-html",
        fs::read(advanced_root.join("live/whatwg-html-standard.html"))?,
    )?;
    let limits = ResourceBudget::conservative();
    let parsed = ParsedHtmlDocument::parse(&document, limits)?;
    let matrix: Value = serde_json::from_str(MATRIX_JSON)?;

    let css_plan = Plan::new([output("dfns", css("dfn[id]")?.text())?])?;
    assert_locked_case(
        &document,
        &parsed,
        &css_plan,
        expected_case(&matrix, "html_css")?,
        OracleProjection::Text,
    )?;

    let xpath_plan = Plan::new([output("links", xpath("//a[@href]")?.attribute("href")?)?])?;
    assert_locked_case(
        &document,
        &parsed,
        &xpath_plan,
        expected_case(&matrix, "html_xpath")?,
        OracleProjection::Attribute("href"),
    )?;

    let text_plan = Plan::new([output(
        "user_agent",
        tree_text_contains("user agent")?.node(),
    )?])?;
    assert_locked_case(
        &document,
        &parsed,
        &text_plan,
        expected_case(&matrix, "html_text")?,
        OracleProjection::NodeReference,
    )?;
    Ok(())
}
