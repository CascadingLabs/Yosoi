//! Emit Rust-authored WebTarget conversion and borrowed-view fixtures.
//!
//! Build with `cargo build -p yosoi --example python_webtarget_conformance`.
//! Each input is authored here and passed through the public `From` impls and
//! `AsRef<str>` implementation before being emitted as exact raw text.

use std::{
    borrow::Cow,
    error::Error,
    io::{self, Write},
};

use serde::Serialize;
use serde_json::json;
use yosoi::request::WebTarget;

const OPERATION_PATH: &str = "yosoi::request::WebTarget::from";
const AS_REF_PATH: &str = "yosoi::request::WebTarget::as_ref";
const NEW_PATH: &str = "yosoi::request::WebTarget::new";
const AS_STR_PATH: &str = "yosoi::request::WebTarget::as_str";

const INPUTS: [(&str, &str); 4] = [
    ("unicode-url-idn", "https://例え.テスト/道?q=雪"),
    ("unicode-url-path", "https://example.com/路径/naïve"),
    ("empty", ""),
    ("invalid-authored-text", "  not a URL/雪  "),
];

const CONVERSIONS: [(&str, &str); 6] = [
    ("from-str", "&str"),
    ("from-string", "String"),
    ("from-string-ref", "&String"),
    ("from-box-str", "Box<str>"),
    ("from-cow-borrowed", "Cow<'_, str>"),
    ("from-cow-owned", "Cow<'_, str>"),
];

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Fixture {
    name: String,
    value_name: String,
    conversion: String,
    rust_argument_type: String,
    operation_path: &'static str,
    operation_trait: &'static str,
    as_ref_path: &'static str,
    as_ref_trait: &'static str,
    new_path: &'static str,
    as_str_path: &'static str,
    input: String,
    raw: String,
    as_ref_raw: String,
    new_raw: String,
    as_str_raw: String,
    #[serde(rename = "fixturePassed")]
    passed: bool,
}

fn convert(conversion: &str, value: &str) -> Result<WebTarget, Box<dyn Error>> {
    let target = match conversion {
        "from-str" => WebTarget::from(value),
        "from-string" => WebTarget::from(value.to_owned()),
        "from-string-ref" => {
            let owned = value.to_owned();
            WebTarget::from(&owned)
        }
        "from-box-str" => WebTarget::from(value.to_owned().into_boxed_str()),
        "from-cow-borrowed" => WebTarget::from(Cow::Borrowed(value)),
        "from-cow-owned" => WebTarget::from(Cow::Owned(value.to_owned())),
        _ => return Err(io::Error::other(format!("unknown conversion: {conversion}")).into()),
    };
    Ok(target)
}

fn main() -> Result<(), Box<dyn Error>> {
    let capacity = INPUTS
        .len()
        .checked_mul(CONVERSIONS.len())
        .ok_or_else(|| io::Error::other("WebTarget fixture capacity overflow"))?;
    let mut cases = Vec::with_capacity(capacity);
    for (value_name, input) in INPUTS {
        for (conversion, rust_argument_type) in CONVERSIONS {
            let target = convert(conversion, input)?;
            let raw = target.as_str();
            let as_ref_raw = <WebTarget as AsRef<str>>::as_ref(&target);
            let new_target = WebTarget::new(input.to_owned());
            let new_raw = new_target.as_str();
            let as_str_raw = target.as_str();
            cases.push(Fixture {
                name: format!("{value_name}/{conversion}"),
                value_name: value_name.to_owned(),
                conversion: conversion.to_owned(),
                rust_argument_type: rust_argument_type.to_owned(),
                operation_path: OPERATION_PATH,
                operation_trait: "From",
                as_ref_path: AS_REF_PATH,
                as_ref_trait: "AsRef",
                new_path: NEW_PATH,
                as_str_path: AS_STR_PATH,
                input: input.to_owned(),
                raw: raw.to_owned(),
                as_ref_raw: as_ref_raw.to_owned(),
                new_raw: new_raw.to_owned(),
                as_str_raw: as_str_raw.to_owned(),
                passed: raw == input
                    && as_ref_raw == input
                    && new_raw == input
                    && as_str_raw == input,
            });
        }
    }

    let output = json!({
        "schemaVersion": 1,
        "kind": "yosoi-web-target-conversion-fixtures",
        "cases": cases,
    });
    let stdout = io::stdout();
    let mut writer = stdout.lock();
    serde_json::to_writer(&mut writer, &output)?;
    writer.write_all(b"\n")?;
    Ok(())
}
