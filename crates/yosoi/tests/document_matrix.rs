#![allow(clippy::panic_in_result_fn)] // Conformance helpers use assertions plus fallible decoding.

use std::{
    collections::BTreeSet,
    error::Error,
    fmt::Write as _,
    fs, io,
    path::{Path, PathBuf},
};

use serde_json::Value;
use yosoi::prelude as ys;

macro_rules! matrix_query {
    ($case:expr, $document_kind:expr) => {{
        let case = $case;
        let document_kind = $document_kind;
        let locator = field(case, "locator")?;
        let locator_kind = string_field(locator, "kind")?;
        let expression = string_field(locator, "expression")?;
        let mut query = match locator_kind {
            "css" => ys::css(expression)?,
            "xpath" => ys::xpath(expression)?,
            "json_pointer" => ys::json_pointer(expression)?,
            "json_path" => ys::json_path(expression)?,
            "role" => ys::role(expression)?,
            "regex" => ys::regex(expression)?,
            "text" => match document_kind {
                "html" | "xml" | "dom" => ys::tree_text_contains(expression)?,
                "ax" => ys::accessibility_text(expression)?,
                "text" => ys::text_literal(expression)?,
                kind => {
                    return Err(invalid(format!(
                        "text locator is not supported for matrix document kind {kind}"
                    ))
                    .into());
                }
            },
            kind => return Err(invalid(format!("unsupported matrix locator kind {kind}")).into()),
        };

        if let Some(bindings) = locator.get("namespace_bindings") {
            let bindings = bindings
                .as_object()
                .ok_or_else(|| invalid("namespace_bindings must be an object"))?;
            for (prefix, uri) in bindings {
                let uri = uri
                    .as_str()
                    .ok_or_else(|| invalid("namespace binding URI must be a string"))?;
                query = if prefix.is_empty() && locator_kind == "css" {
                    query.with_default_namespace(uri)?
                } else {
                    query.with_namespace(prefix.as_str(), uri)?
                };
            }
        }

        query
    }};
}

struct Corpus {
    fixture_root: PathBuf,
    manifest: Value,
    matrix: Value,
}

impl Corpus {
    fn load() -> Result<Self, Box<dyn Error>> {
        let fixture_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("benchmarks/fixtures/document-locators/v1");
        let manifest = read_json(&fixture_root.join("manifest.json"))?;
        let matrix = read_json(&fixture_root.join("matrix.json"))?;
        Ok(Self {
            fixture_root,
            manifest,
            matrix,
        })
    }

    fn golden_cases(&self) -> Result<&[Value], io::Error> {
        field(&self.matrix, "golden_cases")?
            .as_array()
            .map(Vec::as_slice)
            .ok_or_else(|| invalid("matrix golden_cases must be an array"))
    }

    fn region_cases(&self) -> Result<&[Value], io::Error> {
        field(&self.matrix, "region_cases")?
            .as_array()
            .map(Vec::as_slice)
            .ok_or_else(|| invalid("matrix region_cases must be an array"))
    }

    fn document(&self, case: &Value) -> Result<ys::Document, Box<dyn Error>> {
        let fixture_id = string_field(case, "fixture_id")?;
        let files = field(&self.manifest, "files")?
            .as_array()
            .ok_or_else(|| invalid("manifest files must be an array"))?;
        let file = files
            .iter()
            .find(|file| file.get("id").and_then(Value::as_str) == Some(fixture_id))
            .ok_or_else(|| invalid(format!("manifest has no fixture {fixture_id}")))?;
        let relative_path = string_field(file, "path")?;
        let bytes = fs::read(self.fixture_root.join(relative_path))?;
        let document = match string_field(case, "document_kind")? {
            "html" => ys::Document::html(fixture_id, bytes)?,
            "xml" => ys::Document::xml(fixture_id, bytes)?,
            "json" => ys::Document::json(fixture_id, bytes)?,
            "text" => ys::Document::text(fixture_id, bytes)?,
            "dom" => ys::Document::rendered_dom(fixture_id, document_epoch(&bytes)?, bytes)?,
            "ax" => ys::Document::accessibility_tree(fixture_id, document_epoch(&bytes)?, bytes)?,
            kind => return Err(invalid(format!("unsupported matrix document kind {kind}")).into()),
        };
        Ok(document)
    }

    fn case_for_kind(&self, document_kind: &str) -> Result<&Value, io::Error> {
        self.golden_cases()?
            .iter()
            .find(|case| case.get("document_kind").and_then(Value::as_str) == Some(document_kind))
            .ok_or_else(|| invalid(format!("matrix has no golden case for {document_kind}")))
    }

    fn xml_namespace_case(&self) -> Result<&Value, io::Error> {
        let cases = field(&self.matrix, "advanced_cases")?
            .as_array()
            .ok_or_else(|| invalid("matrix advanced_cases must be an array"))?;
        cases
            .iter()
            .find(|case| {
                case.get("document_kind").and_then(Value::as_str) == Some("xml")
                    && case
                        .get("locator")
                        .and_then(|locator| locator.get("namespace_bindings"))
                        .and_then(Value::as_object)
                        .is_some_and(|bindings| !bindings.is_empty())
            })
            .ok_or_else(|| invalid("matrix has no XML locator with namespace bindings"))
    }
}

#[test]
fn public_sdk_matches_every_golden_document_case() -> Result<(), Box<dyn Error>> {
    let corpus = Corpus::load()?;

    for case in corpus.golden_cases()? {
        let document = corpus.document(case)?;
        let plan = plan_for_case(case)?;
        let outcome = document.locate(&plan);
        assert_case_matches_authority(case, &document, &outcome)?;
    }

    Ok(())
}

#[test]
fn public_sdk_preserves_region_lineage_and_global_order() -> Result<(), Box<dyn Error>> {
    let corpus = Corpus::load()?;
    let case = corpus
        .region_cases()?
        .first()
        .ok_or_else(|| invalid("matrix has no region case"))?;
    let document = corpus.document(case)?;
    let plan = plan_for_region_case(case)?;
    let outcome = document.locate(&plan);

    assert_region_case_matches_authority(case, &document, &outcome)
}

#[test]
fn public_sdk_rejects_cross_representation_plans() -> Result<(), Box<dyn Error>> {
    let corpus = Corpus::load()?;
    let html_case = corpus.case_for_kind("html")?;
    let json_case = corpus.case_for_kind("json")?;

    let mixed = ys::Plan::new([
        ys::output("html_title", ys::css("h1")?.text())?,
        ys::output("json_value", ys::json_pointer("/price")?.value())?,
    ]);
    assert!(
        mixed.is_err(),
        "mixed HTML and JSON outputs unexpectedly formed a plan"
    );

    let html_plan = plan_for_case(html_case)?;
    let json_document = corpus.document(json_case)?;
    assert!(matches!(
        json_document.locate(&html_plan),
        ys::LocateOutcome::Failed {
            failure: ys::LocateFailure::UnsupportedCombination {
                document: ys::DocumentClass::SourceJson,
            }
        }
    ));

    assert_xml_namespace_binding_from_matrix(&corpus)?;

    Ok(())
}

fn assert_xml_namespace_binding_from_matrix(corpus: &Corpus) -> Result<(), Box<dyn Error>> {
    let case = corpus.xml_namespace_case()?;
    let locator = field(case, "locator")?;
    let expected_bindings = field(locator, "namespace_bindings")?
        .as_object()
        .ok_or_else(|| invalid("namespace_bindings must be an object"))?;
    let plan = plan_for_case(case)?;
    let wire = serde_json::to_value(&plan)?;
    let actual_bindings = wire
        .pointer("/outputs/0/query/namespace_bindings")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid("serialized XML plan has no namespace_bindings array"))?;
    assert_eq!(actual_bindings.len(), expected_bindings.len());
    for binding in actual_bindings {
        assert_eq!(
            expected_bindings
                .get(string_field(binding, "prefix")?)
                .and_then(Value::as_str),
            Some(string_field(binding, "namespace_uri")?)
        );
    }

    let document = ys::Document::xml(
        "namespace.xml",
        br#"<rfc-index xmlns='https://www.rfc-editor.org/rfc-index'><bcp-entry><doc-id>RFC TEST</doc-id></bcp-entry></rfc-index>"#.to_vec(),
    )?;
    let ys::LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(invalid("namespace-aware XML plan did not match the inline document").into());
    };
    assert_eq!(result.findings().len(), 1);
    let finding = result
        .findings()
        .first()
        .ok_or_else(|| invalid("namespace-aware XML result has no finding"))?;
    assert!(matches!(
        finding.value(),
        ys::ProjectedValue::Text(value) if value == "RFC TEST"
    ));

    Ok(())
}

fn read_json(path: &Path) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn document_epoch(bytes: &[u8]) -> Result<ys::DocumentEpoch, Box<dyn Error>> {
    let wire: Value = serde_json::from_slice(bytes)?;
    let epoch = field(&wire, "document_epoch")?
        .as_u64()
        .ok_or_else(|| invalid("document_epoch must be an unsigned integer"))?;
    Ok(ys::DocumentEpoch::try_from(epoch)?)
}

fn plan_for_case(case: &Value) -> Result<ys::Plan, Box<dyn Error>> {
    let document_kind = string_field(case, "document_kind")?;
    let query = matrix_query!(case, document_kind);
    let projection = field(case, "projection")?;
    let output_plan = match string_field(projection, "kind")? {
        "text" | "matched_text" | "accessibility_text" => query.text(),
        "attribute" => query.attribute(string_field(projection, "name")?)?,
        "json_value" => query.value(),
        "node_reference" => query.node(),
        "accessible_name" => query.name(),
        "matched_text_with_captures" => {
            let names = field(projection, "names")?
                .as_array()
                .ok_or_else(|| invalid("capture names must be an array"))?;
            let names = names
                .iter()
                .map(|name| {
                    name.as_str()
                        .map(str::to_owned)
                        .ok_or_else(|| invalid("capture name must be a string"))
                })
                .collect::<Result<Vec<_>, _>>()?;
            query.captures(names)?
        }
        kind => return Err(invalid(format!("unsupported matrix projection kind {kind}")).into()),
    };
    let output_id = case
        .get("output_id")
        .and_then(Value::as_str)
        .or_else(|| case.get("id").and_then(Value::as_str))
        .ok_or_else(|| invalid("matrix case has no output id or case id"))?;
    Ok(ys::Plan::new([ys::output(output_id, output_plan)?])?)
}

fn plan_for_region_case(case: &Value) -> Result<ys::Plan, Box<dyn Error>> {
    let document_kind = string_field(case, "document_kind")?;
    let region_spec = field(case, "region")?;
    let region_query = matrix_query!(region_spec, document_kind);
    let region = region_query.each_as_region(string_field(region_spec, "id")?)?;
    let output_cases = field(case, "outputs")?
        .as_array()
        .ok_or_else(|| invalid("region outputs must be an array"))?;
    let mut named_outputs = Vec::with_capacity(output_cases.len());

    for output_case in output_cases {
        let query = matrix_query!(output_case, document_kind);
        let selection = region.find(query);
        let projection = field(output_case, "projection")?;
        let output_plan = match string_field(projection, "kind")? {
            "text" | "matched_text" | "accessibility_text" => selection.text(),
            "attribute" => selection.attribute(string_field(projection, "name")?)?,
            "json_value" => selection.value(),
            "node_reference" => selection.node(),
            "accessible_name" => selection.name(),
            "matched_text_with_captures" => {
                let names = field(projection, "names")?
                    .as_array()
                    .ok_or_else(|| invalid("capture names must be an array"))?;
                let names = names
                    .iter()
                    .map(|name| {
                        name.as_str()
                            .map(str::to_owned)
                            .ok_or_else(|| invalid("capture name must be a string"))
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                selection.captures(names)?
            }
            kind => {
                return Err(invalid(format!("unsupported region projection kind {kind}")).into());
            }
        };
        named_outputs.push(ys::output(
            string_field(output_case, "output_id")?,
            output_plan,
        )?);
    }

    Ok(ys::Plan::new(named_outputs)?)
}

fn assert_region_case_matches_authority(
    case: &Value,
    document: &ys::Document,
    outcome: &ys::LocateOutcome,
) -> Result<(), Box<dyn Error>> {
    let case_id = string_field(case, "id")?;
    let ys::LocateOutcome::Matched { result } = outcome else {
        return Err(invalid(format!(
            "region case {case_id} did not produce matches: {outcome:?}"
        ))
        .into());
    };
    assert_eq!(result.document_id().as_str(), document.id().as_str());

    let outputs = field(case, "outputs")?
        .as_array()
        .ok_or_else(|| invalid("region outputs must be an array"))?;
    let mut global_order = 0_u64;
    let mut region_ordinals = BTreeSet::new();
    for output_case in outputs {
        let output_id = string_field(output_case, "output_id")?;
        let expected = field(output_case, "expected")?;
        let expected_matches = field(expected, "matches")?
            .as_array()
            .ok_or_else(|| invalid("region expected matches must be an array"))?;
        assert_eq!(
            u64::try_from(expected_matches.len())?,
            integer_field(expected, "match_count")?,
            "region case {case_id} output {output_id} authority count"
        );

        for expected_match in expected_matches {
            let index = usize::try_from(global_order)?;
            let finding = result
                .findings()
                .get(index)
                .ok_or_else(|| invalid(format!("region case {case_id} has too few findings")))?;
            assert_eq!(
                finding.output_id().as_str(),
                output_id,
                "region case {case_id}"
            );
            assert_eq!(finding.order(), global_order, "region case {case_id}");
            assert_projected_value(output_case, document, finding, expected_match)?;
            assert_coordinate(finding.coordinate(), field(expected_match, "coordinate")?)?;

            let expected_region = field(expected_match, "parent_region")?;
            let actual_region = finding
                .parent_region()
                .ok_or_else(|| invalid("region finding has no parent lineage"))?;
            assert_eq!(
                actual_region.region_id().as_str(),
                string_field(expected_region, "id")?
            );
            assert_eq!(
                actual_region.region_ordinal(),
                integer_field(expected_region, "ordinal")?
            );
            region_ordinals.insert(actual_region.region_ordinal());
            assert_coordinate(
                actual_region.coordinate(),
                field(expected_region, "coordinate")?,
            )?;
            global_order = global_order
                .checked_add(1)
                .ok_or_else(|| invalid("region global order overflowed"))?;
        }
    }

    assert_eq!(
        u64::try_from(result.findings().len())?,
        global_order,
        "region case {case_id} returned unexpected findings"
    );
    assert_eq!(
        u64::try_from(region_ordinals.len())?,
        integer_field(case, "expected_region_count")?,
        "region case {case_id} region count"
    );
    Ok(())
}

fn assert_case_matches_authority(
    case: &Value,
    document: &ys::Document,
    outcome: &ys::LocateOutcome,
) -> Result<(), Box<dyn Error>> {
    let case_id = string_field(case, "id")?;
    let expected = field(case, "expected")?;
    let expected_match_count = field(expected, "match_count")?
        .as_u64()
        .ok_or_else(|| invalid("expected match_count must be an unsigned integer"))?;
    let expected_matches = field(expected, "matches")?
        .as_array()
        .ok_or_else(|| invalid("expected matches must be an array"))?;
    assert_eq!(
        u64::try_from(expected_matches.len())?,
        expected_match_count,
        "case {case_id} authority match list disagrees with match_count"
    );

    let ys::LocateOutcome::Matched { result } = outcome else {
        return Err(invalid(format!(
            "case {case_id} did not produce matches: {outcome:?}"
        ))
        .into());
    };
    assert_eq!(
        u64::try_from(result.findings().len())?,
        expected_match_count,
        "case {case_id} match_count"
    );
    assert_eq!(result.document_id().as_str(), document.id().as_str());

    let output_id = case
        .get("output_id")
        .and_then(Value::as_str)
        .or_else(|| case.get("id").and_then(Value::as_str))
        .ok_or_else(|| invalid(format!("case {case_id} has no output id")))?;

    for (ordinal, (finding, expected_match)) in
        result.findings().iter().zip(expected_matches).enumerate()
    {
        assert_eq!(finding.output_id().as_str(), output_id, "case {case_id}");
        assert_eq!(
            finding.order(),
            u64::try_from(ordinal)?,
            "case {case_id} order"
        );
        assert_projected_value(case, document, finding, expected_match)?;
        assert_coordinate(finding.coordinate(), field(expected_match, "coordinate")?)?;
        if let Some(expected_completeness) = expected.get("completeness") {
            assert_eq!(
                serde_json::to_value(finding.completeness())?,
                *expected_completeness,
                "case {case_id} completeness"
            );
        }
    }

    Ok(())
}

fn assert_projected_value(
    case: &Value,
    document: &ys::Document,
    finding: &ys::Finding,
    expected_match: &Value,
) -> Result<(), Box<dyn Error>> {
    let expected_value = field(expected_match, "value")?;
    let projection = field(case, "projection")?;
    match string_field(projection, "kind")? {
        "text" | "matched_text" | "accessible_name" | "accessibility_text" => {
            let ys::ProjectedValue::Text(actual) = finding.value() else {
                return Err(invalid("text projection returned a non-text value").into());
            };
            assert_eq!(Some(actual.as_str()), expected_value.as_str());
        }
        "attribute" => {
            let ys::ProjectedValue::Attribute { name, value } = finding.value() else {
                return Err(invalid("attribute projection returned a different value kind").into());
            };
            assert_eq!(name, string_field(projection, "name")?);
            assert_eq!(Some(value.as_str()), expected_value.as_str());
        }
        "json_value" => {
            let ys::ProjectedValue::Json(actual) = finding.value() else {
                return Err(invalid("JSON projection returned a different value kind").into());
            };
            assert_eq!(actual, expected_value);
        }
        "node_reference" => {
            let ys::ProjectedValue::Node(reference) = finding.value() else {
                return Err(
                    invalid("node-reference projection returned a different value kind").into(),
                );
            };
            assert_eq!(reference.document_id().as_str(), document.id().as_str());
            assert_eq!(reference.coordinate(), finding.coordinate());
            assert_node_identity(
                reference.coordinate(),
                expected_value,
                field(expected_match, "coordinate")?,
            )?;
        }
        "matched_text_with_captures" => {
            let ys::ProjectedValue::TextWithCaptures { text, captures } = finding.value() else {
                return Err(invalid("capture projection returned a different value kind").into());
            };
            assert_eq!(Some(text.as_str()), field(expected_value, "text")?.as_str());
            assert_eq!(
                serde_json::to_value(captures)?,
                *field(expected_value, "captures")?
            );
        }
        kind => return Err(invalid(format!("unsupported expected projection kind {kind}")).into()),
    }
    Ok(())
}

fn assert_node_identity(
    coordinate: &ys::NativeCoordinate,
    expected_value: &Value,
    expected_coordinate: &Value,
) -> Result<(), Box<dyn Error>> {
    match coordinate {
        ys::NativeCoordinate::SourceTree(tree) => {
            if let Some(expected_path) = expected_value.get("path") {
                assert_eq!(expected_path, field(expected_coordinate, "path")?);
            }
            if string_field(expected_coordinate, "kind")? == "source_tree_path" {
                assert_eq!(
                    serde_json::to_value(tree.child_path())?,
                    *field(expected_coordinate, "child_path")?
                );
            }
        }
        ys::NativeCoordinate::RenderedDom(actual) => {
            assert_eq!(
                actual.document_epoch().get(),
                field(expected_value, "document_epoch")?
                    .as_u64()
                    .ok_or_else(|| invalid("node reference epoch must be an unsigned integer"))?
            );
            assert_eq!(
                actual.node_id().get(),
                field(expected_value, "node_id")?
                    .as_u64()
                    .ok_or_else(|| invalid("DOM node id must be an unsigned integer"))?
            );
        }
        ys::NativeCoordinate::Accessibility(actual) => {
            assert_eq!(
                actual.document_epoch().get(),
                field(expected_value, "document_epoch")?
                    .as_u64()
                    .ok_or_else(|| invalid("node reference epoch must be an unsigned integer"))?
            );
            assert_eq!(actual.node_id(), string_field(expected_value, "node_id")?);
        }
        _ => {
            return Err(
                invalid("matrix node reference uses an unsupported coordinate kind").into(),
            );
        }
    }
    Ok(())
}

fn assert_coordinate(
    actual: &ys::NativeCoordinate,
    expected: &Value,
) -> Result<(), Box<dyn Error>> {
    let coordinate_kind = expected.get("kind").and_then(Value::as_str);
    match actual {
        ys::NativeCoordinate::SourceTree(tree) => match coordinate_kind {
            Some("source_tree_path") => {
                assert_eq!(
                    serde_json::to_value(tree.child_path())?,
                    *field(expected, "child_path")?
                );
            }
            Some("source_byte_range") => {
                let source_bytes = tree
                    .source_bytes()
                    .ok_or_else(|| invalid("XML coordinate has no source byte range"))?;
                assert_eq!(source_bytes.start(), integer_field(expected, "start")?);
                assert_eq!(source_bytes.end(), integer_field(expected, "end")?);
                let path = xml_coordinate_path(tree)?;
                assert_eq!(path, string_field(expected, "path")?);
            }
            kind => {
                return Err(
                    invalid(format!("unexpected source-tree coordinate kind {kind:?}")).into(),
                );
            }
        },
        ys::NativeCoordinate::Json(coordinate) => {
            assert_eq!(coordinate_kind, Some("json_pointer"));
            assert_eq!(coordinate.as_pointer(), string_field(expected, "pointer")?);
        }
        ys::NativeCoordinate::RenderedDom(coordinate) => {
            assert_eq!(
                coordinate.document_epoch().get(),
                integer_field(expected, "document_epoch")?
            );
            assert_eq!(
                coordinate.node_id().get(),
                integer_field(expected, "node_id")?
            );
        }
        ys::NativeCoordinate::Accessibility(coordinate) => {
            assert_eq!(coordinate_kind, Some("document_node"));
            assert_eq!(
                coordinate.document_epoch().get(),
                integer_field(expected, "document_epoch")?
            );
            assert_eq!(coordinate.node_id(), string_field(expected, "node_id")?);
        }
        ys::NativeCoordinate::DecodedText(coordinate) => {
            assert_eq!(coordinate_kind, Some("decoded_text_byte_range"));
            let byte_range = coordinate.byte_range();
            let scalar_range = coordinate.scalar_range();
            assert_eq!(byte_range.start(), integer_field(expected, "start")?);
            assert_eq!(byte_range.end(), integer_field(expected, "end")?);
            assert_eq!(
                scalar_range.start(),
                integer_field(expected, "scalar_start")?
            );
            assert_eq!(scalar_range.end(), integer_field(expected, "scalar_end")?);
        }
    }
    Ok(())
}

fn xml_coordinate_path(coordinate: &ys::TreeCoordinate) -> Result<String, io::Error> {
    let segments = coordinate
        .expanded_name_path()
        .ok_or_else(|| invalid("XML coordinate has no expanded-name path"))?;
    let mut path = String::new();
    for segment in segments {
        path.push('/');
        if let Some(namespace_uri) = segment.namespace_uri().filter(|uri| !uri.is_empty()) {
            path.push('{');
            path.push_str(namespace_uri);
            path.push('}');
        }
        path.push_str(segment.local_name());
        write!(&mut path, "[{}]", segment.same_name_sibling_index())
            .map_err(|_| invalid("could not format XML coordinate path"))?;
    }
    Ok(path)
}

fn field<'a>(value: &'a Value, name: &str) -> Result<&'a Value, io::Error> {
    value
        .get(name)
        .ok_or_else(|| invalid(format!("authority object is missing {name}")))
}

fn string_field<'a>(value: &'a Value, name: &str) -> Result<&'a str, io::Error> {
    field(value, name)?
        .as_str()
        .ok_or_else(|| invalid(format!("authority field {name} must be a string")))
}

fn integer_field(value: &Value, name: &str) -> Result<u64, io::Error> {
    field(value, name)?.as_u64().ok_or_else(|| {
        invalid(format!(
            "authority field {name} must be an unsigned integer"
        ))
    })
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}
