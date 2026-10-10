//! Emit exact JSON wire fixtures from the public Rust SDK's actual Serde types.
//!
//! Build with `cargo build -p yosoi --example python_serde_conformance`. Every
//! input is authored or constructed in Rust. The Python runner only consumes
//! this output; it never sends Python-created values back into this fixture.

use std::{
    collections::BTreeMap,
    error::Error,
    io::{self, Write},
};

use serde::{Serialize, de::DeserializeOwned};
use serde_json::{Value, json};
use yosoi::{
    CountLimit, DocumentId, Policy, StepLimit,
    contracts::{Money, RuntimeFieldValue, RuntimeValue},
    documents::DocumentEpoch,
    locators::{
        AccessibilityCoordinate, ByteRange, DecodedTextCoordinate, DomCoordinate, DomNodeId,
        ExpandedNamePathSegment, JsonCoordinate, NamespaceBinding, NativeCoordinate, NodeReference,
        ProjectedValue, QueryAtom, QueryResultShape, QuerySpec, TextRange, TreeCoordinate,
    },
    map::{LimitReached, MapTermination},
    policy::{
        AddressableByteLimit, BrowserLimits, DirectHttpRedirects, Documents, EventLimit, Filters,
        Limits, Locators, Map, MaximumElapsed, Page, RedirectHopLimit, Request, Scope,
        SourceLimits, Tuning, search::Search,
    },
};

fn json_path<'a>(value: &'a Value, path: &str) -> Option<&'a Value> {
    let mut current = value;
    for part in path.split('.') {
        current = if let Some(object) = current.as_object() {
            object.get(part)?
        } else if let (Some(array), Ok(index)) = (current.as_array(), part.parse::<usize>()) {
            array.get(index)?
        } else {
            return None;
        };
    }
    Some(current)
}

fn shape_passes(value: &Value, expectation: &Value) -> bool {
    let null_paths = expectation
        .get("nullPaths")
        .and_then(Value::as_array)
        .map_or(&[][..], Vec::as_slice);
    let absent_paths = expectation
        .get("absentPaths")
        .and_then(Value::as_array)
        .map_or(&[][..], Vec::as_slice);
    null_paths.iter().all(|path| {
        path.as_str()
            .and_then(|path| json_path(value, path))
            .is_some_and(Value::is_null)
    }) && absent_paths.iter().all(|path| {
        path.as_str()
            .is_some_and(|path| json_path(value, path).is_none())
    })
}

struct CaseMetadata<'a> {
    name: &'a str,
    rust_type: &'a str,
    construction: &'a str,
    wire_input: Option<Value>,
    rust_output: Value,
    decoder_supported: bool,
    round_trip_passed: Option<bool>,
    operation: Option<Value>,
    shape_expectations: Value,
}

fn finish_case(metadata: CaseMetadata<'_>) -> Value {
    let CaseMetadata {
        name,
        rust_type,
        construction,
        wire_input,
        rust_output,
        decoder_supported,
        round_trip_passed,
        operation,
        shape_expectations,
    } = metadata;
    let rust_shape_passed = shape_passes(&rust_output, &shape_expectations);
    let fixture_passed = rust_shape_passed && round_trip_passed != Some(false);
    json!({
        "name": name,
        "rust_type": rust_type,
        "construction": construction,
        "input_source": "rust",
        "wire_input_available": wire_input.is_some(),
        "wire_input": wire_input,
        "rust_output": rust_output,
        "decoder_supported": decoder_supported,
        "round_trip_passed": round_trip_passed,
        "operation": operation,
        "shape_expectations": shape_expectations,
        "rust_shape_passed": rust_shape_passed,
        "fixture_passed": fixture_passed,
    })
}

fn round_trip_passed<T: Serialize + DeserializeOwned>(rust_output: &Value) -> bool {
    serde_json::from_value::<T>(rust_output.clone()).is_ok_and(|round_tripped| {
        serde_json::to_value(round_tripped).is_ok_and(|value| value.eq(rust_output))
    })
}

fn typed_case<T>(
    name: &str,
    rust_type: &str,
    construction: &str,
    wire_input: Value,
    operation: Option<Value>,
    shape_expectations: Value,
) -> Result<Value, Box<dyn Error>>
where
    T: Serialize + DeserializeOwned,
{
    let decoded = serde_json::from_value::<T>(wire_input.clone())?;
    let rust_output = serde_json::to_value(&decoded)?;
    let round_trip_passed = round_trip_passed::<T>(&rust_output);
    Ok(finish_case(CaseMetadata {
        name,
        rust_type,
        construction,
        wire_input: Some(wire_input),
        rust_output,
        decoder_supported: true,
        round_trip_passed: Some(round_trip_passed),
        operation,
        shape_expectations,
    }))
}

fn constructed_case<T>(
    name: &str,
    rust_type: &str,
    construction: &str,
    value: T,
    shape_expectations: Value,
) -> Result<Value, Box<dyn Error>>
where
    T: Serialize + DeserializeOwned,
{
    let wire_input = serde_json::to_value(value)?;
    typed_case::<T>(
        name,
        rust_type,
        construction,
        wire_input,
        None,
        shape_expectations,
    )
}

fn transformed_case<T, F>(
    name: &str,
    rust_type: &str,
    construction: &str,
    value: T,
    operation: Value,
    transform: F,
    shape_expectations: Value,
) -> Result<Value, Box<dyn Error>>
where
    T: Serialize + DeserializeOwned,
    F: FnOnce(T) -> Result<T, Box<dyn Error>>,
{
    let wire_input = serde_json::to_value(value)?;
    let decoded = serde_json::from_value::<T>(wire_input.clone())?;
    let transformed = transform(decoded)?;
    let rust_output = serde_json::to_value(&transformed)?;
    let round_trip_passed = round_trip_passed::<T>(&rust_output);
    Ok(finish_case(CaseMetadata {
        name,
        rust_type,
        construction,
        wire_input: Some(wire_input),
        rust_output,
        decoder_supported: true,
        round_trip_passed: Some(round_trip_passed),
        operation: Some(operation),
        shape_expectations,
    }))
}

fn transformed_wire_case<T, F>(
    name: &str,
    rust_type: &str,
    construction: &str,
    wire_input: Value,
    operation: Value,
    transform: F,
    shape_expectations: Value,
) -> Result<Value, Box<dyn Error>>
where
    T: Serialize + DeserializeOwned,
    F: FnOnce(T) -> Result<T, Box<dyn Error>>,
{
    let decoded = serde_json::from_value::<T>(wire_input.clone())?;
    let transformed = transform(decoded)?;
    let rust_output = serde_json::to_value(&transformed)?;
    let round_trip_passed = round_trip_passed::<T>(&rust_output);
    Ok(finish_case(CaseMetadata {
        name,
        rust_type,
        construction,
        wire_input: Some(wire_input),
        rust_output,
        decoder_supported: true,
        round_trip_passed: Some(round_trip_passed),
        operation: Some(operation),
        shape_expectations,
    }))
}

fn serialize_only_case<T: Serialize>(
    name: &str,
    rust_type: &str,
    construction: &str,
    value: T,
    shape_expectations: Value,
) -> Result<Value, Box<dyn Error>> {
    let rust_output = serde_json::to_value(value)?;
    Ok(finish_case(CaseMetadata {
        name,
        rust_type,
        construction,
        wire_input: None,
        rust_output,
        decoder_supported: false,
        round_trip_passed: None,
        operation: None,
        shape_expectations,
    }))
}

fn default_case<T>(
    output: &mut Vec<Value>,
    name: &str,
    rust_type: &str,
) -> Result<(), Box<dyn Error>>
where
    T: Default + Serialize + DeserializeOwned,
{
    output.push(constructed_case(
        name,
        rust_type,
        "Rust Default::default",
        T::default(),
        json!({}),
    )?);
    Ok(())
}

fn build_fixtures() -> Result<Vec<Value>, Box<dyn Error>> {
    let mut output = Vec::new();

    // Seventeen public policy defaults. The nested cases each exercise the
    // direct Rust type and its own Python model, in addition to Policy itself.
    default_case::<Policy>(&mut output, "default-policy", "yosoi::Policy")?;
    default_case::<Page>(&mut output, "default-policy-page", "yosoi::policy::Page")?;
    default_case::<Request>(
        &mut output,
        "default-policy-request",
        "yosoi::policy::Request",
    )?;
    default_case::<SourceLimits>(
        &mut output,
        "default-source-limits",
        "yosoi::policy::SourceLimits",
    )?;
    default_case::<BrowserLimits>(
        &mut output,
        "default-browser-limits",
        "yosoi::policy::BrowserLimits",
    )?;
    default_case::<DirectHttpRedirects>(
        &mut output,
        "default-direct-http-redirects",
        "yosoi::policy::DirectHttpRedirects",
    )?;
    default_case::<Documents>(
        &mut output,
        "default-policy-documents",
        "yosoi::policy::Documents",
    )?;
    default_case::<Locators>(
        &mut output,
        "default-policy-locators",
        "yosoi::policy::Locators",
    )?;
    default_case::<Map>(&mut output, "default-policy-map", "yosoi::policy::Map")?;
    default_case::<Limits>(&mut output, "default-map-limits", "yosoi::policy::Limits")?;
    default_case::<Filters>(&mut output, "default-map-filters", "yosoi::policy::Filters")?;
    default_case::<Scope>(&mut output, "default-map-scope", "yosoi::policy::Scope")?;
    default_case::<Tuning>(
        &mut output,
        "default-policy-tuning",
        "yosoi::policy::Tuning",
    )?;
    default_case::<Search>(
        &mut output,
        "default-policy-search",
        "yosoi::policy::search::Search",
    )?;
    default_case::<EventLimit>(
        &mut output,
        "default-event-limit",
        "yosoi::policy::EventLimit",
    )?;
    let maximum_elapsed = MaximumElapsed::default();
    let elapsed_microseconds = maximum_elapsed.as_microseconds();
    let mut maximum_elapsed_case = constructed_case(
        "default-maximum-elapsed",
        "yosoi::policy::MaximumElapsed",
        "Rust Default::default",
        maximum_elapsed,
        json!({}),
    )?;
    let unit_observation = json!({
        "name": "MaximumElapsed.as_microseconds",
        "rust_result": elapsed_microseconds
    });
    maximum_elapsed_case
        .as_object_mut()
        .ok_or_else(|| io::Error::other("MaximumElapsed fixture must be an object"))?
        .insert("unit_observation".to_owned(), unit_observation);
    output.push(maximum_elapsed_case);
    default_case::<RedirectHopLimit>(
        &mut output,
        "default-redirect-hop-limit",
        "yosoi::policy::RedirectHopLimit",
    )?;

    output.push(constructed_case(
        "count-limit-try-from",
        "yosoi::CountLimit",
        "Rust TryFrom<u64>",
        CountLimit::try_from(17_u64)?,
        json!({}),
    )?);
    output.push(constructed_case(
        "step-limit-try-from",
        "yosoi::StepLimit",
        "Rust TryFrom<u32>",
        StepLimit::try_from(9_u32)?,
        json!({}),
    )?);
    output.push(constructed_case(
        "addressable-byte-limit-try-from",
        "yosoi::policy::AddressableByteLimit",
        "Rust TryFrom<u64>",
        AddressableByteLimit::try_from(2048_u64)?,
        json!({}),
    )?);
    output.push(constructed_case(
        "document-id-try-new",
        "yosoi::DocumentId",
        "Rust DocumentId::try_new",
        DocumentId::try_new("serde-conformance-document")?,
        json!({}),
    )?);
    output.push(constructed_case(
        "document-epoch-try-from",
        "yosoi::documents::DocumentEpoch",
        "Rust TryFrom<u64>",
        DocumentEpoch::try_from(11_u64)?,
        json!({}),
    )?);
    output.push(constructed_case(
        "dom-node-id-try-new",
        "yosoi::locators::DomNodeId",
        "Rust DomNodeId::try_new",
        DomNodeId::try_new(15_u64)?,
        json!({}),
    )?);

    let css_atom = QueryAtom::Css("title".to_owned());
    output.push(constructed_case(
        "query-atom-css",
        "yosoi::locators::QueryAtom",
        "Rust QueryAtom::Css",
        css_atom.clone(),
        json!({}),
    )?);
    output.push(constructed_case(
        "query-result-shape-tree-nodes",
        "yosoi::locators::QueryResultShape",
        "Rust QueryResultShape::TreeNodes",
        QueryResultShape::TreeNodes,
        json!({}),
    )?);
    let query_new_input = json!({
        "atom": {"kind": "css", "value": "title"},
        "result_shape": "tree_nodes"
    });
    output.push(transformed_wire_case::<QuerySpec, _>(
        "query-spec-new",
        "yosoi::locators::QuerySpec",
        "Rust QuerySpec::new from Rust-authored atom and result-shape JSON",
        query_new_input.clone(),
        json!({
            "name": "QuerySpec.new",
            "rustArguments": query_new_input,
            "pythonArguments": query_new_input
        }),
        |spec| Ok(QuerySpec::new(spec.atom().clone(), spec.result_shape())),
        json!({"absentPaths": ["namespace_bindings"]}),
    )?);
    let namespace_prefix = "t";
    let namespace_uri = "urn:test";
    output.push(transformed_case(
        "query-spec-with-namespace",
        "yosoi::locators::QuerySpec",
        "Rust QuerySpec::new then QuerySpec::with_namespace",
        QuerySpec::new(css_atom, QueryResultShape::TreeNodes),
        json!({
            "name": "QuerySpec.with_namespace",
            "rustArguments": {
                "prefix": namespace_prefix,
                "namespace_uri": namespace_uri
            },
            "pythonArguments": {"prefix": namespace_prefix, "uri": namespace_uri}
        }),
        |spec| {
            spec.with_namespace(namespace_prefix, namespace_uri)
                .map_err(Box::<dyn Error>::from)
        },
        json!({}),
    )?);
    output.push(typed_case::<NamespaceBinding>(
        "namespace-binding-from-rust-authored-wire",
        "yosoi::locators::NamespaceBinding",
        "Rust serde_json::from_value on Rust-authored JSON",
        json!({"prefix": "t", "namespace_uri": "urn:test"}),
        None,
        json!({}),
    )?);

    let absent_path_tree = TreeCoordinate::try_new(vec![1], None)?;
    output.push(constructed_case(
        "tree-coordinate-null-source-and-omitted-expanded-path",
        "yosoi::locators::TreeCoordinate",
        "Rust TreeCoordinate::try_new",
        absent_path_tree,
        json!({
            "nullPaths": ["source_bytes"],
            "absentPaths": ["expanded_name_path"]
        }),
    )?);
    let segment = ExpandedNamePathSegment::try_new(None, "title", 1)?;
    output.push(constructed_case(
        "expanded-name-segment-present-null-namespace",
        "yosoi::locators::ExpandedNamePathSegment",
        "Rust ExpandedNamePathSegment::try_new",
        segment.clone(),
        json!({"nullPaths": ["namespace_uri"]}),
    )?);
    let expanded_tree = TreeCoordinate::with_expanded_name_path(vec![1, 2], None, vec![segment])?;
    output.push(constructed_case(
        "tree-coordinate-expanded-name-path",
        "yosoi::locators::TreeCoordinate",
        "Rust TreeCoordinate::with_expanded_name_path",
        expanded_tree,
        json!({"nullPaths": ["source_bytes", "expanded_name_path.0.namespace_uri"]}),
    )?);
    output.push(constructed_case(
        "byte-range-try-new",
        "yosoi::locators::ByteRange",
        "Rust ByteRange::try_new",
        ByteRange::try_new(4, 9)?,
        json!({}),
    )?);
    output.push(constructed_case(
        "text-range-try-new",
        "yosoi::locators::TextRange",
        "Rust TextRange::try_new",
        TextRange::try_new(2, 5)?,
        json!({}),
    )?);

    let epoch = DocumentEpoch::try_from(23_u64)?;
    let byte_range = ByteRange::try_new(4, 9)?;
    let text_range = TextRange::try_new(2, 5)?;
    let source_tree = TreeCoordinate::try_new(vec![1, 2], Some(byte_range))?;
    let json_coordinate = JsonCoordinate::try_new("/title")?;
    let dom_coordinate = DomCoordinate::new(epoch, DomNodeId::try_new(15_u64)?);
    let accessibility_coordinate = AccessibilityCoordinate::try_new(epoch, "ax-23")?;
    let decoded_text_coordinate = DecodedTextCoordinate::new(byte_range, text_range);

    output.push(constructed_case(
        "native-coordinate-source-tree",
        "yosoi::locators::NativeCoordinate",
        "Rust NativeCoordinate::SourceTree",
        NativeCoordinate::SourceTree(source_tree.clone()),
        json!({}),
    )?);
    output.push(constructed_case(
        "native-coordinate-json",
        "yosoi::locators::NativeCoordinate",
        "Rust NativeCoordinate::Json",
        NativeCoordinate::Json(json_coordinate.clone()),
        json!({}),
    )?);
    output.push(constructed_case(
        "native-coordinate-rendered-dom",
        "yosoi::locators::NativeCoordinate",
        "Rust NativeCoordinate::RenderedDom",
        NativeCoordinate::RenderedDom(dom_coordinate),
        json!({}),
    )?);
    output.push(constructed_case(
        "native-coordinate-accessibility",
        "yosoi::locators::NativeCoordinate",
        "Rust NativeCoordinate::Accessibility",
        NativeCoordinate::Accessibility(accessibility_coordinate.clone()),
        json!({}),
    )?);
    output.push(constructed_case(
        "native-coordinate-decoded-text",
        "yosoi::locators::NativeCoordinate",
        "Rust NativeCoordinate::DecodedText",
        NativeCoordinate::DecodedText(decoded_text_coordinate),
        json!({}),
    )?);
    output.push(constructed_case(
        "json-coordinate-try-new",
        "yosoi::locators::JsonCoordinate",
        "Rust JsonCoordinate::try_new",
        json_coordinate,
        json!({}),
    )?);
    output.push(constructed_case(
        "dom-coordinate-new",
        "yosoi::locators::DomCoordinate",
        "Rust DomCoordinate::new",
        DomCoordinate::new(epoch, DomNodeId::try_new(15_u64)?),
        json!({}),
    )?);
    output.push(constructed_case(
        "accessibility-coordinate-try-new",
        "yosoi::locators::AccessibilityCoordinate",
        "Rust AccessibilityCoordinate::try_new",
        accessibility_coordinate,
        json!({}),
    )?);
    output.push(constructed_case(
        "decoded-text-coordinate-new",
        "yosoi::locators::DecodedTextCoordinate",
        "Rust DecodedTextCoordinate::new",
        DecodedTextCoordinate::new(byte_range, text_range),
        json!({}),
    )?);

    let document_id = DocumentId::try_new("projected-value-document")?;
    let projected_node = NodeReference::new(document_id, NativeCoordinate::SourceTree(source_tree));
    let captures = BTreeMap::from([("word".to_owned(), "Yosoi".to_owned())]);
    let projected_values = [
        ("projected-text", ProjectedValue::Text("Yosoi".to_owned())),
        (
            "projected-text-with-captures",
            ProjectedValue::TextWithCaptures {
                text: "Yosoi".to_owned(),
                captures,
            },
        ),
        (
            "projected-attribute",
            ProjectedValue::Attribute {
                name: "title".to_owned(),
                value: "Yosoi".to_owned(),
            },
        ),
        (
            "projected-json-object-nested-nullable",
            ProjectedValue::Json(json!({
                "nullable": null,
                "enabled": true,
                "count": 7,
                "ratio": 1.25,
                "nested": {"values": [null, false, {"label": "kept"}]}
            })),
        ),
        ("projected-node", ProjectedValue::Node(projected_node)),
        ("projected-json-null", ProjectedValue::Json(Value::Null)),
        ("projected-json-bool", ProjectedValue::Json(json!(true))),
        ("projected-json-int", ProjectedValue::Json(json!(7))),
        ("projected-json-float", ProjectedValue::Json(json!(7.25))),
        (
            "projected-json-nested-nullable",
            ProjectedValue::Json(json!({"outer": {"present": null}, "items": [1, null]})),
        ),
    ];
    for (name, value) in projected_values {
        let expectations = if name == "projected-json-null" {
            json!({"nullPaths": ["value"]})
        } else {
            json!({})
        };
        output.push(constructed_case(
            name,
            "yosoi::locators::ProjectedValue",
            "Rust ProjectedValue variant constructor",
            value,
            expectations,
        )?);
    }

    let money = Money::from_archived_usd_minor_units(1299)
        .ok_or("nonnegative money fixture value did not construct")?;
    output.push(constructed_case(
        "runtime-money-usd",
        "yosoi::contracts::Money",
        "Rust Money::from_archived_usd_minor_units",
        money,
        json!({}),
    )?);
    output.push(constructed_case(
        "runtime-value-string",
        "yosoi::contracts::RuntimeValue",
        "Rust RuntimeValue::String",
        RuntimeValue::String("sample".to_owned()),
        json!({}),
    )?);
    output.push(constructed_case(
        "runtime-value-money-usd",
        "yosoi::contracts::RuntimeValue",
        "Rust RuntimeValue::MoneyUsd",
        RuntimeValue::MoneyUsd(
            Money::from_archived_usd_minor_units(1299)
                .ok_or("nonnegative money fixture value did not construct")?,
        ),
        json!({}),
    )?);
    output.push(constructed_case(
        "runtime-field-exactly-one",
        "yosoi::contracts::RuntimeFieldValue",
        "Rust RuntimeFieldValue::ExactlyOne",
        RuntimeFieldValue::ExactlyOne {
            value: RuntimeValue::String("one".to_owned()),
        },
        json!({}),
    )?);
    output.push(constructed_case(
        "runtime-field-zero-or-one-null",
        "yosoi::contracts::RuntimeFieldValue",
        "Rust RuntimeFieldValue::ZeroOrOne { value: None }",
        RuntimeFieldValue::ZeroOrOne { value: None },
        json!({"nullPaths": ["value"]}),
    )?);
    output.push(constructed_case(
        "runtime-field-many",
        "yosoi::contracts::RuntimeFieldValue",
        "Rust RuntimeFieldValue::Many",
        RuntimeFieldValue::Many {
            values: vec![
                RuntimeValue::String("many".to_owned()),
                RuntimeValue::MoneyUsd(
                    Money::from_archived_usd_minor_units(1299)
                        .ok_or("nonnegative money fixture value did not construct")?,
                ),
            ],
        },
        json!({}),
    )?);

    output.push(serialize_only_case(
        "map-termination-exhausted-unit",
        "yosoi::map::MapTermination",
        "Rust MapTermination::Exhausted (Serialize only)",
        MapTermination::Exhausted,
        json!({"absentPaths": ["value"]}),
    )?);
    output.push(serialize_only_case(
        "map-termination-limit-payload",
        "yosoi::map::MapTermination",
        "Rust MapTermination::Limit (Serialize only)",
        MapTermination::Limit(LimitReached::Urls),
        json!({}),
    )?);

    Ok(output)
}

fn main() -> Result<(), Box<dyn Error>> {
    let fixtures = build_fixtures()?;
    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());
    serde_json::to_writer(
        &mut writer,
        &json!({
            "schema_version": 1,
            "kind": "yosoi-python-rust-serde-fixtures",
            "fixtures": fixtures,
        }),
    )?;
    writeln!(writer)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::build_fixtures;
    use serde_json::Value;
    use std::collections::BTreeSet;

    #[test]
    fn fixtures_cover_public_types_and_keep_null_distinct_from_absence() {
        let fixtures = build_fixtures().expect("Rust-authored fixtures should be valid");
        let rust_types: BTreeSet<_> = fixtures
            .iter()
            .filter_map(|fixture| fixture.get("rust_type").and_then(Value::as_str))
            .collect();
        assert!(rust_types.len() >= 30, "covered {} types", rust_types.len());

        let find = |name: &str| {
            fixtures
                .iter()
                .find(|fixture| fixture.get("name").and_then(Value::as_str) == Some(name))
                .expect("fixture exists")
        };
        let tree = find("tree-coordinate-null-source-and-omitted-expanded-path");
        let tree_output = &tree["rust_output"];
        assert_eq!(tree_output.get("source_bytes"), Some(&Value::Null));
        assert!(tree_output.get("expanded_name_path").is_none());

        let nullable = find("runtime-field-zero-or-one-null");
        assert_eq!(nullable["rust_output"].get("value"), Some(&Value::Null));
        assert!(nullable["fixture_passed"].as_bool().unwrap_or(false));

        let exhausted = find("map-termination-exhausted-unit");
        assert_eq!(exhausted["decoder_supported"], false);
        assert!(exhausted["rust_output"].get("value").is_none());
    }
}
