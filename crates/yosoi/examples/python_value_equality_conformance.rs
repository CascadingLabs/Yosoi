//! Emit actual public Rust ProjectedValue equality cases for Python parity.

use std::{
    collections::BTreeMap,
    error::Error,
    io::{self, Write},
};

use serde_json::{Value, json};
use yosoi::{
    documents::DocumentId,
    locators::{ByteRange, NativeCoordinate, NodeReference, ProjectedValue, TreeCoordinate},
};

fn record_case(
    output: &mut Vec<Value>,
    name: &str,
    left: &ProjectedValue,
    right: &ProjectedValue,
    expected_eq: bool,
) -> Result<(), serde_json::Error> {
    let rust_eq = left.eq(right);
    let rust_ne = left.ne(right);
    output.push(json!({
        "name": name,
        "left": serde_json::to_value(left)?,
        "right": serde_json::to_value(right)?,
        "expected_eq": expected_eq,
        "expected_ne": !expected_eq,
        "rust_eq": rust_eq,
        "rust_ne": rust_ne,
        "fixture_passed": rust_eq == expected_eq && rust_ne != expected_eq,
    }));
    Ok(())
}

fn public_variants() -> Result<Vec<(&'static str, ProjectedValue)>, Box<dyn Error>> {
    let captures = BTreeMap::from([("word".to_owned(), "Yosoi".to_owned())]);
    let document_id = DocumentId::try_new("equality-fixture-document")?;
    let coordinate = TreeCoordinate::try_new(vec![1, 2], Some(ByteRange::try_new(4, 9)?))?;
    let node = NodeReference::new(document_id, NativeCoordinate::SourceTree(coordinate));

    Ok(vec![
        ("Text", ProjectedValue::Text("Yosoi".to_owned())),
        (
            "TextWithCaptures",
            ProjectedValue::TextWithCaptures {
                text: "Yosoi".to_owned(),
                captures,
            },
        ),
        (
            "Attribute",
            ProjectedValue::Attribute {
                name: "title".to_owned(),
                value: "Yosoi".to_owned(),
            },
        ),
        (
            "Json",
            ProjectedValue::Json(json!({"name": "Yosoi", "active": true})),
        ),
        ("Node", ProjectedValue::Node(node)),
    ])
}

fn record_json_cases(output: &mut Vec<Value>) -> Result<(), serde_json::Error> {
    let cases = [
        ("json-true-vs-int-one", json!(true), json!(1), false),
        ("json-false-vs-int-zero", json!(false), json!(0), false),
        ("json-int-one-vs-float-one", json!(1), json!(1.0), false),
        (
            "json-nested-bool-vs-int",
            json!({"items": [true]}),
            json!({"items": [1]}),
            false,
        ),
        (
            "json-array-order-differs",
            json!(["first", "second"]),
            json!(["second", "first"]),
            false,
        ),
        (
            "json-object-key-order-equal",
            json!({"alpha": 1, "beta": 2}),
            json!({"beta": 2, "alpha": 1}),
            true,
        ),
        ("json-null-equal", Value::Null, Value::Null, true),
    ];
    for (name, left, right, expected_eq) in cases {
        record_case(
            output,
            name,
            &ProjectedValue::Json(left),
            &ProjectedValue::Json(right),
            expected_eq,
        )?;
    }
    Ok(())
}

fn record_cross_variant_cases(
    output: &mut Vec<Value>,
    variants: &[(&'static str, ProjectedValue)],
) -> Result<(), serde_json::Error> {
    let Some(((left_name, left), rest)) = variants.split_first() else {
        return Ok(());
    };
    for (right_name, right) in rest {
        record_case(
            output,
            &format!("cross-variant-{left_name}-vs-{right_name}"),
            left,
            right,
            false,
        )?;
    }
    record_cross_variant_cases(output, rest)
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut output = Vec::new();
    let variants = public_variants()?;

    for (name, value) in &variants {
        record_case(
            &mut output,
            &format!("{name}-equal-identical"),
            value,
            value,
            true,
        )?;
    }
    record_cross_variant_cases(&mut output, &variants)?;
    record_json_cases(&mut output)?;

    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());
    serde_json::to_writer(&mut writer, &output)?;
    writeln!(writer)?;
    Ok(())
}
