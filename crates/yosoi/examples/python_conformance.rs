//! Machine-readable public Rust results for cross-language conformance.

use serde_json::{Value, json};
use std::{
    error::Error,
    io::{self, Read},
};
use yosoi::{
    contracts::{
        ContractSchema, RuntimeContract, RuntimeContractOutcome, RuntimeFieldValue, RuntimeValue,
    },
    documents::{Document, DocumentId, DocumentProfile},
    locators::Plan,
    policy::{Policy, PolicySnapshot},
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
            "policy" => {
                let policy: Policy = if case["policy"].is_null() {
                    Policy::default()
                } else {
                    serde_json::from_value(case["policy"].clone())?
                };
                let snapshot = PolicySnapshot::from_policy(&policy)?;
                let identity = snapshot.identity();
                json!({"policy": policy, "effective": policy.effective_policy()?,
                    "snapshot": {"policy": snapshot.policy(), "effective_policy": snapshot.effective_policy(),
                        "identity": {"version": identity.version(), "sha256": identity.digest().to_string()}}})
            }
            "document" | "contract" => {
                let profile: DocumentProfile = serde_json::from_value(case["profile"].clone())?;
                let id = DocumentId::try_new(name)?;
                let content = case
                    .get("content")
                    .and_then(Value::as_str)
                    .ok_or("case content missing")?;
                let document = Document::from_profile(id, profile, content.as_bytes())?;
                let plan: Plan = serde_json::from_value(case["plan"].clone())?;
                let located = document.locate(&plan);
                if kind == "contract" {
                    let schema: ContractSchema = serde_json::from_value(case["schema"].clone())?;
                    let contract = RuntimeContract::new(schema)?;
                    let extracted = contract.extract(&located);
                    let outcome = extracted.clone().validate();
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
                        "extracted": extracted, "outcome": outcome, "required": required, "typed_values": typed_values})
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

fn scalar(value: &RuntimeValue) -> Value {
    match value {
        RuntimeValue::String(value) => json!(value),
        RuntimeValue::MoneyUsd(value) => json!(value),
    }
}
