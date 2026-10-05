//! Pure public scalar/catalog operations remain Rust-owned.

use std::cmp::Ordering;

use pyo3::prelude::*;
use serde_json::Value;
use yosoi::{
    contracts::{ContractValue, Money},
    map::{
        DiscoverySource, Observation, OmissionReason, PublicProvider, Rejection, Relationship,
        RelationshipKind,
    },
    search::SearchResultUrl,
};

use crate::errors::{MapError, SearchError};

#[pyfunction]
pub const fn contract_value_type_id(money: bool) -> &'static str {
    if money {
        <Money as ContractValue>::TYPE_ID
    } else {
        <String as ContractValue>::TYPE_ID
    }
}

fn provider(value: &str) -> PyResult<PublicProvider> {
    for item in PublicProvider::all() {
        let key =
            serde_json::to_value(item).map_err(|error| MapError::new_err(error.to_string()))?;
        if key.as_str() == Some(value) {
            return Ok(*item);
        }
    }
    Err(MapError::new_err("unknown public provider"))
}

#[pyfunction]
pub fn public_providers() -> PyResult<String> {
    serde_json::to_string(PublicProvider::all())
        .map_err(|error| MapError::new_err(error.to_string()))
}

#[pyfunction]
pub fn public_provider_name(value: &str) -> PyResult<&'static str> {
    Ok(provider(value)?.name())
}

#[pyfunction]
pub fn public_provider_endpoint(value: &str, domain: &str) -> PyResult<String> {
    provider(value)?
        .endpoint(domain)
        .map(|url| url.to_string())
        .map_err(|error| MapError::new_err(error.to_string()))
}

#[pyfunction]
pub fn search_result_url(value: &str) -> PyResult<String> {
    SearchResultUrl::parse(value)
        .map(|url| url.as_str().to_owned())
        .map_err(|error| SearchError::new_err(error.to_string()))
}

#[pyfunction]
pub fn rejection_message(value: &str) -> PyResult<String> {
    for rejection in [
        Rejection::InvalidUrl,
        Rejection::UnsupportedScheme,
        Rejection::Credentials,
        Rejection::HostScope,
        Rejection::OriginScope,
        Rejection::PathScope,
        Rejection::Filtered,
        Rejection::UrlLength,
        Rejection::InvalidHost,
        Rejection::UnsupportedDomainScope,
        Rejection::HostnameLength,
    ] {
        let key = serde_json::to_value(rejection)
            .map_err(|error| MapError::new_err(error.to_string()))?;
        if key.as_str() == Some(value) {
            return Ok(rejection.to_string());
        }
    }
    Err(MapError::new_err("unknown map rejection"))
}

fn parse_json(value: &str, side: &str) -> PyResult<Value> {
    serde_json::from_str(value)
        .map_err(|error| MapError::new_err(format!("invalid {side} map ordering value: {error}")))
}

fn object_field<'a>(value: &'a Value, key: &str, kind: &str) -> PyResult<&'a Value> {
    value
        .as_object()
        .and_then(|object| object.get(key))
        .ok_or_else(|| MapError::new_err(format!("{kind} ordering value needs field {key:?}")))
}

fn string_value<'a>(value: &'a Value, kind: &str) -> PyResult<&'a str> {
    value
        .as_str()
        .ok_or_else(|| MapError::new_err(format!("{kind} ordering value must be a string")))
}

fn enum_tag<'a>(value: &'a Value, kind: &str) -> PyResult<&'a str> {
    let tag = object_field(value, "kind", kind)?;
    string_value(tag, kind)
}

fn optional_enum_value(value: &Value) -> Option<&Value> {
    match value.as_object().and_then(|object| object.get("value")) {
        None | Some(Value::Null) => None,
        Some(value) => Some(value),
    }
}

fn require_unit_value(value: &Value, kind: &str, variant: &str) -> PyResult<()> {
    if optional_enum_value(value).is_some() {
        return Err(MapError::new_err(format!(
            "{kind} variant {variant:?} does not accept a value"
        )));
    }
    Ok(())
}

fn decode_discovery_source(value: &Value) -> PyResult<DiscoverySource> {
    let tag = enum_tag(value, "discovery_source")?;
    match tag {
        "seed" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::Seed)
        }
        "html_link" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::HtmlLink)
        }
        "xml_link" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::XmlLink)
        }
        "passive_provider" => {
            let provider_value = optional_enum_value(value)
                .ok_or_else(|| MapError::new_err("passive_provider requires a provider value"))?;
            let provider = provider(string_value(provider_value, "public_provider")?)?;
            Ok(DiscoverySource::PassiveProvider(provider))
        }
        "sitemap" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::Sitemap)
        }
        "robots" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::Robots)
        }
        "redirect" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::Redirect)
        }
        "passive_certificate" => {
            require_unit_value(value, "discovery_source", tag)?;
            Ok(DiscoverySource::PassiveCertificate)
        }
        _ => Err(MapError::new_err(format!(
            "unknown discovery source {tag:?}"
        ))),
    }
}

fn decode_rejection(value: &Value) -> PyResult<Rejection> {
    let value = string_value(value, "rejection")?;
    for rejection in [
        Rejection::InvalidUrl,
        Rejection::UnsupportedScheme,
        Rejection::Credentials,
        Rejection::HostScope,
        Rejection::OriginScope,
        Rejection::PathScope,
        Rejection::Filtered,
        Rejection::UrlLength,
        Rejection::InvalidHost,
        Rejection::UnsupportedDomainScope,
        Rejection::HostnameLength,
    ] {
        let key = serde_json::to_value(rejection)
            .map_err(|error| MapError::new_err(error.to_string()))?;
        if key.as_str() == Some(value) {
            return Ok(rejection);
        }
    }
    Err(MapError::new_err(format!(
        "unknown map rejection {value:?}"
    )))
}

fn decode_omission_reason(value: &Value) -> PyResult<OmissionReason> {
    let tag = enum_tag(value, "omission_reason")?;
    match tag {
        "admission" => {
            let rejection = optional_enum_value(value)
                .ok_or_else(|| MapError::new_err("admission omission requires a rejection"))?;
            Ok(OmissionReason::Admission(decode_rejection(rejection)?))
        }
        "robots" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Robots)
        }
        "depth" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Depth)
        }
        "sitemap_depth" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::SitemapDepth)
        }
        "pending" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Pending)
        }
        "inventory" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Inventory)
        }
        "retention" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Retention)
        }
        "wildcard" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Wildcard)
        }
        "other" => {
            require_unit_value(value, "omission_reason", tag)?;
            Ok(OmissionReason::Other)
        }
        _ => Err(MapError::new_err(format!(
            "unknown omission reason {tag:?}"
        ))),
    }
}

fn decode_relationship_kind(value: &Value) -> PyResult<RelationshipKind> {
    match string_value(value, "relationship_kind")? {
        "link" => Ok(RelationshipKind::Link),
        "redirect" => Ok(RelationshipKind::Redirect),
        "canonical" => Ok(RelationshipKind::Canonical),
        value => Err(MapError::new_err(format!(
            "unknown relationship kind {value:?}"
        ))),
    }
}

fn decode_observation(value: &Value) -> PyResult<Observation> {
    let source = decode_discovery_source(object_field(value, "source", "observation")?)?;
    let source_url = match object_field(value, "source_url", "observation")? {
        Value::Null => None,
        source_url => {
            let source_url = string_value(source_url, "observation source_url")?;
            Some(source_url.parse().map_err(|error| {
                MapError::new_err(format!("invalid observation source_url: {error}"))
            })?)
        }
    };
    Ok(Observation { source, source_url })
}

fn decode_relationship(value: &Value) -> PyResult<Relationship> {
    let from = string_value(
        object_field(value, "from", "relationship")?,
        "relationship from",
    )?
    .parse()
    .map_err(|error| MapError::new_err(format!("invalid relationship from URL: {error}")))?;
    let to = string_value(
        object_field(value, "to", "relationship")?,
        "relationship to",
    )?
    .parse()
    .map_err(|error| MapError::new_err(format!("invalid relationship to URL: {error}")))?;
    let kind = decode_relationship_kind(object_field(value, "kind", "relationship")?)?;
    Ok(Relationship { from, to, kind })
}

fn ordering_value<T: Ord>(left: &T, right: &T) -> i8 {
    match left.cmp(right) {
        Ordering::Less => -1,
        Ordering::Equal => 0,
        Ordering::Greater => 1,
    }
}

/// Compare serialized SDK Map values using their public Rust `Ord` contract.
#[pyfunction]
pub fn map_value_compare(kind: &str, left_json: &str, right_json: &str) -> PyResult<i8> {
    let left = parse_json(left_json, "left")?;
    let right = parse_json(right_json, "right")?;
    match kind {
        "discovery_source" => Ok(ordering_value(
            &decode_discovery_source(&left)?,
            &decode_discovery_source(&right)?,
        )),
        "observation" => Ok(ordering_value(
            &decode_observation(&left)?,
            &decode_observation(&right)?,
        )),
        "omission_reason" => Ok(ordering_value(
            &decode_omission_reason(&left)?,
            &decode_omission_reason(&right)?,
        )),
        "public_provider" => Ok(ordering_value(
            &provider(string_value(&left, "public_provider")?)?,
            &provider(string_value(&right, "public_provider")?)?,
        )),
        "rejection" => Ok(ordering_value(
            &decode_rejection(&left)?,
            &decode_rejection(&right)?,
        )),
        "relationship" => Ok(ordering_value(
            &decode_relationship(&left)?,
            &decode_relationship(&right)?,
        )),
        "relationship_kind" => Ok(ordering_value(
            &decode_relationship_kind(&left)?,
            &decode_relationship_kind(&right)?,
        )),
        _ => Err(MapError::new_err(format!(
            "unknown map ordering type {kind:?}"
        ))),
    }
}
