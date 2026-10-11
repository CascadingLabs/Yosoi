use std::{error::Error, io};

use serde_json::Value;

pub const DEFAULT_POLICY_JSON: &str = include_str!("../fixtures/default-policy.json");

pub type TestResult = Result<(), Box<dyn Error>>;

pub fn default_policy_json_value() -> Result<Value, serde_json::Error> {
    serde_json::from_str(DEFAULT_POLICY_JSON)
}

#[allow(
    dead_code,
    reason = "shared by test crates that compile this support module independently"
)]
pub fn set_json_value(document: &mut Value, pointer: &str, value: Value) -> Result<(), io::Error> {
    let destination = document.pointer_mut(pointer).ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("the default policy fixture has no {pointer} field"),
        )
    })?;
    *destination = value;
    Ok(())
}
