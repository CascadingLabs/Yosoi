//! Native, per-tab MediaStream source and bounded MediaRecorder event relay.

use super::Page;
use super::shared::event_listener_config;
use crate::internal::browser::{
    error::{Result, VoidCrawlError},
    vendor::chromiumoxide::{
        cdp::{
            browser_protocol::page::{
                CreateIsolatedWorldParams, EventDomContentEventFired, EventFrameNavigated,
            },
            js_protocol::runtime::{
                AddBindingParams, EvaluateParams, EventBindingCalled, RemoveBindingParams,
            },
        },
        listeners::{EventDelivery, EventOverflowPolicy, EventStream},
    },
};
use base64::{Engine, engine::general_purpose::STANDARD};
use futures::StreamExt;
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::HashMap,
    fmt::{self, Debug, Formatter},
    num::NonZeroUsize,
    sync::Arc,
    time::Instant,
};
use tokio::{
    runtime::Handle as RuntimeHandle,
    sync::{Mutex, broadcast, mpsc, oneshot},
    task::JoinHandle,
    time::{Duration, timeout},
};
use tokio_util::sync::CancellationToken;

const MAX_MEDIA_CHUNK_BYTES: u64 = 256 * 1024;
const MAX_SOURCE_EVENT_CAPACITY: usize = 128;
const DOCUMENT_READY_DEADLINE: Duration = Duration::from_secs(10);
const MEDIA_COMMAND_TIMEOUT: Duration = Duration::from_secs(5);
const MEDIA_SOURCE_SETUP_TIMEOUT: Duration = Duration::from_secs(20);
const MEDIA_CAPTURE_SCRIPT: &str = include_str!("media_capture.js");
// Reuse one trusted realm per tab/document, including across sequential sources.
const MEDIA_CAPTURE_WORLD: &str = "yosoi.capture";

/// A shared transient-byte permit retained by one queued/consumed media event.
pub trait NativeMediaBufferLease: Send + Sync {}
impl<T: Send + Sync> NativeMediaBufferLease for T {}

/// Admission callback used before the provider broadcasts each decoded chunk.
pub type NativeMediaBufferAdmitter =
    Arc<dyn Fn(u64) -> Option<Arc<dyn NativeMediaBufferLease>> + Send + Sync>;

/// A single chunk or lifecycle event from one native tab capture source.
#[derive(Clone)]
pub enum NativeTabMediaEvent {
    /// One independently encoded MediaRecorder chunk.
    Chunk {
        /// Logical recording output identity.
        output_id: String,
        /// Segment ordinal within that output.
        segment: u32,
        /// Zero-based MediaRecorder chunk sequence.
        sequence: u64,
        /// MediaRecorder timecode in milliseconds.
        media_time_ms: f64,
        /// Browser-selected WebM container and codecs.
        mime_type: String,
        /// Exact chunk bytes.
        bytes: Arc<[u8]>,
        /// Shared Session transient-buffer permit held while this chunk is in flight.
        _buffer_lease: Arc<dyn NativeMediaBufferLease>,
        /// Monotonic time when the provider received the chunk.
        received_at: Instant,
    },
    /// One uninterrupted MediaRecorder segment began.
    SegmentStarted {
        /// Logical recording output identity.
        output_id: String,
        /// Segment ordinal within that output.
        segment: u32,
        /// Browser-selected WebM container and codecs.
        mime_type: String,
        /// Monotonic source time when the segment began.
        started_at: Instant,
    },
    /// A top-level document navigation interrupted the current segment.
    Navigation {
        /// Logical recording output identity.
        output_id: String,
        /// Segment ordinal that ended at navigation.
        segment: u32,
        /// Monotonic source time when the gap began.
        at: Instant,
    },
    /// The requested MediaRecorder output has stopped and flushed its last chunk.
    OutputStopped {
        /// Logical recording output identity.
        output_id: String,
        /// Segment ordinal that stopped.
        segment: u32,
        /// Monotonic source time when stop completed.
        at: Instant,
    },
    /// A MediaRecorder ended with its document during navigation but the logical output remains active.
    SegmentStopped {
        /// Logical recording output identity.
        output_id: String,
        /// Segment ordinal that ended.
        segment: u32,
        /// Monotonic source time when the document ended.
        at: Instant,
    },
    /// The capture source failed or its bounded event stream overflowed.
    SourceFailure {
        /// Monotonic source time when failure was observed.
        at: Instant,
    },
    /// The MediaRecorder rejected an output or exceeded its chunk bound.
    OutputFailure {
        /// Logical recording output identity.
        output_id: String,
        /// Segment ordinal that failed.
        segment: u32,
        /// Whether the failure came from the bounded source queue or provider.
        reason: NativeTabMediaFailureReason,
        /// Monotonic source time when failure was observed.
        at: Instant,
    },
}

impl Debug for NativeTabMediaEvent {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        let (name, output) = match self {
            Self::Chunk { output_id, .. } => ("Chunk", Some(output_id)),
            Self::SegmentStarted { output_id, .. } => ("SegmentStarted", Some(output_id)),
            Self::Navigation { output_id, .. } => ("Navigation", Some(output_id)),
            Self::OutputStopped { output_id, .. } => ("OutputStopped", Some(output_id)),
            Self::SegmentStopped { output_id, .. } => ("SegmentStopped", Some(output_id)),
            Self::SourceFailure { .. } => ("SourceFailure", None),
            Self::OutputFailure { output_id, .. } => ("OutputFailure", Some(output_id)),
        };
        formatter
            .debug_struct(name)
            .field("output_id", &output)
            .finish_non_exhaustive()
    }
}

/// Native per-tab capture failure category.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeTabMediaFailureReason {
    /// The browser produced a chunk larger than the configured bound or a receiver lagged.
    BufferLimit,
    /// Browser MediaRecorder or its provider event stream failed.
    SourceFailure,
}

/// Receiver and first-segment metadata for one independent output.
#[derive(Debug)]
pub struct NativeTabMediaOutput {
    /// Logical recording output identity.
    pub output_id: String,
    /// Browser-selected container and codecs for the first segment.
    pub mime_type: String,
    /// Events from the shared per-tab capture source.
    pub events: broadcast::Receiver<NativeTabMediaEvent>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum BindingMessage {
    Chunk {
        token: String,
        output_id: String,
        segment: u32,
        sequence: u64,
        media_time_ms: Option<f64>,
        mime_type: String,
        data: String,
    },
    OutputStopped {
        token: String,
        output_id: String,
        segment: u32,
    },
    StreamEnded {
        token: String,
    },
    OutputFailure {
        token: String,
        output_id: String,
        segment: u32,
    },
    Overflow {
        token: String,
        output_id: String,
        segment: u32,
    },
}

struct OutputState {
    segment: u32,
    include_audio: bool,
    maximum_chunk_bytes: u64,
    mime_type: String,
    stop_requested: bool,
}

enum SourceCommand {
    StartOutput {
        output_id: String,
        include_audio: bool,
        maximum_chunk_bytes: u64,
        reply: oneshot::Sender<Result<String>>,
    },
    StopOutput {
        output_id: String,
    },
}

#[derive(Clone)]
struct SourceContext {
    id: String,
    binding: String,
    token: String,
    property: String,
    page: Arc<Page>,
    frames_per_second: u32,
    source_audio: bool,
    maximum_chunk_bytes: u64,
    commands: mpsc::Sender<SourceCommand>,
    events: broadcast::Sender<NativeTabMediaEvent>,
    cancellation: CancellationToken,
    tab_closing: CancellationToken,
    buffer_admitter: NativeMediaBufferAdmitter,
}

struct SourceState {
    context: SourceContext,
    task: Mutex<Option<JoinHandle<()>>>,
}

/// Bounded configuration passed through the provider boundary for one tab source.
pub struct NativeTabMediaSourceOptions {
    /// Logical source identity retained in completed recording metadata.
    pub id: String,
    /// Whether the shared source requests an audio track.
    pub source_audio: bool,
    /// Maximum MediaRecorder frame rate from 1 through 60.
    pub frames_per_second: u32,
    /// Maximum transient bytes admitted for each compatible recording output.
    pub maximum_buffer_bytes: u64,
    /// Session-owned transient-byte admission callback.
    pub buffer_admitter: NativeMediaBufferAdmitter,
    /// Cancels setup if the requesting output no longer needs the source.
    pub setup_cancellation: CancellationToken,
    /// Cancels the shared source when its owning Session closes.
    pub cancellation: CancellationToken,
    /// Runtime used to own the source event task and cleanup guard.
    pub executor: RuntimeHandle,
}

impl Debug for NativeTabMediaSourceOptions {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeTabMediaSourceOptions")
            .field("id", &self.id)
            .field("source_audio", &self.source_audio)
            .field("frames_per_second", &self.frames_per_second)
            .field("maximum_buffer_bytes", &self.maximum_buffer_bytes)
            .finish_non_exhaustive()
    }
}

struct SourceSetupGuard {
    page: Arc<Page>,
    binding: String,
    property: String,
    executor: RuntimeHandle,
    armed: bool,
}

impl SourceSetupGuard {
    const fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for SourceSetupGuard {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let page = Arc::clone(&self.page);
        let binding = self.binding.clone();
        let property = self.property.clone();
        let _cleanup = self.executor.spawn(async move {
            remove_binding(&page, &binding).await;
            stop_stream(&page, &property, &binding).await;
        });
    }
}

impl Drop for SourceState {
    fn drop(&mut self) {
        self.context.cancellation.cancel();
    }
}

/// Shared tab MediaStream source; compatible recording handles create separate recorders.
#[derive(Clone)]
pub struct NativeTabMediaSource {
    inner: Arc<SourceState>,
}

impl Debug for NativeTabMediaSource {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeTabMediaSource")
            .field("id", &self.inner.context.id)
            .field("frames_per_second", &self.inner.context.frames_per_second)
            .field("source_audio", &self.inner.context.source_audio)
            .finish_non_exhaustive()
    }
}

impl NativeTabMediaSource {
    /// Creates one self-tab MediaStream source after the Session's explicit permission is checked.
    pub async fn start(
        page: &Arc<Page>,
        options: NativeTabMediaSourceOptions,
        tab_closing: CancellationToken,
    ) -> Result<Self> {
        let NativeTabMediaSourceOptions {
            id,
            source_audio,
            frames_per_second,
            maximum_buffer_bytes,
            buffer_admitter,
            setup_cancellation,
            cancellation,
            executor,
        } = options;
        if !(1..=60).contains(&frames_per_second) || maximum_buffer_bytes == 0 {
            return Err(unsupported_capture("tab MediaStream bounds"));
        }
        timeout(MEDIA_COMMAND_TIMEOUT, page.ensure_active())
            .await
            .map_err(|_| unsupported_capture("tab MediaStream page state"))??;
        timeout(MEDIA_COMMAND_TIMEOUT, page.ensure_runtime_enabled())
            .await
            .map_err(|_| unsupported_capture("tab MediaStream Runtime setup"))??;
        let event_capacity = event_capacity(maximum_buffer_bytes)?;
        let listener = event_listener_config(event_capacity.get(), EventOverflowPolicy::Close);
        let binding = format!("__yosoi_media_{}", uuid::Uuid::new_v4().simple());
        let token = uuid::Uuid::new_v4().to_string();
        let property = format!("__yosoi_media_state_{}", uuid::Uuid::new_v4().simple());
        let mut setup = SourceSetupGuard {
            page: Arc::new(page.clone_handle()),
            binding: binding.clone(),
            property: property.clone(),
            executor: executor.clone(),
            armed: true,
        };
        let binding_events = timeout(
            MEDIA_COMMAND_TIMEOUT,
            page.cdp().event_listener::<EventBindingCalled>(listener),
        )
        .await
        .map_err(|_| unsupported_capture("tab MediaStream event setup"))?
        .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let navigation_events = timeout(
            MEDIA_COMMAND_TIMEOUT,
            page.cdp().event_listener::<EventFrameNavigated>(listener),
        )
        .await
        .map_err(|_| unsupported_capture("tab MediaStream navigation events"))?
        .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let content_events = timeout(
            MEDIA_COMMAND_TIMEOUT,
            page.cdp()
                .event_listener::<EventDomContentEventFired>(listener),
        )
        .await
        .map_err(|_| unsupported_capture("tab MediaStream document events"))?
        .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let mut binding_params = AddBindingParams::new(binding.clone());
        binding_params.execution_context_name = Some(MEDIA_CAPTURE_WORLD.to_owned());
        timeout(MEDIA_COMMAND_TIMEOUT, page.cdp().execute(binding_params))
            .await
            .map_err(|_| unsupported_capture("tab MediaStream binding setup"))?
            .map_err(|_| VoidCrawlError::BrowserClosed)?;

        let maximum_chunk_bytes = maximum_buffer_bytes.clamp(1, MAX_MEDIA_CHUNK_BYTES);
        let initial_stream = tokio::select! {
            biased;
            () = setup_cancellation.cancelled() => Err(VoidCrawlError::BrowserClosed),
            () = cancellation.cancelled() => Err(VoidCrawlError::BrowserClosed),
            () = tab_closing.cancelled() => Err(VoidCrawlError::BrowserClosed),
            result = timeout(MEDIA_SOURCE_SETUP_TIMEOUT, start_stream(
                page,
                &binding,
                &property,
                &token,
                source_audio,
                frames_per_second,
            )) => result.unwrap_or_else(|_| Err(unsupported_capture("tab MediaStream startup timeout"))),
        };
        let initial_stream = match initial_stream {
            Ok(started) => started,
            Err(error) => {
                remove_binding(page, &binding).await;
                stop_stream(page, &property, &binding).await;
                setup.disarm();
                return Err(error);
            }
        };
        if !initial_stream {
            remove_binding(page, &binding).await;
            stop_stream(page, &property, &binding).await;
            setup.disarm();
            return Err(unsupported_capture("self-tab MediaStream permission"));
        }
        let channel_capacity = event_capacity.get();
        let (events, _) = broadcast::channel(channel_capacity);
        let (commands, command_rx) = mpsc::channel(32);
        let context = SourceContext {
            id,
            binding: binding.clone(),
            token: token.clone(),
            property: property.clone(),
            page: Arc::new(page.clone_handle()),
            frames_per_second,
            source_audio,
            maximum_chunk_bytes,
            commands,
            events,
            cancellation: cancellation.child_token(),
            tab_closing,
            buffer_admitter,
        };
        let inner = Arc::new(SourceState {
            context: context.clone(),
            task: Mutex::new(None),
        });
        let task = executor.spawn(run_source(
            context,
            binding_events,
            navigation_events,
            content_events,
            command_rx,
        ));
        setup.disarm();
        *inner.task.lock().await = Some(task);
        Ok(Self { inner })
    }

    /// Returns the source identity shared by compatible recording outputs.
    pub(crate) fn id(&self) -> &str {
        &self.inner.context.id
    }

    /// Starts an independent MediaRecorder output over this source's selected tracks.
    pub(crate) async fn start_output(
        &self,
        output_id: String,
        include_audio: bool,
    ) -> Result<NativeTabMediaOutput> {
        if include_audio && !self.inner.context.source_audio {
            return Err(unsupported_capture("tab audio source is not active"));
        }
        let events = self.inner.context.events.subscribe();
        let (reply, response) = oneshot::channel();
        self.inner
            .context
            .commands
            .try_send(SourceCommand::StartOutput {
                output_id: output_id.clone(),
                include_audio,
                maximum_chunk_bytes: self.inner.context.maximum_chunk_bytes,
                reply,
            })
            .map_err(|_| VoidCrawlError::BrowserClosed)?;
        let mime_type = timeout(MEDIA_COMMAND_TIMEOUT, response)
            .await
            .map_err(|_| VoidCrawlError::Timeout("MediaRecorder start reply".into()))?
            .map_err(|_| VoidCrawlError::BrowserClosed)??;
        Ok(NativeTabMediaOutput {
            output_id,
            mime_type,
            events,
        })
    }

    /// Stops one output without stopping compatible sibling recorders.
    pub(crate) fn request_stop_output(&self, output_id: String) -> Result<()> {
        self.inner
            .context
            .commands
            .try_send(SourceCommand::StopOutput { output_id })
            .map_err(|_| VoidCrawlError::BrowserClosed)?;
        Ok(())
    }

    /// Stops the shared source after its final output has ended or its tab/session closes.
    pub(crate) fn cancel(&self) {
        self.inner.context.cancellation.cancel();
    }

    /// Stops the shared source and waits for bounded provider cleanup.
    pub(crate) async fn close(&self) {
        let _ = self
            .inner
            .context
            .events
            .send(NativeTabMediaEvent::SourceFailure { at: Instant::now() });
        self.cancel();
        let source_task = { self.inner.task.lock().await.take() };
        if let Some(mut task) = source_task
            && timeout(Duration::from_secs(15), &mut task).await.is_err()
        {
            task.abort();
            let _ = task.await;
        }
    }
}

fn event_capacity(maximum_buffer_bytes: u64) -> Result<NonZeroUsize> {
    let maximum_capacity = u64::try_from(MAX_SOURCE_EVENT_CAPACITY)
        .map_err(|_| unsupported_capture("tab MediaStream event capacity"))?;
    let chunk_bound = (maximum_buffer_bytes / MAX_MEDIA_CHUNK_BYTES).clamp(1, maximum_capacity);
    let capacity = usize::try_from(chunk_bound)
        .map_err(|_| unsupported_capture("tab MediaStream event capacity"))?;
    NonZeroUsize::new(capacity).ok_or_else(|| unsupported_capture("tab MediaStream event capacity"))
}

async fn start_stream(
    page: &Page,
    binding: &str,
    property: &str,
    token: &str,
    audio: bool,
    fps: u32,
) -> Result<bool> {
    timeout(MEDIA_COMMAND_TIMEOUT, page.cdp().bring_to_front())
        .await
        .map_err(|_| VoidCrawlError::Timeout("tab MediaStream activation".into()))?
        .map_err(|_| unsupported_capture("tab MediaStream activation"))?;
    let value = evaluate_media_script(
        page,
        "start_source",
        serde_json::json!({
            "binding": binding,
            "property": property,
            "token": token,
            "include_audio": audio,
            "frames_per_second": fps,
            "start_timeout_ms": u64::try_from(MEDIA_SOURCE_SETUP_TIMEOUT.as_millis())
                .unwrap_or(u64::MAX),
        }),
        true,
        true,
        MEDIA_SOURCE_SETUP_TIMEOUT,
    )
    .await?;
    Ok(value.as_bool() == Some(true))
}

async fn start_output(
    page: &Page,
    property: &str,
    output_id: &str,
    segment: u32,
    include_audio: bool,
    maximum_chunk_bytes: u64,
) -> Result<String> {
    let value = evaluate_media_script(
        page,
        "start_output",
        serde_json::json!({
            "property": property,
            "output_id": output_id,
            "segment": segment,
            "include_audio": include_audio,
            "maximum_chunk_bytes": maximum_chunk_bytes,
        }),
        false,
        false,
        MEDIA_COMMAND_TIMEOUT,
    )
    .await?;
    value
        .get("mime_type")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| unsupported_capture("MediaRecorder MIME type"))
}

async fn stop_output(page: &Page, property: &str, output_id: &str) -> Result<()> {
    let _ = evaluate_media_script(
        page,
        "stop_output",
        serde_json::json!({"property":property,"output_id":output_id}),
        false,
        false,
        MEDIA_COMMAND_TIMEOUT,
    )
    .await?;
    Ok(())
}

async fn stop_stream(page: &Page, property: &str, binding: &str) {
    let _ = evaluate_media_script(
        page,
        "stop_source",
        serde_json::json!({"property":property,"binding":binding}),
        false,
        false,
        MEDIA_COMMAND_TIMEOUT,
    )
    .await;
}

async fn remove_binding(page: &Page, binding: &str) {
    let _ = timeout(
        MEDIA_COMMAND_TIMEOUT,
        page.cdp()
            .execute(RemoveBindingParams::new(binding.to_owned())),
    )
    .await;
}

async fn evaluate_media_script(
    page: &Page,
    operation: &str,
    input: Value,
    await_promise: bool,
    user_gesture: bool,
    command_timeout: Duration,
) -> Result<Value> {
    let operation = serde_json::to_string(operation)
        .map_err(|_| unsupported_capture("native media operation"))?;
    let input =
        serde_json::to_string(&input).map_err(|_| unsupported_capture("native media input"))?;
    let expression =
        format!("(function() {{{MEDIA_CAPTURE_SCRIPT}}}).apply(null, [{operation}, {input}])");
    // Site scripts must not replace recorder intrinsics or access the capture binding.
    // The named world is recreated for the current main frame after navigation.
    timeout(command_timeout, async {
        let frame = page
            .cdp()
            .mainframe()
            .await
            .map_err(|_| unsupported_capture("native media frame"))?
            .ok_or_else(|| unsupported_capture("native media frame"))?;
        let mut world = CreateIsolatedWorldParams::new(frame);
        world.world_name = Some(MEDIA_CAPTURE_WORLD.to_owned());
        world.grant_univeral_access = Some(false);
        let context = page
            .cdp()
            .execute(world)
            .await
            .map_err(|_| unsupported_capture("native media isolated world"))?
            .execution_context_id;
        let params = EvaluateParams::builder()
            .expression(expression)
            .context_id(context)
            .await_promise(await_promise)
            .return_by_value(true)
            .user_gesture(user_gesture)
            .build()
            .map_err(|_| unsupported_capture("native media evaluation"))?;
        page.cdp()
            .evaluate_expression(params)
            .await
            .map_err(|_| unsupported_capture("native media evaluation"))?
            .into_value::<Value>()
            .map_err(|_| unsupported_capture("native media result"))
    })
    .await
    .map_err(|_| VoidCrawlError::Timeout("native media command".into()))?
}

struct SourceRuntime {
    source: SourceContext,
    outputs: HashMap<String, OutputState>,
    pending_rearm: bool,
    stream_active: bool,
}

impl SourceRuntime {
    fn new(source: SourceContext) -> Self {
        Self {
            source,
            outputs: HashMap::new(),
            pending_rearm: false,
            stream_active: true,
        }
    }

    async fn handle_command(&mut self, command: Option<SourceCommand>) -> bool {
        match command {
            Some(SourceCommand::StartOutput {
                output_id,
                include_audio,
                maximum_chunk_bytes,
                reply,
            }) => {
                self.start_output_command(output_id, include_audio, maximum_chunk_bytes, reply)
                    .await
            }
            Some(SourceCommand::StopOutput { output_id }) => {
                self.stop_output_command(output_id).await
            }
            None => false,
        }
    }

    async fn start_output_command(
        &mut self,
        output_id: String,
        include_audio: bool,
        maximum_chunk_bytes: u64,
        reply: oneshot::Sender<Result<String>>,
    ) -> bool {
        if !self.stream_active
            || self.outputs.contains_key(&output_id)
            || (include_audio && !self.source.source_audio)
        {
            let _ = reply.send(Err(unsupported_capture(
                "MediaRecorder source is unavailable",
            )));
            return true;
        }
        let result = start_output(
            &self.source.page,
            &self.source.property,
            &output_id,
            0,
            include_audio,
            maximum_chunk_bytes,
        )
        .await;
        match result {
            Ok(mime_type) => {
                self.outputs.insert(
                    output_id.clone(),
                    OutputState {
                        segment: 0,
                        include_audio,
                        maximum_chunk_bytes,
                        mime_type: mime_type.clone(),
                        stop_requested: false,
                    },
                );
                let _ = self
                    .source
                    .events
                    .send(NativeTabMediaEvent::SegmentStarted {
                        output_id: output_id.clone(),
                        segment: 0,
                        mime_type: mime_type.clone(),
                        started_at: Instant::now(),
                    });
                if reply.send(Ok(mime_type)).is_err() {
                    if let Some(output) = self.outputs.get_mut(&output_id) {
                        output.stop_requested = true;
                    }
                    if stop_output(&self.source.page, &self.source.property, &output_id)
                        .await
                        .is_err()
                    {
                        self.fail_and_stop_source().await;
                        return false;
                    }
                }
                true
            }
            Err(error) => {
                if stop_output(&self.source.page, &self.source.property, &output_id)
                    .await
                    .is_err()
                {
                    self.fail_and_stop_source().await;
                    return false;
                }
                let _ = reply.send(Err(error));
                true
            }
        }
    }

    async fn stop_output_command(&mut self, output_id: String) -> bool {
        let segment = self.outputs.get(&output_id).map(|output| output.segment);
        if let Some(output) = self.outputs.get_mut(&output_id) {
            output.stop_requested = true;
        }
        let result = match segment {
            Some(_) if self.stream_active => {
                stop_output(&self.source.page, &self.source.property, &output_id).await
            }
            Some(segment) => {
                self.outputs.remove(&output_id);
                let _ = self.source.events.send(NativeTabMediaEvent::OutputStopped {
                    output_id,
                    segment,
                    at: Instant::now(),
                });
                Ok(())
            }
            None => Ok(()),
        };
        if result.is_err() {
            self.fail_and_stop_source().await;
            return false;
        }
        if self.outputs.is_empty() {
            stop_stream(
                &self.source.page,
                &self.source.property,
                &self.source.binding,
            )
            .await;
            return false;
        }
        true
    }

    async fn handle_binding_delivery(
        &mut self,
        delivery: Option<EventDelivery<EventBindingCalled>>,
    ) -> bool {
        match delivery {
            Some(EventDelivery::Event(event)) if event.name == self.source.binding => {
                let Ok(message) = serde_json::from_str::<BindingMessage>(&event.payload) else {
                    return true;
                };
                self.handle_binding_message(message).await
            }
            Some(EventDelivery::Event(_)) => true,
            Some(EventDelivery::Lagged { .. }) | None => {
                self.source_failure();
                false
            }
        }
    }

    async fn handle_binding_message(&mut self, message: BindingMessage) -> bool {
        match message {
            BindingMessage::Chunk {
                token,
                output_id,
                segment,
                sequence,
                media_time_ms,
                mime_type,
                data,
            } if token == self.source.token => {
                self.handle_chunk(output_id, segment, sequence, media_time_ms, mime_type, data);
                true
            }
            BindingMessage::OutputStopped {
                token,
                output_id,
                segment,
            } if token == self.source.token => self.handle_output_stopped(output_id, segment).await,
            BindingMessage::StreamEnded { token } if token == self.source.token => {
                self.source_failure();
                false
            }
            BindingMessage::OutputFailure {
                token,
                output_id,
                segment,
            } if token == self.source.token => {
                self.output_failure(
                    output_id,
                    segment,
                    NativeTabMediaFailureReason::SourceFailure,
                );
                true
            }
            BindingMessage::Overflow {
                token,
                output_id,
                segment,
            } if token == self.source.token => {
                self.output_failure(output_id, segment, NativeTabMediaFailureReason::BufferLimit);
                true
            }
            _ => true,
        }
    }

    fn handle_chunk(
        &self,
        output_id: String,
        segment: u32,
        sequence: u64,
        media_time_ms: Option<f64>,
        mime_type: String,
        data: String,
    ) {
        let Some(output) = self.outputs.get(&output_id) else {
            return;
        };
        let Some(media_time_ms) = media_time_ms else {
            self.output_failure(
                output_id,
                segment,
                NativeTabMediaFailureReason::SourceFailure,
            );
            return;
        };
        if output.segment != segment
            || output.mime_type != mime_type
            || !media_time_ms.is_finite()
            || media_time_ms < 0.0
        {
            return;
        }
        let Ok(bytes) = STANDARD.decode(data) else {
            self.output_failure(
                output_id,
                segment,
                NativeTabMediaFailureReason::SourceFailure,
            );
            return;
        };
        let Ok(byte_len) = u64::try_from(bytes.len()) else {
            self.output_failure(
                output_id,
                segment,
                NativeTabMediaFailureReason::SourceFailure,
            );
            return;
        };
        if byte_len > output.maximum_chunk_bytes {
            self.output_failure(output_id, segment, NativeTabMediaFailureReason::BufferLimit);
            return;
        }
        let Some(buffer_lease) = (self.source.buffer_admitter)(byte_len) else {
            self.output_failure(output_id, segment, NativeTabMediaFailureReason::BufferLimit);
            return;
        };
        let _ = self.source.events.send(NativeTabMediaEvent::Chunk {
            output_id,
            segment,
            sequence,
            media_time_ms,
            mime_type,
            bytes: Arc::from(bytes),
            _buffer_lease: buffer_lease,
            received_at: Instant::now(),
        });
    }

    fn output_failure(&self, output_id: String, segment: u32, reason: NativeTabMediaFailureReason) {
        let _ = self.source.events.send(NativeTabMediaEvent::OutputFailure {
            output_id,
            segment,
            reason,
            at: Instant::now(),
        });
    }

    async fn handle_output_stopped(&mut self, output_id: String, segment: u32) -> bool {
        let at = Instant::now();
        if self
            .outputs
            .get(&output_id)
            .is_some_and(|output| output.segment == segment && output.stop_requested)
        {
            self.outputs.remove(&output_id);
            let _ = self.source.events.send(NativeTabMediaEvent::OutputStopped {
                output_id,
                segment,
                at,
            });
        } else if self
            .outputs
            .get(&output_id)
            .is_some_and(|output| output.segment == segment)
        {
            let _ = self
                .source
                .events
                .send(NativeTabMediaEvent::SegmentStopped {
                    output_id,
                    segment,
                    at,
                });
        }
        if self.outputs.is_empty() {
            stop_stream(
                &self.source.page,
                &self.source.property,
                &self.source.binding,
            )
            .await;
            return false;
        }
        true
    }

    fn handle_navigation_delivery(
        &mut self,
        delivery: Option<EventDelivery<EventFrameNavigated>>,
    ) -> bool {
        match delivery {
            Some(EventDelivery::Event(event)) if event.frame.parent_id.is_none() => {
                if self.stream_active && !self.outputs.is_empty() {
                    let at = Instant::now();
                    for (output_id, output) in &self.outputs {
                        let _ = self.source.events.send(NativeTabMediaEvent::Navigation {
                            output_id: output_id.clone(),
                            segment: output.segment,
                            at,
                        });
                    }
                    self.stream_active = false;
                    self.pending_rearm = true;
                }
                true
            }
            Some(EventDelivery::Event(_)) => true,
            Some(EventDelivery::Lagged { .. }) | None => {
                self.source_failure();
                false
            }
        }
    }

    async fn handle_content_delivery(
        &mut self,
        delivery: Option<EventDelivery<EventDomContentEventFired>>,
    ) -> bool {
        match delivery {
            Some(EventDelivery::Event(_)) if self.pending_rearm && !self.outputs.is_empty() => {
                self.rearm_source().await
            }
            Some(EventDelivery::Event(_)) => true,
            Some(EventDelivery::Lagged { .. }) | None => {
                self.source_failure();
                false
            }
        }
    }

    async fn rearm_source(&mut self) -> bool {
        let ready = tokio::select! {
            biased;
            () = self.source.cancellation.cancelled() => false,
            () = self.source.tab_closing.cancelled() => false,
            result = timeout(DOCUMENT_READY_DEADLINE, self.source.page.wait_for_main_execution_context()) =>
                matches!(result, Ok(Ok(()))),
        };
        if !ready {
            self.source_failure();
            return false;
        }
        let rearmed = tokio::select! {
            biased;
            () = self.source.cancellation.cancelled() => false,
            () = self.source.tab_closing.cancelled() => false,
            result = start_stream(
                &self.source.page,
                &self.source.binding,
                &self.source.property,
                &self.source.token,
                self.source.source_audio,
                self.source.frames_per_second,
            ) => matches!(result, Ok(true)),
        };
        if !rearmed {
            self.source_failure();
            return false;
        }
        self.stream_active = true;
        self.pending_rearm = false;
        self.rearm_outputs().await;
        true
    }

    async fn rearm_outputs(&mut self) {
        let output_ids = self.outputs.keys().cloned().collect::<Vec<_>>();
        for output_id in output_ids {
            let Some(output) = self.outputs.get(&output_id) else {
                continue;
            };
            let Some(segment) = output.segment.checked_add(1) else {
                self.output_failure(
                    output_id,
                    output.segment,
                    NativeTabMediaFailureReason::SourceFailure,
                );
                continue;
            };
            let (include_audio, maximum_chunk_bytes) =
                (output.include_audio, output.maximum_chunk_bytes);
            match start_output(
                &self.source.page,
                &self.source.property,
                &output_id,
                segment,
                include_audio,
                maximum_chunk_bytes,
            )
            .await
            {
                Ok(mime_type) => {
                    if let Some(output) = self.outputs.get_mut(&output_id) {
                        output.segment = segment;
                        output.mime_type.clone_from(&mime_type);
                        output.stop_requested = false;
                    }
                    let _ = self
                        .source
                        .events
                        .send(NativeTabMediaEvent::SegmentStarted {
                            output_id,
                            segment,
                            mime_type,
                            started_at: Instant::now(),
                        });
                }
                Err(_) => self.output_failure(
                    output_id,
                    segment,
                    NativeTabMediaFailureReason::SourceFailure,
                ),
            }
        }
    }

    fn source_failure(&self) {
        let _ = self
            .source
            .events
            .send(NativeTabMediaEvent::SourceFailure { at: Instant::now() });
    }

    async fn fail_and_stop_source(&self) {
        self.source_failure();
        stop_stream(
            &self.source.page,
            &self.source.property,
            &self.source.binding,
        )
        .await;
    }

    async fn finish(self) {
        if !self.outputs.is_empty() {
            self.source_failure();
        }
        // Unregister first so a racing navigation cannot re-expose the binding
        // between removing the JavaScript property and ending the CDP registration.
        remove_binding(&self.source.page, &self.source.binding).await;
        stop_stream(
            &self.source.page,
            &self.source.property,
            &self.source.binding,
        )
        .await;
    }
}

async fn run_source(
    source: SourceContext,
    mut binding_events: EventStream<EventBindingCalled>,
    mut navigation_events: EventStream<EventFrameNavigated>,
    mut content_events: EventStream<EventDomContentEventFired>,
    mut commands: mpsc::Receiver<SourceCommand>,
) {
    let mut runtime = SourceRuntime::new(source);
    let cancellation = runtime.source.cancellation.clone();
    let tab_closing = runtime.source.tab_closing.clone();
    loop {
        let keep_running = tokio::select! {
            biased;
            () = cancellation.cancelled() => false,
            () = tab_closing.cancelled() => false,
            command = commands.recv() => runtime.handle_command(command).await,
            delivery = binding_events.next() => runtime.handle_binding_delivery(delivery).await,
            delivery = navigation_events.next() => runtime.handle_navigation_delivery(delivery),
            delivery = content_events.next() => runtime.handle_content_delivery(delivery).await,
        };
        if !keep_running {
            break;
        }
    }
    runtime.finish().await;
}

const fn unsupported_capture(operation: &'static str) -> VoidCrawlError {
    VoidCrawlError::UnsupportedCapability { operation }
}
