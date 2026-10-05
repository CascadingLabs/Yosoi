//! Emit real public SDK operation failures for Python error parity review.

use std::{
    error::Error,
    io::{self, Write},
    str::FromStr,
};

use serde::Serialize;
use serde_json::{Value, json};
use tokio::runtime::Builder;
use yosoi::{
    map,
    policy::{Policy, search::Search},
    request::{self, ActivityId, CaptureId},
    search::{self, SearchQueryError, SearchSendError},
};

type IdentityParseError = <ActivityId as FromStr>::Err;

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
    error_path: String,
    input: Value,
    error: ErrorRecord,
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

fn fixture(
    name: &str,
    operation_path: &str,
    error_path: &str,
    input: Value,
    error: ErrorRecord,
) -> Fixture {
    Fixture {
        name: name.to_owned(),
        operation_path: operation_path.to_owned(),
        operation_trait: None,
        error_path: error_path.to_owned(),
        input,
        error,
    }
}

fn identity_fixture<T>(
    identity: &str,
    scenario: &str,
    operation_path: &str,
    error_path: &str,
    value: &str,
    result: Result<T, IdentityParseError>,
) -> Result<Fixture, Box<dyn Error>> {
    let Err(error) = result else {
        return Err(io::Error::other(format!(
            "{identity} unexpectedly accepted an invalid occurrence ID"
        ))
        .into());
    };
    let variant = match &error {
        IdentityParseError::InvalidUuid => "InvalidUuid",
        IdentityParseError::NonCanonical => "NonCanonical",
        IdentityParseError::NotRandomV4 => "NotRandomV4",
    };
    let mut fixture = fixture(
        &format!("{identity}-{scenario}"),
        operation_path,
        error_path,
        json!({"identity": identity, "value": value}),
        error_record(
            &error,
            "yosoi_types::OccurrenceIdParseError",
            Some(variant),
            json!({}),
        ),
    );
    fixture.operation_trait = Some("FromStr".to_owned());
    Ok(fixture)
}

fn main() -> Result<(), Box<dyn Error>> {
    const INVALID_TARGET: &str = "ftp://example.com";

    let mut fixtures = Vec::new();
    let policy = Policy::default();

    let request = request::new(INVALID_TARGET).bind(&policy);
    let error = require_error(request.validate(), "Request bound validation")?;
    fixtures.push(fixture(
        "request-bound-validate-invalid-scheme",
        "yosoi::request::BoundPageRequest::validate",
        "yosoi::request::RequestPreparationError",
        json!({"target": INVALID_TARGET, "policy": "default"}),
        error_record(
            &error,
            "yosoi::request::RequestPreparationError",
            None,
            json!({"opaque": true}),
        ),
    ));

    let map_request = map::new(INVALID_TARGET).bind(&policy);
    let error = require_error(map_request.validate(), "Map bound validation")?;
    fixtures.push(fixture(
        "map-bound-validate-invalid-scheme",
        "yosoi::map::MapRequest::validate",
        "yosoi::map::MapError",
        json!({"seed": INVALID_TARGET, "policy": "default"}),
        error_record(
            &error,
            "yosoi::map::MapError",
            None,
            json!({"opaque": true}),
        ),
    ));

    let request = request::new(INVALID_TARGET).bind(&policy);
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let error = require_error(runtime.block_on(request.send()), "Request bound send")?;
    fixtures.push(fixture(
        "request-bound-send-invalid-scheme",
        "yosoi::request::BoundPageRequest::send",
        "yosoi::request::RequestSendError",
        json!({"target": INVALID_TARGET, "policy": "default"}),
        error_record(
            &error,
            "yosoi::request::RequestSendError",
            None,
            json!({"opaque": true}),
        ),
    ));

    let empty_query = " \n".to_owned();
    let error = require_error(search::new(empty_query.clone()), "Empty Search query")?;
    let (variant, details) = match &error {
        SearchQueryError::Empty => ("Empty", json!({})),
        SearchQueryError::TooLong { maximum, observed } => {
            ("TooLong", json!({"maximum": maximum, "observed": observed}))
        }
    };
    fixtures.push(fixture(
        "search-new-empty-query",
        "yosoi::search::SearchRequest::new",
        "yosoi::search::SearchQueryError::Empty",
        json!({"query": empty_query}),
        error_record(
            &error,
            "yosoi::search::SearchQueryError",
            Some(variant),
            details,
        ),
    ));

    let long_query = format!("{}x", "é".repeat(256));
    let error = require_error(search::new(long_query.clone()), "Oversized Search query")?;
    let (variant, details) = match &error {
        SearchQueryError::Empty => ("Empty", json!({})),
        SearchQueryError::TooLong { maximum, observed } => {
            ("TooLong", json!({"maximum": maximum, "observed": observed}))
        }
    };
    fixtures.push(fixture(
        "search-new-513-byte-query",
        "yosoi::search::SearchRequest::new",
        "yosoi::search::SearchQueryError::TooLong",
        json!({"query": long_query, "query_bytes": 513}),
        error_record(
            &error,
            "yosoi::search::SearchQueryError",
            Some(variant),
            details,
        ),
    ));

    let policy = Policy {
        search: Search::disabled(),
        ..Policy::default()
    };
    let request = search::new("rust")?.bind(&policy);
    let error = require_error(request.validate(), "Search without providers")?;
    let (variant, details, error_path) = match &error {
        SearchSendError::NoProviderConfigured => (
            "NoProviderConfigured",
            json!({}),
            "yosoi::search::SearchSendError::NoProviderConfigured",
        ),
        SearchSendError::Policy(_) | SearchSendError::Execution(_) => {
            return Err(
                io::Error::other(format!("unexpected Search validation error: {error}")).into(),
            );
        }
    };
    fixtures.push(fixture(
        "search-bound-validate-no-providers",
        "yosoi::search::BoundSearchRequest::validate",
        error_path,
        json!({"query": "rust", "policy": "search-disabled"}),
        error_record(
            &error,
            "yosoi::search::SearchSendError",
            Some(variant),
            details,
        ),
    ));

    for (name, value) in [
        ("invalid-uuid", "invalid"),
        ("noncanonical", "550E8400-E29B-41D4-A716-446655440000"),
        ("not-random-v4", "550e8400-e29b-11d4-a716-446655440000"),
    ] {
        fixtures.push(identity_fixture(
            "activity-id",
            name,
            "yosoi::request::ActivityId::from_str",
            "yosoi::request::ActivityId::Err",
            value,
            value.parse::<ActivityId>().map(|_| ()),
        )?);
        fixtures.push(identity_fixture(
            "capture-id",
            name,
            "yosoi::request::CaptureId::from_str",
            "yosoi::request::CaptureId::Err",
            value,
            value.parse::<CaptureId>().map(|_| ()),
        )?);
    }

    let stdout = io::stdout();
    let mut output = stdout.lock();
    serde_json::to_writer(
        &mut output,
        &json!({
            "schemaVersion": 1,
            "kind": "yosoi-operation-error-fixtures",
            "cases": fixtures,
        }),
    )?;
    writeln!(output)?;
    Ok(())
}
