//! Emit real public Rust SDK document and parse errors for Python parity.

use std::{
    error::Error,
    io::{self, Write},
};

use serde::Serialize;
use serde_json::{Value, error::Category, json};
use yosoi::{
    Document, DocumentId,
    documents::{DocumentEpoch, DocumentError, DocumentProfile, ParseError},
    policy::{AddressableByteLimit, Policy},
};

type DocumentEpochError = <DocumentEpoch as TryFrom<u64>>::Error;

#[derive(Serialize)]
#[serde(rename_all = "snake_case")]
struct ErrorRecord {
    rust_type: String,
    variant: Option<String>,
    details: Value,
    message: String,
    source_chain: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Fixture {
    name: String,
    operation_path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    operation_trait: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    construction_paths: Option<Vec<String>>,
    error_path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    error_type_path: Option<String>,
    input: Value,
    error: ErrorRecord,
}

#[derive(Clone, Copy)]
struct FixturePaths<'a> {
    operation_path: &'a str,
    operation_trait: Option<&'a str>,
    construction_paths: Option<&'a [&'a str]>,
    error_path: &'a str,
    error_type_path: Option<&'a str>,
}

fn source_chain(error: &(dyn Error + 'static)) -> Vec<String> {
    let mut chain = Vec::new();
    let mut source = error.source();
    while let Some(error) = source {
        chain.push(error.to_string());
        source = error.source();
    }
    chain
}

fn error_record(
    error: &(dyn Error + 'static),
    rust_type: &str,
    variant: Option<&str>,
    details: Value,
) -> ErrorRecord {
    ErrorRecord {
        rust_type: rust_type.to_owned(),
        variant: variant.map(str::to_owned),
        details,
        message: error.to_string(),
        source_chain: source_chain(error),
    }
}

fn require_error<T, E: Error + 'static>(
    result: Result<T, E>,
    name: &str,
) -> Result<E, Box<dyn Error>> {
    match result {
        Err(error) => Ok(error),
        Ok(_) => Err(io::Error::other(format!("{name} unexpectedly succeeded")).into()),
    }
}

fn fixture(name: &str, paths: FixturePaths<'_>, input: Value, error: ErrorRecord) -> Fixture {
    Fixture {
        name: name.to_owned(),
        operation_path: paths.operation_path.to_owned(),
        operation_trait: paths.operation_trait.map(str::to_owned),
        construction_paths: paths
            .construction_paths
            .map(|paths| paths.iter().map(|path| (*path).to_owned()).collect()),
        error_path: paths.error_path.to_owned(),
        error_type_path: paths.error_type_path.map(str::to_owned),
        input,
        error,
    }
}

fn document_error_record(error: &DocumentError) -> ErrorRecord {
    let variant = match error {
        DocumentError::EmptyId => "EmptyId",
        DocumentError::EmptyPayload => "EmptyPayload",
        DocumentError::PayloadLengthOverflow => "PayloadLengthOverflow",
        DocumentError::InvalidProfile(_) => "InvalidProfile",
    };
    error_record(
        error,
        "yosoi_documents::DocumentError",
        Some(variant),
        json!({}),
    )
}

fn epoch_error_record(error: DocumentEpochError) -> ErrorRecord {
    let variant = match error {
        DocumentEpochError::IncompatibleAxes => "IncompatibleAxes",
        DocumentEpochError::UnexpectedEpoch => "UnexpectedEpoch",
        DocumentEpochError::MissingEpoch => "MissingEpoch",
        DocumentEpochError::ZeroEpoch => "ZeroEpoch",
    };
    error_record(
        &error,
        "yosoi_documents::DocumentProfileError",
        Some(variant),
        json!({}),
    )
}

fn parse_error_record(error: &ParseError) -> ErrorRecord {
    let (variant, details) = match error {
        ParseError::InvalidResourcePolicy { limit } => {
            ("InvalidResourcePolicy", json!({"limit": limit}))
        }
        ParseError::Document(source) => (
            "Document",
            json!({
                "source": {
                    "rust_type": "yosoi_documents::DocumentParseError",
                    "message": source.to_string()
                }
            }),
        ),
    };
    error_record(error, "yosoi_engine::ParseError", Some(variant), details)
}

fn serde_profile_error_record(error: &serde_json::Error) -> ErrorRecord {
    let (variant, category) = match error.classify() {
        Category::Io => ("Io", "io"),
        Category::Syntax => ("Syntax", "syntax"),
        Category::Data => ("Data", "data"),
        Category::Eof => ("Eof", "eof"),
    };
    error_record(
        error,
        "serde_json::Error",
        Some(variant),
        json!({
            "category": category,
            "line": error.line(),
            "column": error.column()
        }),
    )
}

fn parse_fixture(name: &str, id: &str, content: &str) -> Result<Fixture, Box<dyn Error>> {
    let document = Document::json(id, content.as_bytes().to_vec())?;
    let error = require_error(document.parse(), name)?;
    Ok(fixture(
        name,
        FixturePaths {
            operation_path: "yosoi::Document::parse",
            operation_trait: None,
            construction_paths: Some(&["yosoi::Document::json"]),
            error_path: "yosoi::documents::ParseError::Document",
            error_type_path: Some("yosoi::documents::ParseError"),
        },
        json!({"id": id, "content": content}),
        parse_error_record(&error),
    ))
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut fixtures = Vec::new();

    let value = "";
    let error = require_error(
        DocumentId::try_from(value.to_owned()),
        "DocumentId::try_from with an empty value",
    )?;
    fixtures.push(fixture(
        "document-id-empty",
        FixturePaths {
            operation_path: "yosoi::DocumentId::try_from",
            operation_trait: Some("TryFrom"),
            construction_paths: None,
            error_path: "yosoi::DocumentId::Error",
            error_type_path: Some("yosoi::DocumentId::Error"),
        },
        json!({"value": value}),
        document_error_record(&error),
    ));

    let id = "empty-payload";
    let content = "";
    let error = require_error(
        Document::json(id, content.as_bytes().to_vec()),
        "Document JSON with an empty payload",
    )?;
    fixtures.push(fixture(
        "document-json-empty-payload",
        FixturePaths {
            operation_path: "yosoi::Document::json",
            operation_trait: None,
            construction_paths: None,
            error_path: "yosoi::documents::DocumentError::EmptyPayload",
            error_type_path: Some("yosoi::documents::DocumentError"),
        },
        json!({"id": id, "content": content}),
        document_error_record(&error),
    ));

    let value = 0_u64;
    let error: DocumentEpochError =
        require_error(DocumentEpoch::try_from(value), "DocumentEpoch::try_from(0)")?;
    fixtures.push(fixture(
        "document-epoch-zero",
        FixturePaths {
            operation_path: "yosoi::documents::DocumentEpoch::try_from",
            operation_trait: Some("TryFrom"),
            construction_paths: None,
            error_path: "yosoi::documents::DocumentEpoch::Error",
            error_type_path: Some("yosoi::documents::DocumentEpoch::Error"),
        },
        json!({"value": value}),
        epoch_error_record(error),
    ));

    fixtures.push(parse_fixture(
        "document-parse-json-duplicate-key",
        "duplicate-json",
        r#"{"title":"first","title":"second"}"#,
    )?);
    fixtures.push(parse_fixture(
        "document-parse-json-truncated",
        "truncated-json",
        r#"{"title":"#,
    )?);

    let id = "limited-html";
    let content = "<main>content</main>";
    let mut policy = Policy::default();
    policy.documents.max_input_bytes = AddressableByteLimit::try_from(1_u64)?;
    let document = Document::html(id, content.as_bytes().to_vec())?;
    let bound = document.bind(&policy);
    let error = require_error(bound.parse(), "HTML parse above the input limit")?;
    fixtures.push(fixture(
        "document-parse-html-input-limit",
        FixturePaths {
            operation_path: "yosoi::documents::BoundDocument::parse",
            operation_trait: None,
            construction_paths: Some(&["yosoi::Document::html", "yosoi::Document::bind"]),
            error_path: "yosoi::documents::ParseError::Document",
            error_type_path: Some("yosoi::documents::ParseError"),
        },
        json!({
            "id": id,
            "content": content,
            "policy": {"documents": {"max_input_bytes": 1}}
        }),
        parse_error_record(&error),
    ));

    const INVALID_PROFILE: &str =
        r#"{"representation":"source","source_format":"html","schema":"xml10","epoch":null}"#;
    let error = require_error(
        serde_json::from_str::<DocumentProfile>(INVALID_PROFILE),
        "Deserialize incompatible DocumentProfile axes",
    )?;
    fixtures.push(fixture(
        "document-profile-serde-incompatible-axes",
        FixturePaths {
            operation_path: "serde_json::from_str::<yosoi::documents::DocumentProfile>",
            operation_trait: Some("Deserialize"),
            construction_paths: None,
            error_path: "serde_json::Error",
            error_type_path: Some("serde_json::Error"),
        },
        json!({"profile_json": INVALID_PROFILE}),
        serde_profile_error_record(&error),
    ));

    let stdout = io::stdout();
    let mut output = stdout.lock();
    serde_json::to_writer(
        &mut output,
        &json!({
            "schemaVersion": 1,
            "kind": "yosoi-document-error-fixtures",
            "cases": fixtures,
        }),
    )?;
    writeln!(output)?;
    Ok(())
}
