//! Session-owned source sharing and independently stoppable tab recordings.

use super::{BrowserSession, capture_admission::CapturePermit};
use crate::{
    documents::{FileLimits, FileMetadata, MAX_FILE_BYTES, VideoDocument},
    internal::browser::VoidCrawlError,
    internal::{
        browser::page::{
            NativeMediaBufferAdmitter, NativeMediaBufferLease, NativeTabMediaEvent,
            NativeTabMediaFailureReason, NativeTabMediaOutput, NativeTabMediaSource,
            NativeTabMediaSourceOptions,
        },
        web_capture::{BrowserControlError, RuntimeBrowserControl, RuntimeBrowserTabLease},
    },
    session::{
        RecordingGap, RecordingGapReason, RecordingHandle, RecordingOptions, RecordingOutcome,
        RecordingScope, RecordingSegment, RecordingSegmentMetadata, RecordingSource,
        RecordingSourceKind, RecordingStopReason, RetainedByteReservation, SessionError,
        new_operation_id,
    },
};
use std::{
    collections::HashMap,
    future, mem,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU32, Ordering},
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{
    runtime::Handle,
    sync::{Mutex, Notify, broadcast, oneshot},
    time::{Duration, Instant as TokioInstant, sleep_until, timeout},
};
use tokio_util::sync::CancellationToken;

/// Compatible tab-source settings share one getDisplayMedia stream and use separate recorders.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct SourceKey {
    tab_id: String,
    include_audio: bool,
    frames_per_second: u32,
    maximum_buffer_bytes: u64,
}

struct SharedSource {
    media: NativeTabMediaSource,
    started_at_unix_ms: Option<u64>,
    started: Instant,
    active_outputs: AtomicU32,
    _source_permit: CapturePermit,
}

struct SourceStartGuard {
    registry: TabCaptureRegistry,
    key: SourceKey,
    source: Arc<SharedSource>,
    executor: Handle,
    armed: bool,
}

impl SourceStartGuard {
    const fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for SourceStartGuard {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let registry = self.registry.clone();
        let key = self.key.clone();
        let source = Arc::clone(&self.source);
        let _cleanup = self.executor.spawn(async move {
            registry.remove_if_idle(&key, &source).await;
        });
    }
}

/// Native tab sources owned by one retained browser Session.
#[derive(Clone)]
pub(super) struct TabCaptureRegistry {
    sources: Arc<Mutex<HashMap<SourceKey, Arc<SharedSource>>>>,
    pending: Arc<PendingStarts>,
    active_outputs: Arc<AtomicU32>,
    output_changed: Arc<Notify>,
}

struct PendingStarts {
    count: AtomicU32,
    closed: AtomicBool,
    changed: Notify,
}

struct PendingStartGuard {
    pending: Arc<PendingStarts>,
}

struct OutputActivityGuard {
    active_outputs: Arc<AtomicU32>,
    changed: Arc<Notify>,
}

impl Drop for OutputActivityGuard {
    fn drop(&mut self) {
        let _ = self
            .active_outputs
            .try_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                active.checked_sub(1)
            });
        self.changed.notify_waiters();
    }
}

impl Drop for PendingStartGuard {
    fn drop(&mut self) {
        let _ = self
            .pending
            .count
            .try_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                count.checked_sub(1)
            });
        self.pending.changed.notify_waiters();
    }
}

impl TabCaptureRegistry {
    pub(super) fn new() -> Self {
        Self {
            sources: Arc::new(Mutex::new(HashMap::new())),
            pending: Arc::new(PendingStarts {
                count: AtomicU32::new(0),
                closed: AtomicBool::new(false),
                changed: Notify::new(),
            }),
            active_outputs: Arc::new(AtomicU32::new(0)),
            output_changed: Arc::new(Notify::new()),
        }
    }

    pub(super) async fn start(
        &self,
        session: &BrowserSession,
        control: &RuntimeBrowserControl,
        tab_id: String,
        options: RecordingOptions,
        retention: Option<RetainedByteReservation>,
        setup_cancellation: CancellationToken,
    ) -> Result<RecordingHandle, SessionError> {
        if self.pending.closed.load(Ordering::Acquire) {
            return Err(SessionError::Closed);
        }
        let pending = self.begin_start()?;
        let executor = provider_executor(session)?;
        let session = session.clone();
        let control = control.clone();
        let registry = self.clone();
        let (reply, response) = oneshot::channel();
        let _start_task = executor.spawn(async move {
            let _pending = pending;
            let result = registry
                .start_inner(
                    &session,
                    &control,
                    tab_id,
                    options,
                    retention,
                    setup_cancellation,
                )
                .await;
            if let Err(Ok(handle)) = reply.send(result) {
                let _ = handle.stop().await;
            }
        });
        response.await.map_err(|_| SessionError::Closed)?
    }

    async fn start_inner(
        &self,
        session: &BrowserSession,
        control: &RuntimeBrowserControl,
        tab_id: String,
        options: RecordingOptions,
        retention: Option<RetainedByteReservation>,
        setup_cancellation: CancellationToken,
    ) -> Result<RecordingHandle, SessionError> {
        if session.is_closed() {
            return Err(SessionError::Closed);
        }
        if setup_cancellation.is_cancelled() {
            return Err(SessionError::Cancelled);
        }
        if !session.inner.native_tab_capture {
            return Err(SessionError::Denied);
        }
        validate_options(&options)?;
        let executor = provider_executor(session)?;
        let output_permit = session.inner.capture_admission.output()?;
        let key = SourceKey {
            tab_id: tab_id.clone(),
            include_audio: options.include_audio,
            frames_per_second: options.frames_per_second,
            maximum_buffer_bytes: options.max_buffer_bytes,
        };
        let source = self
            .get_or_create_source(session, control, key.clone(), setup_cancellation.clone())
            .await?;
        let mut source_start_guard = SourceStartGuard {
            registry: self.clone(),
            key: key.clone(),
            source: Arc::clone(&source),
            executor: executor.clone(),
            armed: true,
        };
        let output_id = new_operation_id();
        let output_start = source
            .media
            .start_output(output_id.clone(), options.include_audio);
        tokio::pin!(output_start);
        let media_output = match tokio::select! {
            biased;
            () = setup_cancellation.cancelled() => Err(SessionError::Cancelled),
            result = &mut output_start => result.map_err(|error| map_provider_error(&error)),
        } {
            Ok(output) => output,
            Err(error) => {
                self.remove_if_idle(&key, &source).await;
                source_start_guard.disarm();
                return Err(error);
            }
        };
        if source
            .active_outputs
            .try_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                active.checked_add(1)
            })
            .is_err()
        {
            let _ = source.media.request_stop_output(output_id);
            self.remove_if_idle(&key, &source).await;
            source_start_guard.disarm();
            return Err(SessionError::Admission);
        }
        if self
            .active_outputs
            .try_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                active.checked_add(1)
            })
            .is_err()
        {
            let _ = source.media.request_stop_output(output_id);
            self.release_output(&key, &source).await;
            source_start_guard.disarm();
            return Err(SessionError::Admission);
        }
        source_start_guard.disarm();

        let (stop, stop_signal) = oneshot::channel();
        let session_cancellation = session.cancellation();
        let tab_cancellation = control.closing();
        let session_id = session.id();
        let source_info = RecordingSource {
            id: source.media.id().to_owned(),
            scope: RecordingScope::Tab {
                tab_id: tab_id.clone(),
            },
            kind: RecordingSourceKind::TabMediaStream,
            started_at_unix_ms: source.started_at_unix_ms,
        };
        let registry = self.clone();
        let output_activity = OutputActivityGuard {
            active_outputs: Arc::clone(&self.active_outputs),
            changed: Arc::clone(&self.output_changed),
        };
        let source_for_task = Arc::clone(&source);
        let task = executor.spawn(async move {
            Ok(collect_output(CollectOutputTask {
                registry,
                key,
                source: source_for_task,
                output: media_output,
                output_id,
                source_info,
                session_id,
                tab_id,
                options,
                retention,
                _output_permit: output_permit,
                stop: stop_signal,
                session_cancellation,
                tab_cancellation,
                _output_activity: output_activity,
            })
            .await)
        });
        Ok(RecordingHandle {
            stop: Some(stop),
            task: Some(task),
        })
    }

    async fn get_or_create_source(
        &self,
        session: &BrowserSession,
        control: &RuntimeBrowserControl,
        key: SourceKey,
        setup_cancellation: CancellationToken,
    ) -> Result<Arc<SharedSource>, SessionError> {
        let existing = self.sources.lock().await.get(&key).cloned();
        if let Some(source) = existing {
            return Ok(source);
        }
        let source_permit = session.inner.capture_admission.source()?;
        let admission = session.inner.capture_admission.clone();
        let buffer_admitter: NativeMediaBufferAdmitter = Arc::new(move |bytes| {
            admission.buffer(bytes).ok().map(|permit| {
                let lease: Arc<dyn NativeMediaBufferLease> = Arc::new(permit);
                lease
            })
        });
        let source_id = new_operation_id();
        let executor = provider_executor(session)?;
        let media = control
            .start_native_tab_media_source(NativeTabMediaSourceOptions {
                id: source_id,
                source_audio: key.include_audio,
                frames_per_second: key.frames_per_second,
                maximum_buffer_bytes: key.maximum_buffer_bytes,
                buffer_admitter,
                setup_cancellation,
                cancellation: session.cancellation(),
                executor,
            })
            .await
            .map_err(|error| map_control_error(&error))?;
        if self.pending.closed.load(Ordering::Acquire) || session.is_closed() {
            media.close().await;
            return Err(SessionError::Closed);
        }
        let candidate = Arc::new(SharedSource {
            media,
            started_at_unix_ms: unix_millis(),
            started: Instant::now(),
            active_outputs: AtomicU32::new(0),
            _source_permit: source_permit,
        });
        let mut sources = self.sources.lock().await;
        if let Some(existing) = sources.get(&key).cloned() {
            drop(sources);
            candidate.media.close().await;
            return Ok(existing);
        }
        sources.insert(key, Arc::clone(&candidate));
        drop(sources);
        Ok(candidate)
    }

    async fn remove_if_idle(&self, key: &SourceKey, source: &Arc<SharedSource>) {
        if source.active_outputs.load(Ordering::Acquire) != 0 {
            return;
        }
        let removed = {
            let mut sources = self.sources.lock().await;
            let matches = sources
                .get(key)
                .is_some_and(|candidate| Arc::ptr_eq(candidate, source));
            if matches { sources.remove(key) } else { None }
        };
        if let Some(removed) = removed {
            removed.media.close().await;
        }
    }

    async fn release_output(&self, key: &SourceKey, source: &Arc<SharedSource>) {
        let was_last = source
            .active_outputs
            .try_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                active.checked_sub(1)
            })
            .is_ok_and(|active| active == 1);
        if was_last {
            self.remove_if_idle(key, source).await;
        }
    }

    pub(super) async fn close(&self) {
        self.pending.closed.store(true, Ordering::Release);
        let wait_for_starts = async {
            loop {
                let changed = self.pending.changed.notified();
                if self.pending.count.load(Ordering::Acquire) == 0 {
                    break;
                }
                changed.await;
            }
        };
        let _ = timeout(Duration::from_secs(30), wait_for_starts).await;
        let sources = {
            let mut sources = self.sources.lock().await;
            mem::take(&mut *sources).into_values().collect::<Vec<_>>()
        };
        for source in &sources {
            source.media.cancel();
        }
        for source in sources {
            source.media.close().await;
        }
        let wait_for_outputs = async {
            loop {
                let changed = self.output_changed.notified();
                if self.active_outputs.load(Ordering::Acquire) == 0 {
                    break;
                }
                changed.await;
            }
        };
        let _ = timeout(Duration::from_secs(20), wait_for_outputs).await;
    }

    fn begin_start(&self) -> Result<PendingStartGuard, SessionError> {
        if self.pending.closed.load(Ordering::Acquire) {
            return Err(SessionError::Closed);
        }
        self.pending
            .count
            .try_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                count.checked_add(1)
            })
            .map_err(|_| SessionError::Admission)?;
        let guard = PendingStartGuard {
            pending: Arc::clone(&self.pending),
        };
        if self.pending.closed.load(Ordering::Acquire) {
            drop(guard);
            return Err(SessionError::Closed);
        }
        Ok(guard)
    }
}

impl BrowserSession {
    /// Looks up one Session-owned tab by its opaque public identity.
    pub async fn tab_by_id(&self, tab_id: &str) -> Option<RuntimeBrowserTabLease> {
        let tabs = self.inner.tabs.lock().await;
        tabs.iter()
            .find(|tab| tab.id().to_string() == tab_id)
            .cloned()
    }

    /// Starts one bounded per-tab recording output over a shared native source.
    pub(crate) async fn start_tab_recording(
        &self,
        control: &RuntimeBrowserControl,
        tab_id: String,
        options: RecordingOptions,
        retention: Option<RetainedByteReservation>,
        setup_cancellation: CancellationToken,
    ) -> Result<RecordingHandle, SessionError> {
        self.inner
            .tab_capture
            .start(
                self,
                control,
                tab_id,
                options,
                retention,
                setup_cancellation,
            )
            .await
    }
}

fn provider_executor(session: &BrowserSession) -> Result<Handle, SessionError> {
    session
        .inner
        .budget
        .lock()
        .map_err(|_| SessionError::EvidenceUnavailable)?
        .as_ref()
        .map(|budget| budget.executor.clone())
        .ok_or(SessionError::Closed)
}

fn validate_options(options: &RecordingOptions) -> Result<(), SessionError> {
    if options.max_bytes == 0
        || options.max_bytes > MAX_FILE_BYTES
        || options.max_buffer_bytes == 0
        || options.max_duration_ms == 0
        || Instant::now()
            .checked_add(Duration::from_millis(options.max_duration_ms))
            .is_none()
        || !(1..=60).contains(&options.frames_per_second)
    {
        return Err(SessionError::InvalidInput);
    }
    Ok(())
}

const fn map_provider_error(error: &VoidCrawlError) -> SessionError {
    match error {
        VoidCrawlError::UnsupportedCapability { operation } => SessionError::Unsupported(operation),
        _ => SessionError::EvidenceUnavailable,
    }
}

const fn map_control_error(error: &BrowserControlError) -> SessionError {
    match error {
        BrowserControlError::Cancelled => SessionError::Cancelled,
        BrowserControlError::Deadline => SessionError::Deadline,
        BrowserControlError::Ownership(_) => SessionError::Closed,
        BrowserControlError::Provider(error) => map_provider_error(error),
        _ => SessionError::EvidenceUnavailable,
    }
}

struct SegmentBuffer {
    sequence: u32,
    start_offset_ms: u64,
    media_start_ms: Option<f64>,
    media_end_ms: f64,
    last_sequence: Option<u64>,
    mime_type: String,
    bytes: Vec<u8>,
    complete: bool,
}

struct CollectOutputTask {
    registry: TabCaptureRegistry,
    key: SourceKey,
    source: Arc<SharedSource>,
    output: NativeTabMediaOutput,
    output_id: String,
    source_info: RecordingSource,
    session_id: String,
    tab_id: String,
    options: RecordingOptions,
    retention: Option<RetainedByteReservation>,
    _output_permit: CapturePermit,
    stop: oneshot::Receiver<()>,
    session_cancellation: CancellationToken,
    tab_cancellation: CancellationToken,
    _output_activity: OutputActivityGuard,
}

#[derive(Clone, Copy)]
struct SegmentContext<'a> {
    started: Instant,
    session_id: &'a str,
    tab_id: &'a str,
    output_id: &'a str,
    maximum_bytes: u64,
}

#[expect(
    clippy::cognitive_complexity,
    reason = "One output state machine preserves segment, gap, cancellation and stop transitions for a shared native source"
)]
async fn collect_output(task: CollectOutputTask) -> RecordingOutcome {
    let CollectOutputTask {
        registry,
        key,
        source,
        output,
        output_id,
        source_info,
        session_id,
        tab_id,
        options,
        retention,
        _output_permit,
        mut stop,
        session_cancellation,
        tab_cancellation,
        _output_activity,
    } = task;
    let started = source.started;
    let hard_deadline = TokioInstant::now()
        .checked_add(Duration::from_millis(options.max_duration_ms))
        .unwrap_or_else(TokioInstant::now);
    let finish_grace = Duration::from_secs(3);
    let mut current: Option<SegmentBuffer> = None;
    let mut segments = Vec::new();
    let mut gaps = Vec::new();
    let mut gap_start: Option<(u64, RecordingGapReason)> = None;
    let mut total_bytes = 0_u64;
    let mut stop_reason = RecordingStopReason::Requested;
    let mut stopping = false;
    let mut stopped = false;
    let mut finish_deadline: Option<TokioInstant> = None;
    let mut events = output.events;
    loop {
        tokio::select! {
            biased;
            () = session_cancellation.cancelled(), if !stopping => {
                stop_reason = RecordingStopReason::SessionClosed;
                open_gap(&mut gap_start, offset_ms(started, Instant::now()), RecordingGapReason::SourceFailure);
                begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
            }
            () = tab_cancellation.cancelled(), if !stopping => {
                stop_reason = RecordingStopReason::TabClosed;
                open_gap(&mut gap_start, offset_ms(started, Instant::now()), RecordingGapReason::TabClosed);
                begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
            }
            () = sleep_until(hard_deadline), if !stopping => {
                stop_reason = RecordingStopReason::DurationLimit;
                begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
            }
            () = async { if let Some(deadline) = finish_deadline { sleep_until(deadline).await } else { future::pending::<()>().await } }, if stopping => {
                break;
            }
            result = &mut stop, if !stopping => {
                let _ = result;
                stop_reason = RecordingStopReason::Requested;
                begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
            }
            delivery = events.recv() => {
                match delivery {
                    Ok(NativeTabMediaEvent::SegmentStarted { output_id: event_id, segment, mime_type, started_at })
                        if event_id == output_id =>
                    {
                        if let Some((gap_at, reason)) = gap_start.take() {
                            gaps.push(RecordingGap {
                                start_offset_ms: gap_at,
                                end_offset_ms: offset_ms(started, started_at),
                                reason,
                            });
                        }
                        if current.is_some() {
                            let _ = finalize_segment(
                                &mut current,
                                &mut segments,
                                started_at,
                                false,
                                SegmentContext {
                                    started,
                                    session_id: &session_id,
                                    tab_id: &tab_id,
                                    output_id: &output_id,
                                    maximum_bytes: options.max_bytes,
                                },
                            );
                        }
                        current = Some(SegmentBuffer {
                            sequence: segment,
                            start_offset_ms: offset_ms(started, started_at),
                            media_start_ms: None,
                            media_end_ms: 0.0,
                            last_sequence: None,
                            mime_type,
                            bytes: Vec::new(),
                            complete: false,
                        });
                    }
                    Ok(NativeTabMediaEvent::Chunk { output_id: event_id, segment, sequence, media_time_ms, mime_type: _, bytes, received_at, .. })
                        if event_id == output_id =>
                    {
                        let Some(current_segment) = current.as_mut().filter(|current| current.sequence == segment) else { continue; };
                        if media_time_ms < current_segment.media_end_ms {
                            stop_reason = RecordingStopReason::SourceFailure;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::SourceFailure);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        }
                        let expected_sequence = current_segment
                            .last_sequence
                            .map_or(Some(0), |last| last.checked_add(1));
                        if expected_sequence != Some(sequence) {
                            stop_reason = RecordingStopReason::BufferLimit;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::BufferLimit);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        }
                        let Ok(chunk_len) = u64::try_from(bytes.len()) else {
                            stop_reason = RecordingStopReason::ByteLimit;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::ByteLimit);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        };
                        let Some(next_total) = total_bytes.checked_add(chunk_len) else {
                            stop_reason = RecordingStopReason::ByteLimit;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::ByteLimit);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        };
                        if next_total > options.max_bytes {
                            stop_reason = RecordingStopReason::ByteLimit;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::ByteLimit);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        }
                        if retention.as_ref().is_some_and(|reservation| !reservation.try_add(chunk_len)) {
                            stop_reason = RecordingStopReason::RetentionLimit;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::RetentionLimit);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        }
                        if current_segment.bytes.len().checked_add(bytes.len()).is_none() {
                            stop_reason = RecordingStopReason::ByteLimit;
                            open_gap(&mut gap_start, offset_ms(started, received_at), RecordingGapReason::ByteLimit);
                            begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                            continue;
                        }
                        current_segment.media_start_ms.get_or_insert(media_time_ms);
                        current_segment.media_end_ms = media_time_ms;
                        current_segment.last_sequence = Some(sequence);
                        current_segment.bytes.extend_from_slice(&bytes);
                        total_bytes = next_total;
                    }
                    Ok(NativeTabMediaEvent::Navigation { output_id: event_id, segment, at })
                        if event_id == output_id =>
                    {
                        let end = offset_ms(started, at);
                        if current.as_ref().is_some_and(|current| current.sequence == segment)
                            && let Some(mut ended) = current.take()
                        {
                            ended.complete = false;
                            let _ = push_segment(ended, end, &mut segments, &session_id, &tab_id, &output_id, options.max_bytes);
                        }
                        open_gap(&mut gap_start, end, RecordingGapReason::Navigation);
                    }
                    Ok(NativeTabMediaEvent::SegmentStopped { output_id: event_id, segment, at })
                        if event_id == output_id =>
                    {
                        if current.as_ref().is_some_and(|current| current.sequence == segment)
                            && let Some(mut ended) = current.take()
                        {
                            ended.complete = false;
                            let _ = push_segment(
                                ended,
                                offset_ms(started, at),
                                &mut segments,
                                &session_id,
                                &tab_id,
                                &output_id,
                                options.max_bytes,
                            );
                        }
                        open_gap(
                            &mut gap_start,
                            offset_ms(started, at),
                            RecordingGapReason::SourceRearming,
                        );
                    }
                    Ok(NativeTabMediaEvent::OutputStopped { output_id: event_id, segment, at })
                        if event_id == output_id =>
                    {
                        let end = offset_ms(started, at);
                        if current.as_ref().is_some_and(|current| current.sequence == segment)
                            && let Some(mut ended) = current.take()
                        {
                            ended.complete = matches!(stop_reason, RecordingStopReason::Requested | RecordingStopReason::DurationLimit);
                            let _ = push_segment(ended, end, &mut segments, &session_id, &tab_id, &output_id, options.max_bytes);
                        }
                        close_gap(&mut gap_start, end, &mut gaps);
                        stopped = true;
                        break;
                    }
                    Ok(NativeTabMediaEvent::SourceFailure { at }) => {
                        stop_reason = RecordingStopReason::SourceFailure;
                        open_gap(&mut gap_start, offset_ms(started, at), RecordingGapReason::SourceFailure);
                        break;
                    }
                    Ok(NativeTabMediaEvent::OutputFailure { output_id: event_id, segment, reason, at })
                        if event_id == output_id =>
                    {
                        stop_reason = match reason {
                            NativeTabMediaFailureReason::BufferLimit => RecordingStopReason::BufferLimit,
                            NativeTabMediaFailureReason::SourceFailure => RecordingStopReason::SourceFailure,
                        };
                        let gap_reason = match reason {
                            NativeTabMediaFailureReason::BufferLimit => RecordingGapReason::BufferLimit,
                            NativeTabMediaFailureReason::SourceFailure => RecordingGapReason::SourceFailure,
                        };
                        if current.as_ref().is_some_and(|current| current.sequence == segment)
                            && let Some(mut ended) = current.take()
                        {
                            ended.complete = false;
                            let _ = push_segment(ended, offset_ms(started, at), &mut segments, &session_id, &tab_id, &output_id, options.max_bytes);
                        }
                        open_gap(&mut gap_start, offset_ms(started, at), gap_reason);
                        begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                    }
                    Err(broadcast::error::RecvError::Lagged(_)) => {
                        stop_reason = RecordingStopReason::BufferLimit;
                        open_gap(&mut gap_start, offset_ms(started, Instant::now()), RecordingGapReason::BufferLimit);
                        begin_output_stop(&source, &output_id, &mut stopping, &mut finish_deadline, finish_grace);
                    }
                    Err(broadcast::error::RecvError::Closed) => {
                        stop_reason = RecordingStopReason::SourceFailure;
                        open_gap(&mut gap_start, offset_ms(started, Instant::now()), RecordingGapReason::SourceFailure);
                        break;
                    }
                    _ => {}
                }
            }
        }
    }
    if !stopped && stopping {
        let _ = timeout(finish_grace, async {
            loop {
                match events.recv().await {
                    Ok(NativeTabMediaEvent::Chunk {
                        output_id: event_id,
                        segment,
                        sequence,
                        media_time_ms,
                        bytes,
                        received_at,
                        ..
                    }) if event_id == output_id => {
                        if let Some(current_segment) = current
                            .as_mut()
                            .filter(|current| current.sequence == segment)
                        {
                            let expected_sequence = current_segment
                                .last_sequence
                                .map_or(Some(0), |last| last.checked_add(1));
                            if expected_sequence != Some(sequence)
                                || media_time_ms < current_segment.media_end_ms
                            {
                                open_gap(
                                    &mut gap_start,
                                    offset_ms(started, received_at),
                                    RecordingGapReason::BufferLimit,
                                );
                                continue;
                            }
                            let chunk_len = u64::try_from(bytes.len()).unwrap_or(u64::MAX);
                            let next = total_bytes.checked_add(chunk_len);
                            if next.is_some_and(|value| value <= options.max_bytes)
                                && retention
                                    .as_ref()
                                    .is_none_or(|reservation| reservation.try_add(chunk_len))
                            {
                                current_segment.media_start_ms.get_or_insert(media_time_ms);
                                current_segment.media_end_ms = media_time_ms;
                                current_segment.last_sequence = Some(sequence);
                                current_segment.bytes.extend_from_slice(&bytes);
                                total_bytes = next.unwrap_or(total_bytes);
                            } else {
                                open_gap(
                                    &mut gap_start,
                                    offset_ms(started, received_at),
                                    RecordingGapReason::ByteLimit,
                                );
                            }
                        }
                    }
                    Ok(NativeTabMediaEvent::OutputStopped {
                        output_id: event_id,
                        segment,
                        at,
                    }) if event_id == output_id => {
                        if current
                            .as_ref()
                            .is_some_and(|current| current.sequence == segment)
                            && let Some(mut ended) = current.take()
                        {
                            ended.complete = matches!(
                                stop_reason,
                                RecordingStopReason::Requested | RecordingStopReason::DurationLimit
                            );
                            let _ = push_segment(
                                ended,
                                offset_ms(started, at),
                                &mut segments,
                                &session_id,
                                &tab_id,
                                &output_id,
                                options.max_bytes,
                            );
                        }
                        close_gap(&mut gap_start, offset_ms(started, at), &mut gaps);
                        stopped = true;
                        break;
                    }
                    Ok(_) => {}
                    Err(_) => break,
                }
            }
        })
        .await;
    }
    if let Some(mut current) = current.take() {
        current.complete = false;
        let _ = push_segment(
            current,
            offset_ms(started, Instant::now()),
            &mut segments,
            &session_id,
            &tab_id,
            &output_id,
            options.max_bytes,
        );
    }
    let stopped_offset = offset_ms(started, Instant::now());
    close_gap(&mut gap_start, stopped_offset, &mut gaps);
    if !stopped
        && matches!(
            stop_reason,
            RecordingStopReason::Requested | RecordingStopReason::DurationLimit
        )
    {
        stop_reason = RecordingStopReason::SourceFailure;
        if gaps.is_empty() {
            gaps.push(RecordingGap {
                start_offset_ms: stopped_offset,
                end_offset_ms: stopped_offset,
                reason: RecordingGapReason::SourceFailure,
            });
        }
    }
    let document_bytes = segments.iter().try_fold(0_u64, |total, segment| {
        total.checked_add(segment.document.byte_len())
    });
    if document_bytes != Some(total_bytes) {
        segments.clear();
        stop_reason = RecordingStopReason::SourceFailure;
        gaps.push(RecordingGap {
            start_offset_ms: 0,
            end_offset_ms: stopped_offset,
            reason: RecordingGapReason::SourceFailure,
        });
    } else if segments.is_empty() && gaps.is_empty() {
        stop_reason = RecordingStopReason::SourceFailure;
        gaps.push(RecordingGap {
            start_offset_ms: 0,
            end_offset_ms: stopped_offset,
            reason: RecordingGapReason::SourceFailure,
        });
    }
    if let Some(retention) = &retention
        && !segments.is_empty()
        && !retention.commit()
    {
        segments.clear();
        gaps.push(RecordingGap {
            start_offset_ms: 0,
            end_offset_ms: stopped_offset,
            reason: RecordingGapReason::RetentionLimit,
        });
        stop_reason = RecordingStopReason::RetentionLimit;
    }
    registry.release_output(&key, &source).await;
    let complete = !segments.is_empty()
        && gaps.is_empty()
        && segments.iter().all(|segment| segment.metadata.complete)
        && matches!(
            stop_reason,
            RecordingStopReason::Requested | RecordingStopReason::DurationLimit
        );
    if !complete && let Some(retention) = &retention {
        retention.mark_failure();
    }
    RecordingOutcome {
        id: output_id,
        source: source_info,
        segments,
        gaps,
        actions: Vec::new(),
        lost_action_events: 0,
        stopped_at_unix_ms: unix_millis(),
        stop_reason,
        complete,
    }
}

fn begin_output_stop(
    source: &SharedSource,
    output_id: &str,
    stopping: &mut bool,
    finish_deadline: &mut Option<TokioInstant>,
    grace: Duration,
) {
    if *stopping {
        return;
    }
    *stopping = true;
    *finish_deadline = TokioInstant::now().checked_add(grace);
    let _ = source.media.request_stop_output(output_id.to_owned());
}

const fn open_gap(
    gap_start: &mut Option<(u64, RecordingGapReason)>,
    offset_ms: u64,
    reason: RecordingGapReason,
) {
    if gap_start.is_none() {
        *gap_start = Some((offset_ms, reason));
    }
}

fn close_gap(
    gap_start: &mut Option<(u64, RecordingGapReason)>,
    end_offset_ms: u64,
    gaps: &mut Vec<RecordingGap>,
) {
    if let Some((start_offset_ms, reason)) = gap_start.take() {
        gaps.push(RecordingGap {
            start_offset_ms,
            end_offset_ms: end_offset_ms.max(start_offset_ms),
            reason,
        });
    }
}

fn finalize_segment(
    current: &mut Option<SegmentBuffer>,
    segments: &mut Vec<RecordingSegment>,
    ended: Instant,
    complete: bool,
    context: SegmentContext<'_>,
) -> Result<(), SessionError> {
    if let Some(mut segment) = current.take() {
        segment.complete = complete;
        push_segment(
            segment,
            offset_ms(context.started, ended),
            segments,
            context.session_id,
            context.tab_id,
            context.output_id,
            context.maximum_bytes,
        )?;
    }
    Ok(())
}

fn push_segment(
    segment: SegmentBuffer,
    end_offset_ms: u64,
    segments: &mut Vec<RecordingSegment>,
    session_id: &str,
    tab_id: &str,
    output_id: &str,
    maximum_bytes: u64,
) -> Result<(), SessionError> {
    if segment.bytes.is_empty() {
        return Ok(());
    }
    let sequence = u32::try_from(segments.len()).map_err(|_| SessionError::InvalidInput)?;
    let id = format!("video-{output_id}-{sequence}");
    let metadata = FileMetadata::new()
        .with_declared_media_type(segment.mime_type.clone())
        .map_err(|_| SessionError::EvidenceUnavailable)?
        .with_source("yosoi.session.tab_media_recorder")
        .map_err(|_| SessionError::EvidenceUnavailable)?
        .with_capture_id(output_id.to_owned())
        .map_err(|_| SessionError::EvidenceUnavailable)?
        .with_session_id(session_id.to_owned())
        .map_err(|_| SessionError::EvidenceUnavailable)?
        .with_tab_id(tab_id.to_owned())
        .map_err(|_| SessionError::EvidenceUnavailable)?;
    let limits = FileLimits::new(maximum_bytes).map_err(|_| SessionError::InvalidInput)?;
    let document = VideoDocument::from_bytes_with_metadata(id, segment.bytes, metadata, limits)
        .map_err(|_| SessionError::EvidenceUnavailable)?;
    let metadata = RecordingSegmentMetadata {
        document_id: document.id().as_str().to_owned(),
        sha256: document.sha256().to_owned(),
        byte_len: document.byte_len(),
        sequence,
        start_offset_ms: segment.start_offset_ms,
        end_offset_ms: end_offset_ms.max(segment.start_offset_ms),
        media_start_ms: segment.media_start_ms.unwrap_or(0.0),
        media_end_ms: segment.media_end_ms,
        mime_type: segment.mime_type,
        complete: segment.complete,
    };
    segments.push(RecordingSegment { document, metadata });
    Ok(())
}

fn offset_ms(started: Instant, at: Instant) -> u64 {
    u64::try_from(at.saturating_duration_since(started).as_millis()).unwrap_or(u64::MAX)
}

fn unix_millis() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}
