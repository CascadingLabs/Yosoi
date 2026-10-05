//! Machine-readable public Rust results for cross-language conformance.

use serde_json::{Value, json};
use std::{
    error::Error,
    io::{self, Read},
};
use yosoi::{
    contracts::{
        ContractSchema, ContractValue, Money, RuntimeContract, RuntimeContractOutcome,
        RuntimeFieldValue, RuntimeValue,
    },
    documents::{Document, DocumentId, DocumentProfile},
    locators::{Plan, QuerySpec, TreeCoordinate, css, xpath},
    map::{MapTermination, Summary},
    policy::{Filters as PolicyFilters, Map as PolicyMap, Policy, PolicySnapshot},
    search::SearchHitMetadata,
};

fn main() -> Result<(), Box<dyn Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let cases: Vec<Value> = serde_json::from_str(&input)?;
    let mut results = Vec::new();
    for case in cases {
        let kind = case
            .get("kind")
            .and_then(Value::as_str)
            .ok_or("case kind missing")?;
        let name = case
            .get("name")
            .and_then(Value::as_str)
            .ok_or("case name missing")?;
        let result = match kind {
            "contract_value_identity" => {
                struct CustomValue;
                impl ContractValue for CustomValue {
                    const TYPE_ID: &'static str = "custom.review";
                }
                struct EmptyIdentity;
                impl ContractValue for EmptyIdentity {
                    const TYPE_ID: &'static str = "";
                }
                json!({
                    "string": <String as ContractValue>::TYPE_ID,
                    "money": <Money as ContractValue>::TYPE_ID,
                    "custom": <CustomValue as ContractValue>::TYPE_ID,
                    "empty": <EmptyIdentity as ContractValue>::TYPE_ID,
                })
            }
            "wire_view" => {
                let value = match name {
                    "tree-required-null" => {
                        serde_json::to_value(TreeCoordinate::try_new(vec![1], None)?)?
                    }
                    "query-absent-namespaces" => serde_json::to_value(css("article")?)?,
                    "query-present-namespaces" => {
                        serde_json::to_value(xpath("//p:name")?.with_namespace("p", "urn:test")?)?
                    }
                    "map-unit-termination" => serde_json::to_value(MapTermination::Exhausted)?,
                    "runtime-optional-null" => {
                        serde_json::to_value(RuntimeFieldValue::ZeroOrOne { value: None })?
                    }
                    _ => return Err("unknown wire-view case".into()),
                };
                json!({"value": value})
            }
            "model_clone" => {
                let type_name = case
                    .get("rust_type")
                    .and_then(Value::as_str)
                    .ok_or("clone type missing")?;
                let marker = case
                    .get("marker")
                    .and_then(Value::as_str)
                    .ok_or("clone marker missing")?;
                match type_name {
                    "yosoi::Policy" => {
                        let original = Policy::default();
                        let mut cloned = original.clone();
                        cloned
                            .map
                            .filters
                            .excluded_query_keys
                            .push(marker.to_owned());
                        json!({"original": original, "clone": cloned})
                    }
                    "yosoi::policy::Map" => {
                        let original = PolicyMap::default();
                        let mut cloned = original.clone();
                        cloned.filters.excluded_query_keys.push(marker.to_owned());
                        json!({"original": original, "clone": cloned})
                    }
                    "yosoi::policy::Filters" => {
                        let original = PolicyFilters::default();
                        let mut cloned = original.clone();
                        cloned.excluded_query_keys.push(marker.to_owned());
                        json!({"original": original, "clone": cloned})
                    }
                    _ => return Err("unknown clone type".into()),
                }
            }
            "model_default" => {
                let type_name = case
                    .get("rust_type")
                    .and_then(Value::as_str)
                    .ok_or("model type missing")?;
                let value = default_model(type_name)?;
                let fields = if type_name == "yosoi::Policy" {
                    json!({"tuning": Policy::default().tuning})
                } else {
                    json!({})
                };
                json!({"value": value, "omitted_fields": fields})
            }
            "query" => {
                let source: QuerySpec = serde_json::from_value(
                    case.get("query").ok_or("query source missing")?.clone(),
                )?;
                let operation = case
                    .get("operation")
                    .and_then(Value::as_str)
                    .ok_or("query operation missing")?;
                let query = match operation {
                    "new" => Ok(QuerySpec::new(source.atom().clone(), source.result_shape())),
                    "with_namespace" => source.with_namespace(
                        case.get("prefix")
                            .and_then(Value::as_str)
                            .ok_or("namespace prefix missing")?,
                        case.get("uri")
                            .and_then(Value::as_str)
                            .ok_or("namespace URI missing")?,
                    ),
                    "with_default_namespace" => source.with_default_namespace(
                        case.get("uri")
                            .and_then(Value::as_str)
                            .ok_or("namespace URI missing")?,
                    ),
                    _ => return Err("unknown query operation".into()),
                };
                match query {
                    Ok(query) => json!({
                        "query": query,
                        "atom": query.atom(),
                        "result_shape": query.result_shape(),
                        "namespace_bindings": query.namespace_bindings(),
                        "query_bytes": query.query_bytes()?,
                    }),
                    Err(error) => json!({"error": error.to_string()}),
                }
            }
            "policy" => {
                let policy_value = case.get("policy").ok_or("policy missing")?;
                let policy: Policy = if policy_value.is_null() {
                    Policy::default()
                } else {
                    serde_json::from_value(policy_value.clone())?
                };
                let snapshot = PolicySnapshot::from_policy(&policy)?;
                let identity = snapshot.identity();
                json!({"policy": policy, "effective": policy.effective_policy()?,
                    "snapshot": {"policy": snapshot.policy(), "effective_policy": snapshot.effective_policy(),
                        "identity": {"version": identity.version(), "sha256": identity.digest().to_string()}}})
            }
            "document" | "contract" => {
                let profile: DocumentProfile = serde_json::from_value(
                    case.get("profile")
                        .ok_or("document profile missing")?
                        .clone(),
                )?;
                let id = DocumentId::try_new(name)?;
                let content = case
                    .get("content")
                    .and_then(Value::as_str)
                    .ok_or("case content missing")?;
                let document = Document::from_profile(id, profile, content.as_bytes())?;
                let plan: Plan = serde_json::from_value(
                    case.get("plan").ok_or("document plan missing")?.clone(),
                )?;
                let located = document.locate(&plan);
                if kind == "contract" {
                    let schema: ContractSchema = serde_json::from_value(
                        case.get("schema").ok_or("contract schema missing")?.clone(),
                    )?;
                    let contract = RuntimeContract::new(schema)?;
                    let extracted = contract.extract(&located);
                    let outcome = extracted.clone().validate();
                    let archived = outcome.to_archived(contract.schema())?;
                    let typed_values = match &outcome {
                        RuntimeContractOutcome::Evaluated { records, .. } => records
                            .iter()
                            .map(|record| {
                                let mut object = serde_json::Map::new();
                                for (field, value) in &record.value {
                                    object.insert(
                                        field.as_str().to_owned(),
                                        match value {
                                            RuntimeFieldValue::ExactlyOne { value } => {
                                                scalar(value)
                                            }
                                            RuntimeFieldValue::ZeroOrOne { value } => {
                                                value.as_ref().map_or(Value::Null, scalar)
                                            }
                                            RuntimeFieldValue::Many { values } => {
                                                Value::Array(values.iter().map(scalar).collect())
                                            }
                                        },
                                    );
                                }
                                Value::Object(object)
                            })
                            .collect::<Vec<_>>(),
                        _ => Vec::new(),
                    };
                    let required = match outcome.clone().require_all() {
                        Ok(records) => json!({"records": records}),
                        Err(error) => json!({"error": error}),
                    };
                    json!({"profile": profile, "class": document.class(), "byte_len": document.byte_len(),
                        "plan": plan, "located": located, "identity": contract.schema().identity()?.to_string(),
                        "extracted": extracted, "outcome": outcome, "archived": archived, "required": required, "typed_values": typed_values})
                } else {
                    json!({"profile": profile, "class": document.class(), "byte_len": document.byte_len(),
                        "plan": plan, "located": located})
                }
            }
            _ => return Err("unknown conformance case kind".into()),
        };
        results.push(json!({"name": name, "result": result}));
    }
    println!("{}", serde_json::to_string(&results)?);
    Ok(())
}

fn default_json<T: Default + serde::Serialize>() -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::to_value(T::default())?)
}

fn default_model(type_name: &str) -> Result<Value, Box<dyn Error>> {
    use yosoi::policy as p;
    match type_name {
        "yosoi::Policy" => default_json::<p::Policy>(),
        "yosoi::policy::Page" => default_json::<p::Page>(),
        "yosoi::policy::Request" => default_json::<p::Request>(),
        "yosoi::policy::SourceLimits" => default_json::<p::SourceLimits>(),
        "yosoi::policy::BrowserLimits" => default_json::<p::BrowserLimits>(),
        "yosoi::policy::DirectHttpRedirects" => default_json::<p::DirectHttpRedirects>(),
        "yosoi::policy::Documents" => default_json::<p::Documents>(),
        "yosoi::policy::Locators" => default_json::<p::Locators>(),
        "yosoi::policy::Map" => default_json::<p::Map>(),
        "yosoi::policy::Limits" => default_json::<p::Limits>(),
        "yosoi::policy::Filters" => default_json::<p::Filters>(),
        "yosoi::policy::Scope" => default_json::<p::Scope>(),
        "yosoi::policy::Tuning" => default_json::<p::Tuning>(),
        "yosoi::policy::search::Search" => default_json::<p::search::Search>(),
        "yosoi::policy::EventLimit" => default_json::<p::EventLimit>(),
        "yosoi::policy::MaximumElapsed" => default_json::<p::MaximumElapsed>(),
        "yosoi::policy::RedirectHopLimit" => default_json::<p::RedirectHopLimit>(),
        "yosoi::map::Summary" => default_json::<Summary>(),
        "yosoi::search::SearchHitMetadata" => default_json::<SearchHitMetadata>(),
        _ => Err("unsupported default model".into()),
    }
}

fn scalar(value: &RuntimeValue) -> Value {
    match value {
        RuntimeValue::String(value) => json!(value),
        RuntimeValue::MoneyUsd(value) => json!(value),
    }
}
