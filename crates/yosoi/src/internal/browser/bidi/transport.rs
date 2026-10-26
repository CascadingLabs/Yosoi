//! Correlated commands and bounded events on one owned BiDi WebSocket.
//!
//! Cancellation after enqueue poisons the connection: dropping a caller future
//! cannot prove the browser did not execute its command. The operation owner
//! must preserve its dispatch fence and separately settle browser/process cleanup.

use async_tungstenite::tungstenite::Error as WebSocketError;
use rustls::crypto as tls_crypto;
use std::sync::Once;
use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    fmt,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};
use tokio::time::timeout_at;

use async_tungstenite::{
    tokio::connect_async_with_config,
    tungstenite::{Message, protocol::WebSocketConfig},
};
use futures::io::{AsyncRead, AsyncWrite};
use futures_util::StreamExt;
use serde_json::{Value, json};
use thiserror::Error;
use tokio::{
    sync::{OwnedSemaphorePermit, Semaphore, broadcast, mpsc, oneshot, watch},
    time::{Instant, timeout},
};
use tokio_util::sync::CancellationToken;

const JSON_MAX_INTEGER: u64 = 9_007_199_254_740_991;
// Keep cleanup identities disjoint from all possible user-command replies.
const MAX_COMMAND_ID: u64 = JSON_MAX_INTEGER - 4096;
const MAX_RETAINED_BYTES: usize = 512 * 1024 * 1024;
const IO_CLOSE_LIMIT: Duration = Duration::from_secs(2);

/// A secret-safe failure. Raw protocol diagnostics are available only explicitly.
#[derive(Clone, Error)]
pub enum BidiError {
    #[error("BiDi connection is closed")]
    Closed,
    #[error("BiDi connection stopped without confirmed context/session cleanup")]
    CleanupUncertain,
    #[error("BiDi connection or write failed")]
    Connection,
    #[error("BiDi command deadline elapsed")]
    Deadline,
    #[error("BiDi command cancelled")]
    Cancelled,
    #[error("BiDi command capacity exhausted before enqueue")]
    Capacity,
    #[error("BiDi transport bounds are invalid")]
    InvalidLimits,
    #[error("BiDi message exceeded its byte bound")]
    MessageLimit,
    #[error("BiDi event history overflowed; connection fenced")]
    EventOverflow,
    #[error("BiDi message violates the protocol")]
    InvalidMessage,
    #[error("BiDi command identifiers exhausted")]
    IdentifiersExhausted,
    #[error("BiDi command returned a protocol error")]
    Protocol { code: String, message: String },
}

impl fmt::Debug for BidiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Browser diagnostics can include page URLs, scripts or credentials.
        fmt::Display::fmt(self, f)
    }
}

impl BidiError {
    /// A destroyed realm cannot retain one of our remote handles or observers.
    pub fn remote_target_is_gone(&self) -> bool {
        matches!(self, Self::Protocol { code, .. } if matches!(code.as_str(), "no such frame" | "no such realm" | "no such handle"))
    }
}

/// Limits account for message queues as well as received frame sizes.
#[derive(Clone, Copy, Debug)]
pub struct TransportLimits {
    pub max_message_bytes: usize,
    pub max_event_bytes: usize,
    pub max_pending_commands: usize,
    pub event_capacity: usize,
}

impl Default for TransportLimits {
    fn default() -> Self {
        Self {
            max_message_bytes: 16 * 1024 * 1024,
            max_event_bytes: 1024 * 1024,
            max_pending_commands: 16,
            event_capacity: 16,
        }
    }
}

impl TransportLimits {
    fn validate(self) -> Result<(), BidiError> {
        let event_capacity = self
            .event_capacity
            .checked_next_power_of_two()
            .ok_or(BidiError::InvalidLimits)?;
        let command_bytes = self
            .max_message_bytes
            .checked_mul(self.max_pending_commands)
            .ok_or(BidiError::InvalidLimits)?;
        let event_bytes = self
            .max_event_bytes
            .checked_mul(event_capacity)
            .ok_or(BidiError::InvalidLimits)?;
        let total = command_bytes
            .checked_add(event_bytes)
            .ok_or(BidiError::InvalidLimits)?;
        if self.max_message_bytes == 0
            || self.max_event_bytes == 0
            || self.max_event_bytes > self.max_message_bytes
            || self.max_pending_commands == 0
            || self.max_pending_commands > 1024
            || self.event_capacity == 0
            || event_capacity > 1024
            || total > MAX_RETAINED_BYTES
        {
            return Err(BidiError::InvalidLimits);
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct BidiEvent {
    pub sequence: u64,
    pub method: String,
    pub params: Value,
}

impl fmt::Debug for BidiEvent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BidiEvent")
            .field("sequence", &self.sequence)
            .field("method", &self.method)
            .field("params", &"<redacted>")
            .finish()
    }
}

struct Command {
    id: u64,
    method: &'static str,
    scope_argument: Option<String>,
    text: String,
    answer: oneshot::Sender<Result<Value, BidiError>>,
    permit: OwnedSemaphorePermit,
}

struct Pending {
    method: &'static str,
    scope_argument: Option<String>,
    answer: oneshot::Sender<Result<Value, BidiError>>,
    _permit: OwnedSemaphorePermit,
}

/// Only IDs returned by this connection's successful create commands are owned.
/// A browser that was already running remains outside this logical scope.
#[derive(Default)]
struct SessionScope {
    active: bool,
    contexts: BTreeMap<String, Option<String>>,
    user_contexts: BTreeSet<String>,
}

impl SessionScope {
    fn observe(&mut self, command: &Pending, value: &Value) -> Result<(), BidiError> {
        let identifier = |key| {
            value
                .get(key)
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty() && id.len() <= 512)
                .map(str::to_owned)
                .ok_or(BidiError::InvalidMessage)
        };
        match command.method {
            "session.new" => {
                let _ = identifier("sessionId")?;
                self.active = true;
            }
            "session.end" => self.active = false,
            "browser.createUserContext" => {
                let id = identifier("userContext")?;
                if self.contexts.len().saturating_add(self.user_contexts.len()) >= 1024
                    || !self.user_contexts.insert(id)
                {
                    return Err(BidiError::InvalidMessage);
                }
            }
            "browsingContext.create" => {
                let id = identifier("context")?;
                if self.contexts.len().saturating_add(self.user_contexts.len()) >= 1024
                    || self.contexts.contains_key(&id)
                {
                    return Err(BidiError::InvalidMessage);
                }
                self.contexts.insert(id, command.scope_argument.clone());
            }
            "browsingContext.close" => {
                let id = command
                    .scope_argument
                    .as_ref()
                    .ok_or(BidiError::InvalidMessage)?;
                self.contexts.remove(id);
            }
            "browser.removeUserContext" => {
                let id = command
                    .scope_argument
                    .as_ref()
                    .ok_or(BidiError::InvalidMessage)?;
                self.user_contexts.remove(id);
                self.contexts.retain(|_, owner| owner.as_ref() != Some(id));
            }
            _ => {}
        }
        Ok(())
    }
}

struct Shared {
    commands: mpsc::Sender<Command>,
    permits: Arc<Semaphore>,
    events: broadcast::Sender<BidiEvent>,
    initial_events: Mutex<Option<broadcast::Receiver<BidiEvent>>>,
    stop: CancellationToken,
    stopped: watch::Receiver<Option<bool>>,
    next_id: AtomicU64,
    events_received: Arc<AtomicU64>,
    limits: TransportLimits,
}

impl Drop for Shared {
    fn drop(&mut self) {
        self.stop.cancel();
    }
}

#[derive(Clone)]
pub struct BidiConnection {
    inner: Arc<Shared>,
}

impl fmt::Debug for BidiConnection {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BidiConnection")
            .field("closed", &self.inner.stop.is_cancelled())
            .finish_non_exhaustive()
    }
}

struct CommandFence {
    stop: CancellationToken,
    armed: bool,
}
impl Drop for CommandFence {
    fn drop(&mut self) {
        if self.armed {
            self.stop.cancel();
        }
    }
}

impl BidiConnection {
    /// Connect without leaking endpoint credentials into errors or diagnostics.
    pub async fn connect(
        endpoint: &str,
        limits: TransportLimits,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Self, BidiError> {
        limits.validate()?;
        if cancellation.is_cancelled() {
            return Err(BidiError::Cancelled);
        }
        if Instant::now() >= deadline {
            return Err(BidiError::Deadline);
        }
        let write_limit = limits
            .max_message_bytes
            .checked_add(65_536)
            .ok_or(BidiError::InvalidLimits)?;
        let config = WebSocketConfig::default()
            .max_message_size(Some(limits.max_message_bytes))
            .max_frame_size(Some(limits.max_message_bytes))
            .write_buffer_size(0)
            .max_write_buffer_size(write_limit);
        static CRYPTO: Once = Once::new();
        CRYPTO.call_once(|| {
            if tls_crypto::CryptoProvider::get_default().is_none() {
                let _ = tls_crypto::ring::default_provider().install_default();
            }
        });
        let (socket, _) = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(BidiError::Cancelled),
            result = timeout_at(deadline, connect_async_with_config(endpoint, Some(config))) => result.map_err(|_| BidiError::Deadline)?.map_err(|_| BidiError::Connection)?,
        };
        let (sender, receiver) = mpsc::channel(limits.max_pending_commands);
        let (events, initial_events) = broadcast::channel(limits.event_capacity);
        let (stopped_sender, stopped) = watch::channel(None);
        let stop = CancellationToken::new();
        let events_received = Arc::new(AtomicU64::new(0));
        let inner = Arc::new(Shared {
            commands: sender,
            permits: Arc::new(Semaphore::new(limits.max_pending_commands)),
            events: events.clone(),
            initial_events: Mutex::new(Some(initial_events)),
            stop: stop.clone(),
            stopped,
            next_id: AtomicU64::new(1),
            events_received: Arc::clone(&events_received),
            limits,
        });
        tokio::spawn(run(
            socket,
            receiver,
            events,
            stop,
            stopped_sender,
            limits,
            events_received,
        ));
        Ok(Self { inner })
    }

    /// The first subscription includes bounded events received since connect.
    pub fn subscribe(&self) -> Result<EventStream, BidiError> {
        let mut initial = self
            .inner
            .initial_events
            .lock()
            .map_err(|_| BidiError::Closed)?;
        let receiver = if let Some(receiver) = initial.take() {
            receiver
        } else {
            if self.inner.events.receiver_count() >= self.inner.limits.max_pending_commands {
                return Err(BidiError::Capacity);
            }
            self.inner.events.subscribe()
        };
        drop(initial);
        Ok(EventStream {
            receiver,
            stop: self.inner.stop.clone(),
        })
    }

    pub fn is_closed(&self) -> bool {
        self.inner.stop.is_cancelled()
    }

    /// Events read before an acknowledged command must be applied before the
    /// session uses its cached frame/realm/navigation state.
    pub fn event_sequence(&self) -> u64 {
        self.inner.events_received.load(Ordering::Acquire)
    }

    /// Prevent any further dispatch while the I/O owner settles logical cleanup.
    pub fn fence(&self) {
        self.inner.stop.cancel();
    }

    pub async fn command(
        &self,
        method: &'static str,
        params: Value,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Value, BidiError> {
        if cancellation.is_cancelled() {
            return Err(BidiError::Cancelled);
        }
        if self.is_closed() {
            return Err(BidiError::Closed);
        }
        if Instant::now() >= deadline {
            return Err(BidiError::Deadline);
        }
        if method.is_empty() || method.len() > 256 || !params.is_object() {
            return Err(BidiError::InvalidMessage);
        }
        let permit = Arc::clone(&self.inner.permits)
            .try_acquire_owned()
            .map_err(|_| BidiError::Capacity)?;
        let id = self
            .inner
            .next_id
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
                current
                    .checked_add(1)
                    .filter(|next| *next <= MAX_COMMAND_ID)
            })
            .map_err(|_| BidiError::IdentifiersExhausted)?;
        let text = serde_json::to_string(&json!({"id":id,"method":method,"params":params}))
            .map_err(|_| BidiError::InvalidMessage)?;
        if text.len() > self.inner.limits.max_message_bytes {
            return Err(BidiError::MessageLimit);
        }
        let (answer, result) = oneshot::channel();
        let scope_argument = match method {
            "browsingContext.create" | "browser.removeUserContext" => params.get("userContext"),
            "browsingContext.close" => params.get("context"),
            _ => None,
        }
        .and_then(Value::as_str)
        .map(str::to_owned);
        self.inner
            .commands
            .try_send(Command {
                id,
                method,
                scope_argument,
                text,
                answer,
                permit,
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => BidiError::Capacity,
                mpsc::error::TrySendError::Closed(_) => BidiError::Closed,
            })?;
        let mut fence = CommandFence {
            stop: self.inner.stop.clone(),
            armed: true,
        };
        let result = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(BidiError::Cancelled),
            result = timeout_at(deadline, result) => result.map_err(|_| BidiError::Deadline)?.map_err(|_| BidiError::Closed)?,
        };
        fence.armed = false;
        result
    }

    pub async fn close(&self) -> Result<(), BidiError> {
        self.inner.stop.cancel();
        let mut stopped = self.inner.stopped.clone();
        let complete = timeout(Duration::from_secs(5), stopped.wait_for(Option::is_some))
            .await
            .map_err(|_| BidiError::Deadline)?
            .map_err(|_| BidiError::Closed)?;
        if *complete == Some(true) {
            Ok(())
        } else {
            Err(BidiError::CleanupUncertain)
        }
    }
}

#[derive(Debug)]
pub struct EventStream {
    receiver: broadcast::Receiver<BidiEvent>,
    stop: CancellationToken,
}

impl EventStream {
    pub async fn next(
        &mut self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<BidiEvent, BidiError> {
        tokio::select! {
            biased;
            () = cancellation.cancelled() => Err(BidiError::Cancelled),
            () = self.stop.cancelled() => Err(BidiError::Closed),
            result = timeout_at(deadline, self.receiver.recv()) => match result.map_err(|_| BidiError::Deadline)? {
                Ok(event) => Ok(event),
                Err(broadcast::error::RecvError::Lagged(_)) => { self.stop.cancel(); Err(BidiError::EventOverflow) },
                Err(broadcast::error::RecvError::Closed) => Err(BidiError::Closed),
            },
        }
    }
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "Pending replies are drained by value on connection failure."
)]
async fn run<S>(
    mut socket: async_tungstenite::WebSocketStream<S>,
    mut commands: mpsc::Receiver<Command>,
    events: broadcast::Sender<BidiEvent>,
    stop: CancellationToken,
    stopped: watch::Sender<Option<bool>>,
    limits: TransportLimits,
    events_received: Arc<AtomicU64>,
) where
    S: AsyncRead + AsyncWrite + Unpin + Send + 'static,
{
    let mut pending: HashMap<u64, Pending> = HashMap::new();
    let mut scope = SessionScope::default();
    let failure = loop {
        tokio::select! {
            biased;
            () = stop.cancelled() => break BidiError::Closed,
            command = commands.recv() => {
                let Some(command) = command else { break BidiError::Closed; };
                if command.answer.is_closed() { continue; }
                let id = command.id;
                let text = command.text;
                pending.insert(id, Pending { method: command.method, scope_argument: command.scope_argument, answer: command.answer, _permit: command.permit });
                let sent = tokio::select! {
                    biased;
                    () = stop.cancelled() => break BidiError::Closed,
                    result = timeout(Duration::from_secs(5), socket.send(Message::Text(text.into()))) => result,
                };
                if !matches!(sent, Ok(Ok(()))) { break BidiError::Connection; }
            }
            incoming = socket.next() => {
                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        if let Err(error) = receive(text.as_str(), &mut pending, &events, limits, &mut scope, &events_received) { break error; }
                    }
                    Some(Ok(Message::Ping(bytes))) => {
                        if !matches!(timeout(IO_CLOSE_LIMIT, socket.send(Message::Pong(bytes))).await, Ok(Ok(()))) { break BidiError::Connection; }
                    }
                    Some(Ok(Message::Pong(_))) => {},
                    Some(Ok(Message::Close(_))) | None => break BidiError::Closed,
                    Some(Ok(_)) => break BidiError::InvalidMessage,
                    Some(Err(WebSocketError::Capacity(_))) => break BidiError::MessageLimit,
                    Some(Err(_)) => break BidiError::Connection,
                }
            }
        }
    };
    stop.cancel();
    let uncertain_creation = pending.values().any(|entry| match entry.method {
        "session.new" | "browser.createUserContext" => true,
        "browsingContext.create" => !entry
            .scope_argument
            .as_ref()
            .is_some_and(|owner| scope.user_contexts.contains(owner)),
        _ => false,
    });
    for (_, entry) in pending {
        let _ = entry.answer.send(Err(failure.clone()));
    }
    commands.close();
    while let Ok(command) = commands.try_recv() {
        let _ = command.answer.send(Err(failure.clone()));
    }
    let cleanup_complete = cleanup_scope(&mut socket, &scope).await && !uncertain_creation;
    let _ = timeout(IO_CLOSE_LIMIT, socket.close(None)).await;
    let _ = stopped.send(Some(cleanup_complete));
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "The temporary only borrows a pending entry; removal consumes the actual owner."
)]
fn receive(
    text: &str,
    pending: &mut HashMap<u64, Pending>,
    events: &broadcast::Sender<BidiEvent>,
    limits: TransportLimits,
    scope: &mut SessionScope,
    events_received: &AtomicU64,
) -> Result<(), BidiError> {
    let message: Value = serde_json::from_str(text).map_err(|_| BidiError::InvalidMessage)?;
    match message.get("type").and_then(Value::as_str) {
        Some("success" | "error") => {
            let id = message
                .get("id")
                .and_then(Value::as_u64)
                .ok_or(BidiError::InvalidMessage)?;
            let result = if message.get("type").and_then(Value::as_str) == Some("error") {
                let code = message
                    .get("error")
                    .and_then(Value::as_str)
                    .ok_or(BidiError::InvalidMessage)?;
                let detail = message
                    .get("message")
                    .and_then(Value::as_str)
                    .ok_or(BidiError::InvalidMessage)?;
                Err(BidiError::Protocol {
                    code: code.into(),
                    message: detail.into(),
                })
            } else {
                Ok(message
                    .get("result")
                    .cloned()
                    .ok_or(BidiError::InvalidMessage)?)
            };
            let entry = pending.get(&id).ok_or(BidiError::InvalidMessage)?;
            if let Ok(value) = &result {
                scope.observe(entry, value)?;
            }
            let entry = pending.remove(&id).ok_or(BidiError::InvalidMessage)?;
            let _ = entry.answer.send(result);
        }
        Some("event") => {
            if text.len() > limits.max_event_bytes {
                return Err(BidiError::MessageLimit);
            }
            let method = message
                .get("method")
                .and_then(Value::as_str)
                .filter(|s| s.len() <= 256)
                .ok_or(BidiError::InvalidMessage)?;
            let params = message
                .get("params")
                .filter(|v| v.is_object())
                .cloned()
                .ok_or(BidiError::InvalidMessage)?;
            if method == "browsingContext.contextDestroyed"
                && let Some(context) = params.get("context").and_then(Value::as_str)
            {
                scope.contexts.remove(context);
            }
            let sequence = events_received
                .try_update(Ordering::Release, Ordering::Relaxed, |previous| {
                    previous.checked_add(1)
                })
                .map_err(|_| BidiError::IdentifiersExhausted)?
                .checked_add(1)
                .ok_or(BidiError::IdentifiersExhausted)?;
            let _ = events.send(BidiEvent {
                sequence,
                method: method.into(),
                params,
            });
        }
        _ => return Err(BidiError::InvalidMessage),
    }
    Ok(())
}

/// A fenced connection may perform only these owned cleanup commands. It never
/// returns late action replies as success, closes a foreign process, or admits
/// a new action. Lost creation replies remain explicitly uncertain.
async fn cleanup_scope<S>(
    socket: &mut async_tungstenite::WebSocketStream<S>,
    scope: &SessionScope,
) -> bool
where
    S: AsyncRead + AsyncWrite + Unpin + Send,
{
    if !scope.active {
        return scope.contexts.is_empty() && scope.user_contexts.is_empty();
    }
    let Some(deadline) = Instant::now().checked_add(IO_CLOSE_LIMIT) else {
        return false;
    };
    let mut steps = Vec::new();
    for context in scope.contexts.keys() {
        steps.push(("browsingContext.close", json!({"context":context})));
    }
    for context in &scope.user_contexts {
        steps.push(("browser.removeUserContext", json!({"userContext":context})));
    }
    steps.push(("session.end", json!({})));
    for (index, (method, params)) in steps.into_iter().enumerate() {
        let Some(id) = u64::try_from(index)
            .ok()
            .and_then(|index| JSON_MAX_INTEGER.checked_sub(index))
        else {
            return false;
        };
        if id <= MAX_COMMAND_ID {
            return false;
        }
        if !cleanup_command(socket, method, params, id, deadline).await {
            return false;
        }
    }
    true
}

async fn cleanup_command<S>(
    socket: &mut async_tungstenite::WebSocketStream<S>,
    method: &str,
    params: Value,
    id: u64,
    deadline: Instant,
) -> bool
where
    S: AsyncRead + AsyncWrite + Unpin + Send,
{
    let text = json!({"id":id,"method":method,"params":params}).to_string();
    if !matches!(
        timeout_at(deadline, socket.send(Message::Text(text.into()))).await,
        Ok(Ok(()))
    ) {
        return false;
    }
    loop {
        match timeout_at(deadline, socket.next()).await {
            Ok(Some(Ok(Message::Text(text)))) => {
                let Ok(value) = serde_json::from_str::<Value>(text.as_str()) else {
                    return false;
                };
                if value.get("id").and_then(Value::as_u64) != Some(id) {
                    continue;
                }
                return match value.get("type").and_then(Value::as_str) {
                    Some("success") => value.get("result").is_some(),
                    Some("error") => matches!(
                        (method, value.get("error").and_then(Value::as_str)),
                        ("browsingContext.close", Some("no such frame"))
                            | ("browser.removeUserContext", Some("no such user context"))
                    ),
                    _ => false,
                };
            }
            Ok(Some(Ok(Message::Ping(bytes)))) => {
                if !matches!(
                    timeout_at(deadline, socket.send(Message::Pong(bytes))).await,
                    Ok(Ok(()))
                ) {
                    return false;
                }
            }
            Ok(Some(Ok(Message::Pong(_)))) => {}
            _ => return false,
        }
    }
}

#[cfg(test)]
mod tests;
