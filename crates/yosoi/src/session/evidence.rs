//! Bounded automatic screenshot evidence retained by an owned Session.

use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use crate::{
    automation_record::{MAX_AUTOMATION_RECORD_ITEMS, MAX_OBSERVATION_SCREENSHOT_BYTES},
    internal::policy::policy::ScreenshotScope,
    policy::{Policy, observe::EvidenceFailurePolicy},
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use super::capture::{
    ScreenshotCapture, ScreenshotCaptureMetadata, ScreenshotOptions, ScreenshotRegion,
    ScreenshotTarget,
};
use super::{ActionKind, Session, SessionError, Work};

const MAX_EVIDENCE_ENTRIES: usize = MAX_AUTOMATION_RECORD_ITEMS;
const MAX_PENDING_FAILURES: usize = 32;

/// Phase of an automatic screenshot relative to its associated operation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomaticEvidencePhase {
    /// Captured before the associated operation was dispatched.
    Before,
    /// Captured after the associated operation settled successfully.
    After,
    /// Captured after the associated operation settled with a failure.
    Failure,
}

/// Why one configured automatic screenshot was unavailable.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceGapReason {
    /// Session policy did not permit screenshot capture.
    ScreenshotDenied,
    /// The operation had no uniquely resolved target for a target-scoped capture.
    TargetUnavailable,
    /// The bounded Session evidence byte budget was exhausted.
    RetentionLimit,
    /// The bounded in-flight capture buffer was exhausted.
    BufferLimit,
    /// The bounded number of evidence entries was exhausted.
    EntryLimit,
    /// The provider could not complete the requested screenshot.
    CaptureFailed,
}

/// One automatic screenshot capture or an explicit gap, linked to its action receipt.
#[derive(Clone, Debug, PartialEq)]
pub struct AutomaticEvidence {
    /// ID shared with the associated [`crate::automation_record::OperationReceipt`].
    pub operation_id: String,
    /// Screenshot phase relative to the associated operation.
    pub phase: AutomaticEvidencePhase,
    /// Typed image document and capture provenance when retained successfully.
    pub capture: Option<ScreenshotCapture>,
    /// Explicit reason when the configured screenshot could not be retained.
    pub gap: Option<EvidenceGapReason>,
}

/// Serializable automatic evidence facts without embedded image payloads.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomaticEvidenceMetadata {
    /// ID shared with the associated operation receipt.
    pub operation_id: String,
    /// Screenshot phase relative to the associated operation.
    pub phase: AutomaticEvidencePhase,
    /// Serializable screenshot coordinates and source facts, when capture succeeded.
    pub capture: Option<ScreenshotCaptureMetadata>,
    /// Explicit reason when the configured screenshot could not be retained.
    pub gap: Option<EvidenceGapReason>,
}

impl AutomaticEvidence {
    fn captured(
        operation_id: &str,
        phase: AutomaticEvidencePhase,
        capture: ScreenshotCapture,
    ) -> Self {
        Self {
            operation_id: operation_id.to_owned(),
            phase,
            capture: Some(capture),
            gap: None,
        }
    }

    fn gap(operation_id: &str, phase: AutomaticEvidencePhase, reason: EvidenceGapReason) -> Self {
        Self {
            operation_id: operation_id.to_owned(),
            phase,
            capture: None,
            gap: Some(reason),
        }
    }

    /// Returns serializable phase and capture facts without copying image bytes.
    pub fn metadata(&self) -> AutomaticEvidenceMetadata {
        AutomaticEvidenceMetadata {
            operation_id: self.operation_id.clone(),
            phase: self.phase,
            capture: self
                .capture
                .as_ref()
                .map(|capture| capture.metadata.clone()),
            gap: self.gap,
        }
    }
}

/// Immutable snapshot of automatic screenshots and aggregate evidence retention for a Session.
#[derive(Clone, Debug, PartialEq)]
pub struct SessionEvidence {
    /// Captures and explicit gaps in capture-completion order.
    pub entries: Vec<AutomaticEvidence>,
    retained_bytes: u64,
    maximum_bytes: u64,
    omitted_entries: u64,
}

/// Serializable Session evidence facts without embedded image payloads.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionEvidenceMetadata {
    /// Captures and explicit gaps in capture-completion order.
    pub entries: Vec<AutomaticEvidenceMetadata>,
    /// Retained automatic image and video payload bytes for this Session.
    pub retained_bytes: u64,
    /// Session-wide lifetime retained-evidence byte ceiling.
    pub maximum_bytes: u64,
    /// Outcomes omitted after the bounded entry count was exhausted.
    pub omitted_entries: u64,
}

impl SessionEvidence {
    /// Returns captures and explicit gaps in capture-completion order.
    pub fn entries(&self) -> &[AutomaticEvidence] {
        &self.entries
    }

    /// Returns retained automatic image and video payload bytes for this Session.
    pub const fn retained_bytes(&self) -> u64 {
        self.retained_bytes
    }

    /// Returns the Session's aggregate image and video retention ceiling.
    pub const fn maximum_bytes(&self) -> u64 {
        self.maximum_bytes
    }

    /// Returns how many evidence outcomes could not be individually retained after the entry cap.
    pub const fn omitted_entries(&self) -> u64 {
        self.omitted_entries
    }

    /// Returns whether any configured screenshot is missing or an outcome was omitted.
    pub fn has_gaps(&self) -> bool {
        self.omitted_entries > 0 || self.entries.iter().any(|entry| entry.gap.is_some())
    }

    /// Returns serializable capture facts without embedding image payload bytes.
    pub fn metadata(&self) -> SessionEvidenceMetadata {
        SessionEvidenceMetadata {
            entries: self
                .entries
                .iter()
                .map(AutomaticEvidence::metadata)
                .collect(),
            retained_bytes: self.retained_bytes,
            maximum_bytes: self.maximum_bytes,
            omitted_entries: self.omitted_entries,
        }
    }

    /// Hydrates an immutable snapshot after checking its media and metadata bounds.
    pub(super) fn from_archived(
        metadata: SessionEvidenceMetadata,
        entries: Vec<AutomaticEvidence>,
    ) -> Result<Self, SessionEvidenceValidationError> {
        let SessionEvidenceMetadata {
            entries: expected_entries,
            retained_bytes,
            maximum_bytes,
            omitted_entries,
        } = metadata;
        if maximum_bytes == 0
            || usize::try_from(maximum_bytes).is_err()
            || retained_bytes > maximum_bytes
        {
            return Err(SessionEvidenceValidationError::RetainedBounds);
        }
        if entries.len() > MAX_EVIDENCE_ENTRIES || entries.len() != expected_entries.len() {
            return Err(SessionEvidenceValidationError::EntryCount);
        }
        let mut screenshot_bytes = 0_u64;
        for (entry, expected) in entries.iter().zip(&expected_entries) {
            let actual = entry.metadata();
            if entry.operation_id.is_empty()
                || entry.operation_id.len() > 128
                || actual.ne(expected)
                || entry.capture.is_some() == entry.gap.is_some()
            {
                return Err(SessionEvidenceValidationError::EntryMetadata);
            }
            if let Some(capture) = &entry.capture {
                screenshot_bytes = screenshot_bytes
                    .checked_add(capture.document.byte_len())
                    .ok_or(SessionEvidenceValidationError::RetainedBounds)?;
            }
        }
        if screenshot_bytes > retained_bytes {
            return Err(SessionEvidenceValidationError::RetainedBounds);
        }
        Ok(Self {
            entries,
            retained_bytes,
            maximum_bytes,
            omitted_entries,
        })
    }
}

/// Rejected decoded screenshot-evidence snapshot facts before they receive SDK access.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub(super) enum SessionEvidenceValidationError {
    /// Retained payload totals are zero, unaddressable, exceed the lifetime ceiling, or mismatch.
    #[error("retained Session evidence bytes exceed their validated lifetime bound")]
    RetainedBounds,
    /// Too many per-operation outcomes were supplied, or metadata and payload counts differ.
    #[error("Session evidence entry count is invalid")]
    EntryCount,
    /// One entry has inconsistent capture/gap facts or invalid identity metadata.
    #[error("Session evidence entry metadata is invalid")]
    EntryMetadata,
}

#[derive(Default)]
struct EvidenceState {
    entries: Vec<AutomaticEvidence>,
    retained_bytes: u64,
    reserved_retained_bytes: u64,
    reserved_entries: usize,
    omitted_entries: u64,
    required_failure: bool,
    pending_required_operations: Vec<String>,
    pending_background_failure: bool,
}

/// Session-shared bounded owner for automatic screenshot and recording outputs.
pub(super) struct SessionEvidenceStore {
    state: Arc<Mutex<EvidenceState>>,
    maximum_bytes: u64,
    require_evidence: bool,
}

impl SessionEvidenceStore {
    /// Creates the store from the immutable Session Policy snapshot.
    pub(super) fn new(policy: &Policy) -> Self {
        Self {
            state: Arc::new(Mutex::new(EvidenceState::default())),
            maximum_bytes: policy.observe.limits.max_retained_bytes.get(),
            require_evidence: policy.observe.failure == EvidenceFailurePolicy::Require,
        }
    }

    fn lock(&self) -> MutexGuard<'_, EvidenceState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn reserve(&self, requested_bytes: u64) -> Result<EvidenceReservation, EvidenceGapReason> {
        let mut state = self.lock();
        if state
            .entries
            .len()
            .checked_add(state.reserved_entries)
            .is_none_or(|entries| entries >= MAX_EVIDENCE_ENTRIES)
        {
            return Err(EvidenceGapReason::EntryLimit);
        }
        let used_bytes = state
            .retained_bytes
            .checked_add(state.reserved_retained_bytes)
            .ok_or(EvidenceGapReason::RetentionLimit)?;
        let available_bytes = self
            .maximum_bytes
            .checked_sub(used_bytes)
            .ok_or(EvidenceGapReason::RetentionLimit)?;
        let reserved_bytes = available_bytes.min(requested_bytes);
        if reserved_bytes == 0 {
            return Err(EvidenceGapReason::RetentionLimit);
        }
        let reserved_total = state
            .reserved_retained_bytes
            .checked_add(reserved_bytes)
            .ok_or(EvidenceGapReason::RetentionLimit)?;
        let reserved_entries = state
            .reserved_entries
            .checked_add(1)
            .ok_or(EvidenceGapReason::EntryLimit)?;
        state.reserved_retained_bytes = reserved_total;
        state.reserved_entries = reserved_entries;
        drop(state);
        Ok(EvidenceReservation {
            state: Arc::clone(&self.state),
            maximum_bytes: reserved_bytes,
            require_evidence: self.require_evidence,
            active: true,
        })
    }

    fn record_gap(
        &self,
        operation_id: &str,
        phase: AutomaticEvidencePhase,
        reason: EvidenceGapReason,
    ) {
        let mut state = self.lock();
        defer_required_failure(&mut state, self.require_evidence, operation_id, phase);
        let occupied = state
            .entries
            .len()
            .checked_add(state.reserved_entries)
            .unwrap_or(MAX_EVIDENCE_ENTRIES);
        if occupied < MAX_EVIDENCE_ENTRIES {
            state
                .entries
                .push(AutomaticEvidence::gap(operation_id, phase, reason));
        } else {
            state.omitted_entries = state.omitted_entries.saturating_add(1);
        }
    }

    /// Marks a required recording failure as a gate for later effectful operations.
    pub(super) fn mark_required_failure(&self) {
        if self.require_evidence {
            self.lock().pending_background_failure = true;
        }
    }

    /// Counts one omitted recording result without retaining another evidence entry.
    pub(super) fn note_omitted_recording(&self) {
        let mut state = self.lock();
        state.omitted_entries = state.omitted_entries.saturating_add(1);
    }

    /// Starts an operation boundary and applies background failures from earlier settled work.
    pub(super) fn begin_operation(&self) {
        let mut state = self.lock();
        if state.pending_background_failure {
            state.pending_background_failure = false;
            state.required_failure = true;
        }
    }

    /// Settles a pending before-phase failure and gates later effects when required.
    pub(super) fn settle_operation(&self, operation_id: &str) {
        let mut state = self.lock();
        let mut matched = false;
        state.pending_required_operations.retain(|pending| {
            if pending == operation_id {
                matched = true;
                false
            } else {
                true
            }
        });
        state.required_failure |= matched;
        if state.pending_background_failure {
            state.pending_background_failure = false;
            state.required_failure = true;
        }
    }

    /// Creates a shared reservation for incrementally retained media documents.
    ///
    /// Automatic recording collectors add each accepted chunk before retaining it, then commit
    /// the reservation when the output is published. Dropping every reservation clone releases
    /// its provisional bytes. The same budget also covers automatic screenshot documents.
    pub(super) fn retained_reservation(&self) -> RetainedByteReservation {
        RetainedByteReservation {
            inner: Arc::new(RetainedByteReservationInner {
                state: Arc::clone(&self.state),
                amount: Mutex::new(RetainedReservationState::default()),
                maximum_bytes: self.maximum_bytes,
                require_evidence: self.require_evidence,
            }),
        }
    }

    fn required_failure(&self) -> bool {
        self.lock().required_failure
    }

    fn snapshot(&self) -> SessionEvidence {
        let state = self.lock();
        SessionEvidence {
            entries: state.entries.clone(),
            retained_bytes: state.retained_bytes,
            maximum_bytes: self.maximum_bytes,
            omitted_entries: state.omitted_entries,
        }
    }
}

#[derive(Default)]
struct RetainedReservationState {
    bytes: u64,
    committed: bool,
}

struct RetainedByteReservationInner {
    state: Arc<Mutex<EvidenceState>>,
    amount: Mutex<RetainedReservationState>,
    maximum_bytes: u64,
    require_evidence: bool,
}

impl Drop for RetainedByteReservationInner {
    fn drop(&mut self) {
        let amount = self
            .amount
            .get_mut()
            .unwrap_or_else(PoisonError::into_inner);
        if amount.committed || amount.bytes == 0 {
            return;
        }
        let mut state = lock_state(&self.state);
        state.reserved_retained_bytes = state.reserved_retained_bytes.saturating_sub(amount.bytes);
    }
}

/// Cloneable incremental reservation from the Session's aggregate retained-evidence budget.
///
/// Each accepted media chunk must be reserved with [`Self::try_add`] before the collector keeps
/// it. Native transient capture buffers are bounded through CaptureAdmission. Call
/// [`Self::commit`] when the complete output becomes Session-owned; otherwise dropping all clones
/// releases the provisional lifetime reservation.
#[derive(Clone)]
pub struct RetainedByteReservation {
    inner: Arc<RetainedByteReservationInner>,
}

impl RetainedByteReservation {
    /// Reserves the next chunk if the lifetime evidence budget can retain it.
    pub(crate) fn try_add(&self, bytes: u64) -> bool {
        let mut amount = self
            .inner
            .amount
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if amount.committed {
            return false;
        }
        if bytes == 0 {
            return true;
        }
        let Some(reservation_total) = amount.bytes.checked_add(bytes) else {
            self.mark_failure();
            return false;
        };
        let mut state = lock_state(&self.inner.state);
        let Some(used) = state
            .retained_bytes
            .checked_add(state.reserved_retained_bytes)
        else {
            state.pending_background_failure |= self.inner.require_evidence;
            drop(state);
            return false;
        };
        let Some(global_total) = used.checked_add(bytes) else {
            state.pending_background_failure |= self.inner.require_evidence;
            drop(state);
            return false;
        };
        if global_total > self.inner.maximum_bytes {
            state.pending_background_failure |= self.inner.require_evidence;
            drop(state);
            return false;
        }
        let Some(reserved_total) = state.reserved_retained_bytes.checked_add(bytes) else {
            state.pending_background_failure |= self.inner.require_evidence;
            drop(state);
            return false;
        };
        state.reserved_retained_bytes = reserved_total;
        amount.bytes = reservation_total;
        drop(amount);
        drop(state);
        true
    }

    /// Commits all provisionally accepted bytes to the Session's retained evidence total.
    ///
    /// Returns `false` only if the aggregate bound could not be represented or was exceeded.
    pub(crate) fn commit(&self) -> bool {
        let mut amount = self
            .inner
            .amount
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if amount.committed {
            return true;
        }
        let mut state = lock_state(&self.inner.state);
        let Some(retained_total) = state.retained_bytes.checked_add(amount.bytes) else {
            state.pending_background_failure |= self.inner.require_evidence;
            drop(state);
            return false;
        };
        if retained_total > self.inner.maximum_bytes {
            state.pending_background_failure |= self.inner.require_evidence;
            drop(state);
            return false;
        }
        state.reserved_retained_bytes = state.reserved_retained_bytes.saturating_sub(amount.bytes);
        state.retained_bytes = retained_total;
        amount.committed = true;
        drop(amount);
        drop(state);
        true
    }

    pub(crate) fn mark_failure(&self) {
        let mut state = lock_state(&self.inner.state);
        state.pending_background_failure |= self.inner.require_evidence;
    }
}

struct EvidenceReservation {
    state: Arc<Mutex<EvidenceState>>,
    maximum_bytes: u64,
    require_evidence: bool,
    active: bool,
}

impl EvidenceReservation {
    const fn maximum_bytes(&self) -> u64 {
        self.maximum_bytes
    }

    fn commit_capture(
        mut self,
        operation_id: &str,
        phase: AutomaticEvidencePhase,
        capture: ScreenshotCapture,
    ) {
        let byte_len = capture.document.byte_len();
        let state_ref = Arc::clone(&self.state);
        let mut state = lock_state(&state_ref);
        self.release(&mut state);
        if byte_len > self.maximum_bytes {
            record_gap_locked(
                &mut state,
                self.require_evidence,
                operation_id,
                phase,
                EvidenceGapReason::RetentionLimit,
            );
            return;
        }
        if state.entries.len() >= MAX_EVIDENCE_ENTRIES {
            record_gap_locked(
                &mut state,
                self.require_evidence,
                operation_id,
                phase,
                EvidenceGapReason::EntryLimit,
            );
            return;
        }
        let Some(retained_bytes) = state.retained_bytes.checked_add(byte_len) else {
            record_gap_locked(
                &mut state,
                self.require_evidence,
                operation_id,
                phase,
                EvidenceGapReason::RetentionLimit,
            );
            return;
        };
        state.retained_bytes = retained_bytes;
        state
            .entries
            .push(AutomaticEvidence::captured(operation_id, phase, capture));
    }

    fn commit_gap(
        mut self,
        operation_id: &str,
        phase: AutomaticEvidencePhase,
        reason: EvidenceGapReason,
    ) {
        let state_ref = Arc::clone(&self.state);
        let mut state = lock_state(&state_ref);
        self.release(&mut state);
        record_gap_locked(
            &mut state,
            self.require_evidence,
            operation_id,
            phase,
            reason,
        );
    }

    const fn release(&mut self, state: &mut EvidenceState) {
        if !self.active {
            return;
        }
        state.reserved_retained_bytes = state
            .reserved_retained_bytes
            .saturating_sub(self.maximum_bytes);
        state.reserved_entries = state.reserved_entries.saturating_sub(1);
        self.active = false;
    }
}

impl Drop for EvidenceReservation {
    fn drop(&mut self) {
        if self.active {
            let state_ref = Arc::clone(&self.state);
            let mut state = lock_state(&state_ref);
            self.release(&mut state);
        }
    }
}

fn lock_state(state: &Mutex<EvidenceState>) -> MutexGuard<'_, EvidenceState> {
    state.lock().unwrap_or_else(PoisonError::into_inner)
}

fn record_gap_locked(
    state: &mut EvidenceState,
    require_evidence: bool,
    operation_id: &str,
    phase: AutomaticEvidencePhase,
    reason: EvidenceGapReason,
) {
    defer_required_failure(state, require_evidence, operation_id, phase);
    let occupied = state
        .entries
        .len()
        .checked_add(state.reserved_entries)
        .unwrap_or(MAX_EVIDENCE_ENTRIES);
    if occupied < MAX_EVIDENCE_ENTRIES {
        state
            .entries
            .push(AutomaticEvidence::gap(operation_id, phase, reason));
    } else {
        state.omitted_entries = state.omitted_entries.saturating_add(1);
    }
}

fn defer_required_failure(
    state: &mut EvidenceState,
    require_evidence: bool,
    operation_id: &str,
    phase: AutomaticEvidencePhase,
) {
    if !require_evidence {
        return;
    }
    if phase != AutomaticEvidencePhase::Before {
        state.required_failure = true;
        return;
    }
    if state
        .pending_required_operations
        .iter()
        .any(|pending| pending == operation_id)
    {
        return;
    }
    if state.pending_required_operations.len() < MAX_PENDING_FAILURES {
        state
            .pending_required_operations
            .push(operation_id.to_owned());
    } else {
        state.required_failure = true;
    }
}

/// Captures the configured before-phase screenshot without reacquiring Work's operation lock.
pub(super) async fn capture_before(
    work: &Work,
    operation_id: &str,
    target: Option<ScreenshotTarget>,
    expected_document_epoch: Option<u64>,
) {
    let policy = &work.session.policy().observe;
    let evidence = &work.session.inner.evidence;
    if !policy.enabled {
        return;
    }
    if let Some(scope) = policy.screenshots.before {
        if let Err(error) = work.authorize(ActionKind::Screenshot, "") {
            evidence.record_gap(
                operation_id,
                AutomaticEvidencePhase::Before,
                if matches!(error, SessionError::Denied) {
                    EvidenceGapReason::ScreenshotDenied
                } else {
                    EvidenceGapReason::CaptureFailed
                },
            );
            return;
        }
        capture(
            work,
            operation_id,
            AutomaticEvidencePhase::Before,
            scope,
            target,
            expected_document_epoch,
        )
        .await;
    }
}

/// Captures the configured settled after or failure screenshot without taking Work's lock.
pub(super) async fn capture_after(
    work: &Work,
    operation_id: &str,
    target: Option<ScreenshotTarget>,
    expected_document_epoch: Option<u64>,
    failed: bool,
) {
    let policy = &work.session.policy().observe;
    if policy.enabled {
        let (phase, scope) = if failed {
            (AutomaticEvidencePhase::Failure, policy.screenshots.failure)
        } else {
            (AutomaticEvidencePhase::After, policy.screenshots.after)
        };
        if let Some(scope) = scope {
            if let Err(error) = work.authorize(ActionKind::Screenshot, "") {
                work.session.inner.evidence.record_gap(
                    operation_id,
                    phase,
                    if matches!(error, SessionError::Denied) {
                        EvidenceGapReason::ScreenshotDenied
                    } else {
                        EvidenceGapReason::CaptureFailed
                    },
                );
                work.session.inner.evidence.settle_operation(operation_id);
                return;
            }
            capture(
                work,
                operation_id,
                phase,
                scope,
                target,
                expected_document_epoch,
            )
            .await;
        }
    }
    work.session.inner.evidence.settle_operation(operation_id);
}

async fn capture(
    work: &Work,
    operation_id: &str,
    phase: AutomaticEvidencePhase,
    scope: ScreenshotScope,
    target: Option<ScreenshotTarget>,
    expected_document_epoch: Option<u64>,
) {
    let evidence = &work.session.inner.evidence;
    let region = match scope {
        ScreenshotScope::Target => {
            if let Some(target) = target {
                ScreenshotRegion::Target(target)
            } else {
                evidence.record_gap(operation_id, phase, EvidenceGapReason::TargetUnavailable);
                return;
            }
        }
        ScreenshotScope::Viewport => ScreenshotRegion::Viewport,
    };
    let maximum_bytes = u64::try_from(MAX_OBSERVATION_SCREENSHOT_BYTES).unwrap_or(u64::MAX);
    let reservation = match evidence.reserve(maximum_bytes) {
        Ok(reservation) => reservation,
        Err(reason) => {
            evidence.record_gap(operation_id, phase, reason);
            return;
        }
    };
    let options = ScreenshotOptions {
        region,
        max_bytes: reservation.maximum_bytes(),
        expected_document_epoch,
    };
    // Keep the optional image pipeline out of every action future's inline state.
    match Box::pin(work.capture_screenshot_unlocked(options)).await {
        Ok(capture) => reservation.commit_capture(operation_id, phase, capture),
        Err(error) => reservation.commit_gap(
            operation_id,
            phase,
            match error {
                SessionError::Denied => EvidenceGapReason::ScreenshotDenied,
                SessionError::ResultLimit { .. } => EvidenceGapReason::RetentionLimit,
                _ => EvidenceGapReason::CaptureFailed,
            },
        ),
    }
}

/// Captures Surface action evidence using a capture-bound node identity when Target is selected.
#[cfg(feature = "browser")]
pub(super) async fn capture_surface_before(
    work: &Work,
    operation_id: &str,
    node_id: Option<u64>,
    capture_epoch: u64,
) {
    let policy = &work.session.policy().observe;
    if !policy.enabled {
        return;
    }
    if let Some(scope) = policy.screenshots.before {
        capture_surface(
            work,
            operation_id,
            AutomaticEvidencePhase::Before,
            scope,
            node_id,
            capture_epoch,
        )
        .await;
    }
}

/// Captures settled Surface after/failure evidence and finalizes its operation boundary.
#[cfg(feature = "browser")]
pub(super) async fn capture_surface_after(
    work: &Work,
    operation_id: &str,
    node_id: Option<u64>,
    capture_epoch: u64,
    failed: bool,
) {
    let policy = &work.session.policy().observe;
    if policy.enabled {
        let (phase, scope) = if failed {
            (AutomaticEvidencePhase::Failure, policy.screenshots.failure)
        } else {
            (AutomaticEvidencePhase::After, policy.screenshots.after)
        };
        if let Some(scope) = scope {
            capture_surface(work, operation_id, phase, scope, node_id, capture_epoch).await;
        }
    }
    work.session.inner.evidence.settle_operation(operation_id);
}

#[cfg(feature = "browser")]
async fn capture_surface(
    work: &Work,
    operation_id: &str,
    phase: AutomaticEvidencePhase,
    scope: ScreenshotScope,
    node_id: Option<u64>,
    capture_epoch: u64,
) {
    let evidence = &work.session.inner.evidence;
    if let Err(error) = work.authorize(ActionKind::Screenshot, "") {
        evidence.record_gap(
            operation_id,
            phase,
            if matches!(error, SessionError::Denied) {
                EvidenceGapReason::ScreenshotDenied
            } else {
                EvidenceGapReason::CaptureFailed
            },
        );
        return;
    }
    let (region, expected_document_epoch) = match scope {
        ScreenshotScope::Viewport => (ScreenshotRegion::Viewport, None),
        ScreenshotScope::Target => {
            let Some(node_id) = node_id else {
                evidence.record_gap(operation_id, phase, EvidenceGapReason::TargetUnavailable);
                return;
            };
            if let Ok((region, epoch)) = work
                .surface_target_region_unlocked(node_id, capture_epoch)
                .await
            {
                (region, Some(epoch))
            } else {
                evidence.record_gap(operation_id, phase, EvidenceGapReason::TargetUnavailable);
                return;
            }
        }
    };
    let maximum_bytes = u64::try_from(MAX_OBSERVATION_SCREENSHOT_BYTES).unwrap_or(u64::MAX);
    let reservation = match evidence.reserve(maximum_bytes) {
        Ok(reservation) => reservation,
        Err(reason) => {
            evidence.record_gap(operation_id, phase, reason);
            return;
        }
    };
    let options = ScreenshotOptions {
        region,
        max_bytes: reservation.maximum_bytes(),
        expected_document_epoch,
    };
    match work.capture_screenshot_unlocked(options).await {
        Ok(capture) => reservation.commit_capture(operation_id, phase, capture),
        Err(error) => reservation.commit_gap(
            operation_id,
            phase,
            match error {
                SessionError::Denied => EvidenceGapReason::ScreenshotDenied,
                SessionError::ResultLimit { .. } => EvidenceGapReason::RetentionLimit,
                _ => EvidenceGapReason::CaptureFailed,
            },
        ),
    }
}

/// Returns whether an action may start after any required evidence gap.
pub(super) fn effect_allowed(work: &Work, kind: ActionKind) -> bool {
    if !matches!(
        kind,
        ActionKind::Navigate
            | ActionKind::Click
            | ActionKind::Scroll
            | ActionKind::EnterText
            | ActionKind::Evaluate
            | ActionKind::Record
    ) {
        return true;
    }
    !work.session.inner.evidence.required_failure()
}

impl Session {
    /// Returns the bounded typed screenshot captures and explicit automatic-evidence gaps.
    ///
    /// Captures share their operation IDs with the corresponding operation receipts. The
    /// snapshot clones immutable image-document handles, not image payload bytes. Manual
    /// screenshot results and recording outputs remain available through their owning APIs.
    pub fn evidence(&self) -> SessionEvidence {
        self.inner.evidence.snapshot()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        documents::ImageDocument,
        policy::{AddressableByteLimit, observe::EvidenceFailurePolicy},
    };
    use std::{error::Error, io};

    fn store(
        maximum_bytes: u64,
        failure: EvidenceFailurePolicy,
    ) -> Result<SessionEvidenceStore, Box<dyn Error>> {
        let mut policy = Policy::default();
        policy.observe.failure = failure;
        policy.observe.limits.max_retained_bytes = AddressableByteLimit::try_from(maximum_bytes)?;
        Ok(SessionEvidenceStore::new(&policy))
    }

    fn screenshot_capture(id: &str) -> Result<ScreenshotCapture, Box<dyn Error>> {
        let document = ImageDocument::from_bytes(
            format!("image-{id}"),
            vec![0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a],
        )?;
        Ok(ScreenshotCapture {
            document,
            metadata: ScreenshotCaptureMetadata {
                capture_id: id.to_owned(),
                source_id: "tab-1".to_owned(),
                tab_id: "tab-1".to_owned(),
                captured_at_unix_ms: Some(1),
                region: ScreenshotRegion::Viewport,
                width_pixels: Some(1),
                height_pixels: Some(1),
                document_epoch: Some(1),
                bounds: None,
                viewport_width: Some(1),
                viewport_height: Some(1),
                device_scale_factor: Some(1.0),
                complete: true,
            },
        })
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn required_before_gap_waits_for_matching_operation_settlement() -> Result<(), Box<dyn Error>> {
        let store = store(128, EvidenceFailurePolicy::Require)?;
        store.begin_operation();
        store.record_gap(
            "operation-current",
            AutomaticEvidencePhase::Before,
            EvidenceGapReason::CaptureFailed,
        );

        assert!(!store.required_failure());
        store.settle_operation("operation-other");
        assert!(!store.required_failure());
        store.settle_operation("operation-current");
        assert!(store.required_failure());
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn continue_policy_never_gates_after_screenshot_or_recording_failures()
    -> Result<(), Box<dyn Error>> {
        let store = store(128, EvidenceFailurePolicy::Continue)?;
        store.begin_operation();
        store.record_gap(
            "operation-before",
            AutomaticEvidencePhase::Before,
            EvidenceGapReason::CaptureFailed,
        );
        store.settle_operation("operation-before");
        store.record_gap(
            "operation-after",
            AutomaticEvidencePhase::Failure,
            EvidenceGapReason::CaptureFailed,
        );
        store.mark_required_failure();
        store.begin_operation();

        assert!(!store.required_failure());
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn background_recording_failure_gates_at_the_next_operation_boundary()
    -> Result<(), Box<dyn Error>> {
        let store = store(128, EvidenceFailurePolicy::Require)?;

        store.mark_required_failure();
        assert!(!store.required_failure());
        store.begin_operation();

        assert!(store.required_failure());
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn screenshot_and_video_reservations_share_and_refund_lifetime_bytes()
    -> Result<(), Box<dyn Error>> {
        let store = store(100, EvidenceFailurePolicy::Continue)?;
        let screenshot = store.reserve(60).map_err(|reason| {
            io::Error::other(format!("screenshot reservation failed: {reason:?}"))
        })?;
        let video = store.retained_reservation();

        assert!(!video.try_add(41));
        drop(screenshot);
        assert!(video.try_add(60));
        assert!(video.commit());
        assert_eq!(store.snapshot().retained_bytes(), 60);

        let screenshot = store.reserve(40).map_err(|reason| {
            io::Error::other(format!("screenshot reservation failed: {reason:?}"))
        })?;
        screenshot.commit_capture(
            "operation-image",
            AutomaticEvidencePhase::After,
            screenshot_capture("image-1")?,
        );
        assert_eq!(store.snapshot().retained_bytes(), 68);

        let dropped_video = store.retained_reservation();
        assert!(dropped_video.try_add(32));
        drop(dropped_video);
        let final_video = store.retained_reservation();
        assert!(final_video.try_add(32));
        assert!(final_video.commit());
        assert_eq!(store.snapshot().retained_bytes(), 100);
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn evidence_entry_limit_counts_omitted_gaps_without_growing_the_vec()
    -> Result<(), Box<dyn Error>> {
        let store = store(128, EvidenceFailurePolicy::Continue)?;
        let total = MAX_EVIDENCE_ENTRIES
            .checked_add(5)
            .ok_or_else(|| io::Error::other("entry count overflow"))?;
        for index in 0..total {
            store.record_gap(
                &format!("operation-{index}"),
                AutomaticEvidencePhase::After,
                EvidenceGapReason::CaptureFailed,
            );
        }

        let snapshot = store.snapshot();
        assert_eq!(snapshot.entries.len(), MAX_EVIDENCE_ENTRIES);
        assert_eq!(snapshot.omitted_entries(), 5);
        assert!(snapshot.has_gaps());
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn omitted_recordings_increment_the_gap_counter_and_defer_required_failure()
    -> Result<(), Box<dyn Error>> {
        let store = store(128, EvidenceFailurePolicy::Require)?;
        store.note_omitted_recording();
        store.mark_required_failure();

        let snapshot = store.snapshot();
        assert_eq!(snapshot.entries, Vec::<AutomaticEvidence>::new());
        assert_eq!(snapshot.omitted_entries(), 1);
        assert!(snapshot.has_gaps());
        assert!(!store.required_failure());
        store.begin_operation();
        assert!(store.required_failure());
        Ok(())
    }
}
