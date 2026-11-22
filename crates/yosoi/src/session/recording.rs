//! Session-owned browser and tab recordings with bounded, independent outputs.

#[cfg(feature = "browser")]
use crate::timing;
use crate::{
    automation_record::{MAX_AUTOMATION_RECORD_ITEMS, OperationReceipt, OperationStatus},
    documents::{MAX_FILE_BYTES, VideoDocument},
    policy::{RecordingMode, RecordingRule, observe::MAX_RECORDING_DURATION_MS},
};
use serde::{Deserialize, Serialize};
#[cfg(feature = "browser")]
use std::mem;
use std::{
    collections::HashSet,
    fmt,
    sync::{Arc, atomic::Ordering},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
#[cfg(feature = "browser")]
use tokio::time::sleep_until;
use tokio::{
    sync::{broadcast, oneshot},
    task::JoinHandle,
};

const MAX_RECORDING_ACTIONS: usize = MAX_AUTOMATION_RECORD_ITEMS;

/// Source selected for a recording owned by a Session.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RecordingScope {
    /// Capture the complete private Session-owned browser display, including browser chrome.
    BrowserVisible,
    /// Capture one retained tab by its Session-scoped tab identity.
    Tab {
        /// Identity returned by Tab::id.
        tab_id: String,
    },
}

/// Finite bounds and track selection for a native recording source and output.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingOptions {
    /// Maximum encoded bytes retained by this logical recording.
    pub max_bytes: u64,
    /// Maximum buffered media bytes retained by the provider before a gap or stop is recorded.
    pub max_buffer_bytes: u64,
    /// Hard recording deadline in milliseconds.
    pub max_duration_ms: u64,
    /// Requested video frame rate, applied as a capture ceiling.
    pub frames_per_second: u32,
    /// Explicitly include audio in a tab capture. Browser-visible recordings are silent.
    pub include_audio: bool,
}

impl Default for RecordingOptions {
    fn default() -> Self {
        Self {
            max_bytes: 64_000_000,
            max_buffer_bytes: 16_000_000,
            max_duration_ms: 60_000,
            frames_per_second: 15,
            include_audio: false,
        }
    }
}

impl RecordingOptions {
    /// Sets the encoded output byte bound.
    pub const fn max_bytes(mut self, maximum: u64) -> Self {
        self.max_bytes = maximum;
        self
    }

    /// Sets the in-flight media buffer bound.
    pub const fn max_buffer_bytes(mut self, maximum: u64) -> Self {
        self.max_buffer_bytes = maximum;
        self
    }

    /// Sets the hard recording deadline.
    pub const fn max_duration_ms(mut self, maximum: u64) -> Self {
        self.max_duration_ms = maximum;
        self
    }

    /// Sets the requested capture frame-rate ceiling.
    pub const fn frames_per_second(mut self, maximum: u32) -> Self {
        self.frames_per_second = maximum;
        self
    }

    /// Explicitly requests the tab's audio track. This is rejected unless the bound Policy grants
    /// native self-tab capture permission.
    pub const fn include_audio(mut self, include: bool) -> Self {
        self.include_audio = include;
        self
    }

    fn validate_and_bound(
        mut self,
        maximum_buffer_bytes: u64,
    ) -> Result<Self, super::SessionError> {
        self.max_buffer_bytes = self.max_buffer_bytes.min(maximum_buffer_bytes);
        if self.max_bytes == 0
            || self.max_bytes > MAX_FILE_BYTES
            || self.max_buffer_bytes == 0
            || self.max_duration_ms == 0
            || self.max_duration_ms > MAX_RECORDING_DURATION_MS
            || Instant::now()
                .checked_add(Duration::from_millis(self.max_duration_ms))
                .is_none()
            || !(1..=60).contains(&self.frames_per_second)
        {
            return Err(super::SessionError::InvalidInput);
        }
        Ok(self)
    }
}

/// Physical capture implementation associated with a logical recording source.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordingSourceKind {
    /// Native browser MediaStream and MediaRecorder from one tab.
    TabMediaStream,
    /// FFmpeg capture of the private Session-owned X11 display.
    BrowserDisplay,
}

/// Identity and scope of the live source shared by compatible recording outputs.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingSource {
    /// Stable identity of this active provider source.
    pub id: String,
    /// Requested Session or tab scope.
    pub scope: RecordingScope,
    /// Native capture implementation.
    pub kind: RecordingSourceKind,
    /// Unix timestamp in milliseconds when the source began, when the clock was available.
    pub started_at_unix_ms: Option<u64>,
}

/// Serializable facts for one uninterrupted video segment.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingSegmentMetadata {
    /// Unique video document identity.
    pub document_id: String,
    /// SHA-256 of the exact retained video container bytes.
    pub sha256: String,
    /// Retained container size in bytes.
    pub byte_len: u64,
    /// Zero-based segment ordinal within the logical recording.
    pub sequence: u32,
    /// Source-relative start offset in milliseconds.
    pub start_offset_ms: u64,
    /// Source-relative end offset in milliseconds.
    pub end_offset_ms: u64,
    /// Provider media clock for the first observed unit in this segment.
    ///
    /// Tab MediaStream uses the first MediaRecorder BlobEvent timecode. BrowserDisplay uses the
    /// fixed-rate encoded frame clock.
    pub media_start_ms: f64,
    /// Provider media clock for the last observed unit in this segment.
    ///
    /// Tab MediaStream uses the last MediaRecorder BlobEvent timecode. BrowserDisplay derives it
    /// from the exact encoded frame count and requested frame rate. This is not a measured source
    /// interval; source-relative start/end offsets provide the interval that the Session observed.
    pub media_end_ms: f64,
    /// Browser-reported media container and codecs.
    pub mime_type: String,
    /// Whether the full interval was materialized into the document.
    pub complete: bool,
}

/// A video segment retained as an immutable Archive-ready document.
#[derive(Clone, Debug, PartialEq)]
pub struct RecordingSegment {
    /// Exact video document for this uninterrupted source segment.
    pub document: VideoDocument,
    /// Timing, media type, and completeness facts for this segment.
    pub metadata: RecordingSegmentMetadata,
}

/// Explicit interval for which a logical recording has no media segment.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingGap {
    /// Source-relative start offset in milliseconds.
    pub start_offset_ms: u64,
    /// Source-relative end offset in milliseconds.
    pub end_offset_ms: u64,
    /// Known reason for the missing interval.
    pub reason: RecordingGapReason,
}

/// A settled operation receipt observed while this recording's logical interval was active.
///
/// This marker records receipt identity and classification only. It never copies page content,
/// form values, or operation result payloads. `settled_at_unix_ms` is when this recording's
/// Session published the already-settled receipt, not when browser dispatch began.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingAction {
    /// OperationReceipt identity.
    pub operation_id: String,
    /// OperationReceipt kind, such as `navigate` or `click`.
    pub kind: String,
    /// OperationReceipt effect certainty.
    pub status: OperationStatus,
    /// Source tab identity when the receipt carried an observation.
    pub tab_id: Option<String>,
    /// Unix milliseconds when the Session published the settled receipt.
    pub settled_at_unix_ms: u64,
}

/// Known reason media is absent for one interval.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordingGapReason {
    /// A document navigation ended the current MediaRecorder segment.
    Navigation,
    /// The provider was reinitializing capture after a document change.
    SourceRearming,
    /// The bounded event or output buffer could not accept media bytes.
    BufferLimit,
    /// The configured output byte bound stopped this recording.
    ByteLimit,
    /// The Session-wide lifetime evidence bound rejected this output chunk.
    RetentionLimit,
    /// A tab or its capture target was closed during recording.
    TabClosed,
    /// The native recorder or its provider event stream failed.
    SourceFailure,
}

/// Why a logical recording stopped.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordingStopReason {
    /// The caller stopped the handle.
    Requested,
    /// The configured maximum duration elapsed.
    DurationLimit,
    /// The configured output byte limit was reached.
    ByteLimit,
    /// The bounded native capture queue could not retain another media chunk.
    BufferLimit,
    /// The Session-wide retained evidence byte limit was reached.
    RetentionLimit,
    /// The owning tab closed.
    TabClosed,
    /// The owning Session closed or was cancelled.
    SessionClosed,
    /// The provider source failed or disconnected.
    SourceFailure,
}

/// Serializable recording facts, separate from retained segment bytes.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingOutcomeMetadata {
    /// Unique identity for this requested recording output.
    pub id: String,
    /// Active capture source shared with compatible handles.
    pub source: RecordingSource,
    /// Ordered metadata corresponding to the outcome's video segments.
    pub segments: Vec<RecordingSegmentMetadata>,
    /// Known source-relative intervals with no captured media.
    pub gaps: Vec<RecordingGap>,
    /// Bounded, payload-free settled operation markers correlated to this output interval.
    #[serde(default)]
    pub actions: Vec<RecordingAction>,
    /// Receipt events lost to watch lag, unavailable clocks, unknown tab attribution, or marker
    /// capacity. The count is bounded by saturating addition.
    #[serde(default)]
    pub lost_action_events: u64,
    /// Unix timestamp in milliseconds when this output stopped, when available.
    pub stopped_at_unix_ms: Option<u64>,
    /// Reason the output stopped.
    pub stop_reason: RecordingStopReason,
    /// Whether every observed interval is represented by complete media without gaps.
    pub complete: bool,
}

/// Final result for one output handle, independent of its shared source lifecycle.
#[derive(Clone, Debug, PartialEq)]
pub struct RecordingOutcome {
    /// Unique identity for this requested recording output.
    pub id: String,
    /// Active capture source shared with compatible handles.
    pub source: RecordingSource,
    /// Uninterrupted video segments produced by this output.
    pub segments: Vec<RecordingSegment>,
    /// Known source-relative intervals with no captured media.
    pub gaps: Vec<RecordingGap>,
    /// Bounded, payload-free settled operation markers correlated to this output interval.
    pub actions: Vec<RecordingAction>,
    /// Receipt events lost to watch lag, unavailable clocks, unknown tab attribution, or marker
    /// capacity. The count is bounded by saturating addition.
    pub lost_action_events: u64,
    /// Unix timestamp in milliseconds when this output stopped, when available.
    pub stopped_at_unix_ms: Option<u64>,
    /// Reason the output stopped.
    pub stop_reason: RecordingStopReason,
    /// Whether every observed interval is represented by complete media without gaps.
    pub complete: bool,
}

impl RecordingOutcome {
    /// Returns all outcome facts without copying video payloads.
    pub fn metadata(&self) -> RecordingOutcomeMetadata {
        RecordingOutcomeMetadata {
            id: self.id.clone(),
            source: self.source.clone(),
            segments: self
                .segments
                .iter()
                .map(|segment| segment.metadata.clone())
                .collect(),
            gaps: self.gaps.clone(),
            actions: self.actions.clone(),
            lost_action_events: self.lost_action_events,
            stopped_at_unix_ms: self.stopped_at_unix_ms,
            stop_reason: self.stop_reason,
            complete: self.complete,
        }
    }

    /// Separates serializable outcome facts from ordered video payload documents.
    ///
    /// The video documents correspond by index to RecordingOutcomeMetadata::segments.
    pub fn into_parts(self) -> (RecordingOutcomeMetadata, Vec<VideoDocument>) {
        let metadata = self.metadata();
        let documents = self
            .segments
            .into_iter()
            .map(|segment| segment.document)
            .collect();
        (metadata, documents)
    }
}

/// Handle that can stop one output without stopping compatible sibling outputs.
pub struct RecordingHandle {
    pub(crate) stop: Option<oneshot::Sender<()>>,
    pub(crate) task: Option<JoinHandle<Result<RecordingOutcome, super::SessionError>>>,
}

impl fmt::Debug for RecordingHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RecordingHandle")
            .field("active", &self.task.is_some())
            .finish_non_exhaustive()
    }
}

impl RecordingHandle {
    /// Starts a bounded passive receipt consumer alongside the native output collector.
    /// The consumer owns only a broadcast receiver, never Session or Work authority.
    fn with_action_tracking(
        mut self,
        receiver: broadcast::Receiver<Arc<super::TimedReceipt>>,
        scope: RecordingScope,
    ) -> Result<Self, super::SessionError> {
        let Some(native_task) = self.task.take() else {
            return Err(super::SessionError::Recording);
        };
        let (stop_actions, stop_signal) = oneshot::channel();
        let action_task = tokio::spawn(collect_recording_actions(receiver, stop_signal, scope));
        self.task = Some(tokio::spawn(async move {
            let recording_result = native_task
                .await
                .unwrap_or(Err(super::SessionError::Recording));
            let _ = stop_actions.send(());
            let actions = action_task.await.unwrap_or_else(|_| CollectedActions {
                actions: Vec::new(),
                lost: 1,
            });
            match recording_result {
                Ok(mut outcome) => {
                    apply_recording_actions(&mut outcome, actions);
                    Ok(outcome)
                }
                Err(error) => Err(error),
            }
        }));
        Ok(self)
    }

    /// Stops this output, waits for its bounded collector to finish, and returns all complete
    /// segments and explicit gaps. Other handles sharing the provider source remain active.
    pub async fn stop(mut self) -> Result<RecordingOutcome, super::SessionError> {
        if let Some(sender) = self.stop.take() {
            let _ = sender.send(());
        }
        let Some(task) = self.task.take() else {
            return Err(super::SessionError::Recording);
        };
        task.await.map_err(|_| super::SessionError::Recording)?
    }
}

#[derive(Default)]
struct CollectedActions {
    actions: Vec<RecordingAction>,
    lost: u64,
}

async fn collect_recording_actions(
    mut receiver: broadcast::Receiver<Arc<super::TimedReceipt>>,
    mut stop: oneshot::Receiver<()>,
    scope: RecordingScope,
) -> CollectedActions {
    let mut collected = CollectedActions {
        actions: Vec::with_capacity(MAX_RECORDING_ACTIONS.min(64)),
        lost: 0,
    };
    loop {
        tokio::select! {
            biased;
            _ = &mut stop => {
                drain_recording_actions(&mut receiver, &scope, &mut collected);
                return collected;
            }
            event = receiver.recv() => {
                match event {
                    Ok(receipt) => record_action_receipt(&receipt.receipt, receipt.settled_at_unix_ms, &scope, &mut collected),
                    Err(broadcast::error::RecvError::Lagged(count)) => {
                        collected.lost = collected.lost.saturating_add(count);
                    }
                    Err(broadcast::error::RecvError::Closed) => return collected,
                }
            }
        }
    }
}

fn drain_recording_actions(
    receiver: &mut broadcast::Receiver<Arc<super::TimedReceipt>>,
    scope: &RecordingScope,
    collected: &mut CollectedActions,
) {
    loop {
        match receiver.try_recv() {
            Ok(receipt) => record_action_receipt(
                &receipt.receipt,
                receipt.settled_at_unix_ms,
                scope,
                collected,
            ),
            Err(broadcast::error::TryRecvError::Lagged(count)) => {
                collected.lost = collected.lost.saturating_add(count);
            }
            Err(broadcast::error::TryRecvError::Empty | broadcast::error::TryRecvError::Closed) => {
                return;
            }
        }
    }
}

fn record_action_receipt(
    receipt: &OperationReceipt,
    published_at_unix_ms: Option<u64>,
    scope: &RecordingScope,
    collected: &mut CollectedActions,
) {
    let tab_id = match scope {
        RecordingScope::BrowserVisible => receipt
            .observation
            .as_ref()
            .map(|observation| observation.tab_id.clone()),
        RecordingScope::Tab { tab_id } => match receipt
            .observation
            .as_ref()
            .map(|observation| observation.tab_id.as_str())
        {
            Some(receipt_tab) if receipt_tab == tab_id => Some(tab_id.clone()),
            Some(_) => return,
            None => {
                collected.lost = collected.lost.saturating_add(1);
                return;
            }
        },
    };
    let Some(settled_at_unix_ms) = published_at_unix_ms else {
        collected.lost = collected.lost.saturating_add(1);
        return;
    };
    if collected.actions.len() >= MAX_RECORDING_ACTIONS {
        collected.lost = collected.lost.saturating_add(1);
        return;
    }
    collected.actions.push(RecordingAction {
        operation_id: receipt.id.clone(),
        kind: receipt.kind.clone(),
        status: receipt.status,
        tab_id,
        settled_at_unix_ms,
    });
}

fn apply_recording_actions(outcome: &mut RecordingOutcome, mut collected: CollectedActions) {
    outcome.lost_action_events = outcome.lost_action_events.saturating_add(collected.lost);
    let Some(source_start) = outcome.source.started_at_unix_ms else {
        outcome.lost_action_events = outcome
            .lost_action_events
            .saturating_add(u64::try_from(collected.actions.len()).unwrap_or(u64::MAX));
        return;
    };

    let first_segment_start = outcome
        .segments
        .iter()
        .map(|segment| segment.metadata.start_offset_ms)
        .min();
    let first_gap_start = outcome.gaps.iter().map(|gap| gap.start_offset_ms).min();
    let start_offset = first_segment_start.or(first_gap_start);
    let mut last_offset = outcome
        .segments
        .iter()
        .map(|segment| segment.metadata.end_offset_ms)
        .chain(outcome.gaps.iter().map(|gap| gap.end_offset_ms))
        .max();
    let Some(start_offset) = start_offset else {
        outcome.lost_action_events = outcome
            .lost_action_events
            .saturating_add(u64::try_from(collected.actions.len()).unwrap_or(u64::MAX));
        return;
    };
    let Some(start_unix_ms) = source_start.checked_add(start_offset) else {
        outcome.lost_action_events = outcome
            .lost_action_events
            .saturating_add(u64::try_from(collected.actions.len()).unwrap_or(u64::MAX));
        return;
    };
    if let Some(stopped_at_unix_ms) = outcome.stopped_at_unix_ms {
        let stop_offset = stopped_at_unix_ms.saturating_sub(source_start);
        last_offset = Some(last_offset.map_or(stop_offset, |last| last.max(stop_offset)));
    }
    let Some(last_offset) = last_offset else {
        outcome.lost_action_events = outcome
            .lost_action_events
            .saturating_add(u64::try_from(collected.actions.len()).unwrap_or(u64::MAX));
        return;
    };
    let Some(end_unix_ms) = source_start.checked_add(last_offset) else {
        outcome.lost_action_events = outcome
            .lost_action_events
            .saturating_add(u64::try_from(collected.actions.len()).unwrap_or(u64::MAX));
        return;
    };
    if end_unix_ms < start_unix_ms {
        outcome.lost_action_events = outcome
            .lost_action_events
            .saturating_add(u64::try_from(collected.actions.len()).unwrap_or(u64::MAX));
        return;
    }
    collected.actions.retain(|action| {
        start_unix_ms <= action.settled_at_unix_ms && action.settled_at_unix_ms <= end_unix_ms
    });
    outcome.actions = collected.actions;
}

pub(super) fn unix_millis_now() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

impl Drop for RecordingHandle {
    fn drop(&mut self) {
        if let Some(sender) = self.stop.take() {
            let _ = sender.send(());
        }
        // Dropping Tokio's JoinHandle detaches the completion supervisor. The native collector
        // sees the stop signal; the supervisor then drains the bounded receipt receiver and lets
        // source cleanup finish without retaining Session or Work authority.
        let _ = self.task.take();
    }
}

impl super::Work {
    /// Starts one independently stoppable native recording of this Work's tab.
    ///
    /// Tab capture requires the bound Policy's explicit native-tab permission. The action worker
    /// permit is used only during source setup; the recording keeps its own bounded capture and
    /// output tasks after Work releases this tab. It returns after the first bounded native media
    /// chunk is accepted; the Work operation deadline and cancellation bound that startup wait.
    /// If the source ends before media arrives, the operation returns
    /// [`super::SessionError::EvidenceUnavailable`].
    pub async fn start_recording(
        &self,
        options: RecordingOptions,
    ) -> Result<RecordingHandle, super::SessionError> {
        if self.session.inner.closing.load(Ordering::Acquire) {
            return Err(super::SessionError::Closed);
        }
        let _operation = self.operation()?;
        self.start_recording_unlocked(options, None).await
    }

    /// Starts a recording while the caller already holds Work's operation lock.
    pub(crate) async fn start_recording_unlocked(
        &self,
        options: RecordingOptions,
        retention: Option<super::RetainedByteReservation>,
    ) -> Result<RecordingHandle, super::SessionError> {
        self.authorize(super::ActionKind::Record, "")?;
        if !self.session.policy().observe.native_tab_capture {
            return Err(super::SessionError::Denied);
        }
        let maximum_recordings =
            u64::from(self.session.policy().observe.limits.max_recordings).max(1);
        let shared_buffer = self.session.policy().observe.limits.max_buffer_bytes.get();
        let divisor = maximum_recordings.saturating_mul(4);
        let per_output_buffer = shared_buffer.checked_div(divisor).unwrap_or(0).max(1);
        let mut options = options;
        options.max_buffer_bytes = options.max_buffer_bytes.min(per_output_buffer);
        let options = options.validate_and_bound(shared_buffer)?;
        #[cfg(feature = "browser")]
        {
            let action_receiver = self.session.inner.recording_events.subscribe();
            let deadline = timing::deadline()
                .or_else(|| timing::checked_deadline(self.timeout()))
                .ok_or(super::SessionError::InvalidInput)?;
            let _permit = self.execution_permit(deadline).await?;
            let setup_cancellation = self.session.inner.backend.cancellation().child_token();
            let _setup_guard = setup_cancellation.clone().drop_guard();
            let scoped_cancellation = super::SCOPED_CANCELLATION
                .try_with(Clone::clone)
                .unwrap_or_default();
            let session_cancellation = self.session.inner.backend.cancellation();
            let tab_closing = self.control.closing();
            let recording = self.session.inner.backend.start_tab_recording(
                &self.control,
                self.tab_id.clone(),
                options,
                retention,
                setup_cancellation.clone(),
            );
            tokio::pin!(recording);
            let handle = tokio::select! {
                biased;
                () = scoped_cancellation.cancelled() => {
                    setup_cancellation.cancel();
                    if let Ok(handle) = recording.await {
                        let _ = handle.stop().await;
                    }
                    Err(super::SessionError::Cancelled)
                }
                () = session_cancellation.cancelled() => {
                    setup_cancellation.cancel();
                    if let Ok(handle) = recording.await {
                        let _ = handle.stop().await;
                    }
                    Err(super::SessionError::Cancelled)
                }
                () = tab_closing.cancelled() => {
                    setup_cancellation.cancel();
                    if let Ok(handle) = recording.await {
                        let _ = handle.stop().await;
                    }
                    Err(super::SessionError::Closed)
                }
                () = sleep_until(deadline) => {
                    setup_cancellation.cancel();
                    if let Ok(handle) = recording.await {
                        let _ = handle.stop().await;
                    }
                    Err(super::SessionError::TimeoutAfterDispatch)
                }
                result = &mut recording => result,
            }?;
            handle.with_action_tracking(
                action_receiver,
                RecordingScope::Tab {
                    tab_id: self.tab_id.clone(),
                },
            )
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = (options, retention);
            Err(super::SessionError::BrowserFeatureDisabled)
        }
    }
}

impl super::Session {
    /// Starts a bounded recording from one Session-owned browser or tab source.
    ///
    /// BrowserVisible requires a BrowserVisible recording rule at acquisition so the browser
    /// already runs on its private display. Tab capture requires
    /// Policy.observe.native_tab_capture=true and a retained tab ID from this Session.
    /// A Tab recording returns after its first bounded native media chunk is accepted; if the
    /// source ends before media arrives, this returns [`super::SessionError::EvidenceUnavailable`].
    /// ObservePolicy.enabled gates automatic rules only; this explicit method remains available.
    pub async fn start_recording(
        &self,
        scope: RecordingScope,
        options: RecordingOptions,
    ) -> Result<RecordingHandle, super::SessionError> {
        if !self
            .inner
            .settings
            .allowed_actions
            .contains(&super::ActionKind::Record)
        {
            return Err(super::SessionError::Denied);
        }
        match scope {
            RecordingScope::BrowserVisible => {
                if self.inner.settings.mode != super::BrowserMode::Headful
                    || !self
                        .inner
                        .policy
                        .observe
                        .recordings
                        .iter()
                        .any(|rule| rule.mode == RecordingMode::BrowserVisible)
                {
                    return Err(super::SessionError::Unsupported(
                        "BrowserVisible recording was not configured at Session launch",
                    ));
                }
                if options.include_audio {
                    return Err(super::SessionError::Unsupported(
                        "BrowserVisible recording is silent",
                    ));
                }
                let options = options
                    .validate_and_bound(self.inner.policy.observe.limits.max_buffer_bytes.get())?;
                #[cfg(feature = "browser")]
                {
                    let action_receiver = self.inner.recording_events.subscribe();
                    let handle = self
                        .inner
                        .backend
                        .start_browser_visible_recording(options, None)
                        .await?;
                    handle.with_action_tracking(action_receiver, RecordingScope::BrowserVisible)
                }
                #[cfg(not(feature = "browser"))]
                {
                    let _ = options;
                    Err(super::SessionError::BrowserFeatureDisabled)
                }
            }
            RecordingScope::Tab { tab_id } => {
                if !self.inner.policy.observe.native_tab_capture {
                    return Err(super::SessionError::Denied);
                }
                if tab_id.is_empty() || tab_id.len() > self.inner.settings.maximum_input_bytes {
                    return Err(super::SessionError::InvalidInput);
                }
                #[cfg(feature = "browser")]
                {
                    let tab = self
                        .inner
                        .backend
                        .tab_by_id(&tab_id)
                        .await
                        .ok_or(super::SessionError::InvalidInput)?;
                    let work = self.work_on(tab).await?;
                    work.start_recording(options).await
                }
                #[cfg(not(feature = "browser"))]
                {
                    let _ = (tab_id, options);
                    Err(super::SessionError::BrowserFeatureDisabled)
                }
            }
        }
    }

    /// Returns completed outcomes for Session-started automatic recording rules.
    ///
    /// In-flight rules remain active; deadline, tab-close, and Session-close outcomes become
    /// available here when their bounded collectors finish. Manual handles return their own
    /// outcome from RecordingHandle::stop.
    pub async fn recording_outcomes(&self) -> Result<Vec<RecordingOutcome>, super::SessionError> {
        let finished = {
            let mut recordings = self.inner.automatic_recordings.lock().await;
            let mut finished = Vec::new();
            let mut active = Vec::new();
            for handle in recordings.drain(..) {
                if handle.task.as_ref().is_none_or(JoinHandle::is_finished) {
                    finished.push(handle);
                } else {
                    active.push(handle);
                }
            }
            *recordings = active;
            finished
        };
        self.retain_finished_recordings(finished).await?;
        Ok(self.inner.completed_recordings.lock().await.clone())
    }

    #[cfg(feature = "browser")]
    pub(super) async fn start_automatic_recordings(&self) {
        let policy = &self.inner.policy.observe;
        if !policy.enabled || self.inner.closing.load(Ordering::Acquire) {
            return;
        }
        for rule in &policy.recordings {
            if rule.mode != RecordingMode::BrowserVisible {
                continue;
            }
            if !self
                .inner
                .settings
                .allowed_actions
                .contains(&super::ActionKind::Record)
            {
                self.retain_failed_automatic_recording(
                    RecordingScope::BrowserVisible,
                    RecordingSourceKind::BrowserDisplay,
                )
                .await;
                continue;
            }
            let options = options_for_rule(rule, policy.limits.max_buffer_bytes.get());
            let retention = self.inner.evidence.retained_reservation();
            let action_receiver = self.inner.recording_events.subscribe();
            match self
                .inner
                .backend
                .start_browser_visible_recording(options, Some(retention))
                .await
            {
                Ok(handle) => {
                    let tracked = handle
                        .with_action_tracking(action_receiver, RecordingScope::BrowserVisible);
                    match tracked {
                        Ok(handle) => self.retain_automatic_recording(handle).await,
                        Err(_) => {
                            self.retain_failed_automatic_recording(
                                RecordingScope::BrowserVisible,
                                RecordingSourceKind::BrowserDisplay,
                            )
                            .await;
                        }
                    }
                }
                Err(_) => {
                    self.retain_failed_automatic_recording(
                        RecordingScope::BrowserVisible,
                        RecordingSourceKind::BrowserDisplay,
                    )
                    .await;
                }
            }
        }
    }

    #[cfg(feature = "browser")]
    pub(crate) async fn start_automatic_tab_recordings(&self, work: &super::Work) {
        let policy = &self.inner.policy.observe;
        if !policy.enabled
            || !policy.native_tab_capture
            || self.inner.closing.load(Ordering::Acquire)
        {
            return;
        }
        let current_url = match work.call(work.control.url()).await {
            Ok(Some(url)) if url.starts_with("http://") || url.starts_with("https://") => url,
            _ => return,
        };
        let _ = current_url;
        for (index, rule) in policy.recordings.iter().enumerate() {
            if rule.mode != RecordingMode::EachTab {
                continue;
            }
            let key = (work.tab_id.clone(), index);
            let admission = {
                let mut keys = self.inner.automatic_recording_keys.lock().await;
                admit_automatic_recording_key(&mut keys, key)
            };
            match admission {
                AutomaticRecordingKeyAdmission::AlreadyPresent => continue,
                AutomaticRecordingKeyAdmission::Added => {}
                AutomaticRecordingKeyAdmission::LimitReached => {
                    self.note_omitted_automatic_recording();
                    continue;
                }
            }
            let options = options_for_rule(rule, policy.limits.max_buffer_bytes.get());
            let retention = self.inner.evidence.retained_reservation();
            match work
                .start_recording_unlocked(options, Some(retention))
                .await
            {
                Ok(handle) => self.retain_automatic_recording(handle).await,
                Err(_) => {
                    self.retain_failed_automatic_recording(
                        RecordingScope::Tab {
                            tab_id: work.tab_id.clone(),
                        },
                        RecordingSourceKind::TabMediaStream,
                    )
                    .await;
                }
            }
        }
    }

    async fn retain_automatic_recording(&self, handle: RecordingHandle) {
        let mut recordings = self.inner.automatic_recordings.lock().await;
        if self.inner.closing.load(Ordering::Acquire) {
            drop(recordings);
            if let Ok(outcome) = handle.stop().await {
                self.retain_automatic_outcomes([outcome]).await;
            } else {
                self.inner.evidence.mark_required_failure();
            }
        } else {
            recordings.push(handle);
        }
    }

    #[cfg(feature = "browser")]
    pub(super) async fn stop_automatic_recordings(&self) -> Result<(), super::SessionError> {
        let active = {
            let mut recordings = self.inner.automatic_recordings.lock().await;
            mem::take(&mut *recordings)
        };
        self.retain_finished_recordings(active).await
    }

    async fn retain_finished_recordings(
        &self,
        recordings: Vec<RecordingHandle>,
    ) -> Result<(), super::SessionError> {
        let mut outcomes = Vec::with_capacity(recordings.len());
        let mut failure = false;
        for handle in recordings {
            if let Ok(outcome) = handle.stop().await {
                outcomes.push(outcome);
            } else {
                failure = true;
                self.inner.evidence.mark_required_failure();
            }
        }
        self.retain_automatic_outcomes(outcomes).await;
        if failure {
            return Err(super::SessionError::EvidenceUnavailable);
        }
        Ok(())
    }

    async fn retain_failed_automatic_recording(
        &self,
        scope: RecordingScope,
        kind: RecordingSourceKind,
    ) {
        self.inner.evidence.mark_required_failure();
        self.retain_automatic_outcomes([failed_outcome(scope, kind)])
            .await;
    }

    async fn retain_automatic_outcomes(
        &self,
        outcomes: impl IntoIterator<Item = RecordingOutcome>,
    ) {
        let mut completed = self.inner.completed_recordings.lock().await;
        for outcome in outcomes {
            let used_items = completed.iter().fold(0_usize, |total, existing| {
                total.saturating_add(recording_metadata_item_count(existing))
            });
            let remaining_items = MAX_AUTOMATION_RECORD_ITEMS.saturating_sub(used_items);
            let closing = self.inner.closing.load(Ordering::Acquire);
            match bound_automatic_outcome(outcome, remaining_items, closing) {
                Some(outcome) => completed.push(outcome),
                None => self.note_omitted_automatic_recording(),
            }
        }
    }

    fn note_omitted_automatic_recording(&self) {
        self.inner.evidence.note_omitted_recording();
        self.inner.evidence.mark_required_failure();
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AutomaticRecordingKeyAdmission {
    AlreadyPresent,
    Added,
    LimitReached,
}

fn admit_automatic_recording_key(
    keys: &mut HashSet<(String, usize)>,
    key: (String, usize),
) -> AutomaticRecordingKeyAdmission {
    if keys.contains(&key) {
        return AutomaticRecordingKeyAdmission::AlreadyPresent;
    }
    if keys.len() >= MAX_AUTOMATION_RECORD_ITEMS {
        return AutomaticRecordingKeyAdmission::LimitReached;
    }
    if keys.insert(key) {
        AutomaticRecordingKeyAdmission::Added
    } else {
        AutomaticRecordingKeyAdmission::AlreadyPresent
    }
}

const fn recording_metadata_item_count(outcome: &RecordingOutcome) -> usize {
    1_usize
        .saturating_add(outcome.segments.len())
        .saturating_add(outcome.gaps.len())
        .saturating_add(outcome.actions.len())
}

fn bound_automatic_outcome(
    mut outcome: RecordingOutcome,
    remaining_items: usize,
    session_closing: bool,
) -> Option<RecordingOutcome> {
    if session_closing && outcome.stop_reason == RecordingStopReason::Requested {
        outcome.stop_reason = RecordingStopReason::SessionClosed;
    }
    let structural_items = 1_usize
        .saturating_add(outcome.segments.len())
        .saturating_add(outcome.gaps.len());
    if structural_items > remaining_items {
        return None;
    }
    let maximum_actions = remaining_items.saturating_sub(structural_items);
    let omitted_actions = outcome.actions.len().saturating_sub(maximum_actions);
    if omitted_actions > 0 {
        outcome.actions.truncate(maximum_actions);
        let omitted_actions = u64::try_from(omitted_actions).unwrap_or(u64::MAX);
        outcome.lost_action_events = outcome.lost_action_events.saturating_add(omitted_actions);
    }
    Some(outcome)
}

const fn options_for_rule(rule: &RecordingRule, maximum_buffer_bytes: u64) -> RecordingOptions {
    RecordingOptions {
        max_bytes: rule.max_bytes.get(),
        max_buffer_bytes: maximum_buffer_bytes,
        max_duration_ms: rule.max_duration_ms,
        frames_per_second: 15,
        include_audio: rule.include_audio,
    }
}

fn failed_outcome(scope: RecordingScope, kind: RecordingSourceKind) -> RecordingOutcome {
    RecordingOutcome {
        id: super::new_operation_id(),
        source: RecordingSource {
            id: "unavailable".into(),
            scope,
            kind,
            started_at_unix_ms: None,
        },
        segments: Vec::new(),
        gaps: vec![RecordingGap {
            start_offset_ms: 0,
            end_offset_ms: 0,
            reason: RecordingGapReason::SourceFailure,
        }],
        stopped_at_unix_ms: unix_millis(),
        stop_reason: RecordingStopReason::SourceFailure,
        actions: Vec::new(),
        lost_action_events: 0,
        complete: false,
    }
}

fn unix_millis() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

#[cfg(test)]
mod action_tests {
    use super::{
        CollectedActions, RecordingAction, RecordingGap, RecordingGapReason, RecordingOutcome,
        RecordingScope, RecordingSource, RecordingSourceKind, RecordingStopReason,
        apply_recording_actions, record_action_receipt,
    };
    use crate::automation_record::{Observation, OperationReceipt, OperationStatus};

    fn action(id: &str, at: u64) -> RecordingAction {
        RecordingAction {
            operation_id: id.to_owned(),
            kind: "click".to_owned(),
            status: OperationStatus::Observed,
            tab_id: Some("tab-a".to_owned()),
            settled_at_unix_ms: at,
        }
    }

    fn receipt(id: &str, tab_id: Option<&str>) -> OperationReceipt {
        OperationReceipt {
            browser: None,
            id: id.to_owned(),
            kind: "click".to_owned(),
            status: OperationStatus::Observed,
            result: None,
            observation: tab_id.map(|tab_id| Observation {
                browser: None,
                id: format!("observation-{id}"),
                session_id: "session-a".to_owned(),
                tab_id: tab_id.to_owned(),
                document_epoch: 1,
                html: None,
                url: None,
                screenshot: None,
            }),
            error: None,
        }
    }

    fn outcome(started_at_unix_ms: Option<u64>) -> RecordingOutcome {
        RecordingOutcome {
            id: "recording-a".to_owned(),
            source: RecordingSource {
                id: "source-a".to_owned(),
                scope: RecordingScope::Tab {
                    tab_id: "tab-a".to_owned(),
                },
                kind: RecordingSourceKind::TabMediaStream,
                started_at_unix_ms,
            },
            segments: Vec::new(),
            gaps: vec![RecordingGap {
                start_offset_ms: 100,
                end_offset_ms: 300,
                reason: RecordingGapReason::Navigation,
            }],
            actions: Vec::new(),
            lost_action_events: 0,
            stopped_at_unix_ms: started_at_unix_ms.and_then(|value| value.checked_add(400)),
            stop_reason: RecordingStopReason::Requested,
            complete: false,
        }
    }

    #[test]
    fn markers_stay_inside_the_recorded_logical_interval_including_gaps() {
        let source_start = 1_700_000_000_000;
        let mut outcome = outcome(Some(source_start));
        let before = source_start.saturating_add(99);
        let during_gap = source_start.saturating_add(150);
        let after = source_start.saturating_add(401);
        apply_recording_actions(
            &mut outcome,
            CollectedActions {
                actions: vec![
                    action("before", before),
                    action("during-gap", during_gap),
                    action("after", after),
                ],
                lost: 2,
            },
        );
        assert_eq!(outcome.actions.len(), 1);
        assert_eq!(
            outcome
                .actions
                .first()
                .map(|value| value.operation_id.as_str()),
            Some("during-gap")
        );
        assert_eq!(outcome.lost_action_events, 2);
    }

    #[test]
    fn tab_markers_are_filtered_by_observed_tab_and_unknown_tabs_are_counted_lost() {
        let scope = RecordingScope::Tab {
            tab_id: "tab-a".to_owned(),
        };
        let mut collected = CollectedActions::default();
        record_action_receipt(
            &receipt("other-tab", Some("tab-b")),
            Some(1234),
            &scope,
            &mut collected,
        );
        record_action_receipt(
            &receipt("unknown-tab", None),
            Some(1234),
            &scope,
            &mut collected,
        );
        record_action_receipt(
            &receipt("matching-tab", Some("tab-a")),
            Some(1234),
            &scope,
            &mut collected,
        );
        assert_eq!(collected.actions.len(), 1);
        assert_eq!(
            collected
                .actions
                .first()
                .map(|value| value.operation_id.as_str()),
            Some("matching-tab")
        );
        assert_eq!(collected.lost, 1);
    }

    #[test]
    fn delayed_consumption_preserves_publication_time_and_excludes_pre_capture_receipts() {
        let scope = RecordingScope::Tab {
            tab_id: "tab-a".into(),
        };
        let mut collected = CollectedActions::default();
        record_action_receipt(
            &receipt("before-video", Some("tab-a")),
            Some(1050),
            &scope,
            &mut collected,
        );
        record_action_receipt(
            &receipt("inside-video", Some("tab-a")),
            Some(1150),
            &scope,
            &mut collected,
        );
        let mut output = outcome(Some(1000));
        apply_recording_actions(&mut output, collected);
        assert_eq!(output.actions.len(), 1);
        assert_eq!(
            output
                .actions
                .first()
                .map(|value| (value.operation_id.as_str(), value.settled_at_unix_ms)),
            Some(("inside-video", 1150))
        );
    }

    #[test]
    fn old_recording_manifests_default_action_markers_to_empty() {
        let encoded = r#"{
            "id":"recording-a",
            "source":{"id":"source-a","scope":{"kind":"browser_visible"},"kind":"browser_display","started_at_unix_ms":1000},
            "segments":[],"gaps":[],"stopped_at_unix_ms":null,
            "stop_reason":"requested","complete":false
        }"#;
        let parsed: Result<super::RecordingOutcomeMetadata, _> = serde_json::from_str(encoded);
        assert!(parsed.is_ok());
        let markers = parsed
            .ok()
            .map(|value| (value.actions, value.lost_action_events));
        assert_eq!(markers, Some((Vec::new(), 0)));
    }
}

#[cfg(test)]
mod tests {
    use super::RecordingOptions;
    use crate::policy::observe::MAX_RECORDING_DURATION_MS;

    #[test]
    fn recording_options_share_the_policy_duration_ceiling() {
        for max_duration_ms in [300_000, MAX_RECORDING_DURATION_MS] {
            let options = RecordingOptions {
                max_duration_ms,
                ..RecordingOptions::default()
            };
            assert!(options.validate_and_bound(16_000_000).is_ok());
        }

        let too_long = RecordingOptions {
            max_duration_ms: MAX_RECORDING_DURATION_MS.saturating_add(1),
            ..RecordingOptions::default()
        };
        assert!(too_long.validate_and_bound(16_000_000).is_err());
    }
}

#[cfg(test)]
mod automatic_recording_bounds_tests {
    use super::{
        AutomaticRecordingKeyAdmission, MAX_AUTOMATION_RECORD_ITEMS, RecordingAction,
        RecordingOutcome, RecordingScope, RecordingSource, RecordingSourceKind,
        RecordingStopReason, admit_automatic_recording_key, bound_automatic_outcome,
        recording_metadata_item_count,
    };
    use crate::automation_record::OperationStatus;
    use std::collections::HashSet;

    fn outcome(action_count: usize) -> RecordingOutcome {
        RecordingOutcome {
            id: "recording-a".into(),
            source: RecordingSource {
                id: "source-a".into(),
                scope: RecordingScope::BrowserVisible,
                kind: RecordingSourceKind::BrowserDisplay,
                started_at_unix_ms: Some(1_000),
            },
            segments: Vec::new(),
            gaps: Vec::new(),
            actions: (0..action_count)
                .map(|index| RecordingAction {
                    operation_id: format!("operation-{index}"),
                    kind: "click".into(),
                    status: OperationStatus::Observed,
                    tab_id: None,
                    settled_at_unix_ms: 1_000,
                })
                .collect(),
            lost_action_events: 0,
            stopped_at_unix_ms: Some(1_000),
            stop_reason: RecordingStopReason::Requested,
            complete: false,
        }
    }

    #[test]
    fn automatic_recording_keys_stop_at_the_lifetime_cap() {
        let mut keys = HashSet::new();
        for index in 0..MAX_AUTOMATION_RECORD_ITEMS {
            assert_eq!(
                admit_automatic_recording_key(&mut keys, (format!("tab-{index}"), 0)),
                AutomaticRecordingKeyAdmission::Added
            );
        }
        assert_eq!(keys.len(), MAX_AUTOMATION_RECORD_ITEMS);
        assert_eq!(
            admit_automatic_recording_key(&mut keys, ("tab-overflow".into(), 0)),
            AutomaticRecordingKeyAdmission::LimitReached
        );
        assert_eq!(keys.len(), MAX_AUTOMATION_RECORD_ITEMS);
        assert_eq!(
            admit_automatic_recording_key(&mut keys, ("tab-0".into(), 0)),
            AutomaticRecordingKeyAdmission::AlreadyPresent
        );
    }

    #[test]
    fn automatic_outcome_truncates_actions_and_counts_lost_markers() {
        let bounded = bound_automatic_outcome(outcome(5), 4, false);
        assert_eq!(bounded.as_ref().map(recording_metadata_item_count), Some(4));
        assert_eq!(bounded.as_ref().map(|value| value.actions.len()), Some(3));
        assert_eq!(
            bounded.as_ref().map(|value| value.lost_action_events),
            Some(2)
        );
    }

    #[test]
    fn automatic_outcome_that_cannot_fit_is_omitted() {
        assert!(bound_automatic_outcome(outcome(0), 0, false).is_none());
    }

    #[test]
    fn session_close_reclassifies_only_requested_automatic_stops() {
        let requested = bound_automatic_outcome(outcome(0), 1, true);
        assert_eq!(
            requested.as_ref().map(|value| value.stop_reason),
            Some(RecordingStopReason::SessionClosed)
        );

        let mut duration_limited = outcome(0);
        duration_limited.stop_reason = RecordingStopReason::DurationLimit;
        let duration_limited = bound_automatic_outcome(duration_limited, 1, true);
        assert_eq!(
            duration_limited.as_ref().map(|value| value.stop_reason),
            Some(RecordingStopReason::DurationLimit)
        );
    }
}
