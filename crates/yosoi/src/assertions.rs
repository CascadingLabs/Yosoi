//! Immediate, local Rust predicates over one validated Contract observation.

use crate::locators;
use crate::session;
use crate::{
    contracts::{ContractOutcome, FieldIssue, ValidateContract},
    documents::Document,
    locators::{LocateOutcome, Plan},
    policy::Policy,
    session::new_operation_id,
};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::any as std_any;
use std::panic as std_panic;
use std::{
    fmt,
    io::{self, Write},
    sync::Arc,
};
use thiserror::Error;
#[cfg(feature = "browser")]
use tokio::task::spawn_blocking;

/// Maximum predicates retained in one validated local assertion group.
pub const MAX_CHECKS: usize = 128;
/// Maximum UTF-8 bytes in a nonblank authored predicate name.
pub const MAX_CHECK_NAME_BYTES: usize = 256;
/// Maximum UTF-8 bytes retained for a predicate evaluation error message.
pub const MAX_CHECK_ERROR_BYTES: usize = 1_024;
/// Maximum UTF-8 bytes identifying the Contract type in a saved assertion descriptor.
pub const MAX_ASSERTION_CONTRACT_TYPE_BYTES: usize = 256;

/// A pure comparison. Captures may borrow when evaluated as a local group.
pub struct Check<'a, C> {
    name: Option<String>,
    predicate: Arc<dyn Fn(&C) -> bool + Send + Sync + 'a>,
}
impl<C> fmt::Debug for Check<'_, C> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Check")
            .field("name", &self.name)
            .finish_non_exhaustive()
    }
}
/// Captures a synchronous local predicate without evaluating it or performing browser I/O.
/// The predicate can borrow caller state for `'a`; naming and evaluation are explicit.
pub fn check<'a, C>(predicate: impl Fn(&C) -> bool + Send + Sync + 'a) -> Check<'a, C> {
    Check {
        name: None,
        predicate: Arc::new(predicate),
    }
}
impl<C> Check<'_, C> {
    /// Attaches an authored diagnostic name, validated when the group is evaluated.
    /// The name must then be nonblank and within [`MAX_CHECK_NAME_BYTES`].
    pub fn named(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }
}

/// Group evaluation is synchronous after asynchronous capture; no retry is implied.
pub struct AssertionGroup<'a, C> {
    plan: Plan,
    checks: Vec<Check<'a, C>>,
}
impl<C> fmt::Debug for AssertionGroup<'_, C> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("AssertionGroup")
            .field("plan", &self.plan)
            .field("checks", &self.checks)
            .finish()
    }
}
impl<'a, C: ValidateContract> AssertionGroup<'a, C> {
    /// Owns a locator plan and local checks without executing or validating them yet.
    /// Collection is bounded to detect an excess check count at evaluation;
    /// predicates and names are checked by the evaluation path rather than silently dropped.
    pub fn new(plan: Plan, checks: impl IntoIterator<Item = Check<'a, C>>) -> Self {
        Self {
            plan,
            checks: checks.into_iter().take(MAX_CHECKS + 1).collect(),
        }
    }
    /// Locates and validates one Contract record, then evaluates all local checks with default policy.
    /// Performs no network acquisition or retry. Structural assertion failures
    /// return [`AssertionError`]; source and predicate failures remain in the report.
    pub fn evaluate(&self, document: &Document) -> Result<AssertionReport, AssertionError> {
        self.evaluate_with_policy(document, &Policy::default())
    }
    /// Evaluates one retained document using the supplied complete locator policy.
    ///
    /// Requires exactly one accepted Contract record without field or extraction
    /// issues before predicates can run. All ordinary predicates run even after
    /// a false result; predicate panics become check errors. Returns structural
    /// [`AssertionError`] failures or a report retaining source and predicate evidence.
    pub fn evaluate_with_policy(
        &self,
        document: &Document,
        policy: &Policy,
    ) -> Result<AssertionReport, AssertionError> {
        validate_checks(self.checks.iter().map(|check| check.name.as_deref()))?;
        let located = document.bind(policy).locate(&self.plan);
        let mut report = AssertionReport {
            passed: false,
            checks: self
                .checks
                .iter()
                .enumerate()
                .map(|(index, check)| CheckResult {
                    index,
                    name: check.name.clone(),
                    passed: None,
                    error: None,
                })
                .collect(),
            source_error: None,
            field_issues: Vec::new(),
            extraction_diagnostics: Vec::new(),
            located,
        };
        match C::validate_contract(&report.located) {
            ContractOutcome::Evaluated {
                records,
                issues,
                extraction_diagnostics,
                ..
            } => {
                let had_issues = !issues.is_empty();
                report.field_issues = issues.into_iter().flat_map(|issue| issue.fields).collect();
                report.extraction_diagnostics = extraction_diagnostics
                    .into_iter()
                    .map(serde_json::to_value)
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(|_| AssertionError::ReportEncoding)?;
                if had_issues
                    || !report.field_issues.is_empty()
                    || !report.extraction_diagnostics.is_empty()
                {
                    report.source_error = Some(SourceError::InvalidContract);
                } else if records.len() != 1 {
                    report.source_error = Some(SourceError::RecordCount {
                        actual: records.len(),
                    });
                } else if let Some(record) = records.first() {
                    // All normal predicates run, including those after a false result.
                    for (check, result) in self.checks.iter().zip(&mut report.checks) {
                        match std_panic::catch_unwind(std_panic::AssertUnwindSafe(|| {
                            (check.predicate)(&record.value)
                        })) {
                            Ok(passed) => result.passed = Some(passed),
                            Err(_) => result.error = Some(CheckError::Panicked),
                        }
                    }
                    report.passed = report.checks.iter().all(|check| check.passed == Some(true));
                }
            }
            ContractOutcome::NoMatch { .. } => {
                report.source_error = Some(SourceError::RecordCount { actual: 0 });
            }
            ContractOutcome::Indeterminate { .. } => {
                report.source_error = Some(SourceError::IncompleteEvidence);
            }
            ContractOutcome::LocateFailed { .. } => {
                report.source_error = Some(SourceError::LocateFailed);
            }
            ContractOutcome::ExtractionRejected { .. } => {
                report.source_error = Some(SourceError::ExtractionRejected);
            }
            ContractOutcome::ValidationRejected { .. } => {
                report.source_error = Some(SourceError::ValidationRejected);
            }
        }
        Ok(report)
    }
}

/// One local predicate result, including unevaluated and evaluator-failure distinctions.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CheckResult {
    /// Zero-based position in the authored check list.
    pub index: usize,
    /// Authored nonblank diagnostic name, absent for an unnamed check.
    pub name: Option<String>,
    /// Predicate result, or `None` when no boolean result was established.
    pub passed: Option<bool>,
    /// Evaluator failure, distinct from a predicate returning false.
    pub error: Option<CheckError>,
}

/// Predicate evaluator failed rather than returning an accepted boolean result.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CheckError {
    /// Local predicate code unwound; subsequent ordinary predicates can still be evaluated.
    Panicked,
    /// An external predicate evaluator returned a bounded failure message.
    EvaluationFailed {
        /// Retained evaluator explanation, not a successful predicate result.
        message: String,
    },
}
/// Source evidence cannot provide the one accepted record needed for local predicates.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SourceError {
    /// The accepted record count is not exactly one.
    RecordCount {
        /// Number of accepted Contract records, including zero for complete no-match.
        actual: usize,
    },
    /// Field issues or extraction diagnostics prevented an all-accepted record claim.
    InvalidContract,
    /// Partial or unknown evidence prevents complete Contract evaluation.
    IncompleteEvidence,
    /// Locator execution failed before Contract evaluation.
    LocateFailed,
    /// Schema or resource checks rejected candidate assembly.
    ExtractionRejected,
    /// Schema or accounting budgets rejected record validation.
    ValidationRejected,
}
/// One immediate assertion evaluation with retained source, field, and predicate evidence.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AssertionReport {
    /// True only when source evaluation succeeded and every predicate returned true.
    pub passed: bool,
    /// Authored checks in order, including checks without a boolean result.
    pub checks: Vec<CheckResult>,
    /// Source-level rejection that prevented ordinary predicate evaluation, when present.
    pub source_error: Option<SourceError>,
    /// Retained field rejection details from Contract validation.
    pub field_issues: Vec<FieldIssue>,
    /// Retained serialized candidate-grouping diagnostics.
    pub extraction_diagnostics: Vec<serde_json::Value>,
    /// Exact located values/coordinates, including evidence for successful records.
    pub located: LocateOutcome,
}
/// Structural or binding failure preventing a supported assertion report.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum AssertionError {
    /// Retained diagnostic evidence could not be encoded into the supported report format.
    #[error("assertion diagnostic could not be encoded")]
    ReportEncoding,
    /// The authored group contains zero checks or exceeds [`MAX_CHECKS`].
    #[error("assertion groups require 1..={MAX_CHECKS} checks")]
    CheckCount,
    /// A supplied predicate name is blank or exceeds its UTF-8 byte bound.
    #[error("check names must be nonempty and at most {MAX_CHECK_NAME_BYTES} bytes")]
    CheckName,
    /// A saved descriptor has not been rebound to local predicate code or an external evaluator.
    #[error("local Rust assertion checks must be rebound before invocation")]
    Unbound,
    /// The assertion's authored plan exceeds its permitted encoded input bytes.
    #[error("assertion plan exceeds the configured input bound")]
    PlanLimit,
    /// The saved Contract type identifier is blank or exceeds its UTF-8 byte bound.
    #[error(
        "assertion Contract type identifier must be nonempty and at most {MAX_ASSERTION_CONTRACT_TYPE_BYTES} bytes"
    )]
    ContractType,
    /// External evaluator invocation failed before yielding a valid report.
    #[error("external assertion evaluator failed: {0}")]
    ExternalEvaluator(String),
    /// An external evaluator returned structurally invalid or inconsistent report evidence.
    #[error("external assertion evaluator returned an invalid report")]
    ExternalReport,
    /// The task executing predicate evaluation failed to settle successfully.
    #[error("assertion evaluator task failed")]
    EvaluatorTask,
}
fn validate_checks<'a>(names: impl Iterator<Item = Option<&'a str>>) -> Result<(), AssertionError> {
    let mut count = 0usize;
    for name in names {
        count = count.checked_add(1).ok_or(AssertionError::CheckCount)?;
        if count > MAX_CHECKS {
            return Err(AssertionError::CheckCount);
        }
        if name.is_some_and(|name| name.trim().is_empty() || name.len() > MAX_CHECK_NAME_BYTES) {
            return Err(AssertionError::CheckName);
        }
    }
    if count == 0 {
        return Err(AssertionError::CheckCount);
    }
    Ok(())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    id: String,
    contract_type: String,
    plan: Plan,
    names: Vec<Option<String>>,
}
type Evaluator = dyn Fn(&Document, &Policy, usize, usize) -> Result<AssertionReport, AssertionError>
    + Send
    + Sync;

/// A local executable group plus a portable description. Closure code is never serialized.
#[derive(Clone)]
pub struct LocalAssertion {
    descriptor: Box<Descriptor>,
    evaluator: Option<Arc<Evaluator>>,
}
impl fmt::Debug for LocalAssertion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LocalAssertion")
            .field("descriptor", &self.descriptor)
            .field("bound", &self.evaluator.is_some())
            .finish()
    }
}
impl PartialEq for LocalAssertion {
    fn eq(&self, other: &Self) -> bool {
        self.descriptor == other.descriptor
    }
}
impl Eq for LocalAssertion {}
impl Serialize for LocalAssertion {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.descriptor.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for LocalAssertion {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let descriptor = Descriptor::deserialize(deserializer)?;
        Ok(Self {
            descriptor: Box::new(descriptor),
            evaluator: None,
        })
    }
}
impl LocalAssertion {
    pub(crate) fn new<C: ValidateContract + 'static>(
        plan: Plan,
        checks: impl IntoIterator<Item = Check<'static, C>>,
    ) -> Self {
        let group = AssertionGroup::<C>::new(plan, checks);
        let descriptor = Descriptor {
            id: session::new_operation_id(),
            contract_type: std_any::type_name::<C>().into(),
            plan: group.plan.clone(),
            names: group
                .checks
                .iter()
                .map(|check| check.name.clone())
                .collect(),
        };
        Self {
            descriptor: Box::new(descriptor),
            evaluator: Some(Arc::new(move |document, policy, _, _| {
                group.evaluate_with_policy(document, policy)
            })),
        }
    }

    /// Creates a portable descriptor for an evaluator supplied by another language runtime.
    /// The generated identity is owned by Rust and the executable callback is never serialized.
    pub fn new_external_descriptor(
        contract_type: String,
        plan: Plan,
        names: Vec<Option<String>>,
    ) -> Result<Self, AssertionError> {
        if contract_type.trim().is_empty()
            || contract_type.len() > MAX_ASSERTION_CONTRACT_TYPE_BYTES
        {
            return Err(AssertionError::ContractType);
        }
        validate_checks(names.iter().map(|name| name.as_deref()))?;
        let assertion = Self {
            descriptor: Box::new(Descriptor {
                id: new_operation_id(),
                contract_type,
                plan,
                names,
            }),
            evaluator: None,
        };
        assertion.validate(65_536)?;
        Ok(assertion)
    }

    /// Returns the Rust-generated descriptor identity used to rebind an external evaluator.
    pub fn descriptor_id(&self) -> &str {
        &self.descriptor.id
    }

    /// Binds an external evaluator to this exact saved plan, Contract type and check list.
    /// The callback receives the canonical located observation and the active Policy as JSON.
    pub fn rebind_external(
        &mut self,
        evaluator: impl Fn(&str, &str) -> Result<AssertionReport, AssertionError>
        + Send
        + Sync
        + 'static,
    ) {
        let descriptor = self.descriptor.clone();
        let plan = descriptor.plan.clone();
        self.evaluator = Some(Arc::new(
            move |document, policy, maximum_input, maximum_result| {
                let located = document.bind(policy).locate(&plan);
                let located_json = serialize_bounded(&located, maximum_input)?;
                let policy_json = serialize_bounded(policy, maximum_input)?;
                let report = evaluator(&located_json, &policy_json)?;
                validate_external_report(&descriptor, &located, &report, maximum_result)?;
                Ok(report)
            },
        ));
    }

    /// Returns whether executable predicate code or an external evaluator is bound to this descriptor.
    /// A deserialized descriptor alone cannot evaluate assertions until explicitly rebound.
    pub fn is_bound(&self) -> bool {
        self.evaluator.is_some()
    }
    pub(crate) fn report_matches_descriptor(&self, report: &AssertionReport) -> bool {
        if report.checks.len() != self.descriptor.names.len()
            || !report
                .checks
                .iter()
                .zip(&self.descriptor.names)
                .enumerate()
                .all(|(index, (check, name))| check.index == index && &check.name == name)
        {
            return false;
        }
        let LocateOutcome::Matched { result } = &report.located else {
            return false;
        };
        // Plan keeps its compiled internals private. Its portable wire shape
        // provides the declared output and region identities without closures.
        let Ok(plan) = serde_json::to_value(&self.descriptor.plan) else {
            return false;
        };
        let Some(outputs) = plan.get("outputs").and_then(serde_json::Value::as_array) else {
            return false;
        };
        let Some(regions) = plan.get("regions").and_then(serde_json::Value::as_array) else {
            return false;
        };
        result.findings().iter().all(|finding| {
            matches!(finding.completeness(), locators::Completeness::Complete)
                && outputs.iter().any(|output| {
                    output.get("id").and_then(serde_json::Value::as_str)
                        == Some(finding.output_id().as_str())
                        && output
                            .get("parent_region")
                            .and_then(serde_json::Value::as_str)
                            == finding
                                .parent_region()
                                .map(|region| region.region_id().as_str())
                })
        }) && result.regions().iter().all(|region| {
            regions.iter().any(|declared| {
                declared.get("id").and_then(serde_json::Value::as_str)
                    == Some(region.region_id().as_str())
            })
        })
    }
    pub(crate) fn validate(&self, maximum_bytes: usize) -> Result<(), AssertionError> {
        validate_checks(self.descriptor.names.iter().map(|name| name.as_deref()))?;
        if self.descriptor.contract_type.trim().is_empty()
            || self.descriptor.contract_type.len() > MAX_ASSERTION_CONTRACT_TYPE_BYTES
            || self.descriptor.id.trim().is_empty()
        {
            return Err(AssertionError::ContractType);
        }
        let encoded =
            serde_json::to_vec(&self.descriptor).map_err(|_| AssertionError::PlanLimit)?;
        if encoded.len() > maximum_bytes {
            return Err(AssertionError::PlanLimit);
        }
        Ok(())
    }
    /// Rebind exactly the saved contract, Plan and check names/positions.
    pub fn rebind<C: ValidateContract + 'static>(
        &mut self,
        checks: impl IntoIterator<Item = Check<'static, C>>,
    ) -> Result<(), AssertionError> {
        let replacement = Self::new::<C>(self.descriptor.plan.clone(), checks);
        if replacement.descriptor.contract_type != self.descriptor.contract_type
            || replacement.descriptor.names != self.descriptor.names
        {
            return Err(AssertionError::Unbound);
        }
        self.evaluator = replacement.evaluator;
        Ok(())
    }
    #[cfg(feature = "browser")]
    pub(crate) async fn evaluate(
        &self,
        document: &Document,
        policy: &Policy,
        maximum_input_bytes: usize,
        maximum_result_bytes: usize,
    ) -> Result<AssertionReport, AssertionError> {
        let assertion = self.clone();
        let document = document.clone();
        let policy = policy.clone();
        spawn_blocking(move || {
            assertion.evaluate_blocking(
                &document,
                &policy,
                maximum_input_bytes,
                maximum_result_bytes,
            )
        })
        .await
        .map_err(|_| AssertionError::EvaluatorTask)?
    }

    #[cfg(feature = "browser")]
    fn evaluate_blocking(
        &self,
        document: &Document,
        policy: &Policy,
        maximum_input_bytes: usize,
        maximum_result_bytes: usize,
    ) -> Result<AssertionReport, AssertionError> {
        let report = self.evaluator.as_ref().ok_or(AssertionError::Unbound)?(
            document,
            policy,
            maximum_input_bytes,
            maximum_result_bytes,
        )?;
        Ok(report)
    }
}

fn validate_external_report(
    descriptor: &Descriptor,
    expected_located: &LocateOutcome,
    report: &AssertionReport,
    maximum_result_bytes: usize,
) -> Result<(), AssertionError> {
    if !check_names_match(descriptor, &report.checks) {
        return Err(AssertionError::ExternalReport);
    }
    let expected_located =
        serde_json::to_value(expected_located).map_err(|_| AssertionError::ExternalReport)?;
    let actual_located =
        serde_json::to_value(&report.located).map_err(|_| AssertionError::ExternalReport)?;
    if expected_located != actual_located {
        return Err(AssertionError::ExternalReport);
    }
    if report.checks.iter().any(|check| {
        check.error.as_ref().is_some_and(|error| match error {
            CheckError::Panicked => true,
            CheckError::EvaluationFailed { message } => {
                message.trim().is_empty()
                    || message.len() > MAX_CHECK_ERROR_BYTES
                    || check.passed.is_some()
            }
        })
    }) {
        return Err(AssertionError::ExternalReport);
    }
    let all_passed = report
        .checks
        .iter()
        .all(|check| check.passed == Some(true) && check.error.is_none());
    if report.passed
        != (all_passed
            && report.source_error.is_none()
            && report.field_issues.is_empty()
            && report.extraction_diagnostics.is_empty())
    {
        return Err(AssertionError::ExternalReport);
    }
    if report.source_error.is_some()
        && report
            .checks
            .iter()
            .any(|check| check.passed.is_some() || check.error.is_some())
    {
        return Err(AssertionError::ExternalReport);
    }
    if report.source_error.is_none()
        && report.checks.iter().any(|check| {
            !matches!(
                (&check.passed, &check.error),
                (Some(_), None) | (None, Some(CheckError::EvaluationFailed { .. }))
            )
        })
    {
        return Err(AssertionError::ExternalReport);
    }
    if (!report.field_issues.is_empty() || !report.extraction_diagnostics.is_empty())
        && !matches!(report.source_error, Some(SourceError::InvalidContract))
    {
        return Err(AssertionError::ExternalReport);
    }
    serialize_bounded(report, maximum_result_bytes)?;
    Ok(())
}

fn check_names_match(descriptor: &Descriptor, checks: &[CheckResult]) -> bool {
    checks.len() == descriptor.names.len()
        && checks
            .iter()
            .zip(&descriptor.names)
            .enumerate()
            .all(|(index, (check, name))| check.index == index && &check.name == name)
}

fn serialize_bounded(
    value: &impl Serialize,
    maximum_bytes: usize,
) -> Result<String, AssertionError> {
    let mut writer = BoundedJsonWriter {
        maximum_bytes,
        ..BoundedJsonWriter::default()
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| AssertionError::ExternalReport)?;
    String::from_utf8(writer.bytes).map_err(|_| AssertionError::ExternalReport)
}

#[derive(Default)]
struct BoundedJsonWriter {
    bytes: Vec<u8>,
    maximum_bytes: usize,
}

impl Write for BoundedJsonWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let Some(next_len) = self.bytes.len().checked_add(buffer.len()) else {
            return Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "assertion JSON size overflow",
            ));
        };
        if next_len > self.maximum_bytes {
            return Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "assertion JSON exceeds the configured byte limit",
            ));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
