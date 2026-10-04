use std::collections::{BTreeMap, HashMap};

use serde::{Deserialize, Serialize};
use yosoi_documents::{AccessibilityCompleteness, AccessibilityStateName};

use super::AccessibilityNormalizationError;

#[derive(Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(super) struct CdpAxNode {
    node_id: String,
    ignored: bool,
    role: Option<CdpAxValue>,
    name: Option<CdpAxValue>,
    properties: Option<Vec<CdpAxProperty>>,
    parent_id: Option<String>,
    child_ids: Option<Vec<String>>,
}

#[derive(Deserialize, PartialEq)]
struct CdpAxProperty {
    name: String,
    value: CdpAxValue,
}

#[derive(Deserialize, PartialEq)]
struct CdpAxValue {
    #[serde(rename = "type")]
    value_type: String,
    value: Option<serde_json::Value>,
}

#[derive(Serialize)]
pub(super) struct AccessibilityTreeWire {
    pub(super) schema: &'static str,
    pub(super) document_epoch: u64,
    pub(super) root: String,
    pub(super) completeness: AccessibilityCompleteness,
    pub(super) nodes: Vec<AccessibilityNodeWire>,
}

#[derive(Clone, Serialize)]
pub(super) struct AccessibilityNodeWire {
    pub(super) id: String,
    pub(super) parent: Option<String>,
    pub(super) children: Vec<String>,
    ignored: bool,
    role: String,
    accessible_name: Option<String>,
    text: Option<String>,
    states: BTreeMap<AccessibilityStateName, bool>,
}

pub(super) fn normalize_node(
    raw: CdpAxNode,
) -> Result<AccessibilityNodeWire, AccessibilityNormalizationError> {
    let role = raw
        .role
        .as_ref()
        .ok_or(AccessibilityNormalizationError::MissingRole)
        .and_then(exact_role_string)?;
    let accessible_name = raw.name.as_ref().map(normalize_name).transpose()?.flatten();
    let mut states = BTreeMap::new();
    if let Some(properties) = raw.properties {
        for property in properties {
            let state_name = match property.name.as_str() {
                "expanded" => Some(AccessibilityStateName::Expanded),
                "focused" => Some(AccessibilityStateName::Focused),
                _ => None,
            };
            let Some(state_name) = state_name else {
                continue;
            };
            let Some(state_value) = exact_boolean(&property.value)? else {
                continue;
            };
            if states.insert(state_name, state_value).is_some() {
                return Err(AccessibilityNormalizationError::InvalidState);
            }
        }
    }
    Ok(AccessibilityNodeWire {
        id: raw.node_id,
        parent: raw.parent_id,
        children: raw.child_ids.unwrap_or_default(),
        ignored: raw.ignored,
        role,
        accessible_name,
        // CDP's AXNode value is a control/value channel, not generic tree text.
        text: None,
        states,
    })
}

pub(super) fn deduplicate_exact_nodes(
    raw_nodes: Vec<CdpAxNode>,
) -> Result<Vec<CdpAxNode>, AccessibilityNormalizationError> {
    let mut indexes = HashMap::<String, usize>::with_capacity(raw_nodes.len());
    let mut unique = Vec::with_capacity(raw_nodes.len());
    for node in raw_nodes {
        if let Some(index) = indexes.get(&node.node_id).copied() {
            if unique.get(index) != Some(&node) {
                return Err(AccessibilityNormalizationError::InvalidTreeGraph);
            }
            continue;
        }
        indexes.insert(node.node_id.clone(), unique.len());
        unique.push(node);
    }
    Ok(unique)
}

fn exact_ax_string(
    value: &CdpAxValue,
    required_type: &str,
    error: AccessibilityNormalizationError,
) -> Result<String, AccessibilityNormalizationError> {
    if value.value_type != required_type {
        return Err(error);
    }
    value
        .value
        .as_ref()
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .ok_or(error)
}

fn exact_role_string(value: &CdpAxValue) -> Result<String, AccessibilityNormalizationError> {
    if !matches!(value.value_type.as_str(), "role" | "internalRole") {
        return Err(AccessibilityNormalizationError::InvalidRole);
    }
    value
        .value
        .as_ref()
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .ok_or(AccessibilityNormalizationError::InvalidRole)
}

fn normalize_name(value: &CdpAxValue) -> Result<Option<String>, AccessibilityNormalizationError> {
    if value.value_type == "valueUndefined" && value.value.is_none() {
        return Ok(None);
    }
    if value.value_type != "computedString" && value.value_type != "string" {
        return Err(AccessibilityNormalizationError::InvalidName);
    }
    exact_ax_string(
        value,
        &value.value_type,
        AccessibilityNormalizationError::InvalidName,
    )
    .map(Some)
}

fn exact_boolean(value: &CdpAxValue) -> Result<Option<bool>, AccessibilityNormalizationError> {
    if value.value_type == "booleanOrUndefined" {
        return value
            .value
            .as_ref()
            .map(|value| {
                value
                    .as_bool()
                    .ok_or(AccessibilityNormalizationError::InvalidState)
            })
            .transpose();
    }
    if value.value_type != "boolean" {
        return Err(AccessibilityNormalizationError::InvalidState);
    }
    value
        .value
        .as_ref()
        .and_then(serde_json::Value::as_bool)
        .map(Some)
        .ok_or(AccessibilityNormalizationError::InvalidState)
}
