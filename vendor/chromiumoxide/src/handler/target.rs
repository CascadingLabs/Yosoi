use std::collections::{HashMap, VecDeque};
use std::pin::Pin;
use std::sync::Arc;
use std::time::Instant;

use chromiumoxide_cdp::cdp::browser_protocol::target::DetachFromTargetParams;
use futures::channel::oneshot::Sender;
use futures::stream::Stream;
use futures::task::{Context, Poll};

use chromiumoxide_cdp::cdp::CdpEventMessage;
use chromiumoxide_cdp::cdp::browser_protocol::page::{FrameId, GetFrameTreeParams};
use chromiumoxide_cdp::cdp::browser_protocol::{
    browser::BrowserContextId,
    log as cdplog, performance,
    target::{
        AttachToTargetParams, FilterEntry, SessionId, SetAutoAttachParams, TargetFilter, TargetId,
        TargetInfo,
    },
};
use chromiumoxide_cdp::cdp::events::CdpEvent;
use chromiumoxide_types::{Command, Method, Request, Response};

use crate::auth::Credentials;
use crate::browser::CdpMode;
use crate::cdp::browser_protocol::target::CloseTargetParams;
use crate::cmd::CommandChain;
use crate::cmd::CommandMessage;
use crate::error::{CdpError, Result};
use crate::handler::browser::BrowserContext;
use crate::handler::domworld::DOMWorldKind;
use crate::handler::emulation::EmulationManager;
use crate::handler::frame::{
    FrameEvent, FrameManager, NavigationError, NavigationId, NavigationOk,
};
use crate::handler::frame::{FrameNavigationRequest, UTILITY_WORLD_NAME};
use crate::handler::network::{NetworkEvent, NetworkManager};
use crate::handler::page::PageHandle;
use crate::handler::viewport::Viewport;
use crate::handler::{PageInner, REQUEST_TIMEOUT};
use crate::listeners::{EventListenerRequest, EventListeners};
use crate::{ArcHttpRequest, page::Page};
use chromiumoxide_cdp::cdp::js_protocol::runtime::{
    ExecutionContextId, RunIfWaitingForDebuggerParams,
};
use std::time::Duration;

macro_rules! advance_state {
    ($s:ident, $cx:ident, $now:ident, $cmds: ident, $next_state:expr ) => {{
        if let Poll::Ready(poll) = $cmds.poll($now) {
            return match poll {
                None => {
                    $s.init_state = $next_state;
                    $s.poll($cx, $now)
                }
                Some(Ok((method, params))) => Some(TargetEvent::Request(Request {
                    method,
                    session_id: $s.session_id.clone().map(Into::into),
                    params,
                })),
                Some(Err(_)) => Some($s.on_initialization_failed()),
            };
        } else {
            return None;
        }
    }};
}

#[derive(Debug)]
pub struct Target {
    /// Info about this target as returned from the chromium instance
    info: TargetInfo,
    /// The type of this target
    r#type: TargetType,
    /// Configs for this target
    config: TargetConfig,
    /// The context this target is running in
    browser_context: BrowserContext,
    /// The frame manager that maintains the state of all frames and handles
    /// navigations of frames
    frame_manager: FrameManager,
    /// Handles all the https
    network_manager: NetworkManager,
    emulation_manager: EmulationManager,
    /// The identifier of the session this target is attached to
    session_id: Option<SessionId>,
    /// Normal-mode iframe target sessions owned by this page target.
    frame_sessions: HashMap<SessionId, FrameSessionState>,
    /// The handle of the browser page of this target
    page: Option<PageHandle>,
    /// Drives this target towards initialization
    init_state: TargetInit,
    /// Currently queued events to report to the `Handler`
    queued_events: VecDeque<TargetEvent>,
    /// All registered event subscriptions
    event_listeners: EventListeners,
    /// Senders that need to be notified once the main frame has loaded
    wait_for_frame_navigation: Vec<Sender<ArcHttpRequest>>,
    /// The sender who requested the page.
    initiator: Option<Sender<Result<Page>>>,
    /// Callers waiting for an attached target to finish provider initialization.
    page_waiters: Vec<Sender<Result<Page>>>,
    /// Sticky renderer-crash state, retained if the page handle is created later.
    renderer_crashed: bool,
}

#[derive(Debug)]
struct FrameSessionState {
    parent_session_id: SessionId,
    parent_frame_id: Option<FrameId>,
    initialization: Option<CommandChain>,
    waiting_for_debugger: bool,
}

impl Target {
    /// Create a new target instance with `TargetInfo` after a
    /// `CreateTargetParams` request.
    pub fn new(info: TargetInfo, config: TargetConfig, browser_context: BrowserContext) -> Self {
        let ty = TargetType::new(&info.r#type);
        let request_timeout = config.request_timeout;
        let mut network_manager = NetworkManager::new(config.ignore_https_errors, request_timeout);

        // Both of these queue Network.* CDP commands. In minimal mode the Network
        // domain is never enabled, so issuing them would both fail and re-add the
        // automation tell the mode exists to avoid.
        if !config.cdp_mode.is_minimal() {
            network_manager.set_cache_enabled(config.cache_enabled);
            network_manager.set_request_interception(config.request_intercept);
        }

        Self {
            info,
            r#type: ty,
            config,
            frame_manager: FrameManager::new(request_timeout),
            network_manager,
            emulation_manager: EmulationManager::new(request_timeout),
            session_id: None,
            frame_sessions: HashMap::new(),
            page: None,
            init_state: TargetInit::AttachToTarget,
            wait_for_frame_navigation: Default::default(),
            queued_events: Default::default(),
            event_listeners: Default::default(),
            initiator: None,
            page_waiters: Vec::new(),
            renderer_crashed: false,
            browser_context,
        }
    }

    pub fn set_session_id(&mut self, id: SessionId) {
        self.frame_manager.set_main_session_id(id.clone());
        self.session_id = Some(id)
    }

    pub fn session_id(&self) -> Option<&SessionId> {
        self.session_id.as_ref()
    }

    pub fn browser_context(&self) -> &BrowserContext {
        &self.browser_context
    }

    pub fn session_id_mut(&mut self) -> &mut Option<SessionId> {
        &mut self.session_id
    }

    pub fn detach_session(&mut self, session_id: &SessionId) {
        if self.session_id.as_ref() == Some(session_id) {
            self.session_id = None;
        }
        self.detach_frame_session(session_id);
    }

    pub fn detach_frame_session(&mut self, session_id: &SessionId) {
        self.frame_sessions.remove(session_id);
        self.frame_manager.detach_session(session_id);
    }

    /// The identifier for this target
    pub fn target_id(&self) -> &TargetId {
        &self.info.target_id
    }

    /// The type of this target
    pub fn r#type(&self) -> &TargetType {
        &self.r#type
    }

    /// Whether this target is already initialized
    pub fn is_initialized(&self) -> bool {
        matches!(self.init_state, TargetInit::Initialized)
    }

    /// Navigate a frame
    pub fn goto(&mut self, req: FrameNavigationRequest) {
        self.frame_manager.goto(req)
    }

    fn create_page(&mut self) {
        if self.page.is_none() {
            if let Some(session) = self.session_id.clone() {
                let handle =
                    PageHandle::new(self.target_id().clone(), session, self.opener_id().cloned());
                if self.renderer_crashed {
                    handle.mark_renderer_crashed();
                }
                self.page = Some(handle);
            }
        }
    }

    /// Mark this target as crashed only when the browser-scoped event names
    /// this owned target. Target and session identifiers remain internal.
    pub(crate) fn on_target_crashed(&mut self, target_id: &TargetId) {
        if !self.is_page() || self.target_id() != target_id || self.renderer_crashed {
            return;
        }
        self.renderer_crashed = true;
        if let Some(page) = &self.page {
            page.mark_renderer_crashed();
        }
    }

    /// Tries to create the `PageInner` if this target is already initialized
    pub(crate) fn get_or_create_page(&mut self) -> Option<&Arc<PageInner>> {
        self.create_page();
        self.page.as_ref().map(|p| p.inner())
    }

    pub fn is_page(&self) -> bool {
        self.r#type().is_page()
    }

    pub fn browser_context_id(&self) -> Option<&BrowserContextId> {
        self.info.browser_context_id.as_ref()
    }

    pub fn info(&self) -> &TargetInfo {
        &self.info
    }

    /// Get the target that opened this target. Top-level targets return `None`.
    pub fn opener_id(&self) -> Option<&TargetId> {
        self.info.opener_id.as_ref()
    }

    pub fn frame_manager(&self) -> &FrameManager {
        &self.frame_manager
    }

    pub fn frame_manager_mut(&mut self) -> &mut FrameManager {
        &mut self.frame_manager
    }

    pub fn event_listeners_mut(&mut self) -> &mut EventListeners {
        &mut self.event_listeners
    }

    /// Received a response to a command issued by this target
    pub fn on_response(&mut self, resp: Response, method: &str, session_id: Option<&SessionId>) {
        if session_id == self.session_id.as_ref() {
            if let Some(cmds) = self.init_state.commands_mut() {
                cmds.received_response(method);
            }
        } else if let Some(session_id) = session_id
            && let Some(frame_session) = self.frame_sessions.get_mut(session_id)
            && let Some(cmds) = frame_session.initialization.as_mut()
        {
            cmds.received_response(method);
        }
        #[allow(clippy::single_match)] // allow for now
        match method {
            GetFrameTreeParams::IDENTIFIER => {
                if let Some(resp) = resp
                    .result
                    .and_then(|val| GetFrameTreeParams::response_from_value(val).ok())
                {
                    let mut frame_tree = resp.frame_tree;
                    if frame_tree.frame.parent_id.is_none()
                        && let Some(parent_frame_id) = session_id
                            .and_then(|id| self.frame_sessions.get(id))
                            .and_then(|session| session.parent_frame_id.clone())
                    {
                        frame_tree.frame.parent_id = Some(parent_frame_id);
                    }
                    if let Some(session_id) = session_id {
                        self.frame_manager
                            .on_frame_tree_in_session(frame_tree, session_id);
                    }
                }
            }
            // requests originated from the network manager all return an empty response, hence they
            // can be ignored here
            _ => {}
        }
    }

    pub fn on_event(&mut self, event: CdpEventMessage) {
        let source_session_id = event.session_id.clone().map(SessionId::from);
        let CdpEventMessage { params, method, .. } = event;
        match &params {
            // `FrameManager` events
            CdpEvent::PageFrameAttached(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager.on_frame_attached_in_session(
                        ev.frame_id.clone(),
                        Some(ev.parent_frame_id.clone()),
                        session_id,
                    );
                }
            }
            CdpEvent::PageFrameDetached(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_frame_detached_in_session(ev, session_id);
                }
            }
            CdpEvent::PageFrameNavigated(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    let mut frame = ev.frame.clone();
                    if frame.parent_id.is_none()
                        && self.session_id.as_ref() != Some(session_id)
                        && let Some(parent_frame_id) = self
                            .frame_sessions
                            .get(session_id)
                            .and_then(|session| session.parent_frame_id.clone())
                    {
                        frame.parent_id = Some(parent_frame_id);
                    }
                    self.frame_manager
                        .on_frame_navigated_in_session(&frame, session_id);
                }
            }
            CdpEvent::PageNavigatedWithinDocument(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_frame_navigated_within_document_in_session(ev, session_id);
                }
            }
            CdpEvent::RuntimeExecutionContextCreated(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_frame_execution_context_created_in_session(ev, session_id);
                }
            }
            CdpEvent::RuntimeExecutionContextDestroyed(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_frame_execution_context_destroyed_in_session(ev, session_id);
                }
            }
            CdpEvent::RuntimeExecutionContextsCleared(_) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_execution_contexts_cleared_in_session(session_id);
                }
            }
            CdpEvent::RuntimeBindingCalled(ev) => {
                // TODO check if binding registered and payload is json
                self.frame_manager.on_runtime_binding_called(ev)
            }
            CdpEvent::PageLifecycleEvent(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_page_lifecycle_event_in_session(ev, session_id);
                }
            }
            CdpEvent::PageFrameStartedLoading(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_frame_started_loading_in_session(ev, session_id);
                }
            }
            CdpEvent::PageFrameStoppedLoading(ev) => {
                if let Some(session_id) = source_session_id.as_ref() {
                    self.frame_manager
                        .on_frame_stopped_loading_in_session(ev, session_id);
                }
            }

            // `Target` events
            CdpEvent::TargetAttachedToTarget(ev) => {
                if ev.target_info.r#type == "iframe"
                    && !self.config.cdp_mode.is_minimal()
                    && let Some(parent_session_id) = source_session_id.as_ref()
                {
                    if !self.frame_sessions.contains_key(&ev.session_id) {
                        self.frame_sessions.insert(
                            ev.session_id.clone(),
                            FrameSessionState {
                                parent_session_id: parent_session_id.clone(),
                                parent_frame_id: ev.target_info.parent_frame_id.clone(),
                                initialization: Some(FrameManager::oopif_init_commands(
                                    self.config.request_timeout,
                                )),
                                waiting_for_debugger: ev.waiting_for_debugger,
                            },
                        );
                    }
                } else if ev.waiting_for_debugger {
                    let runtime_cmd = RunIfWaitingForDebuggerParams::default();

                    self.queued_events.push_back(TargetEvent::Request(Request {
                        method: runtime_cmd.identifier(),
                        session_id: Some(ev.session_id.clone().into()),
                        params: serde_json::to_value(runtime_cmd).unwrap(),
                    }));
                }

                if "service_worker" == &ev.target_info.r#type {
                    let detach_command = DetachFromTargetParams::builder()
                        .session_id(ev.session_id.clone())
                        .build();

                    self.queued_events.push_back(TargetEvent::Request(Request {
                        method: detach_command.identifier(),
                        session_id: self.session_id.clone().map(Into::into),
                        params: serde_json::to_value(detach_command).unwrap(),
                    }));
                }
            }

            // `NetworkManager` events
            CdpEvent::FetchRequestPaused(ev) => self.network_manager.on_fetch_request_paused(ev),
            CdpEvent::FetchAuthRequired(ev) => self.network_manager.on_fetch_auth_required(ev),
            CdpEvent::NetworkRequestWillBeSent(ev) => {
                self.network_manager.on_request_will_be_sent(ev)
            }
            CdpEvent::NetworkRequestServedFromCache(ev) => {
                self.network_manager.on_request_served_from_cache(ev)
            }
            CdpEvent::NetworkResponseReceived(ev) => self.network_manager.on_response_received(ev),
            CdpEvent::NetworkLoadingFinished(ev) => {
                self.network_manager.on_network_loading_finished(ev)
            }
            CdpEvent::NetworkLoadingFailed(ev) => {
                self.network_manager.on_network_loading_failed(ev)
            }
            _ => {}
        }
        chromiumoxide_cdp::consume_event!(match params {
           |ev| self.event_listeners.start_send(ev),
           |json| { let _ = self.event_listeners.try_send_custom(&method, json);}
        });
    }

    /// Called when a init command timed out
    fn on_initialization_failed(&mut self) -> TargetEvent {
        if let Some(initiator) = self.initiator.take() {
            let _ = initiator.send(Err(CdpError::Timeout));
        }
        self.init_state = TargetInit::Closing;
        let close_target = CloseTargetParams::new(self.info.target_id.clone());
        TargetEvent::Request(Request {
            method: close_target.identifier(),
            session_id: self.session_id.clone().map(Into::into),
            params: serde_json::to_value(close_target).unwrap(),
        })
    }

    /// Advance that target's state
    pub(crate) fn poll(&mut self, cx: &mut Context<'_>, now: Instant) -> Option<TargetEvent> {
        if !self.is_page() {
            // can only poll pages
            return None;
        }
        match &mut self.init_state {
            TargetInit::AttachToTarget => {
                self.init_state = TargetInit::InitializingFrame(FrameManager::init_commands(
                    self.config.request_timeout,
                    self.config.cdp_mode,
                ));
                let params = AttachToTargetParams::builder()
                    .target_id(self.target_id().clone())
                    .flatten(true)
                    .build()
                    .unwrap();

                return Some(TargetEvent::Request(Request::new(
                    params.identifier(),
                    serde_json::to_value(params).unwrap(),
                )));
            }
            TargetInit::InitializingFrame(cmds) => {
                self.session_id.as_ref()?;
                if let Poll::Ready(poll) = cmds.poll(now) {
                    return match poll {
                        None => {
                            // VoidCrawl minimal-stealth mode (CAS-217): skip the
                            // isolated-world `addScriptToEvaluateOnNewDocument` — a CDP
                            // tell. Trade-off: no `evaluate_function` (main-world
                            // `evaluate_expression` still works) in this mode.
                            if let Some(isolated_world_cmds) = (!self.config.cdp_mode.is_minimal())
                                .then(|| {
                                    self.frame_manager.ensure_isolated_world(UTILITY_WORLD_NAME)
                                })
                                .flatten()
                            {
                                *cmds = isolated_world_cmds;
                            } else {
                                self.init_state = TargetInit::InitializingNetwork(
                                    self.network_manager.init_commands(self.config.cdp_mode),
                                );
                            }
                            self.poll(cx, now)
                        }
                        Some(Ok((method, params))) => Some(TargetEvent::Request(Request {
                            method,
                            session_id: self.session_id.clone().map(Into::into),
                            params,
                        })),
                        Some(Err(_)) => Some(self.on_initialization_failed()),
                    };
                } else {
                    return None;
                }
            }
            TargetInit::InitializingNetwork(cmds) => {
                advance_state!(
                    self,
                    cx,
                    now,
                    cmds,
                    TargetInit::InitializingPage(Self::page_init_commands(
                        self.config.request_timeout,
                        self.config.cdp_mode
                    ))
                );
            }
            TargetInit::InitializingPage(cmds) => {
                advance_state!(
                    self,
                    cx,
                    now,
                    cmds,
                    match self.config.viewport.as_ref() {
                        Some(viewport) => TargetInit::InitializingEmulation(
                            self.emulation_manager.init_commands(viewport)
                        ),
                        None => TargetInit::Initialized,
                    }
                );
            }
            TargetInit::InitializingEmulation(cmds) => {
                advance_state!(self, cx, now, cmds, TargetInit::Initialized);
            }
            TargetInit::Initialized => {
                if !self.page_waiters.is_empty()
                    && let Some(page) = self.get_or_create_page().cloned().map(Page::from)
                {
                    for waiter in std::mem::take(&mut self.page_waiters) {
                        let _ = waiter.send(Ok(page.clone()));
                    }
                }
                if let Some(initiator) = self.initiator.take() {
                    // make sure that the main frame of the page has finished loading
                    if self
                        .frame_manager
                        .main_frame()
                        .map(|frame| frame.is_loaded())
                        .unwrap_or_default()
                    {
                        if let Some(page) = self.get_or_create_page() {
                            let _ = initiator.send(Ok(page.clone().into()));
                        } else {
                            self.initiator = Some(initiator);
                        }
                    } else {
                        self.initiator = Some(initiator);
                    }
                }
            }
            TargetInit::Closing => return None,
        };
        if let Some(event) = self.poll_frame_sessions(now) {
            return Some(event);
        }
        loop {
            if let Some(frame) = self.frame_manager.main_frame() {
                if frame.is_loaded() {
                    while let Some(tx) = self.wait_for_frame_navigation.pop() {
                        let _ = tx.send(frame.http_request().cloned());
                    }
                }
            }

            // Drain queued messages first.
            if let Some(ev) = self.queued_events.pop_front() {
                return Some(ev);
            }

            if let Some(handle) = self.page.as_mut() {
                while let Poll::Ready(Some(msg)) = Pin::new(&mut handle.rx).poll_next(cx) {
                    match msg {
                        TargetMessage::Command(cmd) => {
                            self.queued_events.push_back(TargetEvent::Command(cmd));
                        }
                        TargetMessage::FrameCommand {
                            frame_id,
                            expected_session,
                            mut command,
                        } => {
                            if let Some(session_id) =
                                self.frame_manager.session_for_frame(&frame_id).cloned()
                            {
                                if expected_session
                                    .as_ref()
                                    .is_some_and(|expected| expected != &session_id)
                                {
                                    let _ = command.sender.send(Err(CdpError::NotFound));
                                    continue;
                                }
                                command.session_id = Some(session_id);
                                if command.is_navigation()
                                    && let Some(params) = command.params.as_object_mut()
                                {
                                    params.entry("frameId").or_insert_with(|| {
                                        serde_json::Value::String(frame_id.into())
                                    });
                                }
                                self.queued_events.push_back(TargetEvent::Command(command));
                            } else {
                                let _ = command.sender.send(Err(CdpError::NotFound));
                            }
                        }
                        TargetMessage::FrameRawCommand {
                            frame_id,
                            expected_session,
                            mut command,
                        } => {
                            if let Some(session_id) =
                                self.frame_manager.session_for_frame(&frame_id).cloned()
                            {
                                if expected_session
                                    .as_ref()
                                    .is_some_and(|expected| expected != &session_id)
                                {
                                    let _ = command.sender.send(Err(CdpError::NotFound));
                                    continue;
                                }
                                command.session_id = Some(session_id);
                                if command.is_navigation()
                                    && let Some(params) = command.params.as_object_mut()
                                {
                                    params.entry("frameId").or_insert_with(|| {
                                        serde_json::Value::String(frame_id.into())
                                    });
                                }
                                self.queued_events
                                    .push_back(TargetEvent::RawCommand(command));
                            } else {
                                let _ = command.sender.send(Err(CdpError::NotFound));
                            }
                        }
                        TargetMessage::RawCommand(cmd) => {
                            self.queued_events.push_back(TargetEvent::RawCommand(cmd));
                        }
                        TargetMessage::MainFrame(tx) => {
                            let _ =
                                tx.send(self.frame_manager.main_frame().map(|f| f.id().clone()));
                        }
                        TargetMessage::AllFrames(tx) => {
                            let _ = tx.send(
                                self.frame_manager
                                    .frames()
                                    .map(|f| f.id().clone())
                                    .collect(),
                            );
                        }
                        TargetMessage::Url(req) => {
                            let GetUrl { frame_id, tx } = req;
                            let frame = if let Some(frame_id) = frame_id {
                                self.frame_manager.frame(&frame_id)
                            } else {
                                self.frame_manager.main_frame()
                            };
                            let _ = tx.send(frame.and_then(|f| f.url().map(str::to_string)));
                        }
                        TargetMessage::Name(req) => {
                            let GetName { frame_id, tx } = req;
                            let frame = if let Some(frame_id) = frame_id {
                                self.frame_manager.frame(&frame_id)
                            } else {
                                self.frame_manager.main_frame()
                            };
                            let _ = tx.send(frame.and_then(|f| f.name().map(str::to_string)));
                        }
                        TargetMessage::Parent(req) => {
                            let GetParent { frame_id, tx } = req;
                            let frame = self.frame_manager.frame(&frame_id);
                            let _ = tx.send(frame.and_then(|f| f.parent_id().cloned()));
                        }
                        TargetMessage::WaitForNavigation(tx) => {
                            if let Some(frame) = self.frame_manager.main_frame() {
                                // TODO submit a navigation watcher: waitForFrameNavigation

                                // TODO return the watchers navigationResponse
                                if frame.is_loaded() {
                                    let _ = tx.send(frame.http_request().cloned());
                                } else {
                                    self.wait_for_frame_navigation.push(tx);
                                }
                            } else {
                                self.wait_for_frame_navigation.push(tx);
                            }
                        }
                        TargetMessage::AddEventListener(req) => {
                            // register a new listener
                            self.event_listeners.add_listener(req);
                        }
                        TargetMessage::GetExecutionContext(ctx) => {
                            let GetExecutionContext {
                                dom_world,
                                frame_id,
                                tx,
                            } = ctx;
                            let frame_id = frame_id.or_else(|| {
                                self.frame_manager
                                    .main_frame()
                                    .map(|frame| frame.id().clone())
                            });
                            let context = frame_id.as_ref().and_then(|frame_id| {
                                self.frame_manager
                                    .frame_execution_context_for_session(frame_id, dom_world)
                            });
                            let _ = tx.send(context);
                        }
                        TargetMessage::GetFrameSession { frame_id, tx } => {
                            let session_id =
                                self.frame_manager.session_for_frame(&frame_id).cloned();
                            let _ = tx.send(session_id);
                        }
                        TargetMessage::GetFrameIsSessionRoot { frame_id, tx } => {
                            let is_root = self.frame_manager.frame_is_session_root(&frame_id);
                            let _ = tx.send(is_root);
                        }
                        TargetMessage::Authenticate(credentials) => {
                            self.network_manager.authenticate(credentials);
                        }
                    }
                }
            }

            while let Some(event) = self.network_manager.poll() {
                match event {
                    NetworkEvent::SendCdpRequest((method, params)) => {
                        // send a message to the browser
                        self.queued_events.push_back(TargetEvent::Request(Request {
                            method,
                            session_id: self.session_id.clone().map(Into::into),
                            params,
                        }))
                    }
                    NetworkEvent::Request(_) => {}
                    NetworkEvent::Response(_) => {}
                    NetworkEvent::RequestFailed(request) => {
                        self.frame_manager.on_http_request_finished(request);
                    }
                    NetworkEvent::RequestFinished(request) => {
                        self.frame_manager.on_http_request_finished(request);
                    }
                }
            }

            while let Some(event) = self.frame_manager.poll(now) {
                match event {
                    FrameEvent::NavigationResult(res) => {
                        self.queued_events
                            .push_back(TargetEvent::NavigationResult(res));
                    }
                    FrameEvent::NavigationRequest(id, req) => {
                        self.queued_events
                            .push_back(TargetEvent::NavigationRequest(id, req));
                    }
                }
            }

            if self.queued_events.is_empty() {
                return None;
            }
        }
    }

    fn poll_frame_sessions(&mut self, now: Instant) -> Option<TargetEvent> {
        let session_ids = self.frame_sessions.keys().cloned().collect::<Vec<_>>();
        for session_id in session_ids {
            let Some(frame_session) = self.frame_sessions.get_mut(&session_id) else {
                continue;
            };
            let Some(initialization) = frame_session.initialization.as_mut() else {
                continue;
            };
            match initialization.poll(now) {
                Poll::Pending => {}
                Poll::Ready(Some(Ok((method, params)))) => {
                    return Some(TargetEvent::Request(Request {
                        method,
                        session_id: Some(session_id.into()),
                        params,
                    }));
                }
                Poll::Ready(Some(Err(_))) => {
                    let Some(frame_session) = self.frame_sessions.remove(&session_id) else {
                        return None;
                    };
                    self.frame_manager.detach_session(&session_id);
                    let detach = DetachFromTargetParams::builder()
                        .session_id(session_id.clone())
                        .build();
                    return Some(TargetEvent::Request(Request {
                        method: detach.identifier(),
                        session_id: Some(frame_session.parent_session_id.into()),
                        params: serde_json::json!({ "sessionId": session_id }),
                    }));
                }
                Poll::Ready(None) => {
                    frame_session.initialization = None;
                    if frame_session.waiting_for_debugger {
                        frame_session.waiting_for_debugger = false;
                        let runtime_cmd = RunIfWaitingForDebuggerParams::default();
                        return Some(TargetEvent::Request(Request {
                            method: runtime_cmd.identifier(),
                            session_id: Some(session_id.into()),
                            params: serde_json::json!({}),
                        }));
                    }
                }
            }
        }
        None
    }

    /// Set the sender half of the channel who requested the creation of this
    /// target
    pub fn set_initiator(&mut self, tx: Sender<Result<Page>>) {
        self.initiator = Some(tx);
    }

    pub fn add_page_waiter(&mut self, tx: Sender<Result<Page>>) {
        self.page_waiters.push(tx);
    }

    pub(crate) fn page_init_commands(timeout: Duration, cdp_mode: CdpMode) -> CommandChain {
        // VoidCrawl minimal-stealth mode (CAS-217): a clean CDP browser (nodriver)
        // auto-passes Cloudflare's Managed Challenge because it enables almost no CDP
        // domains. `Target.setAutoAttach(waitForDebuggerOnStart)`, `Performance.enable`,
        // and `Log.enable` are all eager-instrumentation tells. Skip the whole page-init
        // chain in minimal mode (we lose child-target/OOPIF auto-attach, which is fine —
        // cross-origin frame eval is already off in this mode since it needs Runtime).
        if cdp_mode.is_minimal() {
            return CommandChain::new(vec![], timeout);
        }
        let attach = SetAutoAttachParams::builder()
            .flatten(true)
            .auto_attach(true)
            .wait_for_debugger_on_start(true)
            // Service workers are not controlled by this page. Attaching with
            // waitForDebuggerOnStart and immediately detaching races worker
            // startup and can leave registration waiting indefinitely. Keep
            // them running natively while retaining OOPIF/other child targets.
            .filter(TargetFilter::new(vec![
                FilterEntry {
                    exclude: Some(true),
                    r#type: Some("service_worker".into()),
                },
                FilterEntry {
                    exclude: None,
                    r#type: None,
                },
            ]))
            .build()
            .unwrap();
        let enable_performance = performance::EnableParams::default();
        let enable_log = cdplog::EnableParams::default();
        CommandChain::new(
            vec![
                (attach.identifier(), serde_json::to_value(attach).unwrap()),
                (
                    enable_performance.identifier(),
                    serde_json::to_value(enable_performance).unwrap(),
                ),
                (
                    enable_log.identifier(),
                    serde_json::to_value(enable_log).unwrap(),
                ),
            ],
            timeout,
        )
    }
}

impl Drop for Target {
    fn drop(&mut self) {
        if let Some(page) = &self.page {
            page.mark_target_closed();
        }
    }
}

#[derive(Debug, Clone)]
pub struct TargetConfig {
    pub ignore_https_errors: bool,
    ///  Request timeout to use
    pub request_timeout: Duration,
    pub viewport: Option<Viewport>,
    pub request_intercept: bool,
    pub cache_enabled: bool,
    /// VoidCrawl fork: select normal vs anti-bot-safe minimal CDP initialization.
    pub cdp_mode: CdpMode,
}

impl Default for TargetConfig {
    fn default() -> Self {
        Self {
            ignore_https_errors: true,
            request_timeout: Duration::from_secs(REQUEST_TIMEOUT),
            viewport: Default::default(),
            request_intercept: false,
            cache_enabled: true,
            cdp_mode: CdpMode::from_env_default(),
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum TargetType {
    Page,
    BackgroundPage,
    ServiceWorker,
    SharedWorker,
    Other,
    Browser,
    Webview,
    Unknown(String),
}

impl TargetType {
    pub fn new(ty: &str) -> Self {
        match ty {
            "page" => TargetType::Page,
            "background_page" => TargetType::BackgroundPage,
            "service_worker" => TargetType::ServiceWorker,
            "shared_worker" => TargetType::SharedWorker,
            "other" => TargetType::Other,
            "browser" => TargetType::Browser,
            "webview" => TargetType::Webview,
            s => TargetType::Unknown(s.to_string()),
        }
    }

    pub fn is_page(&self) -> bool {
        matches!(self, TargetType::Page)
    }

    pub fn is_background_page(&self) -> bool {
        matches!(self, TargetType::BackgroundPage)
    }

    pub fn is_service_worker(&self) -> bool {
        matches!(self, TargetType::ServiceWorker)
    }

    pub fn is_shared_worker(&self) -> bool {
        matches!(self, TargetType::SharedWorker)
    }

    pub fn is_other(&self) -> bool {
        matches!(self, TargetType::Other)
    }

    pub fn is_browser(&self) -> bool {
        matches!(self, TargetType::Browser)
    }

    pub fn is_webview(&self) -> bool {
        matches!(self, TargetType::Webview)
    }
}

#[derive(Debug)]
pub(crate) enum TargetEvent {
    /// An internal request
    Request(Request),
    /// An internal navigation request
    NavigationRequest(NavigationId, Request),
    /// Indicates that a previous requested navigation has finished
    NavigationResult(Result<NavigationOk, NavigationError>),
    /// A new command arrived via a channel
    Command(CommandMessage),
    /// A command that must not be routed through navigation tracking.
    RawCommand(CommandMessage),
}

// TODO this can be moved into the classes?
#[derive(Debug)]
pub enum TargetInit {
    InitializingFrame(CommandChain),
    InitializingNetwork(CommandChain),
    InitializingPage(CommandChain),
    InitializingEmulation(CommandChain),
    AttachToTarget,
    Initialized,
    Closing,
}

impl TargetInit {
    fn commands_mut(&mut self) -> Option<&mut CommandChain> {
        match self {
            TargetInit::InitializingFrame(cmd) => Some(cmd),
            TargetInit::InitializingNetwork(cmd) => Some(cmd),
            TargetInit::InitializingPage(cmd) => Some(cmd),
            TargetInit::InitializingEmulation(cmd) => Some(cmd),
            TargetInit::AttachToTarget => None,
            TargetInit::Initialized => None,
            TargetInit::Closing => None,
        }
    }
}

#[derive(Debug)]
pub struct GetExecutionContext {
    /// For which world the execution context was requested
    pub dom_world: DOMWorldKind,
    /// The if of the frame to get the `ExecutionContext` for
    pub frame_id: Option<FrameId>,
    /// Sender half of the channel to send the response back
    pub tx: Sender<Option<(ExecutionContextId, SessionId)>>,
}

impl GetExecutionContext {
    pub fn new(tx: Sender<Option<(ExecutionContextId, SessionId)>>) -> Self {
        Self {
            dom_world: DOMWorldKind::Main,
            frame_id: None,
            tx,
        }
    }
}

#[derive(Debug)]
pub struct GetUrl {
    /// The id of the frame to get the url for (None = main frame)
    pub frame_id: Option<FrameId>,
    /// Sender half of the channel to send the response back
    pub tx: Sender<Option<String>>,
}

impl GetUrl {
    pub fn new(tx: Sender<Option<String>>) -> Self {
        Self { frame_id: None, tx }
    }
}

#[derive(Debug)]
pub struct GetName {
    /// The id of the frame to get the name for (None = main frame)
    pub frame_id: Option<FrameId>,
    /// Sender half of the channel to send the response back
    pub tx: Sender<Option<String>>,
}

#[derive(Debug)]
pub struct GetParent {
    /// The id of the frame to get the parent for (None = main frame)
    pub frame_id: FrameId,
    /// Sender half of the channel to send the response back
    pub tx: Sender<Option<FrameId>>,
}

#[derive(Debug)]
pub enum TargetMessage {
    /// Execute a command within the session of this target
    Command(CommandMessage),
    /// Execute a command in the session currently owning a frame.
    FrameCommand {
        frame_id: FrameId,
        expected_session: Option<SessionId>,
        command: CommandMessage,
    },
    /// Execute a frame command without navigation lifecycle tracking.
    FrameRawCommand {
        frame_id: FrameId,
        expected_session: Option<SessionId>,
        command: CommandMessage,
    },
    /// Execute a command without Chromiumoxide navigation tracking.
    RawCommand(CommandMessage),
    /// Return the main frame of this target's page
    MainFrame(Sender<Option<FrameId>>),
    /// Return all the frames of this target's page
    AllFrames(Sender<Vec<FrameId>>),
    /// Return the url if available
    Url(GetUrl),
    /// Return the name if available
    Name(GetName),
    /// Return the parent id of a frame
    Parent(GetParent),
    /// A Message that resolves when the frame finished loading a new url
    WaitForNavigation(Sender<ArcHttpRequest>),
    /// A request to submit a new listener that gets notified with every
    /// received event
    AddEventListener(EventListenerRequest),
    /// Get the `ExecutionContext` if available
    GetExecutionContext(GetExecutionContext),
    /// Return the session currently responsible for a frame.
    GetFrameSession {
        frame_id: FrameId,
        tx: Sender<Option<SessionId>>,
    },
    /// Return whether a frame is the root of its current flat session.
    GetFrameIsSessionRoot {
        frame_id: FrameId,
        tx: Sender<Option<bool>>,
    },
    Authenticate(Credentials),
}

#[cfg(test)]
#[allow(clippy::expect_used)]
mod renderer_crash_tests {
    use super::*;
    use chromiumoxide_cdp::cdp::browser_protocol::target::EventTargetCrashed;
    use tokio::time::{Duration, timeout};

    fn page_target(target_id: TargetId) -> Target {
        Target::new(
            TargetInfo {
                target_id,
                r#type: "page".to_string(),
                title: String::new(),
                url: "about:blank".to_string(),
                attached: false,
                parent_id: None,
                opener_id: None,
                can_access_opener: false,
                opener_frame_id: None,
                parent_frame_id: None,
                browser_context_id: None,
                subtype: None,
                embedder_data: None,
            },
            TargetConfig::default(),
            Default::default(),
        )
    }

    #[tokio::test]
    async fn crash_is_correlated_sticky_and_idempotent_for_owned_page() {
        let target_id = TargetId::new("owned-page");
        let mut target = page_target(target_id.clone());
        target.set_session_id(SessionId::new("owned-session"));
        target.create_page();
        let page = Page::from(
            target
                .get_or_create_page()
                .cloned()
                .expect("initialized page handle"),
        );

        let wrong_target = EventTargetCrashed {
            target_id: TargetId::new("different-page"),
            status: "crashed".to_string(),
            error_code: 1,
        };
        target.on_target_crashed(&wrong_target.target_id);
        assert!(!page.is_renderer_crashed());

        let event = EventTargetCrashed {
            target_id: target_id.clone(),
            status: "crashed".to_string(),
            error_code: 1,
        };
        let waiting_page = page.clone();
        let waiter = tokio::spawn(async move { waiting_page.wait_for_renderer_crash().await });
        target.on_target_crashed(&event.target_id);
        target.on_target_crashed(&event.target_id);

        timeout(Duration::from_millis(100), waiter)
            .await
            .expect("owned page crash wakes listener")
            .expect("crash listener task");
        assert!(page.is_renderer_crashed());
        timeout(Duration::from_millis(100), page.wait_for_renderer_crash())
            .await
            .expect("late listener observes sticky crash");
    }
}
