//! Own runtime Contracts and preserve extraction/validation outcome semantics.

use pyo3::prelude::*;
use yosoi::contracts::{
    ContractSchema, ExtractionLimits, FieldSchema, Money, RuntimeContract, RuntimeContractOutcome,
    RuntimeExtracted, ValidationLimits,
};
use yosoi::locators::LocateOutcome;

use crate::errors::ContractError;

fn encode(value: &impl serde::Serialize) -> PyResult<String> {
    serde_json::to_string(value).map_err(|error| ContractError::new_err(error.to_string()))
}

#[pyclass(frozen, module = "yosoi._native", name = "Contract")]
#[derive(Debug)]
pub struct NativeContract {
    inner: RuntimeContract,
}

#[pymethods]
impl NativeContract {
    #[new]
    fn new(schema_json: &str) -> PyResult<Self> {
        let schema: ContractSchema = serde_json::from_str(schema_json)
            .map_err(|error| ContractError::new_err(error.to_string()))?;
        let inner = RuntimeContract::new(schema)
            .map_err(|error| ContractError::new_err(error.to_string()))?;
        Ok(Self { inner })
    }

    fn identity(&self) -> PyResult<String> {
        self.inner
            .schema()
            .identity()
            .map(|identity| identity.to_string())
            .map_err(|error| ContractError::new_err(error.to_string()))
    }

    #[pyo3(signature = (located_json, limits_json=None))]
    fn extract(
        &self,
        py: Python<'_>,
        located_json: &str,
        limits_json: Option<&str>,
    ) -> PyResult<NativeExtracted> {
        let located: LocateOutcome = serde_json::from_str(located_json)
            .map_err(|error| ContractError::new_err(error.to_string()))?;
        let limits = limits_json
            .map(|json| {
                serde_json::from_str::<ExtractionLimitsWire>(json)
                    .map(ExtractionLimitsWire::into_limits)
                    .map_err(|error| ContractError::new_err(error.to_string()))
            })
            .transpose()?;
        Ok(py.detach(|| NativeExtracted {
            inner: match limits {
                Some(limits) => self.inner.extract_with_limits(&located, limits),
                None => self.inner.extract(&located),
            },
        }))
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "Extracted")]
#[derive(Debug)]
pub struct NativeExtracted {
    inner: RuntimeExtracted,
}

#[pymethods]
impl NativeExtracted {
    fn to_json(&self) -> PyResult<String> {
        encode(&self.inner)
    }

    #[pyo3(signature = (limits_json=None))]
    fn validate(
        &self,
        py: Python<'_>,
        limits_json: Option<&str>,
    ) -> PyResult<NativeContractOutcome> {
        let limits = limits_json
            .map(|json| {
                serde_json::from_str::<ValidationLimitsWire>(json)
                    .map(ValidationLimitsWire::into_limits)
                    .map_err(|error| ContractError::new_err(error.to_string()))
            })
            .transpose()?;
        Ok(py.detach(|| NativeContractOutcome {
            inner: match limits {
                Some(limits) => self.inner.clone().validate_with_limits(limits),
                None => self.inner.clone().validate(),
            },
        }))
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "ContractOutcome")]
#[derive(Debug)]
pub struct NativeContractOutcome {
    inner: RuntimeContractOutcome,
}

#[pymethods]
impl NativeContractOutcome {
    fn to_json(&self) -> PyResult<String> {
        encode(&self.inner)
    }

    fn require_all(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| match self.inner.clone().require_all() {
            Ok(records) => encode(&serde_json::json!({"records": records})),
            Err(error) => encode(&serde_json::json!({"error": error})),
        })
    }
}

#[pyfunction]
pub fn validate_money(value: &str) -> PyResult<String> {
    let money: Money =
        serde_json::from_str(value).map_err(|error| ContractError::new_err(error.to_string()))?;
    Ok(money.to_string())
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ExtractionLimitsWire {
    max_scanned_regions: u64,
    max_scanned_findings: u64,
    max_matching_findings: u64,
    max_candidates: u64,
    max_values_per_field: u64,
    max_retained_evidence: u64,
    max_diagnostics: u64,
}
impl ExtractionLimitsWire {
    fn into_limits(self) -> ExtractionLimits {
        ExtractionLimits {
            max_scanned_regions: self.max_scanned_regions,
            max_scanned_findings: self.max_scanned_findings,
            max_matching_findings: self.max_matching_findings,
            max_candidates: self.max_candidates,
            max_values_per_field: self.max_values_per_field,
            max_retained_evidence: self.max_retained_evidence,
            max_diagnostics: self.max_diagnostics,
        }
    }
}
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ValidationLimitsWire {
    max_fields: u64,
    max_records: u64,
    max_conversions: u64,
    max_issues: u64,
    max_retained_provenance: u64,
}
impl ValidationLimitsWire {
    fn into_limits(self) -> ValidationLimits {
        ValidationLimits {
            max_fields: self.max_fields,
            max_records: self.max_records,
            max_conversions: self.max_conversions,
            max_issues: self.max_issues,
            max_retained_provenance: self.max_retained_provenance,
        }
    }
}
#[pyfunction]
pub fn validation_limits_defaults() -> PyResult<String> {
    let limits = ValidationLimits::default();
    encode(
        &serde_json::json!({"max_fields": limits.max_fields, "max_records": limits.max_records,
        "max_conversions": limits.max_conversions, "max_issues": limits.max_issues,
        "max_retained_provenance": limits.max_retained_provenance}),
    )
}
#[pyfunction]
pub fn contract_schema_identity(value: &str) -> PyResult<String> {
    let schema: ContractSchema =
        serde_json::from_str(value).map_err(|error| ContractError::new_err(error.to_string()))?;
    schema
        .identity()
        .map(|identity| identity.to_string())
        .map_err(|error| ContractError::new_err(error.to_string()))
}

#[pyfunction]
pub fn field_schema_validate(value: &str) -> PyResult<()> {
    serde_json::from_str::<FieldSchema>(value)
        .map(|_| ())
        .map_err(|error| ContractError::new_err(error.to_string()))
}
