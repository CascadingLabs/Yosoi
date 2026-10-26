//! Native logical sessions; executable ownership is separate from remote scope.

use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    net::SocketAddr,
    sync::{Arc, Weak},
    time::Duration,
};

use serde_json::{Value, json};
use thiserror::Error;
use tokio::{
    sync::{Mutex, Notify},
    time::{Instant, timeout_at},
};
use tokio_util::sync::CancellationToken;

use crate::browser::{BrowserConfig, BrowserEngine};

use super::{
    process::{ExecutableIdentity, LaunchError, OwnedProcess},
    transport::{BidiConnection, BidiError, BidiEvent, TransportLimits},
};

#[derive(Debug, Error)]
pub enum SessionError {
    #[error(transparent)]
    Launch(#[from] LaunchError),
    #[error(transparent)]
    Transport(#[from] BidiError),
    #[error("browser did not report the required native session identity")]
    Identity,
    #[error("browser context is closed or not owned by this session")]
    Context,
    #[error("native input target or input value was rejected before dispatch")]
    InvalidInput,
    #[error("invalid {operation} argument: {reason}")]
    InvalidArgument {
        operation: &'static str,
        reason: &'static str,
    },
    #[error("visual target has no visible rectangle")]
    TargetNotVisible,
    #[error("visual target has multiple visible rectangles")]
    TargetAmbiguous,
    #[error("target kind has no visual geometry")]
    UnsupportedVisualTarget,
    #[error("native keyboard target was lost before typing")]
    InputTargetLost,
    #[error("browser state exceeded its bounded context/realm capacity")]
    Capacity,
    #[error("browser script failed")]
    Script,
    #[error("browser result has no supported JSON representation")]
    Serialization,
    #[error("document changed during the observation")]
    DocumentChanged,
    #[error("browser capability is unsupported: {0}")]
    Unsupported(&'static str),
}

/// Wire claims and executable attestation remain distinct.
#[derive(Clone, Debug)]
pub struct SessionIdentity {
    pub browser_name: Option<String>,
    pub browser_version: Option<String>,
    pub executable: Option<ExecutableIdentity>,
    pub reported_headless: Option<bool>,
}

#[derive(Default)]
struct State {
    // Only successful creates through this connection populate ownership.
    contexts: BTreeMap<String, String>,
    users: BTreeSet<String>,
    realms: BTreeMap<String, Realm>,
    fenced: bool,
    next_frame: u64,
    next_input: u64,
    last_event: u64,
    navigating: BTreeMap<String, Option<String>>,
}

#[derive(Clone)]
struct Realm {
    context: String,
    id: String,
}

pub struct Session {
    pub connection: BidiConnection,
    pub identity: SessionIdentity,
    pub config: BrowserConfig,
    pub headful: bool,
    proxy: Option<SocketAddr>,
    process: Mutex<Option<OwnedProcess>>,
    state: Mutex<State>,
    stop: CancellationToken,
    changed: Notify,
}

impl fmt::Debug for Session {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BidiSession")
            .field("identity", &self.identity)
            .field("closed", &self.stop.is_cancelled())
            .finish_non_exhaustive()
    }
}

impl Session {
    pub async fn launch(
        config: BrowserConfig,
        headful: bool,
        proxy: Option<SocketAddr>,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Arc<Self>, SessionError> {
        config
            .validate_headful(headful)
            .map_err(LaunchError::from)?;
        if config.engine == BrowserEngine::Chrome {
            return Err(SessionError::Identity);
        }
        if let Some(proxy) = proxy
            && (config.endpoint.is_some() || !proxy.ip().is_loopback())
        {
            return Err(SessionError::Unsupported(
                "native route requires an owned process and loopback SOCKS relay",
            ));
        }
        let mut process = match &config.endpoint {
            Some(_) => None,
            None => Some(
                OwnedProcess::launch(&config, headful, proxy.is_some(), cancellation, deadline)
                    .await?,
            ),
        };
        let endpoint = config
            .endpoint
            .as_deref()
            .or_else(|| process.as_ref().map(|process| process.endpoint.as_str()))
            .ok_or(SessionError::Identity)?;
        let connection = BidiConnection::connect(
            endpoint,
            TransportLimits {
                event_capacity: 128,
                ..TransportLimits::default()
            },
            cancellation,
            deadline,
        )
        .await?;
        let setup = async {
            let reply = connection
                .command(
                    "session.new",
                    json!({"capabilities":{}}),
                    cancellation,
                    deadline,
                )
                .await?;
            let capabilities = reply.get("capabilities").ok_or(SessionError::Identity)?;
            // Moli currently reports neither field. Absence is not an attestation
            // failure and must not be replaced with a fictitious Chrome banner.
            let browser_name = optional_identity(capabilities, "browserName")?;
            let browser_version = optional_identity(capabilities, "browserVersion")?;
            let expected = match config.engine {
                BrowserEngine::Firefox => "firefox",
                BrowserEngine::Moli => "moli",
                BrowserEngine::Chrome => return Err(SessionError::Identity),
            };
            if browser_name
                .as_ref()
                .is_some_and(|name| !name.eq_ignore_ascii_case(expected))
            {
                return Err(SessionError::Identity);
            }
            if let Some(process) = &process
                && (browser_version
                    .as_ref()
                    .is_some_and(|version| *version != process.identity.release_version)
                    || (config.engine == BrowserEngine::Firefox
                        && (browser_name.is_none() || browser_version.is_none())))
            {
                return Err(SessionError::Identity);
            }
            if capabilities
                .get("moz:headless")
                .and_then(Value::as_bool)
                .is_some_and(|observed| observed == headful)
            {
                return Err(SessionError::Identity);
            }
            connection.command("session.subscribe", json!({"events":[
                "browsingContext", "script.realmCreated", "script.realmDestroyed", "script.message"
            ]}), cancellation, deadline).await?;
            Ok::<_, SessionError>((
                browser_name,
                browser_version,
                capabilities.get("moz:headless").and_then(Value::as_bool),
            ))
        }
        .await;
        let (browser_name, browser_version, reported_headless) = match setup {
            Ok(identity) => identity,
            Err(error) => {
                let _ = connection.close().await;
                if let (Some(process), Some(deadline)) = (
                    process.as_mut(),
                    Instant::now().checked_add(Duration::from_secs(5)),
                ) {
                    let _ = process.close_before(deadline).await;
                }
                return Err(error);
            }
        };
        let mut events = connection.subscribe()?;
        let session = Arc::new(Self {
            identity: SessionIdentity {
                browser_name,
                browser_version,
                executable: process.as_ref().map(|process| process.identity.clone()),
                reported_headless,
            },
            config,
            headful,
            proxy,
            connection,
            process: Mutex::new(process),
            state: Mutex::new(State::default()),
            stop: CancellationToken::new(),
            changed: Notify::new(),
        });
        let weak = Arc::downgrade(&session);
        let stop = session.stop.clone();
        tokio::spawn(async move {
            // Bound an individual parked receive without polling for readiness.
            while let Some(deadline) = Instant::now().checked_add(Duration::from_hours(24)) {
                match events.next(&stop, deadline).await {
                    Ok(event) => {
                        let Some(session) = weak.upgrade() else { break };
                        if session.observe(event).await.is_err() {
                            session.state.lock().await.fenced = true;
                            session.changed.notify_waiters();
                            let _ = session.connection.close().await;
                            break;
                        }
                    }
                    Err(BidiError::Deadline) => {}
                    Err(_) => {
                        if let Some(session) = weak.upgrade() {
                            session.state.lock().await.fenced = true;
                            session.changed.notify_waiters();
                        }
                        break;
                    }
                }
            }
        });
        Ok(session)
    }

    async fn observe(&self, event: BidiEvent) -> Result<(), SessionError> {
        let mut state = self.state.lock().await;
        if state.last_event.checked_add(1) != Some(event.sequence) {
            return Err(SessionError::Context);
        }
        match event.method.as_str() {
            "script.realmCreated"
                if event.params.get("type").and_then(Value::as_str) == Some("window")
                    && event.params.get("sandbox").is_none() =>
            {
                let id = identifier(&event.params, "realm")?;
                let context = identifier(&event.params, "context")?;
                if state.realms.len() >= 4096 && !state.realms.contains_key(&id) {
                    return Err(SessionError::Capacity);
                }
                // Moli does not emit realmDestroyed for every replacement.
                // Keep the latest main world per context, not historical aliases.
                state.realms.retain(|_, realm| realm.context != context);
                state.realms.insert(id.clone(), Realm { context, id });
            }
            "script.realmDestroyed" => {
                let id = identifier(&event.params, "realm")?;
                state.realms.remove(&id);
            }
            "browsingContext.contextDestroyed" => {
                let context = identifier(&event.params, "context")?;
                state.contexts.remove(&context);
                state.navigating.remove(&context);
                state.realms.retain(|_, realm| realm.context != context);
            }
            "browsingContext.navigationStarted" => {
                let context = identifier(&event.params, "context")?;
                if state.contexts.contains_key(&context) {
                    let navigation = optional_identity(&event.params, "navigation")?;
                    state.navigating.insert(context, navigation);
                }
            }
            "browsingContext.domContentLoaded"
            | "browsingContext.load"
            | "browsingContext.navigationFailed"
            | "browsingContext.navigationAborted" => {
                let context = identifier(&event.params, "context")?;
                let navigation = optional_identity(&event.params, "navigation")?;
                if state
                    .navigating
                    .get(&context)
                    .is_some_and(|pending| pending.as_deref() == navigation.as_deref())
                {
                    state.navigating.remove(&context);
                }
            }
            "browsingContext.fragmentNavigated" | "browsingContext.historyUpdated" => {
                let context = identifier(&event.params, "context")?;
                state.navigating.remove(&context);
            }
            _ => {}
        }
        state.last_event = event.sequence;
        drop(state);
        self.changed.notify_waiters();
        Ok(())
    }

    pub(in crate::internal::browser) async fn synchronize_events(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        let through = self.connection.event_sequence();
        loop {
            let changed = self.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let state = self.state.lock().await;
            if state.fenced {
                return Err(SessionError::Context);
            }
            if state.last_event >= through {
                return Ok(());
            }
            drop(state);
            tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(BidiError::Cancelled.into()),
                () = self.stop.cancelled() => return Err(SessionError::Context),
                result = timeout_at(deadline, changed) => result.map_err(|_| BidiError::Deadline)?,
            }
        }
    }

    pub(super) async fn input_channel(&self) -> Result<String, SessionError> {
        let mut state = self.state.lock().await;
        state.next_input = state
            .next_input
            .checked_add(1)
            .ok_or(SessionError::Capacity)?;
        let channel = format!("yosoi-native-input-{}", state.next_input);
        drop(state);
        Ok(channel)
    }

    pub async fn new_user_context(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<String, SessionError> {
        let reply = self
            .connection
            .command(
                "browser.createUserContext",
                self.proxy.map_or_else(|| json!({}), |proxy| json!({"proxy":{"proxyType":"manual","socksProxy":proxy.to_string(),"socksVersion":5}})),
                cancellation,
                deadline,
            )
            .await?;
        let user = identifier(&reply, "userContext")?;
        let mut state = self.state.lock().await;
        if state.fenced || state.users.len() >= 1024 {
            return Err(SessionError::Capacity);
        }
        state.users.insert(user.clone());
        drop(state);
        Ok(user)
    }

    pub async fn new_page(
        self: &Arc<Self>,
        user_context: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Page, SessionError> {
        if !self.state.lock().await.users.contains(user_context) {
            return Err(SessionError::Context);
        }
        let reply = self
            .connection
            .command(
                "browsingContext.create",
                json!({"type":"tab", "userContext":user_context}),
                cancellation,
                deadline,
            )
            .await?;
        let context = identifier(&reply, "context")?;
        let mut state = self.state.lock().await;
        if state.fenced || state.contexts.len() >= 1024 {
            return Err(SessionError::Capacity);
        }
        state.next_frame = state
            .next_frame
            .checked_add(1)
            .ok_or(SessionError::Capacity)?;
        let frame_id = state.next_frame;
        state
            .contexts
            .insert(context.clone(), user_context.to_owned());
        Ok(Page {
            session: Arc::clone(self),
            context,
            frame_id,
            document: Arc::new(Mutex::new((None, 0))),
            navigation_state: Arc::default(),
            active_watch: Arc::default(),
            viewport: Arc::default(),
        })
    }

    pub async fn remove_user_context(
        &self,
        user_context: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        if !self.state.lock().await.users.contains(user_context) {
            return Err(SessionError::Context);
        }
        self.connection
            .command(
                "browser.removeUserContext",
                json!({"userContext":user_context}),
                cancellation,
                deadline,
            )
            .await?;
        let mut state = self.state.lock().await;
        state.contexts.retain(|_, owner| owner != user_context);
        state.users.remove(user_context);
        drop(state);
        Ok(())
    }

    pub async fn close(&self) -> Result<(), SessionError> {
        self.stop.cancel();
        let logical = self.connection.close().await;
        let mut process = self.process.lock().await;
        if let Some(process) = process.as_mut() {
            let deadline = Instant::now()
                .checked_add(Duration::from_secs(5))
                .ok_or(SessionError::Context)?;
            process.close_before(deadline).await?;
        }
        drop(process);
        logical?;
        Ok(())
    }
}

#[cfg(test)]
mod tests;

impl Drop for Session {
    fn drop(&mut self) {
        self.stop.cancel();
    }
}

#[derive(Clone)]
pub struct Page {
    pub session: Arc<Session>,
    pub context: String,
    pub frame_id: u64,
    pub document: Arc<Mutex<(Option<String>, u64)>>,
    // Serializes viewport changes with temporary capture overrides.
    pub(super) viewport: Arc<Mutex<super::emulation::ViewportState>>,
    pub(in crate::internal::browser) navigation_state:
        Arc<super::super::active_navigation::NavigationState>,
    pub(in crate::internal::browser) active_watch: Arc<Mutex<Option<Weak<super::watch::Inner>>>>,
}

impl fmt::Debug for Page {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BidiPage").finish_non_exhaustive()
    }
}

impl Page {
    pub(in crate::internal::browser) async fn stop_loading_native(
        &self,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        if self.session.config.engine == BrowserEngine::Moli
            && self.navigation_pending(token, deadline).await?
        {
            return Err(SessionError::Unsupported(
                "Moli stopping an uncommitted navigation",
            ));
        }
        self.session.synchronize_events(token, deadline).await?;
        let pending_before_stop = self
            .session
            .state
            .lock()
            .await
            .navigating
            .get(&self.context)
            .cloned();
        // This fixed utility must bypass waits for the document being stopped.
        let result = self
            .command(
                "script.evaluate",
                json!({
                    "expression":"window.stop()", "target":{"context":self.context},
                    "awaitPromise":false, "resultOwnership":"none",
                }),
                token,
                deadline,
            )
            .await?;
        if result.get("type").and_then(Value::as_str) != Some("success") {
            return Err(SessionError::Script);
        }
        {
            let mut state = self.session.state.lock().await;
            if let Some(pending) = state.navigating.get(&self.context) {
                if pending_before_stop.as_ref() != Some(pending) {
                    return Err(SessionError::DocumentChanged);
                }
                state.navigating.remove(&self.context);
            }
            drop(state);
            self.session.changed.notify_waiters();
        }
        Ok(())
    }

    pub(in crate::internal::browser) async fn navigation_pending(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<bool, SessionError> {
        self.session
            .synchronize_events(cancellation, deadline)
            .await?;
        Ok(self
            .session
            .state
            .lock()
            .await
            .navigating
            .contains_key(&self.context))
    }
    /// Wait only for an already-observed navigation on this owned context.
    async fn wait_document_ready(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        self.session
            .synchronize_events(cancellation, deadline)
            .await?;
        loop {
            let changed = self.session.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let state = self.session.state.lock().await;
            if state.fenced || !state.contexts.contains_key(&self.context) {
                return Err(SessionError::Context);
            }
            if !state.navigating.contains_key(&self.context) {
                return Ok(());
            }
            drop(state);
            tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(BidiError::Cancelled.into()),
                () = self.session.stop.cancelled() => return Err(SessionError::Context),
                result = timeout_at(deadline, changed) => result.map_err(|_| BidiError::Deadline)?,
            }
        }
    }

    /// Child contexts in Moli 1.1.19 require an observed realm alias. Never
    /// replay author code to discover this compatibility issue.
    pub async fn evaluate_in_frame(
        &self,
        pattern: &str,
        expression: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Value, SessionError> {
        self.wait_document_ready(cancellation, deadline).await?;
        let frames = self.frames(cancellation, deadline).await?;
        let mut matches = frames.iter().filter(|frame| frame.url.contains(pattern));
        let frame = matches.next().ok_or(SessionError::Context)?;
        if matches.next().is_some() {
            return Err(SessionError::Context);
        }
        let target = if frame.context == self.context {
            let (_, realm) = self.evaluate("0", cancellation, deadline).await?;
            realm
        } else if self.session.config.engine == BrowserEngine::Moli {
            let raw = loop {
                let changed = self.session.changed.notified();
                tokio::pin!(changed);
                changed.as_mut().enable();
                let state = self.session.state.lock().await;
                if state.fenced {
                    return Err(SessionError::Context);
                }
                let mut candidates = state
                    .realms
                    .values()
                    .filter(|realm| realm.context == frame.context);
                if let Some(realm) = candidates.next() {
                    if candidates.next().is_some() {
                        return Err(SessionError::Context);
                    }
                    break realm.id.clone();
                }
                drop(state);
                tokio::select! {
                    biased;
                    () = cancellation.cancelled() => return Err(BidiError::Cancelled.into()),
                    result = timeout_at(deadline, changed) => result.map_err(|_| BidiError::Deadline)?,
                }
            };
            moli_realm_alias(&self.context, &raw)?
        } else {
            let reply = self
                .command(
                    "script.getRealms",
                    json!({"context":frame.context,"type":"window"}),
                    cancellation,
                    deadline,
                )
                .await?;
            let realms = reply
                .get("realms")
                .and_then(Value::as_array)
                .ok_or(SessionError::Context)?;
            let mut candidates = realms.iter().filter(|realm| realm.get("sandbox").is_none());
            let realm = candidates.next().ok_or(SessionError::Context)?;
            if candidates.next().is_some() {
                return Err(SessionError::Context);
            }
            identifier(realm, "realm")?
        };
        // Resolve the target using a side-effect-free probe. Author expression
        // is never sent to target.context then retried against a different realm.
        let observed = self
            .evaluate_realm("location.href", &target, cancellation, deadline)
            .await?
            .0;
        if observed.as_str() != Some(frame.url.as_str()) {
            return Err(SessionError::DocumentChanged);
        }
        Ok(self
            .evaluate_realm(expression, &target, cancellation, deadline)
            .await?
            .0)
    }

    pub async fn ensure_owned(&self) -> Result<(), SessionError> {
        let state = self.session.state.lock().await;
        let unavailable = state.fenced
            || !state.contexts.contains_key(&self.context)
            || self.session.connection.is_closed();
        drop(state);
        if unavailable {
            return Err(SessionError::Context);
        }
        Ok(())
    }

    pub async fn command(
        &self,
        method: &'static str,
        params: Value,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Value, SessionError> {
        self.session
            .synchronize_events(cancellation, deadline)
            .await?;
        self.ensure_owned().await?;
        let result = self
            .session
            .connection
            .command(method, params, cancellation, deadline)
            .await
            .map_err(|error| match error {
                BidiError::Protocol { ref code, .. }
                    if matches!(code.as_str(), "unknown command" | "unsupported operation") =>
                {
                    SessionError::Unsupported(method)
                }
                error => SessionError::Transport(error),
            })?;
        self.session
            .synchronize_events(cancellation, deadline)
            .await?;
        Ok(result)
    }

    pub async fn navigate(
        &self,
        url: &str,
        wait: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        self.command(
            "browsingContext.navigate",
            json!({"context":self.context,"url":url,"wait":wait}),
            cancellation,
            deadline,
        )
        .await?;
        Ok(())
    }

    /// Resolve to a realm first: author code is sent once, never retried in a new document.
    pub async fn evaluate(
        &self,
        expression: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(Value, String), SessionError> {
        let realm = self.ready_realm(cancellation, deadline).await?;
        self.evaluate_realm(expression, &realm, cancellation, deadline)
            .await
    }

    /// Only the internal read-only probe can repeat; author code is sent once.
    pub(super) async fn ready_realm(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<String, SessionError> {
        for _ in 0..4 {
            self.wait_document_ready(cancellation, deadline).await?;
            let probe = self.command("script.evaluate", json!({"expression":"0","target":{"context":self.context},"awaitPromise":false}), cancellation, deadline).await?;
            if probe.get("type").and_then(Value::as_str) != Some("success") {
                return Err(SessionError::Script);
            }
            if !self
                .session
                .state
                .lock()
                .await
                .navigating
                .contains_key(&self.context)
            {
                return identifier(&probe, "realm");
            }
        }
        Err(SessionError::DocumentChanged)
    }

    pub async fn evaluate_realm(
        &self,
        expression: &str,
        realm: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(Value, String), SessionError> {
        // Reuse the existing SDK's lexical function/expression classification.
        // This only parses source; native operations still use BiDi directly.
        use crate::internal::browser::vendor::chromiumoxide::js::Evaluation;
        let (method, mut params) = match Evaluation::from(expression) {
            Evaluation::Expression(params) => {
                ("script.evaluate", json!({"expression":params.expression}))
            }
            Evaluation::Function(params) => (
                "script.callFunction",
                json!({"functionDeclaration":params.function_declaration,"arguments":[]}),
            ),
        };
        let parameters = params.as_object_mut().ok_or(SessionError::Serialization)?;
        parameters.insert("target".into(), json!({"realm":realm}));
        parameters.insert("awaitPromise".into(), Value::Bool(true));
        parameters.insert(
            "serializationOptions".into(),
            json!({"maxObjectDepth":32,"maxDomDepth":0}),
        );
        parameters.insert("resultOwnership".into(), json!("none"));
        let result = self.command(method, params, cancellation, deadline).await?;
        if result.get("type").and_then(Value::as_str) != Some("success") {
            return Err(SessionError::Script);
        }
        let reported = identifier(&result, "realm")?;
        if reported != realm {
            return Err(SessionError::DocumentChanged);
        }
        let value = remote_json(result.get("result").ok_or(SessionError::Serialization)?, 0)?;
        Ok((value, reported))
    }

    pub async fn close(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        self.command(
            "browsingContext.close",
            json!({"context":self.context}),
            cancellation,
            deadline,
        )
        .await?;
        self.session
            .state
            .lock()
            .await
            .contexts
            .remove(&self.context);
        Ok(())
    }
}

fn identifier(value: &Value, key: &str) -> Result<String, SessionError> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty() && id.len() <= 512)
        .map(str::to_owned)
        .ok_or(SessionError::Identity)
}

fn optional_identity(value: &Value, key: &str) -> Result<Option<String>, SessionError> {
    match value.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(_) => identifier(value, key).map(Some),
    }
}

pub(super) fn moli_realm_alias(context: &str, raw: &str) -> Result<String, SessionError> {
    let (prefix, suffix) = raw.rsplit_once(':').ok_or(SessionError::Context)?;
    if prefix != "moli-default" && prefix != context {
        return Err(SessionError::Context);
    }
    let (context_id, realm_id) = suffix.split_once('.').ok_or(SessionError::Context)?;
    if context_id.is_empty()
        || realm_id.is_empty()
        || !context_id.bytes().all(|byte| byte.is_ascii_digit())
        || !realm_id.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(SessionError::Context);
    }
    Ok(format!("{context}:{suffix}"))
}

/// BiDi remote values are tagged; object keys are strings or tagged strings.
pub(super) fn remote_json(value: &Value, depth: usize) -> Result<Value, SessionError> {
    if depth > 32 {
        return Err(SessionError::Serialization);
    }
    match value.get("type").and_then(Value::as_str) {
        Some("null" | "undefined") => Ok(Value::Null),
        Some("string") if value.get("value").is_some_and(Value::is_string) => value
            .get("value")
            .cloned()
            .ok_or(SessionError::Serialization),
        Some("boolean") if value.get("value").is_some_and(Value::is_boolean) => value
            .get("value")
            .cloned()
            .ok_or(SessionError::Serialization),
        Some("number") if value.get("value").is_some_and(Value::is_number) => value
            .get("value")
            .cloned()
            .ok_or(SessionError::Serialization),
        Some("array") => value
            .get("value")
            .and_then(Value::as_array)
            .ok_or(SessionError::Serialization)?
            .iter()
            .map(|value| remote_json(value, depth.saturating_add(1)))
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array),
        Some("object") => {
            let entries = value
                .get("value")
                .and_then(Value::as_array)
                .ok_or(SessionError::Serialization)?;
            let mut object = serde_json::Map::new();
            for entry in entries {
                let pair = entry
                    .as_array()
                    .filter(|pair| pair.len() == 2)
                    .ok_or(SessionError::Serialization)?;
                let key = pair.first().ok_or(SessionError::Serialization)?;
                let key = match key.as_str() {
                    Some(key) => key.to_owned(),
                    None => remote_json(key, depth.saturating_add(1))?
                        .as_str()
                        .ok_or(SessionError::Serialization)?
                        .to_owned(),
                };
                let value = remote_json(
                    pair.get(1).ok_or(SessionError::Serialization)?,
                    depth.saturating_add(1),
                )?;
                if object.insert(key, value).is_some() {
                    return Err(SessionError::Serialization);
                }
            }
            Ok(Value::Object(object))
        }
        _ => Err(SessionError::Serialization),
    }
}
