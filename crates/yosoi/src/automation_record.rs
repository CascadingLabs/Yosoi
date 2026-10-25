//! Versioned, offline-first automation evidence records.
//!
//! This first-pass container stores one bounded JSON record as a validated
//! Yosoi text Document. The Archive's immutable Document reference is the
//! durable identity; source observation IDs and their session/tab coordinates
//! remain the provenance carried by the record itself.

use crate::assertions;
use crate::browser as browser_config;
use crate::flow;
use crate::internal::engine as internal_engine;
use crate::locators;
use crate::session;
use std::error as std_error;
use std::io as std_io;
use std::{fmt, io::Write};

use serde::{Deserialize, Serialize};

use crate::{
    documents::{DocumentClass, DocumentProfile},
    flow::{
        Continuation, Flow, FlowCancellationCause, FlowFailureCause, FlowOutcome, FlowPolicy,
        FlowStopCause, FlowTermination, Step, StopScope,
    },
};

/// Current logical schema version for an [`AutomationRecord`].
pub const AUTOMATION_RECORD_VERSION: u32 = 1;

/// Maximum encoded record size accepted by this prototype container.
pub const MAX_AUTOMATION_RECORD_BYTES: u64 = 64 * 1024 * 1024;

/// Maximum number of observations or operation receipts in one record.
pub const MAX_AUTOMATION_RECORD_ITEMS: usize = 4_096;

/// Maximum retained HTML bytes in one observation.
pub const MAX_OBSERVATION_HTML_BYTES: usize = 6 * 1024 * 1024;

/// Maximum retained screenshot bytes in one observation.
pub const MAX_OBSERVATION_SCREENSHOT_BYTES: usize = 2 * 1024 * 1024;

/// Maximum combined raw HTML and screenshot bytes in one record.
pub const MAX_AUTOMATION_RECORD_EVIDENCE_BYTES: usize = 8 * 1024 * 1024;

/// A browser observation retained as primary evidence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    /// Optional native-engine provenance; absent in legacy Chrome records.
    /// This records identity and declarations, not live browser authority.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub browser: Option<browser_config::BrowserExecutionIdentity>,
    /// Unique identity of this retained observation within the record.
    pub id: String,
    /// Browser Session provenance; it does not reopen or grant authority to that Session.
    pub session_id: String,
    /// Source tab provenance, distinct from a live tab-control handle.
    pub tab_id: String,
    /// Positive source-document generation used to bind DOM evidence.
    pub document_epoch: u64,
    /// Captured HTML bytes represented as text, absent when not retained.
    pub html: Option<String>,
    /// Observed source URL, if available; it can contain user-sensitive data.
    pub url: Option<String>,
    /// Retained screenshot bytes, subject to observation and aggregate record limits.
    pub screenshot: Option<Vec<u8>>,
}

/// The execution certainty attached to one attempted browser operation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationStatus {
    /// The operation returned a supported observed result; business success needs its own check.
    Observed,
    /// The operation or assertion returned a known rejection.
    Rejected,
    /// Possible dispatch or incomplete evidence prevents establishing the effect.
    Unknown,
}

/// One operation result and the evidence observed alongside it.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OperationReceipt {
    /// Admitted/reported native-engine identity, retained even without after-state.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub browser: Option<browser_config::BrowserExecutionIdentity>,
    /// Unique identity correlating this operation with recorded Flow evidence.
    pub id: String,
    /// Operation category label, such as navigate, click, or until.
    pub kind: String,
    /// Effect certainty, separate from authored continuation or business completion.
    pub status: OperationStatus,
    /// Bounded operation-specific result payload, absent when none was established.
    pub result: Option<serde_json::Value>,
    /// Current-tab evidence captured alongside the operation, if available.
    pub observation: Option<Observation>,
    /// Retained failure or uncertainty explanation; it does not undo external effects.
    pub error: Option<String>,
}

/// One immutable Archive handle and the logical record schema version.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationRecordRef {
    version: u32,
    document: internal_engine::DocumentArchiveRef,
}

impl AutomationRecordRef {
    /// Returns the logical record schema version named by this reference.
    pub const fn version(&self) -> u32 {
        self.version
    }

    /// Returns the exact immutable Document reference persisted in Archive.
    pub const fn document(&self) -> &internal_engine::DocumentArchiveRef {
        &self.document
    }
}

/// Run provenance recorded alongside canonical evidence.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationContext {
    /// Recorded resolved Policy identity used for the run.
    pub effective_policy_identity: String,
    /// Execution and evidence settings recorded for the owning Session.
    pub session_policy: session::SessionPolicy,
    /// Recorded browser provider label, not a live provider handle.
    pub provider: String,
    /// Browser identity recorded by the caller, absent when unavailable.
    pub browser_identity: Option<String>,
    /// Source revision provenance supplied by the caller, not verified by capture itself.
    pub source_revision: Option<String>,
    /// Immutable parent record reference for linking separate evidence records.
    pub parent: Option<AutomationRecordRef>,
}

/// A bounded versioned set of observations and operation receipts.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationRecord {
    version: u32,
    id: String,
    observations: Vec<Observation>,
    operations: Vec<OperationReceipt>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    flow_outcome: Option<FlowOutcome>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    context: Option<AutomationContext>,
}

impl AutomationRecord {
    /// Retains one Flow outcome, including cleanup and failure-capture receipts.
    ///
    /// Observations are deduplicated by identity only when their evidence agrees.
    /// Rejected and unknown operations remain unchanged. Returns a record error
    /// for inconsistent identities, invalid outcomes or excessive retained data.
    pub fn from_flow(
        id: impl Into<String>,
        outcome: FlowOutcome,
    ) -> Result<Self, AutomationRecordError> {
        let operations: Vec<_> = outcome
            .steps
            .iter()
            .map(|step| step.receipt.clone())
            .chain(outcome.cleanup.iter().cloned())
            .chain(outcome.failure_capture.iter().cloned())
            .collect();
        let mut observations: Vec<Observation> = Vec::new();
        for observation in operations
            .iter()
            .filter_map(|operation| operation.observation.as_ref())
        {
            if let Some(prior) = observations.iter().find(|prior| prior.id == observation.id) {
                if prior != observation {
                    return Err(AutomationRecordError::DuplicateIdentity {
                        field: "observation",
                    });
                }
            } else {
                observations.push(observation.clone());
            }
        }
        Self::new(id, observations, operations)?.with_flow_outcome(outcome)
    }

    /// Creates a record after validating its stable identity and retained size.
    pub fn new(
        id: impl Into<String>,
        observations: Vec<Observation>,
        operations: Vec<OperationReceipt>,
    ) -> Result<Self, AutomationRecordError> {
        let record = Self {
            version: AUTOMATION_RECORD_VERSION,
            id: id.into(),
            observations,
            operations,
            flow_outcome: None,
            context: None,
        };
        record.validate()?;
        Ok(record)
    }

    /// Returns the logical record schema version.
    pub const fn version(&self) -> u32 {
        self.version
    }

    /// Returns the caller-authored stable record identity.
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Returns observations in their recorded order.
    pub fn observations(&self) -> &[Observation] {
        &self.observations
    }

    /// Returns operation receipts in their recorded order.
    pub fn operations(&self) -> &[OperationReceipt] {
        &self.operations
    }

    /// Returns the recorded flow definition and ordered step outcomes, if present.
    pub const fn flow_outcome(&self) -> Option<&FlowOutcome> {
        self.flow_outcome.as_ref()
    }

    /// Borrows optional run provenance without reopening browser resources.
    pub const fn context(&self) -> Option<&AutomationContext> {
        self.context.as_ref()
    }

    /// Attaches owned run provenance after validating bounded context fields and the record.
    /// Returns [`AutomationRecordError`] for invalid record shape or excessive retained bytes.
    /// Caller-supplied browser and source identities remain provenance claims, not live authority.
    pub fn with_context(
        mut self,
        context: AutomationContext,
    ) -> Result<Self, AutomationRecordError> {
        let maximum = [
            context.effective_policy_identity.len(),
            context.provider.len(),
            context.browser_identity.as_ref().map_or(0, String::len),
            context.source_revision.as_ref().map_or(0, String::len),
        ]
        .into_iter()
        .max()
        .unwrap_or(0);
        if maximum > 4096 {
            return Err(AutomationRecordError::EncodedSizeExceeded {
                maximum: 4096,
                observed: u64::try_from(maximum).unwrap_or(u64::MAX),
            });
        }
        self.context = Some(context);
        self.validate()?;
        Ok(self)
    }

    /// Attaches a typed flow definition and its recorded step outcomes.
    pub fn with_flow_outcome(
        mut self,
        flow_outcome: FlowOutcome,
    ) -> Result<Self, AutomationRecordError> {
        self.flow_outcome = Some(flow_outcome);
        self.validate()?;
        Ok(self)
    }

    /// Adds an observation while preserving unique observation identities.
    pub fn push_observation(
        &mut self,
        observation: Observation,
    ) -> Result<(), AutomationRecordError> {
        if self.observations.len() >= MAX_AUTOMATION_RECORD_ITEMS {
            return Err(AutomationRecordError::ItemLimitExceeded {
                field: "observations",
                maximum: MAX_AUTOMATION_RECORD_ITEMS,
            });
        }
        if self
            .observations
            .iter()
            .any(|existing| existing.id == observation.id)
        {
            return Err(AutomationRecordError::DuplicateIdentity {
                field: "observation",
            });
        }
        validate_observation(&observation)?;
        self.observations.push(observation);
        if let Err(error) = self.validate_evidence_size() {
            let _ = self.observations.pop();
            return Err(error);
        }
        Ok(())
    }

    /// Adds one operation receipt in recorded order.
    pub fn push_operation(
        &mut self,
        operation: OperationReceipt,
    ) -> Result<(), AutomationRecordError> {
        if self.operations.len() >= MAX_AUTOMATION_RECORD_ITEMS {
            return Err(AutomationRecordError::ItemLimitExceeded {
                field: "operations",
                maximum: MAX_AUTOMATION_RECORD_ITEMS,
            });
        }
        if self
            .operations
            .iter()
            .any(|existing| existing.id == operation.id)
        {
            return Err(AutomationRecordError::DuplicateIdentity {
                field: "operation receipt",
            });
        }
        validate_identity("operation receipt id", &operation.id)?;
        validate_identity("operation kind", &operation.kind)?;
        validate_browser_provenance(&operation)?;
        if let Some(observation) = &operation.observation {
            validate_observation(observation)?;
        }
        self.operations.push(operation);
        if let Err(error) = self.validate_evidence_size() {
            let _ = self.operations.pop();
            return Err(error);
        }
        Ok(())
    }

    /// Writes this record as an immutable text Document and returns its handle.
    pub async fn write_to(
        &self,
        archive: &internal_engine::Archive,
    ) -> Result<AutomationRecordRef, AutomationRecordError> {
        self.validate()?;
        let bytes = encode_record(self)?;

        let document = internal_engine::Document::text(self.id.clone(), bytes)
            .map_err(|error| AutomationRecordError::Document(error.to_string()))?;
        let reference = archive
            .write(document.archive_value())
            .await
            .map_err(|error| AutomationRecordError::Archive(error.to_string()))?;
        Ok(AutomationRecordRef {
            version: self.version,
            document: reference,
        })
    }

    /// Reads and validates one archived record without browser or network work.
    pub async fn read_from(
        archive: &internal_engine::Archive,
        reference: &AutomationRecordRef,
    ) -> Result<Self, AutomationRecordError> {
        if reference.version != AUTOMATION_RECORD_VERSION {
            return Err(AutomationRecordError::UnsupportedVersion {
                observed: reference.version,
                supported: AUTOMATION_RECORD_VERSION,
            });
        }
        let archived = archive
            .read(&reference.document)
            .await
            .map_err(|error| AutomationRecordError::Archive(error.to_string()))?;
        let document = internal_engine::Document::from_archived(archived);
        if document.class() != DocumentClass::SourceText
            || document.profile() != DocumentProfile::source_text()
        {
            return Err(AutomationRecordError::WrongDocumentProfile);
        }
        let observed = document.byte_len();
        if observed > MAX_AUTOMATION_RECORD_BYTES {
            return Err(AutomationRecordError::EncodedSizeExceeded {
                maximum: MAX_AUTOMATION_RECORD_BYTES,
                observed,
            });
        }
        let record: Self = serde_json::from_slice(document.bytes())
            .map_err(|error| AutomationRecordError::Serialization(error.to_string()))?;
        record.validate()?;
        if record.version != reference.version {
            return Err(AutomationRecordError::UnsupportedVersion {
                observed: record.version,
                supported: reference.version,
            });
        }
        if document.id().as_str() != record.id.as_str() {
            return Err(AutomationRecordError::DocumentIdentityMismatch);
        }
        Ok(record)
    }

    pub(crate) fn validate(&self) -> Result<(), AutomationRecordError> {
        if self.version != AUTOMATION_RECORD_VERSION {
            return Err(AutomationRecordError::UnsupportedVersion {
                observed: self.version,
                supported: AUTOMATION_RECORD_VERSION,
            });
        }
        validate_identity("record id", &self.id)?;
        if self.observations.len() > MAX_AUTOMATION_RECORD_ITEMS {
            return Err(AutomationRecordError::ItemLimitExceeded {
                field: "observations",
                maximum: MAX_AUTOMATION_RECORD_ITEMS,
            });
        }
        if self.operations.len() > MAX_AUTOMATION_RECORD_ITEMS {
            return Err(AutomationRecordError::ItemLimitExceeded {
                field: "operations",
                maximum: MAX_AUTOMATION_RECORD_ITEMS,
            });
        }
        let mut observation_ids = Vec::with_capacity(self.observations.len());
        for observation in &self.observations {
            validate_observation(observation)?;
            if observation_ids
                .iter()
                .any(|id: &&String| id.as_str() == observation.id.as_str())
            {
                return Err(AutomationRecordError::DuplicateIdentity {
                    field: "observation",
                });
            }
            observation_ids.push(&observation.id);
        }
        let mut operation_ids = Vec::with_capacity(self.operations.len());
        for operation in &self.operations {
            validate_identity("operation receipt id", &operation.id)?;
            validate_identity("operation kind", &operation.kind)?;
            validate_browser_provenance(operation)?;
            validate_until_receipt(operation)?;
            if operation.kind == "until"
                && let Some(trigger) = until_report(operation)?.trigger
                && self
                    .operations
                    .iter()
                    .any(|canonical| canonical.id == trigger.id && *canonical != trigger)
            {
                return Err(AutomationRecordError::InvalidUntilReport(
                    "trigger identity has inconsistent canonical receipts".into(),
                ));
            }
            if operation_ids
                .iter()
                .any(|id: &&String| id.as_str() == operation.id.as_str())
            {
                return Err(AutomationRecordError::DuplicateIdentity {
                    field: "operation receipt",
                });
            }
            operation_ids.push(&operation.id);
            if let Some(observation) = &operation.observation {
                validate_observation(observation)?;
            }
        }
        if let Some(flow_outcome) = &self.flow_outcome {
            validate_flow_outcome(flow_outcome)?;
            for step in &flow_outcome.steps {
                if self
                    .operations
                    .iter()
                    .any(|canonical| canonical.id == step.receipt.id && *canonical != step.receipt)
                {
                    return Err(AutomationRecordError::InvalidUntilReport(
                        "canonical operation differs from Flow receipt".into(),
                    ));
                }
            }
        }
        self.validate_evidence_size()
    }

    fn validate_evidence_size(&self) -> Result<(), AutomationRecordError> {
        let mut observed = 0_usize;
        for observation in self
            .observations
            .iter()
            .chain(
                self.operations
                    .iter()
                    .filter_map(|operation| operation.observation.as_ref()),
            )
            .chain(self.flow_outcome.iter().flat_map(|outcome| {
                outcome
                    .steps
                    .iter()
                    .filter_map(|step| step.receipt.observation.as_ref())
            }))
            .chain(self.flow_outcome.iter().filter_map(|outcome| {
                outcome
                    .failure_capture
                    .as_ref()
                    .and_then(|receipt| receipt.observation.as_ref())
            }))
            .chain(self.flow_outcome.iter().flat_map(|outcome| {
                outcome
                    .cleanup
                    .iter()
                    .filter_map(|receipt| receipt.observation.as_ref())
            }))
        {
            if let Some(html) = &observation.html {
                observed = observed.checked_add(html.len()).ok_or(
                    AutomationRecordError::EvidenceSizeExceeded {
                        maximum: MAX_AUTOMATION_RECORD_EVIDENCE_BYTES,
                    },
                )?;
            }
            if let Some(screenshot) = &observation.screenshot {
                observed = observed.checked_add(screenshot.len()).ok_or(
                    AutomationRecordError::EvidenceSizeExceeded {
                        maximum: MAX_AUTOMATION_RECORD_EVIDENCE_BYTES,
                    },
                )?;
            }
            if observed > MAX_AUTOMATION_RECORD_EVIDENCE_BYTES {
                return Err(AutomationRecordError::EvidenceSizeExceeded {
                    maximum: MAX_AUTOMATION_RECORD_EVIDENCE_BYTES,
                });
            }
        }
        for receipt in self.operations.iter().chain(
            self.flow_outcome
                .iter()
                .flat_map(|outcome| outcome.steps.iter().map(|step| &step.receipt)),
        ) {
            if receipt.kind == "until" {
                let bytes = until_report(receipt)?.encoded_size().map_err(|error| {
                    AutomationRecordError::InvalidUntilReport(error.to_string())
                })?;
                observed = observed.checked_add(bytes).ok_or(
                    AutomationRecordError::EvidenceSizeExceeded {
                        maximum: MAX_AUTOMATION_RECORD_EVIDENCE_BYTES,
                    },
                )?;
                if observed > MAX_AUTOMATION_RECORD_EVIDENCE_BYTES {
                    return Err(AutomationRecordError::EvidenceSizeExceeded {
                        maximum: MAX_AUTOMATION_RECORD_EVIDENCE_BYTES,
                    });
                }
            }
        }
        Ok(())
    }
}

fn validate_flow_outcome(outcome: &FlowOutcome) -> Result<(), AutomationRecordError> {
    if !matches!(outcome.version, 1..=3) {
        return Err(AutomationRecordError::UnsupportedFlowVersion {
            observed: outcome.version,
            supported: 3,
        });
    }
    outcome
        .flow
        .validate()
        .map_err(|error| AutomationRecordError::InvalidFlow(error.to_string()))?;
    if outcome.version < 3 && outcome.flow.has_until() {
        return Err(AutomationRecordError::InvalidUntilReport(
            "waiting assertions require current outcome provenance".into(),
        ));
    }
    let mut expected_paths = Vec::new();
    collect_action_paths(&outcome.flow, &mut Vec::new(), &mut expected_paths)?;
    if outcome.steps.len() > expected_paths.len()
        || outcome.skipped_steps.len() > expected_paths.len()
        || outcome.cleanup.len() > 2
    {
        return Err(AutomationRecordError::FlowStepCountMismatch);
    }
    if outcome.version == 1 && has_nested_flow(&outcome.flow) {
        return Err(AutomationRecordError::InvalidFlowStepPath);
    }
    if outcome.version < 3
        && (outcome.flow.has_continuation_configuration()
            || !outcome.skipped_steps.is_empty()
            || outcome.stop_reason.is_some()
            || !outcome.cleanup.is_empty()
            || !outcome.continuation_defaults.is_default()
            || outcome.steps.iter().any(|step| {
                step.failure.is_some()
                    || step.cancellation.is_some()
                    || step.cancelled_flow.is_some()
            }))
    {
        return Err(AutomationRecordError::InvalidFlowStepPath);
    }
    let mut covered_paths = vec![false; expected_paths.len()];
    let mut prior_rank = None;
    let mut previous_index = None;
    let receipt_capacity = outcome
        .steps
        .len()
        .checked_add(outcome.cleanup.len())
        .and_then(|count| count.checked_add(usize::from(outcome.failure_capture.is_some())))
        .ok_or(AutomationRecordError::FlowStepCountMismatch)?;
    let mut receipt_ids: Vec<&String> = Vec::with_capacity(receipt_capacity);
    let mut until_trigger_ids: Vec<String> = Vec::new();
    for (position, step) in outcome.steps.iter().enumerate() {
        let expected_index =
            u64::try_from(position).map_err(|_| AutomationRecordError::FlowStepCountMismatch)?;
        if step.index != expected_index || previous_index.is_some_and(|index| step.index <= index) {
            return Err(AutomationRecordError::InvalidFlowStepOrder);
        }
        previous_index = Some(step.index);
        let rank = if outcome.version < 3 {
            let expected_path = expected_paths
                .get(position)
                .ok_or(AutomationRecordError::FlowStepCountMismatch)?;
            match outcome.version {
                1 if !step.flow_path.is_empty() || expected_path.len() != 1 => {
                    return Err(AutomationRecordError::InvalidFlowStepPath);
                }
                2 if &step.flow_path != expected_path => {
                    return Err(AutomationRecordError::InvalidFlowStepPath);
                }
                _ => {}
            }
            position
        } else {
            expected_paths
                .iter()
                .position(|path| path == &step.flow_path)
                .ok_or(AutomationRecordError::InvalidFlowStepPath)?
        };
        if prior_rank.is_some_and(|previous| rank <= previous) {
            return Err(AutomationRecordError::InvalidFlowStepOrder);
        }
        prior_rank = Some(rank);
        if covered_paths.get(rank).is_none_or(|covered| *covered) {
            return Err(AutomationRecordError::InvalidFlowStepPath);
        }
        if let Some(covered) = covered_paths.get_mut(rank) {
            *covered = true;
        }
        if outcome.version == 3 {
            validate_step_causes(step)?;
            validate_cancelled_flow(outcome, step)?;
        }
        validate_receipt(
            &step.receipt,
            "flow receipt id",
            "flow operation kind",
            &mut receipt_ids,
        )?;
        let authored_path = if outcome.version < 3 {
            expected_paths
                .get(rank)
                .ok_or(AutomationRecordError::InvalidFlowStepPath)?
                .as_slice()
        } else {
            step.flow_path.as_slice()
        };
        let (authored, _) = recorded_step_policy(outcome, authored_path)?;
        if matches!(authored.operation(), Step::Until { .. })
            && step.receipt.status == OperationStatus::Observed
            && step.receipt.kind != "until"
        {
            return Err(AutomationRecordError::InvalidUntilReport(
                "successful waiting step lacks its confirmation report".into(),
            ));
        }
        if step.receipt.kind == "until" {
            validate_until_authored(&step.receipt, authored, &mut until_trigger_ids)?;
        }
    }
    if until_trigger_ids.iter().any(|trigger| {
        outcome.steps.iter().any(|step| step.receipt.id == *trigger)
            || outcome.cleanup.iter().any(|receipt| receipt.id == *trigger)
    }) {
        return Err(AutomationRecordError::DuplicateIdentity {
            field: "until trigger and separate flow operation",
        });
    }

    if outcome.version == 3 {
        validate_skipped_steps(outcome, &expected_paths, &mut covered_paths)?;
        if covered_paths.iter().any(|covered| !covered) {
            return Err(AutomationRecordError::FlowStepCountMismatch);
        }
    } else if outcome.steps.len() > expected_paths.len()
        || (outcome.terminal == FlowTermination::Completed
            && outcome.steps.len() != expected_paths.len())
        || (outcome.terminal != FlowTermination::Completed && outcome.steps.is_empty())
    {
        return Err(AutomationRecordError::FlowStepCountMismatch);
    }

    let terminal_status_matches = match (outcome.terminal, outcome.steps.last()) {
        (FlowTermination::Completed, _) => {
            outcome.steps.iter().all(|step| {
                step.receipt.status == OperationStatus::Observed
                    && step.failure.is_none()
                    && step.cancellation.is_none()
            }) && outcome.skipped_steps.is_empty()
                && outcome
                    .cleanup
                    .iter()
                    .all(|receipt| receipt.status == OperationStatus::Observed)
        }
        (FlowTermination::CompletedWithIssues, _) => {
            outcome.version == 3
                && (outcome
                    .steps
                    .iter()
                    .any(|step| step.failure.is_some() || step.cancellation.is_some())
                    || !outcome.skipped_steps.is_empty()
                    || outcome
                        .cleanup
                        .iter()
                        .any(|receipt| receipt.status != OperationStatus::Observed))
        }
        (FlowTermination::Failed, Some(step)) => {
            step.receipt.status == OperationStatus::Rejected
                && (outcome.version < 3 || step.failure.is_some())
        }
        (FlowTermination::Cancelled, Some(step)) => {
            if outcome.version < 3 {
                step.receipt.status == OperationStatus::Rejected
            } else {
                step.cancellation.is_some() && step.receipt.status != OperationStatus::Unknown
            }
        }
        (FlowTermination::Unknown, Some(step)) => {
            step.receipt.status == OperationStatus::Unknown
                && (outcome.version < 3 || step.failure == Some(FlowFailureCause::UnknownOutcome))
        }
        (_, None) => false,
    };
    if !terminal_status_matches {
        return Err(AutomationRecordError::FlowTerminalMismatch);
    }
    if outcome.version == 3 {
        validate_execution_stops(outcome)?;
        validate_stop_reason(outcome)?;
        validate_cleanup(&outcome.cleanup, &mut receipt_ids)?;
    }
    if let Some(receipt) = &outcome.failure_capture {
        validate_receipt(
            receipt,
            "failure capture receipt id",
            "failure capture operation kind",
            &mut receipt_ids,
        )?;
    }
    Ok(())
}

const fn validate_step_causes(step: &flow::StepOutcome) -> Result<(), AutomationRecordError> {
    let status = step.receipt.status;
    match (status, step.failure) {
        (
            OperationStatus::Observed | OperationStatus::Rejected,
            Some(FlowFailureCause::UnknownOutcome),
        )
        | (OperationStatus::Observed, Some(_)) => {
            return Err(AutomationRecordError::FlowTerminalMismatch);
        }
        (OperationStatus::Unknown, Some(FlowFailureCause::UnknownOutcome)) => {}
        (OperationStatus::Unknown, _) => return Err(AutomationRecordError::FlowTerminalMismatch),
        (OperationStatus::Rejected, None) if step.cancellation.is_none() => {
            return Err(AutomationRecordError::FlowTerminalMismatch);
        }
        _ => {}
    }
    Ok(())
}

fn recorded_step_policy<'a>(
    outcome: &'a FlowOutcome,
    path: &[u64],
) -> Result<(&'a Step, FlowPolicy), AutomationRecordError> {
    let mut flow = &outcome.flow;
    let mut policy = FlowPolicy {
        on_failure: flow
            .on_failure_override()
            .unwrap_or(outcome.continuation_defaults.on_failure),
        on_cancellation: flow
            .on_cancellation_override()
            .unwrap_or(outcome.continuation_defaults.on_cancellation),
    };
    let mut remaining = path;
    loop {
        let (index, rest) = remaining
            .split_first()
            .ok_or(AutomationRecordError::InvalidFlowStepPath)?;
        let index =
            usize::try_from(*index).map_err(|_| AutomationRecordError::InvalidFlowStepPath)?;
        let step = flow
            .steps()
            .get(index)
            .ok_or(AutomationRecordError::InvalidFlowStepPath)?;
        if rest.is_empty() {
            return Ok((
                step,
                FlowPolicy {
                    on_failure: step.failure_override().unwrap_or(policy.on_failure),
                    on_cancellation: step
                        .cancellation_override()
                        .unwrap_or(policy.on_cancellation),
                },
            ));
        }
        let Step::NestedFlow { flow: child } = step.operation() else {
            return Err(AutomationRecordError::InvalidFlowStepPath);
        };
        policy = FlowPolicy {
            on_failure: step
                .failure_override()
                .or_else(|| child.on_failure_override())
                .unwrap_or(policy.on_failure),
            on_cancellation: step
                .cancellation_override()
                .or_else(|| child.on_cancellation_override())
                .unwrap_or(policy.on_cancellation),
        };
        flow = child;
        remaining = rest;
    }
}

fn validate_cancelled_flow(
    outcome: &FlowOutcome,
    trigger: &flow::StepOutcome,
) -> Result<(), AutomationRecordError> {
    let Some(scope) = &trigger.cancelled_flow else {
        return Ok(());
    };
    if trigger.cancellation != Some(FlowCancellationCause::Step)
        || scope.is_empty()
        || scope.len() >= trigger.flow_path.len()
        || !trigger.flow_path.starts_with(scope)
    {
        return Err(AutomationRecordError::InvalidFlowStepPath);
    }
    let (node, _) = recorded_step_policy(outcome, scope)?;
    if !matches!(node.operation(), Step::NestedFlow { .. }) {
        return Err(AutomationRecordError::InvalidFlowStepPath);
    }
    let mut configured = node;
    loop {
        match configured {
            Step::Configured {
                cancellation_binding_required: true,
                ..
            } => return Ok(()),
            Step::Configured { action, .. } | Step::Timed { action, .. } => configured = action,
            _ => return Err(AutomationRecordError::InvalidFlowStepPath),
        }
    }
}

fn selected_stop_policy(
    trigger: &flow::StepOutcome,
    policy: FlowPolicy,
) -> Option<(Continuation, FlowStopCause)> {
    [
        trigger
            .failure
            .map(|_| (policy.on_failure, FlowStopCause::Failure)),
        trigger
            .cancellation
            .map(|_| (policy.on_cancellation, FlowStopCause::Cancellation)),
    ]
    .into_iter()
    .flatten()
    .filter(|(mode, _)| matches!(mode, Continuation::Stop(_)))
    .max_by_key(|(mode, _)| match mode {
        Continuation::Stop(StopScope::Invocation) => 1_u8,
        _ => 0_u8,
    })
}

fn validate_execution_stops(outcome: &FlowOutcome) -> Result<(), AutomationRecordError> {
    for (position, trigger) in outcome.steps.iter().enumerate() {
        let next = position
            .checked_add(1)
            .ok_or(AutomationRecordError::InvalidFlowStepOrder)?;
        let later = outcome
            .steps
            .get(next..)
            .ok_or(AutomationRecordError::InvalidFlowStepOrder)?;
        let hard_cancellation = matches!(
            trigger.cancellation,
            Some(FlowCancellationCause::Invocation | FlowCancellationCause::Session)
        );
        let unsafe_state = outcome.stop_reason.as_ref().is_some_and(|reason| {
            reason.cause == FlowStopCause::UnsafeState && reason.flow_path == trigger.flow_path
        });
        if trigger.receipt.status == OperationStatus::Unknown || hard_cancellation || unsafe_state {
            let expected = if trigger.receipt.status == OperationStatus::Unknown {
                FlowTermination::Unknown
            } else if hard_cancellation {
                FlowTermination::Cancelled
            } else {
                FlowTermination::Failed
            };
            if !later.is_empty() || outcome.terminal != expected {
                return Err(AutomationRecordError::FlowTerminalMismatch);
            }
            continue;
        }
        let effective = recorded_step_policy(outcome, &trigger.flow_path)?.1;
        let selected = selected_stop_policy(trigger, effective);
        let scope = if selected
            .is_some_and(|(mode, _)| mode == Continuation::Stop(StopScope::Invocation))
        {
            Some(&[][..])
        } else if let Some(cancelled_flow) = &trigger.cancelled_flow {
            Some(cancelled_flow.as_slice())
        } else if selected.is_some() {
            Some(
                trigger
                    .flow_path
                    .get(..trigger.flow_path.len().saturating_sub(1))
                    .ok_or(AutomationRecordError::InvalidFlowStepPath)?,
            )
        } else {
            None
        };
        if let Some(scope) = scope {
            if later.iter().any(|step| step.flow_path.starts_with(scope)) {
                return Err(AutomationRecordError::FlowTerminalMismatch);
            }
            if scope.is_empty() {
                let expected =
                    if selected.is_some_and(|(_, cause)| cause == FlowStopCause::Cancellation) {
                        FlowTermination::Cancelled
                    } else {
                        FlowTermination::Failed
                    };
                if outcome.terminal != expected {
                    return Err(AutomationRecordError::FlowTerminalMismatch);
                }
            }
        }
    }
    Ok(())
}

fn validate_skipped_steps(
    outcome: &FlowOutcome,
    expected_paths: &[Vec<u64>],
    covered_paths: &mut [bool],
) -> Result<(), AutomationRecordError> {
    for skipped in &outcome.skipped_steps {
        let rank = expected_paths
            .iter()
            .position(|path| path == &skipped.flow_path)
            .ok_or(AutomationRecordError::InvalidFlowStepPath)?;
        if covered_paths.get(rank).is_none_or(|covered| *covered) {
            return Err(AutomationRecordError::InvalidFlowStepPath);
        }
        if let Some(covered) = covered_paths.get_mut(rank) {
            *covered = true;
        }
        let trigger = outcome
            .steps
            .iter()
            .find(|step| step.flow_path == skipped.stopped_by)
            .ok_or(AutomationRecordError::InvalidFlowStepPath)?;
        let trigger_rank = expected_paths
            .iter()
            .position(|path| path == &trigger.flow_path)
            .ok_or(AutomationRecordError::InvalidFlowStepPath)?;
        if rank <= trigger_rank {
            return Err(AutomationRecordError::InvalidFlowStepOrder);
        }
        let effective = recorded_step_policy(outcome, &trigger.flow_path)?.1;
        let event_matches = match skipped.cause {
            FlowStopCause::Failure => trigger.failure.is_some_and(|cause| {
                matches!(
                    cause,
                    FlowFailureCause::Rejected | FlowFailureCause::Execution
                )
            }),
            FlowStopCause::Cancellation => trigger.cancellation.is_some(),
            FlowStopCause::UnknownOutcome => {
                trigger.failure == Some(FlowFailureCause::UnknownOutcome)
                    && trigger.receipt.status == OperationStatus::Unknown
                    && skipped.scope == StopScope::Invocation
            }
            FlowStopCause::UnsafeState => {
                trigger.failure == Some(FlowFailureCause::Execution)
                    && trigger.receipt.status == OperationStatus::Rejected
                    && skipped.scope == StopScope::Invocation
                    && outcome.stop_reason.as_ref().is_some_and(|reason| {
                        reason.cause == FlowStopCause::UnsafeState
                            && reason.flow_path == trigger.flow_path
                    })
            }
        };
        if !event_matches {
            return Err(AutomationRecordError::FlowTerminalMismatch);
        }
        let authority_stop = skipped.cause == FlowStopCause::Cancellation
            && matches!(
                trigger.cancellation,
                Some(FlowCancellationCause::Invocation | FlowCancellationCause::Session)
            );
        let cancelled_child = skipped.cause == FlowStopCause::Cancellation
            && trigger.cancelled_flow.is_some()
            && skipped.scope == StopScope::CurrentFlow
            && !selected_stop_policy(trigger, effective)
                .is_some_and(|(mode, _)| mode == Continuation::Stop(StopScope::Invocation));
        let policy_stop = match skipped.cause {
            FlowStopCause::Failure => effective.on_failure == Continuation::Stop(skipped.scope),
            FlowStopCause::Cancellation => {
                effective.on_cancellation == Continuation::Stop(skipped.scope)
            }
            FlowStopCause::UnknownOutcome | FlowStopCause::UnsafeState => true,
        };
        if authority_stop && skipped.scope != StopScope::Invocation
            || !(authority_stop || cancelled_child || policy_stop)
        {
            return Err(AutomationRecordError::FlowTerminalMismatch);
        }
        if skipped.scope == StopScope::CurrentFlow {
            let scope_path = if cancelled_child {
                trigger
                    .cancelled_flow
                    .as_deref()
                    .ok_or(AutomationRecordError::InvalidFlowStepPath)?
            } else {
                skipped
                    .stopped_by
                    .get(..skipped.stopped_by.len().saturating_sub(1))
                    .ok_or(AutomationRecordError::InvalidFlowStepPath)?
            };
            if !skipped.flow_path.starts_with(scope_path) {
                return Err(AutomationRecordError::InvalidFlowStepPath);
            }
        }
    }
    Ok(())
}

fn validate_stop_reason(outcome: &FlowOutcome) -> Result<(), AutomationRecordError> {
    let terminal_requires_reason = matches!(
        outcome.terminal,
        FlowTermination::Failed | FlowTermination::Cancelled | FlowTermination::Unknown
    );
    if !terminal_requires_reason {
        return if outcome.stop_reason.is_none() {
            Ok(())
        } else {
            Err(AutomationRecordError::FlowTerminalMismatch)
        };
    }
    let reason = outcome
        .stop_reason
        .as_ref()
        .ok_or(AutomationRecordError::FlowTerminalMismatch)?;
    let last = outcome
        .steps
        .last()
        .ok_or(AutomationRecordError::FlowTerminalMismatch)?;
    if reason.flow_path != last.flow_path {
        return Err(AutomationRecordError::InvalidFlowStepPath);
    }
    let effective = recorded_step_policy(outcome, &last.flow_path)?.1;
    let selected = selected_stop_policy(last, effective);
    let recorded_stop_matches = selected
        .is_some_and(|(mode, cause)| reason.continuation == Some(mode) && reason.cause == cause);
    let matched = match (outcome.terminal, reason.cause) {
        (FlowTermination::Failed, FlowStopCause::Failure) => {
            last.failure.is_some_and(|cause| {
                matches!(
                    cause,
                    FlowFailureCause::Rejected | FlowFailureCause::Execution
                )
            }) && recorded_stop_matches
        }
        (FlowTermination::Cancelled, FlowStopCause::Cancellation) => {
            match (last.cancellation, reason.continuation) {
                (Some(FlowCancellationCause::Step), Some(Continuation::Stop(_))) => {
                    recorded_stop_matches
                }
                (
                    Some(FlowCancellationCause::Invocation | FlowCancellationCause::Session),
                    None,
                ) => true,
                _ => false,
            }
        }
        (FlowTermination::Unknown, FlowStopCause::UnknownOutcome) => {
            last.receipt.status == OperationStatus::Unknown && reason.continuation.is_none()
        }
        (FlowTermination::Failed, FlowStopCause::UnsafeState) => {
            last.receipt.status == OperationStatus::Rejected
                && last.failure == Some(FlowFailureCause::Execution)
                && last.cancellation.is_none()
                && reason.continuation.is_none()
        }
        _ => false,
    };
    if !matched {
        return Err(AutomationRecordError::FlowTerminalMismatch);
    }
    Ok(())
}

fn validate_cleanup<'a>(
    cleanup: &'a [OperationReceipt],
    receipt_ids: &mut Vec<&'a String>,
) -> Result<(), AutomationRecordError> {
    if !cleanup.is_empty()
        && (cleanup.len() != 2
            || cleanup.first().map(|receipt| receipt.kind.as_str()) != Some("session.release")
            || cleanup.get(1).map(|receipt| receipt.kind.as_str()) != Some("session.close"))
    {
        return Err(AutomationRecordError::FlowTerminalMismatch);
    }
    for receipt in cleanup {
        validate_receipt(receipt, "cleanup receipt", "cleanup operation", receipt_ids)?;
        if receipt.observation.is_some()
            || (receipt.status == OperationStatus::Observed
                && (receipt.error.is_some() || receipt.result.is_some()))
            || (receipt.status != OperationStatus::Observed
                && receipt.error.as_ref().is_none_or(String::is_empty))
        {
            return Err(AutomationRecordError::FlowTerminalMismatch);
        }
    }
    Ok(())
}

fn validate_receipt<'a>(
    receipt: &'a OperationReceipt,
    id_field: &'static str,
    kind_field: &'static str,
    receipt_ids: &mut Vec<&'a String>,
) -> Result<(), AutomationRecordError> {
    validate_identity(id_field, &receipt.id)?;
    validate_identity(kind_field, &receipt.kind)?;
    validate_browser_provenance(receipt)?;
    if receipt_ids
        .iter()
        .any(|id| id.as_str() == receipt.id.as_str())
    {
        return Err(AutomationRecordError::DuplicateIdentity {
            field: "flow operation receipt",
        });
    }
    receipt_ids.push(&receipt.id);
    validate_until_receipt(receipt)?;
    if let Some(observation) = &receipt.observation {
        validate_observation(observation)?;
    }
    Ok(())
}

fn validate_browser_provenance(receipt: &OperationReceipt) -> Result<(), AutomationRecordError> {
    if let (Some(browser), Some(observed)) = (
        &receipt.browser,
        receipt
            .observation
            .as_ref()
            .and_then(|observation| observation.browser.as_ref()),
    ) && browser != observed
    {
        return Err(AutomationRecordError::BrowserProvenanceMismatch);
    }
    Ok(())
}

fn until_report(receipt: &OperationReceipt) -> Result<session::UntilReport, AutomationRecordError> {
    let value = receipt
        .result
        .as_ref()
        .ok_or_else(|| AutomationRecordError::InvalidUntilReport("missing report".into()))?;
    serde_json::from_value(value.clone())
        .map_err(|error| AutomationRecordError::InvalidUntilReport(error.to_string()))
}

fn validate_until_receipt(receipt: &OperationReceipt) -> Result<(), AutomationRecordError> {
    if receipt.kind != "until" {
        return Ok(());
    }
    let report = until_report(receipt)?;
    report
        .validate()
        .map_err(|error| AutomationRecordError::InvalidUntilReport(error.to_string()))?;
    let satisfied = report.termination == session::UntilTermination::Satisfied;
    if satisfied != (receipt.status == OperationStatus::Observed)
        || (satisfied && receipt.error.is_some())
    {
        return Err(AutomationRecordError::InvalidUntilReport(
            "receipt status differs from confirmation".into(),
        ));
    }
    if let Some(trigger) = &report.trigger {
        validate_identity("until trigger id", &trigger.id)?;
        if trigger.id == receipt.id {
            return Err(AutomationRecordError::DuplicateIdentity {
                field: "until trigger",
            });
        }
    }
    if satisfied && receipt.observation.is_none() {
        return Err(AutomationRecordError::InvalidUntilReport(
            "successful confirmation lacks an observation".into(),
        ));
    }
    if let Some(observation) = &receipt.observation
        && (observation.session_id != report.scope.session_id
            || observation.tab_id != report.scope.tab_id
            || observation.document_epoch != report.scope.document_epoch)
    {
        return Err(AutomationRecordError::InvalidUntilReport(
            "confirmation scope differs from observation".into(),
        ));
    }
    for check in report
        .checks
        .iter()
        .filter(|check| check.state == session::UntilCheckState::Satisfied)
    {
        let evidence = check.evidence.as_ref().ok_or_else(|| {
            AutomationRecordError::InvalidUntilReport("missing confirmed source evidence".into())
        })?;
        if evidence
            .get("document_epoch")
            .and_then(serde_json::Value::as_u64)
            != Some(report.scope.document_epoch)
            || evidence
                .get("observed_at_unix_ms")
                .and_then(serde_json::Value::as_u64)
                .is_none_or(|timestamp| timestamp == 0)
        {
            return Err(AutomationRecordError::InvalidUntilReport(
                "source scope or capture timestamp differs from confirmation".into(),
            ));
        }
        if check.source == "dom"
            && evidence
                .get("observation_id")
                .and_then(serde_json::Value::as_str)
                != receipt
                    .observation
                    .as_ref()
                    .map(|observation| observation.id.as_str())
        {
            return Err(AutomationRecordError::InvalidUntilReport(
                "DOM evidence belongs to another observation".into(),
            ));
        }
        if check.source == "network" {
            if evidence
                .get("started_at_unix_us")
                .and_then(serde_json::Value::as_u64)
                .is_none_or(|start| start == 0)
            {
                return Err(AutomationRecordError::InvalidUntilReport(
                    "response request start is unavailable".into(),
                ));
            }
            if evidence
                .get("top_level")
                .and_then(serde_json::Value::as_bool)
                != Some(true)
                || report.scope.frame_id.as_ref().is_none_or(|frame| {
                    evidence.get("frame_id").and_then(serde_json::Value::as_str)
                        != Some(frame.as_str())
                })
                || report.scope.loader_id.as_ref().is_none_or(|loader| {
                    evidence
                        .get("loader_id")
                        .and_then(serde_json::Value::as_str)
                        != Some(loader.as_str())
                })
            {
                return Err(AutomationRecordError::InvalidUntilReport(
                    "response scope differs from original frame or loader".into(),
                ));
            }
            if let Some(start) = report
                .trigger
                .as_ref()
                .and_then(|trigger| trigger.result.as_ref())
                .and_then(|result| result.get("started_at_unix_us"))
                .and_then(serde_json::Value::as_u64)
                && evidence
                    .get("started_at_unix_us")
                    .and_then(serde_json::Value::as_u64)
                    .is_none_or(|request| request < start)
            {
                return Err(AutomationRecordError::InvalidUntilReport(
                    "response request precedes trigger dispatch".into(),
                ));
            }
        }
    }
    Ok(())
}

fn validate_until_authored(
    receipt: &OperationReceipt,
    authored: &Step,
    trigger_ids: &mut Vec<String>,
) -> Result<(), AutomationRecordError> {
    use crate::{expect::Expectation, session::UntilCheckState};
    let Step::Until {
        trigger,
        expectation,
    } = authored.operation()
    else {
        return Err(AutomationRecordError::InvalidUntilReport(
            "receipt does not belong to a waiting step".into(),
        ));
    };
    let report = until_report(receipt)?;
    if let Some(actual) = &report.trigger {
        let expected = trigger.as_ref().ok_or_else(|| {
            AutomationRecordError::InvalidUntilReport("unexpected trigger".into())
        })?;
        if actual.kind != expected.kind() {
            return Err(AutomationRecordError::InvalidUntilReport(
                "trigger kind differs from recipe".into(),
            ));
        }
        if trigger_ids.contains(&actual.id) {
            return Err(AutomationRecordError::DuplicateIdentity {
                field: "until trigger",
            });
        }
        trigger_ids.push(actual.id.clone());
    } else if trigger.is_some() && report.termination == session::UntilTermination::Satisfied {
        return Err(AutomationRecordError::InvalidUntilReport(
            "attached action has no trigger receipt".into(),
        ));
    }
    let mut stack = vec![expectation];
    let mut leaves = Vec::new();
    while let Some(expected) = stack.pop() {
        if let Expectation::All { expectations } = expected {
            stack.extend(expectations.iter().rev());
        } else {
            leaves.push(expected);
        }
    }
    if leaves.len() != report.checks.len() {
        return Err(AutomationRecordError::InvalidUntilReport(
            "check count differs from recipe".into(),
        ));
    }
    for (expected, check) in leaves.iter().zip(&report.checks) {
        let expected_source = match expected {
            Expectation::Condition { .. } | Expectation::Contract { .. } => "dom",
            Expectation::Accessibility { .. } => "accessibility",
            Expectation::Response { .. } => "network",
            Expectation::All { .. } => {
                return Err(AutomationRecordError::InvalidUntilReport(
                    "nested group was not flattened".into(),
                ));
            }
        };
        if check.source != expected_source {
            return Err(AutomationRecordError::InvalidUntilReport(
                "source differs from recipe".into(),
            ));
        }
        if check.state != UntilCheckState::Satisfied {
            continue;
        }
        let evidence = check.evidence.as_ref().ok_or_else(|| {
            AutomationRecordError::InvalidUntilReport("missing leaf evidence".into())
        })?;
        match expected {
            Expectation::Condition { condition } => {
                if evidence.get("actual").and_then(serde_json::Value::as_bool) != Some(true)
                    || evidence.get("expected")
                        != Some(&serde_json::to_value(condition).map_err(|error| {
                            AutomationRecordError::Serialization(error.to_string())
                        })?)
                {
                    return Err(AutomationRecordError::InvalidUntilReport(
                        "DOM condition evidence differs from recipe".into(),
                    ));
                }
            }
            Expectation::Contract {
                assertion: authored,
            } => {
                let recorded = evidence.get("report").ok_or_else(|| {
                    AutomationRecordError::InvalidUntilReport("missing Contract report".into())
                })?;
                let assertion: assertions::AssertionReport =
                    serde_json::from_value(recorded.clone()).map_err(|error| {
                        AutomationRecordError::InvalidUntilReport(error.to_string())
                    })?;
                let located_matches_observation = match &assertion.located {
                    locators::LocateOutcome::Matched { result } => {
                        evidence
                            .get("observation_id")
                            .and_then(serde_json::Value::as_str)
                            == Some(result.document_id().as_str())
                    }
                    _ => false,
                };
                if !assertion.passed
                    || !authored.report_matches_descriptor(&assertion)
                    || !located_matches_observation
                    || assertion.source_error.is_some()
                    || !assertion.field_issues.is_empty()
                    || !assertion.extraction_diagnostics.is_empty()
                    || assertion.checks.is_empty()
                    || assertion
                        .checks
                        .iter()
                        .any(|check| check.passed != Some(true) || check.error.is_some())
                {
                    return Err(AutomationRecordError::InvalidUntilReport(
                        "Contract evidence does not pass".into(),
                    ));
                }
            }
            Expectation::Accessibility { name, role } => {
                if evidence.get("name").and_then(serde_json::Value::as_str) != Some(name.as_str())
                    || evidence.get("role")
                        != Some(&serde_json::to_value(role).map_err(|error| {
                            AutomationRecordError::Serialization(error.to_string())
                        })?)
                    || evidence
                        .get("nodes")
                        .and_then(serde_json::Value::as_array)
                        .is_none_or(|nodes| {
                            !nodes.iter().any(|node| {
                                node.get("ignored").and_then(serde_json::Value::as_bool)
                                    == Some(false)
                                    && node
                                        .get("name")
                                        .and_then(|name| name.get("value"))
                                        .and_then(serde_json::Value::as_str)
                                        == Some(name.as_str())
                                    && role.as_ref().is_none_or(|role| {
                                        node.get("role")
                                            .and_then(|role| role.get("value"))
                                            .and_then(serde_json::Value::as_str)
                                            == Some(role.as_str())
                                    })
                            })
                        })
                {
                    return Err(AutomationRecordError::InvalidUntilReport(
                        "AX evidence differs from recipe".into(),
                    ));
                }
            }
            Expectation::Response {
                url,
                method,
                status,
                json,
            } => {
                if evidence.get("url").and_then(serde_json::Value::as_str) != Some(url.as_str())
                    || method.as_ref().is_some_and(|method| {
                        evidence.get("method").and_then(serde_json::Value::as_str)
                            != Some(method.as_str())
                    })
                    || status.is_some_and(|status| {
                        evidence.get("status").and_then(serde_json::Value::as_u64)
                            != Some(u64::from(status))
                    })
                    || evidence
                        .get("request_id")
                        .and_then(serde_json::Value::as_str)
                        .is_none_or(str::is_empty)
                    || json.iter().any(|item| {
                        evidence
                            .get("body")
                            .and_then(|body| body.pointer(&item.pointer))
                            != Some(&item.value)
                    })
                {
                    return Err(AutomationRecordError::InvalidUntilReport(
                        "response evidence differs from recipe".into(),
                    ));
                }
            }
            Expectation::All { .. } => {}
        }
    }
    Ok(())
}

fn collect_action_paths(
    flow: &Flow,
    parent_path: &mut Vec<u64>,
    output: &mut Vec<Vec<u64>>,
) -> Result<(), AutomationRecordError> {
    for (position, step) in flow.steps().iter().enumerate() {
        let index =
            u64::try_from(position).map_err(|_| AutomationRecordError::FlowStepCountMismatch)?;
        parent_path.push(index);
        if let Step::NestedFlow { flow: child } = step.operation() {
            collect_action_paths(child, parent_path, output)?;
        } else {
            output.push(parent_path.clone());
        }
        let _ = parent_path.pop();
    }
    Ok(())
}

fn has_nested_flow(flow: &Flow) -> bool {
    flow.steps()
        .iter()
        .any(|step| matches!(step.operation(), Step::NestedFlow { .. }))
}

fn validate_observation(observation: &Observation) -> Result<(), AutomationRecordError> {
    validate_identity("observation id", &observation.id)?;
    validate_identity("session id", &observation.session_id)?;
    validate_identity("tab id", &observation.tab_id)?;
    if let Some(html) = &observation.html
        && html.len() > MAX_OBSERVATION_HTML_BYTES
    {
        return Err(AutomationRecordError::FieldSizeExceeded {
            field: "html",
            maximum: MAX_OBSERVATION_HTML_BYTES,
        });
    }
    if let Some(screenshot) = &observation.screenshot
        && screenshot.len() > MAX_OBSERVATION_SCREENSHOT_BYTES
    {
        return Err(AutomationRecordError::FieldSizeExceeded {
            field: "screenshot",
            maximum: MAX_OBSERVATION_SCREENSHOT_BYTES,
        });
    }
    Ok(())
}

fn validate_identity(field: &'static str, value: &str) -> Result<(), AutomationRecordError> {
    if value.trim().is_empty() {
        return Err(AutomationRecordError::EmptyIdentity { field });
    }
    if value.len() > 1_024 {
        return Err(AutomationRecordError::IdentityTooLong { field });
    }
    Ok(())
}

/// Failure while authoring or reading the prototype record container.
#[derive(Clone, Debug, Eq, PartialEq)]
/// Bounded record shape, provenance, encoding, or Archive persistence rejected the evidence.
pub enum AutomationRecordError {
    /// An operation and its attached observation claim different browser provenance.
    BrowserProvenanceMismatch,
    /// A required record, observation, or operation identity is blank.
    EmptyIdentity {
        /// Identity role whose value was rejected.
        field: &'static str,
    },
    /// A required identity exceeds its UTF-8 byte bound.
    IdentityTooLong {
        /// Identity role whose text is oversized.
        field: &'static str,
    },
    /// An observation or receipt identity is repeated within its record scope.
    DuplicateIdentity {
        /// Evidence category containing the repeated identity.
        field: &'static str,
    },
    /// A retained evidence collection exceeds its item-count bound.
    ItemLimitExceeded {
        /// Collection whose items cannot all be retained.
        field: &'static str,
        /// Maximum permitted items in that collection.
        maximum: usize,
    },
    /// One retained evidence field exceeds its byte bound.
    FieldSizeExceeded {
        /// Oversized field role, such as HTML or screenshot evidence.
        field: &'static str,
        /// Maximum permitted bytes for that field.
        maximum: usize,
    },
    /// Aggregate raw or confirmation evidence exceeds record retention limits.
    EvidenceSizeExceeded {
        /// Maximum combined retained evidence bytes.
        maximum: usize,
    },
    /// Encoded record or context data exceeds its permitted byte bound.
    EncodedSizeExceeded {
        /// Maximum accepted bytes for the rejected encoding or context field.
        maximum: u64,
        /// Recorded encoded or attempted field byte count.
        observed: u64,
    },
    /// The logical automation record schema version is unsupported by this build.
    UnsupportedVersion {
        /// Version supplied by the record or reference.
        observed: u32,
        /// Record schema version supported by this build.
        supported: u32,
    },
    /// Archived record bytes do not use the required source-text Document profile.
    WrongDocumentProfile,
    /// Archived Document identity disagrees with the logical record identity.
    DocumentIdentityMismatch,
    /// The embedded Flow outcome schema is outside the supported legacy/current range.
    UnsupportedFlowVersion {
        /// Version supplied by the embedded outcome.
        observed: u32,
        /// Highest Flow outcome version understood by this build.
        supported: u32,
    },
    /// Result, skipped-step, or cleanup counts cannot correspond to the authored Flow.
    FlowStepCountMismatch,
    /// Recorded leaf indexes are not in the required deterministic execution order.
    InvalidFlowStepOrder,
    /// A recorded leaf or stop path does not identify a valid authored action scope.
    InvalidFlowStepPath,
    /// The terminal completion claim disagrees with retained receipts or stop evidence.
    FlowTerminalMismatch,
    /// The embedded authored recipe fails current structural validation.
    InvalidFlow(String),
    /// Saved Until confirmation shape, source coordinates, or success claims are inconsistent.
    InvalidUntilReport(String),
    /// Bounded record encoding or decoding failed.
    Serialization(String),
    /// Construction or interpretation of the immutable record Document failed.
    Document(String),
    /// Archive persistence or retrieval failed before a valid record could be returned.
    Archive(String),
}

impl fmt::Display for AutomationRecordError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BrowserProvenanceMismatch => {
                formatter.write_str("operation and observation browser provenance differ")
            }
            Self::EmptyIdentity { field } => write!(formatter, "{field} cannot be empty"),
            Self::IdentityTooLong { field } => write!(formatter, "{field} exceeds 1024 bytes"),
            Self::DuplicateIdentity { field } => write!(formatter, "duplicate {field} identity"),
            Self::ItemLimitExceeded { field, maximum } => {
                write!(formatter, "{field} exceed the limit of {maximum}")
            }
            Self::FieldSizeExceeded { field, maximum } => {
                write!(formatter, "{field} exceeds the {maximum}-byte limit")
            }
            Self::EvidenceSizeExceeded { maximum } => {
                write!(
                    formatter,
                    "record evidence exceeds the {maximum}-byte limit"
                )
            }
            Self::EncodedSizeExceeded { maximum, observed } => write!(
                formatter,
                "encoded record has {observed} bytes, above the {maximum}-byte limit"
            ),
            Self::UnsupportedVersion {
                observed,
                supported,
            } => write!(
                formatter,
                "record version {observed} is unsupported; this build supports {supported}"
            ),
            Self::WrongDocumentProfile => {
                formatter.write_str("archived record does not use the source-text Document profile")
            }
            Self::DocumentIdentityMismatch => {
                formatter.write_str("archived Document identity differs from its record identity")
            }
            Self::UnsupportedFlowVersion {
                observed,
                supported,
            } => write!(
                formatter,
                "flow outcome version {observed} is unsupported; this build supports {supported}"
            ),
            Self::FlowStepCountMismatch => {
                formatter.write_str("flow outcome contains more step results than authored steps")
            }
            Self::InvalidFlowStepOrder => {
                formatter.write_str("flow outcome step indexes must be strictly increasing")
            }
            Self::InvalidFlowStepPath => {
                formatter.write_str("flow outcome path does not identify an action in its Flow")
            }
            Self::FlowTerminalMismatch => {
                formatter.write_str("flow outcome terminal status does not match its final receipt")
            }
            Self::InvalidFlow(message) => write!(formatter, "recorded flow is invalid: {message}"),
            Self::InvalidUntilReport(message) => write!(
                formatter,
                "recorded waiting assertion is invalid: {message}"
            ),
            Self::Serialization(message) => {
                write!(formatter, "record serialization failed: {message}")
            }
            Self::Document(message) => write!(formatter, "record Document is invalid: {message}"),
            Self::Archive(message) => {
                write!(formatter, "record Archive operation failed: {message}")
            }
        }
    }
}

impl std_error::Error for AutomationRecordError {}

fn encode_record(record: &AutomationRecord) -> Result<Vec<u8>, AutomationRecordError> {
    let maximum = usize::try_from(MAX_AUTOMATION_RECORD_BYTES).map_err(|_| {
        AutomationRecordError::EncodedSizeExceeded {
            maximum: MAX_AUTOMATION_RECORD_BYTES,
            observed: u64::MAX,
        }
    })?;
    let mut writer = BoundedJsonWriter::new(maximum);
    if let Err(error) = serde_json::to_writer(&mut writer, record) {
        if let Some(observed) = writer.exceeded_at {
            let observed = u64::try_from(observed).unwrap_or(u64::MAX);
            return Err(AutomationRecordError::EncodedSizeExceeded {
                maximum: MAX_AUTOMATION_RECORD_BYTES,
                observed,
            });
        }
        return Err(AutomationRecordError::Serialization(error.to_string()));
    }
    Ok(writer.bytes)
}

struct BoundedJsonWriter {
    bytes: Vec<u8>,
    maximum: usize,
    exceeded_at: Option<usize>,
}

impl BoundedJsonWriter {
    fn new(maximum: usize) -> Self {
        Self {
            bytes: Vec::with_capacity(maximum.min(64 * 1024)),
            maximum,
            exceeded_at: None,
        }
    }
}

impl Write for BoundedJsonWriter {
    fn write(&mut self, buffer: &[u8]) -> std_io::Result<usize> {
        let Some(next_len) = self.bytes.len().checked_add(buffer.len()) else {
            self.exceeded_at = Some(usize::MAX);
            return Err(std_io::Error::new(
                std_io::ErrorKind::WriteZero,
                "automation record exceeds its encoded size limit",
            ));
        };
        if next_len > self.maximum {
            self.exceeded_at = Some(next_len);
            return Err(std_io::Error::new(
                std_io::ErrorKind::WriteZero,
                "automation record exceeds its encoded size limit",
            ));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> std_io::Result<()> {
        Ok(())
    }
}
