//! Shared private-display source and independently finalized browser-visible outputs.

use super::{BrowserSession, CaptureAdmission, PrivateDisplay, capture_admission::CapturePermit};
use crate::{
    automation_record::MAX_AUTOMATION_RECORD_ITEMS,
    documents::{FileLimits, FileMetadata, MAX_FILE_BYTES, VideoDocument},
    policy::observe::MAX_RECORDING_DURATION_MS,
    session::{
        RecordingGap, RecordingGapReason, RecordingHandle, RecordingOptions, RecordingOutcome,
        RecordingScope, RecordingSegment, RecordingSegmentMetadata, RecordingSource,
        RecordingSourceKind, RecordingStopReason, RetainedByteReservation, SessionError,
    },
};
use std::{
    fmt::{self, Debug, Formatter},
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering},
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    process::{Child, ChildStdin, ChildStdout},
    sync::{Mutex, broadcast, oneshot},
    task::JoinHandle,
    time::{Instant, sleep_until, timeout},
};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

// Fixed raw source dimensions: 1280 x 720 x RGB24.
const FRAME_BYTES: usize = 2_764_800;
const FRAME_QUEUE_CAPACITY: usize = 2;
const ENCODED_READ_CHUNK_BYTES: usize = 64 * 1024;
const MAX_RECORDING_GAPS: usize = MAX_AUTOMATION_RECORD_ITEMS;
const SOURCE_STOP_TIMEOUT: Duration = Duration::from_secs(5);
const ENCODER_FINALIZE_TIMEOUT: Duration = Duration::from_secs(5);
const FRAME_WRITE_TIMEOUT: Duration = Duration::from_secs(2);

struct DisplayFrame {
    bytes: Vec<u8>,
    offset_ms: u64,
    _buffer: super::capture_admission::CaptureBufferPermit,
}

#[derive(Clone)]
enum DisplayEvent {
    Frame(Arc<DisplayFrame>),
    Gap {
        offset_ms: u64,
        reason: RecordingGapReason,
    },
}

/// One shared physical browser-visible feed used by compatible logical outputs.
pub(super) struct DisplaySource {
    id: String,
    frames_per_second: u32,
    started: Instant,
    started_at_unix_ms: Option<u64>,
    sender: broadcast::Sender<DisplayEvent>,
    initial_receiver: Mutex<Option<broadcast::Receiver<DisplayEvent>>>,
    cancellation: CancellationToken,
    session_cancellation: CancellationToken,
    active: Arc<AtomicBool>,
    outputs: Arc<AtomicU32>,
    latest_offset_ms: Arc<AtomicU64>,
    task: Mutex<Option<JoinHandle<()>>>,
    source_permit: Arc<Mutex<Option<CapturePermit>>>,
}

impl Debug for DisplaySource {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DisplaySource")
            .field("id", &self.id)
            .field("frames_per_second", &self.frames_per_second)
            .field("active", &self.active.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

impl DisplaySource {
    async fn start(
        display: Arc<PrivateDisplay>,
        admission: CaptureAdmission,
        session_cancellation: CancellationToken,
        frames_per_second: u32,
    ) -> Result<Arc<Self>, SessionError> {
        let source_permit = admission.source()?;
        let mut child = display
            .frame_source(frames_per_second)
            .map_err(|_| SessionError::Unsupported("browser-visible capture source unavailable"))?;
        let stdout = child.stdout.take().ok_or(SessionError::Admission)?;
        let (sender, initial_receiver) = broadcast::channel(FRAME_QUEUE_CAPACITY);
        let started = Instant::now();
        let cancellation = CancellationToken::new();
        let active = Arc::new(AtomicBool::new(true));
        let outputs = Arc::new(AtomicU32::new(0));
        let latest_offset_ms = Arc::new(AtomicU64::new(0));
        let source_permit = Arc::new(Mutex::new(Some(source_permit)));
        let source = Arc::new(Self {
            id: Uuid::new_v4().to_string(),
            frames_per_second,
            started,
            started_at_unix_ms: unix_now_ms(),
            sender,
            initial_receiver: Mutex::new(Some(initial_receiver)),
            cancellation: cancellation.clone(),
            session_cancellation: session_cancellation.clone(),
            active: Arc::clone(&active),
            outputs: Arc::clone(&outputs),
            latest_offset_ms: Arc::clone(&latest_offset_ms),
            task: Mutex::new(None),
            source_permit: Arc::clone(&source_permit),
        });
        let read_task = DisplayReadTask {
            sender: source.sender.clone(),
            cancellation,
            session_cancellation,
            started,
            active,
            latest_offset_ms,
            source_permit,
            child,
            stdout,
            admission,
        };
        let task = tokio::spawn(async move {
            read_frames(read_task).await;
        });
        *source.task.lock().await = Some(task);
        Ok(source)
    }

    fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
            && !self.cancellation.is_cancelled()
            && !self.session_cancellation.is_cancelled()
    }

    fn subscribe(
        self: &Arc<Self>,
    ) -> Result<(broadcast::Receiver<DisplayEvent>, DisplayOutputLease), SessionError> {
        if !self.is_active() {
            return Err(SessionError::Admission);
        }
        self.outputs
            .try_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                count.checked_add(1)
            })
            .map_err(|_| SessionError::Admission)?;
        if !self.is_active() {
            let _ = self
                .outputs
                .try_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                    count.checked_sub(1)
                });
            return Err(SessionError::Admission);
        }
        let receiver = self
            .initial_receiver
            .try_lock()
            .ok()
            .and_then(|mut receiver| receiver.take())
            .unwrap_or_else(|| self.sender.subscribe());
        Ok((
            receiver,
            DisplayOutputLease {
                source: Arc::clone(self),
                active: true,
            },
        ))
    }

    fn latest_offset_ms(&self) -> u64 {
        self.latest_offset_ms.load(Ordering::Acquire)
    }

    fn source_metadata(&self) -> RecordingSource {
        RecordingSource {
            id: self.id.clone(),
            scope: RecordingScope::BrowserVisible,
            kind: RecordingSourceKind::BrowserDisplay,
            started_at_unix_ms: self.started_at_unix_ms,
        }
    }

    pub(super) async fn stop(&self) {
        self.cancellation.cancel();
        let task = self.task.lock().await.take();
        if let Some(mut task) = task
            && timeout(SOURCE_STOP_TIMEOUT, &mut task).await.is_err()
        {
            task.abort();
            let _ = task.await;
        }
        self.active.store(false, Ordering::Release);
        self.source_permit.lock().await.take();
    }
}

struct DisplayOutputLease {
    source: Arc<DisplaySource>,
    active: bool,
}

struct DisplayReadTask {
    sender: broadcast::Sender<DisplayEvent>,
    cancellation: CancellationToken,
    session_cancellation: CancellationToken,
    started: Instant,
    active: Arc<AtomicBool>,
    latest_offset_ms: Arc<AtomicU64>,
    source_permit: Arc<Mutex<Option<CapturePermit>>>,
    child: Child,
    stdout: ChildStdout,
    admission: CaptureAdmission,
}

async fn read_frames(task: DisplayReadTask) {
    let DisplayReadTask {
        sender,
        cancellation,
        session_cancellation,
        started,
        active,
        latest_offset_ms,
        source_permit,
        mut child,
        mut stdout,
        admission,
    } = task;
    let elapsed_ms = || u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    loop {
        if cancellation.is_cancelled() || session_cancellation.is_cancelled() {
            break;
        }
        let Ok(buffer) = admission.buffer(u64::try_from(FRAME_BYTES).unwrap_or(u64::MAX)) else {
            let offset_ms = elapsed_ms();
            let _ = sender.send(DisplayEvent::Gap {
                offset_ms,
                reason: RecordingGapReason::BufferLimit,
            });
            break;
        };
        let mut bytes = vec![0_u8; FRAME_BYTES];
        let read = tokio::select! {
            biased;
            () = cancellation.cancelled() => None,
            () = session_cancellation.cancelled() => None,
            result = stdout.read_exact(&mut bytes) => Some(result),
        };
        match read {
            Some(Ok(_)) => {
                let offset_ms = elapsed_ms();
                latest_offset_ms.store(offset_ms, Ordering::Release);
                if sender
                    .send(DisplayEvent::Frame(Arc::new(DisplayFrame {
                        bytes,
                        offset_ms,
                        _buffer: buffer,
                    })))
                    .is_err()
                {
                    break;
                }
            }
            Some(Err(_)) => {
                let offset_ms = elapsed_ms();
                let _ = sender.send(DisplayEvent::Gap {
                    offset_ms,
                    reason: RecordingGapReason::SourceFailure,
                });
                break;
            }
            None => break,
        }
    }

    active.store(false, Ordering::Release);
    cancellation.cancel();
    if child.try_wait().ok().flatten().is_none() {
        let _ = child.start_kill();
        let _ = timeout(SOURCE_STOP_TIMEOUT, child.wait()).await;
    }
    source_permit.lock().await.take();
}

impl Drop for DisplaySource {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

impl Drop for DisplayOutputLease {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let previous =
            self.source
                .outputs
                .try_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                    count.checked_sub(1)
                });
        if previous == Ok(1) {
            self.source.cancellation.cancel();
        }
        self.active = false;
    }
}

impl BrowserSession {
    /// Starts an independently stoppable silent recording of the private browser display.
    ///
    /// Compatible outputs share one bounded raw frame feed, while each output receives its own
    /// encoder and WebM container. Automatic Session-owned outputs pass a lifetime retention
    /// reservation; manually returned outcomes omit it and remain caller-owned.
    pub(crate) async fn start_browser_visible_recording(
        &self,
        options: RecordingOptions,
        retention: Option<RetainedByteReservation>,
    ) -> Result<RecordingHandle, SessionError> {
        if !self.inner.browser_visible_capture || self.inner.private_display.is_none() {
            return Err(SessionError::Denied);
        }
        if self.is_closed() || self.inner.cancellation.is_cancelled() {
            return Err(SessionError::Closed);
        }
        validate_options(&options)?;
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(options.max_duration_ms))
            .ok_or(SessionError::InvalidInput)?;

        let output_permit = self.inner.capture_admission.output()?;
        let display = self
            .inner
            .private_display
            .clone()
            .ok_or(SessionError::Denied)?;
        let source = {
            let mut registered = self.inner.display_source.lock().await;
            if let Some(source) = registered.clone() {
                if source.is_active() {
                    if source.frames_per_second != options.frames_per_second {
                        return Err(SessionError::Unsupported(
                            "browser-visible outputs must share a frame rate",
                        ));
                    }
                    source
                } else {
                    source.stop().await;
                    let source = DisplaySource::start(
                        display,
                        self.inner.capture_admission.clone(),
                        self.inner.cancellation.clone(),
                        options.frames_per_second,
                    )
                    .await?;
                    *registered = Some(Arc::clone(&source));
                    source
                }
            } else {
                let source = DisplaySource::start(
                    display,
                    self.inner.capture_admission.clone(),
                    self.inner.cancellation.clone(),
                    options.frames_per_second,
                )
                .await?;
                *registered = Some(Arc::clone(&source));
                source
            }
        };
        let (frames, output_lease) = source.subscribe()?;
        let mut encoder = PrivateDisplay::output_encoder(options.frames_per_second)
            .map_err(|_| SessionError::Admission)?;
        let stdin = encoder.stdin.take().ok_or(SessionError::Admission)?;
        let stdout = encoder.stdout.take().ok_or(SessionError::Admission)?;
        let recording_id = Uuid::new_v4().to_string();
        let (stop_sender, stop_receiver) = oneshot::channel();
        let admission = self.inner.capture_admission.clone();
        let cancellation = self.inner.cancellation.clone();
        let session_id = self.id();
        let task = tokio::spawn(async move {
            Ok(run_output(DisplayOutputTask {
                source,
                frames,
                _source_lease: output_lease,
                options,
                deadline,
                retention,
                _output_permit: output_permit,
                admission,
                session_cancellation: cancellation,
                recording_id,
                session_id,
                encoder,
                stdin,
                stdout,
                stop: stop_receiver,
            })
            .await)
        });
        Ok(RecordingHandle {
            stop: Some(stop_sender),
            task: Some(task),
        })
    }
}

#[derive(Default)]
struct WriterSummary {
    first_offset_ms: Option<u64>,
    last_offset_ms: Option<u64>,
    frames: u64,
    gaps: Vec<RecordingGap>,
    source_failed: bool,
    write_timed_out: bool,
}

async fn write_frames(
    mut stdin: ChildStdin,
    mut frames: broadcast::Receiver<DisplayEvent>,
    source: Arc<DisplaySource>,
    session_cancellation: CancellationToken,
    writer_cancellation: CancellationToken,
    start_offset_ms: u64,
    maximum_buffer_bytes: u64,
) -> WriterSummary {
    let mut summary = WriterSummary::default();
    loop {
        tokio::select! {
            biased;
            () = writer_cancellation.cancelled() => break,
            () = session_cancellation.cancelled() => {
                summary.source_failed = true;
                break;
            }
            event = frames.recv() => match event {
                Ok(DisplayEvent::Frame(frame)) => {
                    if frame.offset_ms < start_offset_ms {
                        continue;
                    }
                    if u64::try_from(frame.bytes.len()).unwrap_or(u64::MAX) > maximum_buffer_bytes {
                        push_gap(
                            &mut summary.gaps,
                            summary.last_offset_ms.unwrap_or(start_offset_ms),
                            frame.offset_ms,
                            RecordingGapReason::BufferLimit,
                        );
                        break;
                    }
                    match timeout(FRAME_WRITE_TIMEOUT, stdin.write_all(&frame.bytes)).await {
                        Ok(Ok(())) => {}
                        Ok(Err(_)) => {
                            summary.source_failed = true;
                            push_gap(
                                &mut summary.gaps,
                                summary.last_offset_ms.unwrap_or(start_offset_ms),
                                frame.offset_ms,
                                RecordingGapReason::SourceFailure,
                            );
                            break;
                        }
                        Err(_) => {
                            summary.source_failed = true;
                            summary.write_timed_out = true;
                            push_gap(
                                &mut summary.gaps,
                                summary.last_offset_ms.unwrap_or(start_offset_ms),
                                frame.offset_ms,
                                RecordingGapReason::SourceFailure,
                            );
                            break;
                        }
                    }
                    summary.first_offset_ms.get_or_insert(frame.offset_ms);
                    summary.last_offset_ms = Some(frame.offset_ms);
                    let Some(frames) = summary.frames.checked_add(1) else {
                        summary.source_failed = true;
                        break;
                    };
                    summary.frames = frames;
                }
                Ok(DisplayEvent::Gap { offset_ms, reason }) => {
                    push_gap(
                        &mut summary.gaps,
                        summary.last_offset_ms.unwrap_or(start_offset_ms),
                        offset_ms,
                        reason,
                    );
                }
                Err(broadcast::error::RecvError::Lagged(_)) => {
                    push_gap(
                        &mut summary.gaps,
                        summary.last_offset_ms.unwrap_or(start_offset_ms),
                        source.latest_offset_ms(),
                        RecordingGapReason::BufferLimit,
                    );
                }
                Err(broadcast::error::RecvError::Closed) => {
                    summary.source_failed = true;
                    break;
                }
            },
            () = source.cancellation.cancelled() => {
                summary.source_failed = !session_cancellation.is_cancelled();
                break;
            }
        }
    }
    drop(stdin);
    summary
}

struct DisplayOutputTask {
    source: Arc<DisplaySource>,
    frames: broadcast::Receiver<DisplayEvent>,
    _source_lease: DisplayOutputLease,
    options: RecordingOptions,
    deadline: Instant,
    retention: Option<RetainedByteReservation>,
    _output_permit: CapturePermit,
    admission: CaptureAdmission,
    session_cancellation: CancellationToken,
    recording_id: String,
    session_id: String,
    encoder: Child,
    stdin: ChildStdin,
    stdout: ChildStdout,
    stop: oneshot::Receiver<()>,
}

#[expect(
    clippy::cognitive_complexity,
    reason = "One output state machine owns cancellation, bounded reads, draining and encoder finalization"
)]
async fn run_output(task: DisplayOutputTask) -> RecordingOutcome {
    let DisplayOutputTask {
        source,
        frames,
        _source_lease,
        options,
        deadline,
        retention,
        _output_permit,
        admission,
        session_cancellation,
        recording_id,
        session_id,
        mut encoder,
        stdin,
        mut stdout,
        mut stop,
    } = task;
    let start_offset_ms = source.latest_offset_ms();
    let writer_cancellation = CancellationToken::new();
    let (writer_done_sender, mut writer_done) = oneshot::channel();
    let writer_source = Arc::clone(&source);
    let writer_session_cancellation = session_cancellation.clone();
    let writer_cancel = writer_cancellation.clone();
    let mut writer = tokio::spawn(async move {
        let summary = write_frames(
            stdin,
            frames,
            writer_source,
            writer_session_cancellation,
            writer_cancel,
            start_offset_ms,
            options.max_buffer_bytes,
        )
        .await;
        let _ = writer_done_sender.send(summary);
    });
    let mut output = Vec::new();
    let mut output_bytes = 0_u64;
    let mut output_complete = true;
    let mut stop_reason: RecordingStopReason;
    let mut gap_reason = None;
    let mut writer_summary = None;
    let mut chunk = Vec::new();
    let chunk_capacity = usize::try_from(
        options
            .max_buffer_bytes
            .min(options.max_bytes)
            .min(u64::try_from(ENCODED_READ_CHUNK_BYTES).unwrap_or(u64::MAX)),
    )
    .unwrap_or(0);
    let mut keep_output = true;
    if chunk_capacity == 0 {
        output_complete = false;
        stop_reason = RecordingStopReason::SourceFailure;
        gap_reason = Some(RecordingGapReason::BufferLimit);
    } else {
        chunk.resize(chunk_capacity, 0);
        loop {
            let Ok(_buffer_permit) =
                admission.buffer(u64::try_from(chunk.len()).unwrap_or(u64::MAX))
            else {
                output_complete = false;
                stop_reason = RecordingStopReason::SourceFailure;
                gap_reason = Some(RecordingGapReason::BufferLimit);
                break;
            };
            tokio::select! {
                biased;
                result = &mut stop => {
                    let _ = result;
                    stop_reason = RecordingStopReason::Requested;
                    break;
                }
                () = session_cancellation.cancelled() => {
                    stop_reason = RecordingStopReason::SessionClosed;
                    break;
                }
                () = source.cancellation.cancelled() => {
                    output_complete = false;
                    stop_reason = if session_cancellation.is_cancelled() {
                        RecordingStopReason::SessionClosed
                    } else {
                        RecordingStopReason::SourceFailure
                    };
                    gap_reason = Some(RecordingGapReason::SourceFailure);
                    break;
                }
                () = sleep_until(deadline) => {
                    stop_reason = RecordingStopReason::DurationLimit;
                    break;
                }
                result = &mut writer_done => {
                    writer_summary = result.ok();
                    output_complete = false;
                    stop_reason = RecordingStopReason::SourceFailure;
                    gap_reason = Some(RecordingGapReason::SourceFailure);
                    if writer_summary
                        .as_ref()
                        .is_some_and(|summary| summary.write_timed_out)
                    {
                        let _ = encoder.start_kill();
                    }
                    break;
                }
                read = stdout.read(&mut chunk) => match read {
                    Ok(0) | Err(_) => {
                        output_complete = false;
                        stop_reason = RecordingStopReason::SourceFailure;
                        gap_reason = Some(RecordingGapReason::SourceFailure);
                        break;
                    }
                    Ok(read) => {
                        let read_bytes = u64::try_from(read).unwrap_or(u64::MAX);
                        let Some(next_total) = output_bytes.checked_add(read_bytes) else {
                            output_complete = false;
                            stop_reason = RecordingStopReason::ByteLimit;
                            gap_reason = Some(RecordingGapReason::ByteLimit);
                            keep_output = false;
                            break;
                        };
                        if next_total > options.max_bytes {
                            output_complete = false;
                            stop_reason = RecordingStopReason::ByteLimit;
                            gap_reason = Some(RecordingGapReason::ByteLimit);
                            keep_output = false;
                            break;
                        }
                        if retention.as_ref().is_some_and(|reservation| !reservation.try_add(read_bytes)) {
                            output_complete = false;
                            stop_reason = RecordingStopReason::RetentionLimit;
                            gap_reason = Some(RecordingGapReason::RetentionLimit);
                            keep_output = false;
                            break;
                        }
                        let Some(bytes) = chunk.get(..read) else {
                            output_complete = false;
                            stop_reason = RecordingStopReason::SourceFailure;
                            gap_reason = Some(RecordingGapReason::SourceFailure);
                            break;
                        };
                        output.extend_from_slice(bytes);
                        output_bytes = next_total;
                    }
                }
            }
        }
    }

    writer_cancellation.cancel();
    let finalize = drain_encoded(EncodedDrain {
        stdout: &mut stdout,
        admission: &admission,
        chunk_capacity,
        maximum_bytes: options.max_bytes,
        output: &mut output,
        output_bytes: &mut output_bytes,
        retention: retention.as_ref(),
        keep: keep_output,
    });
    match timeout(ENCODER_FINALIZE_TIMEOUT, finalize).await {
        Ok(Ok(Some(reason))) => {
            output_complete = false;
            stop_reason = match reason {
                RecordingGapReason::RetentionLimit => RecordingStopReason::RetentionLimit,
                RecordingGapReason::ByteLimit => RecordingStopReason::ByteLimit,
                _ => RecordingStopReason::SourceFailure,
            };
            gap_reason = Some(reason);
        }
        Ok(Ok(None)) => {}
        Ok(Err(RecordingGapReason::BufferLimit)) => {
            output_complete = false;
            stop_reason = RecordingStopReason::SourceFailure;
            gap_reason = Some(RecordingGapReason::BufferLimit);
            let _ = encoder.start_kill();
        }
        Ok(Err(_)) | Err(_) => {
            output_complete = false;
            stop_reason = RecordingStopReason::SourceFailure;
            gap_reason = Some(RecordingGapReason::SourceFailure);
            let _ = encoder.start_kill();
        }
    }
    let mut writer_summary = if let Some(summary) = writer_summary {
        summary
    } else if let Ok(Ok(summary)) = timeout(SOURCE_STOP_TIMEOUT, &mut writer_done).await {
        summary
    } else {
        writer.abort();
        output_complete = false;
        stop_reason = RecordingStopReason::SourceFailure;
        gap_reason = Some(RecordingGapReason::SourceFailure);
        WriterSummary {
            source_failed: true,
            ..WriterSummary::default()
        }
    };
    match timeout(SOURCE_STOP_TIMEOUT, &mut writer).await {
        Ok(Ok(())) => {}
        Ok(Err(_)) => {
            output_complete = false;
            stop_reason = RecordingStopReason::SourceFailure;
            gap_reason = Some(RecordingGapReason::SourceFailure);
            writer_summary.source_failed = true;
        }
        Err(_) => {
            writer.abort();
            let _ = writer.await;
            output_complete = false;
            stop_reason = RecordingStopReason::SourceFailure;
            gap_reason = Some(RecordingGapReason::SourceFailure);
            writer_summary.source_failed = true;
        }
    }
    if writer_summary.source_failed {
        output_complete = false;
        if stop_reason == RecordingStopReason::Requested {
            stop_reason = if session_cancellation.is_cancelled() {
                RecordingStopReason::SessionClosed
            } else {
                RecordingStopReason::SourceFailure
            };
        }
        gap_reason.get_or_insert(RecordingGapReason::SourceFailure);
    }
    if writer_summary.write_timed_out {
        let _ = encoder.start_kill();
    }

    let encoder_status =
        if let Ok(Ok(status)) = timeout(ENCODER_FINALIZE_TIMEOUT, encoder.wait()).await {
            status.success()
        } else {
            let _ = encoder.start_kill();
            let _ = timeout(ENCODER_FINALIZE_TIMEOUT, encoder.wait()).await;
            false
        };
    output_complete &= encoder_status;
    if !encoder_status {
        if stop_reason == RecordingStopReason::Requested {
            stop_reason = RecordingStopReason::SourceFailure;
        }
        gap_reason.get_or_insert(RecordingGapReason::SourceFailure);
    }

    let mut gaps = writer_summary.gaps;
    if let Some(reason) = gap_reason {
        push_gap(
            &mut gaps,
            writer_summary.last_offset_ms.unwrap_or(start_offset_ms),
            source.latest_offset_ms(),
            reason,
        );
    }
    let mut segments = Vec::new();
    if !output.is_empty() {
        let media_end_ms = if options.frames_per_second == 0 {
            0.0
        } else {
            // Admitted duration and frame-rate limits keep valid counts within this conversion.
            let frames = u32::try_from(writer_summary.frames).unwrap_or(u32::MAX);
            (f64::from(frames) * 1_000.0) / f64::from(options.frames_per_second)
        };
        let sequence = 0_u32;
        let document_id = format!("{recording_id}:{sequence}");
        let file_metadata = FileMetadata::new()
            .with_declared_media_type("video/webm")
            .and_then(|metadata| metadata.with_capture_id(recording_id.clone()))
            .and_then(|metadata| metadata.with_session_id(session_id.clone()))
            .and_then(|metadata| metadata.with_source("browser-visible"));
        let document = file_metadata.and_then(|metadata| {
            VideoDocument::from_bytes_with_metadata(
                document_id.clone(),
                output,
                metadata,
                FileLimits {
                    max_bytes: options.max_bytes,
                },
            )
        });
        if let Ok(document) = document {
            if retention
                .as_ref()
                .is_none_or(RetainedByteReservation::commit)
            {
                let segment_complete = output_complete && gaps.is_empty();
                let start_offset_ms = writer_summary.first_offset_ms.unwrap_or(start_offset_ms);
                let frame_duration_ms = 1_000_u32
                    .checked_div(options.frames_per_second.max(1))
                    .unwrap_or(1_000);
                let end_offset_ms = writer_summary
                    .last_offset_ms
                    .unwrap_or(start_offset_ms)
                    .saturating_add(u64::from(frame_duration_ms));
                segments.push(RecordingSegment {
                    metadata: RecordingSegmentMetadata {
                        document_id,
                        sha256: document.sha256().to_owned(),
                        byte_len: document.byte_len(),
                        sequence,
                        start_offset_ms,
                        end_offset_ms,
                        media_start_ms: 0.0,
                        media_end_ms,
                        mime_type: "video/webm; codecs=vp8".into(),
                        complete: segment_complete,
                    },
                    document,
                });
            } else {
                output_complete = false;
                stop_reason = RecordingStopReason::RetentionLimit;
                push_gap(
                    &mut gaps,
                    writer_summary.last_offset_ms.unwrap_or(start_offset_ms),
                    source.latest_offset_ms(),
                    RecordingGapReason::RetentionLimit,
                );
            }
        } else {
            output_complete = false;
            stop_reason = RecordingStopReason::SourceFailure;
            push_gap(
                &mut gaps,
                start_offset_ms,
                source.latest_offset_ms(),
                RecordingGapReason::SourceFailure,
            );
        }
    }
    if segments.is_empty() {
        output_complete = false;
    }
    let complete = output_complete && !segments.is_empty() && gaps.is_empty();
    RecordingOutcome {
        id: recording_id,
        source: source.source_metadata(),
        segments,
        gaps,
        actions: Vec::new(),
        lost_action_events: 0,
        stopped_at_unix_ms: unix_now_ms(),
        stop_reason,
        complete,
    }
}

struct EncodedDrain<'a> {
    stdout: &'a mut ChildStdout,
    admission: &'a CaptureAdmission,
    chunk_capacity: usize,
    maximum_bytes: u64,
    output: &'a mut Vec<u8>,
    output_bytes: &'a mut u64,
    retention: Option<&'a RetainedByteReservation>,
    keep: bool,
}

async fn drain_encoded(
    task: EncodedDrain<'_>,
) -> Result<Option<RecordingGapReason>, RecordingGapReason> {
    let EncodedDrain {
        stdout,
        admission,
        chunk_capacity,
        maximum_bytes,
        output,
        output_bytes,
        retention,
        mut keep,
    } = task;
    if chunk_capacity == 0 {
        return Err(RecordingGapReason::BufferLimit);
    }
    let mut chunk = vec![0_u8; chunk_capacity];
    let mut gap_reason = None;
    loop {
        let _buffer = admission
            .buffer(u64::try_from(chunk.len()).unwrap_or(u64::MAX))
            .map_err(|_| RecordingGapReason::BufferLimit)?;
        let read = stdout
            .read(&mut chunk)
            .await
            .map_err(|_| RecordingGapReason::SourceFailure)?;
        if read == 0 {
            break;
        }
        if !keep {
            continue;
        }
        let read_bytes = u64::try_from(read).unwrap_or(u64::MAX);
        let Some(next_total) = output_bytes.checked_add(read_bytes) else {
            keep = false;
            gap_reason = Some(RecordingGapReason::ByteLimit);
            continue;
        };
        if next_total > maximum_bytes {
            keep = false;
            gap_reason.get_or_insert(RecordingGapReason::ByteLimit);
            continue;
        }
        if retention.is_some_and(|reservation| !reservation.try_add(read_bytes)) {
            keep = false;
            gap_reason = Some(RecordingGapReason::RetentionLimit);
            continue;
        }
        let Some(bytes) = chunk.get(..read) else {
            return Err(RecordingGapReason::SourceFailure);
        };
        output.extend_from_slice(bytes);
        *output_bytes = next_total;
    }
    Ok(gap_reason)
}

fn push_gap(
    gaps: &mut Vec<RecordingGap>,
    start_offset_ms: u64,
    end_offset_ms: u64,
    reason: RecordingGapReason,
) {
    if gaps.len() >= MAX_RECORDING_GAPS {
        return;
    }
    let (start_offset_ms, end_offset_ms) = if start_offset_ms <= end_offset_ms {
        (start_offset_ms, end_offset_ms)
    } else {
        (end_offset_ms, start_offset_ms)
    };
    gaps.push(RecordingGap {
        start_offset_ms,
        end_offset_ms,
        reason,
    });
}

fn validate_options(options: &RecordingOptions) -> Result<(), SessionError> {
    if options.max_bytes == 0
        || options.max_bytes > MAX_FILE_BYTES
        || options.max_buffer_bytes == 0
        || options.max_duration_ms == 0
        || options.max_duration_ms > MAX_RECORDING_DURATION_MS
        || !(1..=60).contains(&options.frames_per_second)
        || options.include_audio
        || Instant::now()
            .checked_add(Duration::from_millis(options.max_duration_ms))
            .is_none()
    {
        return Err(SessionError::InvalidInput);
    }
    FileLimits::new(options.max_bytes).map_err(|_| SessionError::InvalidInput)?;
    Ok(())
}

fn unix_now_ms() -> Option<u64> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_millis(),
    )
    .ok()
}
