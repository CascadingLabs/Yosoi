use std::collections::VecDeque;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::map::Entry;

use chromiumoxide_cdp::cdp::browser_protocol::network::LoaderId;
use chromiumoxide_cdp::cdp::browser_protocol::page::{
    AddScriptToEvaluateOnNewDocumentParams, CreateIsolatedWorldParams, EventFrameDetached,
    EventFrameStartedLoading, EventFrameStoppedLoading, EventLifecycleEvent,
    EventNavigatedWithinDocument, Frame as CdpFrame, FrameDetachedReason, FrameTree,
};
use chromiumoxide_cdp::cdp::browser_protocol::target::{
    FilterEntry, SessionId, SetAutoAttachParams, TargetFilter,
};
use chromiumoxide_cdp::cdp::js_protocol::runtime::*;
use chromiumoxide_cdp::cdp::{
    browser_protocol::page::{self, FrameId},
    js_protocol::runtime,
};
use chromiumoxide_types::{Method, MethodId, Request};

use crate::browser::CdpMode;
use crate::error::DeadlineExceeded;
use crate::handler::REQUEST_TIMEOUT;
use crate::handler::domworld::{DOMWorld, DOMWorldKind};
use crate::handler::http::HttpRequest;
use crate::{ArcHttpRequest, cmd::CommandChain};

pub const UTILITY_WORLD_NAME: &str = "__chromiumoxide_utility_world__";
const EVALUATION_SCRIPT_URL: &str = "____chromiumoxide_utility_world___evaluation_script__";

/// Represents a frame on the page
#[derive(Debug)]
pub struct Frame {
    parent_frame: Option<FrameId>,
    /// Cdp identifier of this frame
    id: FrameId,
    /// Flat CDP session currently responsible for this frame.
    session_id: Option<SessionId>,
    /// The previous renderer swapped out and a replacement OOPIF session has
    /// not supplied its frame tree yet.
    migration_from_session: Option<SessionId>,
    main_world: DOMWorld,
    secondary_world: DOMWorld,
    loader_id: Option<LoaderId>,
    /// Current url of this frame
    url: Option<String>,
    /// The http request that loaded this with this frame
    http_request: ArcHttpRequest,
    /// The frames contained in this frame
    child_frames: HashSet<FrameId>,
    name: Option<String>,
    /// The received lifecycle events
    lifecycle_events: HashSet<MethodId>,
}

impl Frame {
    pub fn new(id: FrameId) -> Self {
        Self {
            parent_frame: None,
            id,
            session_id: None,
            migration_from_session: None,
            main_world: Default::default(),
            secondary_world: Default::default(),
            loader_id: None,
            url: None,
            http_request: None,
            child_frames: Default::default(),
            name: None,
            lifecycle_events: Default::default(),
        }
    }

    pub fn with_parent(id: FrameId, parent: &mut Frame) -> Self {
        parent.child_frames.insert(id.clone());
        Self {
            parent_frame: Some(parent.id.clone()),
            id,
            session_id: None,
            migration_from_session: None,
            main_world: Default::default(),
            secondary_world: Default::default(),
            loader_id: None,
            url: None,
            http_request: None,
            child_frames: Default::default(),
            name: None,
            lifecycle_events: Default::default(),
        }
    }

    pub fn parent_id(&self) -> Option<&FrameId> {
        self.parent_frame.as_ref()
    }

    pub fn session_id(&self) -> Option<&SessionId> {
        self.session_id.as_ref()
    }

    pub fn id(&self) -> &FrameId {
        &self.id
    }

    pub fn url(&self) -> Option<&str> {
        self.url.as_deref()
    }

    pub fn name(&self) -> Option<&str> {
        self.name.as_deref()
    }

    pub fn main_world(&self) -> &DOMWorld {
        &self.main_world
    }

    pub fn secondary_world(&self) -> &DOMWorld {
        &self.secondary_world
    }

    pub fn lifecycle_events(&self) -> &HashSet<MethodId> {
        &self.lifecycle_events
    }

    pub fn http_request(&self) -> Option<&Arc<HttpRequest>> {
        self.http_request.as_ref()
    }

    fn navigated(&mut self, frame: &CdpFrame) {
        self.name.clone_from(&frame.name);
        let url = if let Some(ref fragment) = frame.url_fragment {
            format!("{}{fragment}", frame.url)
        } else {
            frame.url.clone()
        };
        self.url = Some(url);
    }

    fn navigated_within_url(&mut self, url: String) {
        self.url = Some(url)
    }

    fn on_loading_stopped(&mut self) {
        self.lifecycle_events.insert("DOMContentLoaded".into());
        self.lifecycle_events.insert("load".into());
    }

    fn on_loading_started(&mut self) {
        self.lifecycle_events.clear();
        self.http_request.take();
    }

    pub fn is_loaded(&self) -> bool {
        self.lifecycle_events.contains("load")
    }

    pub fn clear_contexts(&mut self) {
        self.main_world.take_context();
        self.secondary_world.take_context();
    }

    pub fn destroy_context(&mut self, ctx_unique_id: &str) {
        if self.main_world.execution_context_unique_id() == Some(ctx_unique_id) {
            self.main_world.take_context();
        } else if self.secondary_world.execution_context_unique_id() == Some(ctx_unique_id) {
            self.secondary_world.take_context();
        }
    }

    pub fn execution_context(&self) -> Option<ExecutionContextId> {
        self.main_world.execution_context()
    }

    pub fn set_request(&mut self, request: HttpRequest) {
        self.http_request = Some(Arc::new(request))
    }
}

impl From<CdpFrame> for Frame {
    fn from(frame: CdpFrame) -> Self {
        Self {
            parent_frame: frame.parent_id,
            id: frame.id,
            session_id: None,
            migration_from_session: None,
            main_world: Default::default(),
            secondary_world: Default::default(),
            loader_id: Some(frame.loader_id),
            url: Some(frame.url),
            http_request: None,
            child_frames: Default::default(),
            name: frame.name,
            lifecycle_events: Default::default(),
        }
    }
}

/// Maintains the state of the pages frame and listens to events produced by
/// chromium targeting the `Target`. Also listens for events that indicate that
/// a navigation was completed
#[derive(Debug)]
pub struct FrameManager {
    main_frame: Option<FrameId>,
    frames: HashMap<FrameId, Frame>,
    /// The session used for the page target's main frame.
    main_session_id: Option<SessionId>,
    /// Context ids are scoped to a flat session.
    context_ids: HashMap<(SessionId, String), FrameId>,
    isolated_worlds: HashSet<String>,
    /// Timeout after which an anticipated event (related to navigation) doesn't
    /// arrive results in an error
    request_timeout: Duration,
    /// Track currently in progress navigation
    pending_navigations: VecDeque<(FrameNavigationRequest, NavigationWatcher)>,
    /// The currently ongoing navigation
    navigation: Option<(NavigationWatcher, Instant)>,
}

impl FrameManager {
    pub fn new(request_timeout: Duration) -> Self {
        FrameManager {
            main_frame: None,
            frames: Default::default(),
            main_session_id: None,
            context_ids: Default::default(),
            isolated_worlds: Default::default(),
            request_timeout,
            pending_navigations: Default::default(),
            navigation: None,
        }
    }

    /// The commands to execute in order to initialize this frame manager
    pub fn init_commands(timeout: Duration, cdp_mode: CdpMode) -> CommandChain {
        CommandChain::new(Self::init_command_pairs(cdp_mode), timeout)
    }

    /// Initialize an out-of-process frame session before resuming its renderer.
    /// Network is deliberately omitted; frame operations use Page and Runtime.
    pub fn oopif_init_commands(timeout: Duration) -> CommandChain {
        let mut cmds = Self::init_command_pairs(CdpMode::Normal);
        let filter = TargetFilter::new(vec![
            FilterEntry {
                exclude: None,
                r#type: Some("iframe".to_owned()),
            },
            FilterEntry {
                exclude: Some(true),
                r#type: None,
            },
        ]);
        let attach = SetAutoAttachParams {
            auto_attach: true,
            wait_for_debugger_on_start: true,
            flatten: Some(true),
            filter: Some(filter),
        };
        cmds.push((
            attach.identifier(),
            serde_json::json!({
                "autoAttach": true,
                "waitForDebuggerOnStart": true,
                "flatten": true,
                "filter": [
                    { "type": "iframe" },
                    { "exclude": true },
                ],
            }),
        ));
        CommandChain::new(cmds, timeout)
    }

    fn init_command_pairs(cdp_mode: CdpMode) -> Vec<(MethodId, serde_json::Value)> {
        let enable = page::EnableParams::default();
        let get_tree = page::GetFrameTreeParams::default();
        let set_lifecycle = page::SetLifecycleEventsEnabledParams::new(true);
        let mut cmds = vec![
            (enable.identifier(), serde_json::to_value(enable).unwrap()),
            (
                get_tree.identifier(),
                serde_json::to_value(get_tree).unwrap(),
            ),
            (
                set_lifecycle.identifier(),
                serde_json::to_value(set_lifecycle).unwrap(),
            ),
        ];
        // VoidCrawl stealth patch (CAS-147 follow-up): `Runtime.enable` is the single
        // most-cited CDP automation tell — enabling the Runtime domain makes Chrome
        // emit `Runtime.consoleAPICalled`, which Cloudflare/DataDome detect to flag
        // headless/automation (this is exactly why a Managed Challenge clears for a
        // human but not for a CDP-driven browser). In minimal CDP mode we skip it;
        // `Runtime.evaluate` still works in the page's main world without it (the
        // nodriver approach). Trade-off: no per-frame execution-context tracking, so
        // cross-origin `evaluate_js_in_frame` is unavailable in this mode.
        if !cdp_mode.is_minimal() {
            let enable_runtime = runtime::EnableParams::default();
            cmds.push((
                enable_runtime.identifier(),
                serde_json::to_value(enable_runtime).unwrap(),
            ));
        }
        cmds
    }

    pub fn main_frame(&self) -> Option<&Frame> {
        self.main_frame.as_ref().and_then(|id| self.frames.get(id))
    }

    pub fn main_frame_mut(&mut self) -> Option<&mut Frame> {
        if let Some(id) = self.main_frame.as_ref() {
            self.frames.get_mut(id)
        } else {
            None
        }
    }

    pub fn frames(&self) -> impl Iterator<Item = &Frame> + '_ {
        self.frames.values()
    }

    pub fn frame(&self, id: &FrameId) -> Option<&Frame> {
        self.frames.get(id)
    }

    pub fn set_main_session_id(&mut self, session_id: SessionId) {
        self.main_session_id = Some(session_id.clone());
        if let Some(frame_id) = self.main_frame.clone() {
            self.set_frame_owner(&frame_id, session_id, true);
        }
    }

    pub fn session_for_frame(&self, frame_id: &FrameId) -> Option<&SessionId> {
        let frame = self.frames.get(frame_id)?;
        if frame.migration_from_session.is_some() {
            return None;
        }
        frame.session_id().or(self.main_session_id.as_ref())
    }

    pub fn frame_is_session_root(&self, frame_id: &FrameId) -> Option<bool> {
        let frame = self.frames.get(frame_id)?;
        let session_id = self.session_for_frame(frame_id)?;
        let Some(parent_id) = frame.parent_id() else {
            return Some(true);
        };
        let parent_session = self.session_for_frame(parent_id)?;
        Some(parent_session != session_id)
    }

    pub fn frame_execution_context_for_session(
        &self,
        frame_id: &FrameId,
        world: DOMWorldKind,
    ) -> Option<(ExecutionContextId, SessionId)> {
        let frame = self.frames.get(frame_id)?;
        if frame.migration_from_session.is_some() {
            return None;
        }
        let context_id = match world {
            DOMWorldKind::Main => frame.main_world.execution_context(),
            DOMWorldKind::Secondary => frame.secondary_world.execution_context(),
        }?;
        let session_id = frame
            .session_id
            .clone()
            .or_else(|| self.main_session_id.clone())?;
        Some((context_id, session_id))
    }

    fn set_frame_owner(&mut self, frame_id: &FrameId, session_id: SessionId, force: bool) {
        let Some(frame) = self.frames.get_mut(frame_id) else {
            return;
        };
        if frame.session_id.as_ref() == Some(&session_id) {
            frame.migration_from_session = None;
            return;
        }
        if !force && !Self::frame_owner_accepts(&self.main_session_id, frame, &session_id) {
            return;
        }
        frame.clear_contexts();
        frame.session_id = Some(session_id);
        frame.migration_from_session = None;
        self.context_ids.retain(|_, id| id != frame_id);
    }

    pub fn detach_session(&mut self, session_id: &SessionId) {
        self.context_ids.retain(|(owner, _), _| owner != session_id);
        if self.main_session_id.as_ref() == Some(session_id) {
            self.main_session_id = None;
            self.frames.clear();
            self.main_frame = None;
            return;
        }
        for frame in self.frames.values_mut() {
            if frame.session_id.as_ref() == Some(session_id) {
                frame.clear_contexts();
                frame.migration_from_session = Some(session_id.clone());
                frame.session_id = None;
                frame.loader_id = None;
                frame.lifecycle_events.clear();
                frame.http_request.take();
            }
        }
    }

    fn check_lifecycle(&self, watcher: &NavigationWatcher, frame: &Frame) -> bool {
        watcher.expected_lifecycle.iter().all(|ev| {
            frame.lifecycle_events.contains(ev)
                || (frame.url.is_none() && frame.lifecycle_events.contains("DOMContentLoaded"))
        }) && frame
            .child_frames
            .iter()
            .filter_map(|f| self.frames.get(f))
            .all(|f| self.check_lifecycle(watcher, f))
    }

    fn check_lifecycle_complete(
        &self,
        watcher: &NavigationWatcher,
        frame: &Frame,
    ) -> Option<NavigationOk> {
        if !self.check_lifecycle(watcher, frame) {
            return None;
        }
        if frame.loader_id == watcher.loader_id && !watcher.same_document_navigation {
            return None;
        }
        if watcher.same_document_navigation {
            return Some(NavigationOk::SameDocumentNavigation(watcher.id));
        }
        if frame.loader_id != watcher.loader_id {
            return Some(NavigationOk::NewDocumentNavigation(watcher.id));
        }
        None
    }

    /// Track the request in the frame
    pub fn on_http_request_finished(&mut self, request: HttpRequest) {
        if let Some(id) = request.frame.as_ref() {
            if let Some(frame) = self.frames.get_mut(id) {
                frame.set_request(request);
            }
        }
    }

    pub fn poll(&mut self, now: Instant) -> Option<FrameEvent> {
        // check if the navigation completed
        if let Some((watcher, deadline)) = self.navigation.take() {
            if now > deadline {
                // navigation request timed out
                return Some(FrameEvent::NavigationResult(Err(
                    NavigationError::Timeout {
                        err: DeadlineExceeded::new(now, deadline),
                        id: watcher.id,
                    },
                )));
            }
            if let Some(frame) = self.frames.get(&watcher.frame_id) {
                if let Some(nav) = self.check_lifecycle_complete(&watcher, frame) {
                    // request is complete if the frame's lifecycle is complete = frame received all
                    // required events
                    return Some(FrameEvent::NavigationResult(Ok(nav)));
                } else {
                    // not finished yet
                    self.navigation = Some((watcher, deadline));
                }
            } else {
                return Some(FrameEvent::NavigationResult(Err(
                    NavigationError::FrameNotFound {
                        frame: watcher.frame_id,
                        id: watcher.id,
                    },
                )));
            }
        } else if let Some((req, watcher)) = self.pending_navigations.pop_front() {
            // queue in the next navigation that is must be fulfilled until `deadline`
            let deadline = Instant::now() + req.timeout;
            self.navigation = Some((watcher, deadline));
            return Some(FrameEvent::NavigationRequest(req.id, req.req));
        }
        None
    }

    /// Entrypoint for page navigation
    pub fn goto(&mut self, req: FrameNavigationRequest) {
        let requested_frame = req
            .req
            .params
            .get("frameId")
            .and_then(serde_json::Value::as_str)
            .map(|frame_id| FrameId::new(frame_id.to_string()));
        if let Some(frame_id) = requested_frame.or_else(|| self.main_frame.clone()) {
            self.navigate_frame(frame_id, req);
        }
    }

    /// Navigate a specific frame
    pub fn navigate_frame(&mut self, frame_id: FrameId, mut req: FrameNavigationRequest) {
        let loader_id = self.frames.get(&frame_id).and_then(|f| f.loader_id.clone());
        let watcher = NavigationWatcher::until_page_load(req.id, frame_id.clone(), loader_id);
        // insert the frame_id in the request if not present
        req.set_frame_id(frame_id);
        self.pending_navigations.push_back((req, watcher))
    }

    pub fn on_frame_tree_in_session(&mut self, frame_tree: FrameTree, session_id: &SessionId) {
        self.on_frame_attached_in_session(
            frame_tree.frame.id.clone(),
            frame_tree.frame.parent_id.clone(),
            session_id,
        );
        self.on_frame_navigated_in_session(&frame_tree.frame, session_id);
        if let Some(children) = frame_tree.child_frames {
            for child_tree in children {
                self.on_frame_tree_in_session(child_tree, session_id);
            }
        }
    }

    pub fn on_frame_attached_in_session(
        &mut self,
        frame_id: FrameId,
        parent_frame_id: Option<FrameId>,
        session_id: &SessionId,
    ) {
        if self.frames.contains_key(&frame_id) {
            self.set_frame_owner(&frame_id, session_id.clone(), false);
            return;
        }
        let mut frame = if let Some(parent_frame_id) = parent_frame_id {
            if let Some(parent_frame) = self.frames.get_mut(&parent_frame_id) {
                Frame::with_parent(frame_id.clone(), parent_frame)
            } else {
                let mut frame = Frame::new(frame_id.clone());
                frame.parent_frame = Some(parent_frame_id);
                frame
            }
        } else {
            Frame::new(frame_id.clone())
        };
        frame.session_id = Some(session_id.clone());
        self.frames.insert(frame_id, frame);
    }

    pub fn on_frame_detached_in_session(
        &mut self,
        event: &EventFrameDetached,
        session_id: &SessionId,
    ) {
        if let Some(frame) = self.frames.get(&event.frame_id) {
            let reported_by_current_owner = frame.session_id.as_ref() == Some(session_id);
            let removal_reported_by_page = event.reason == FrameDetachedReason::Remove
                && self.main_session_id.as_ref() == Some(session_id);
            if !reported_by_current_owner && !removal_reported_by_page {
                return;
            }
        }
        if event.reason == FrameDetachedReason::Swap {
            if let Some(frame) = self.frames.get_mut(&event.frame_id) {
                frame.clear_contexts();
                frame.migration_from_session = frame
                    .session_id
                    .clone()
                    .or_else(|| Some(session_id.clone()));
                frame.session_id = None;
                frame.loader_id = None;
                frame.lifecycle_events.clear();
                frame.http_request.take();
            }
            self.context_ids
                .retain(|(owner, _), frame_id| owner != session_id || frame_id != &event.frame_id);
        } else {
            self.remove_frames_recursively(&event.frame_id);
        }
    }

    pub fn on_frame_navigated_in_session(&mut self, frame: &CdpFrame, session_id: &SessionId) {
        if let Some(current) = self.frames.get(&frame.id)
            && !Self::frame_owner_accepts(&self.main_session_id, current, session_id)
        {
            return;
        }
        if frame.parent_id.is_some() {
            if let Some((id, mut f)) = self.frames.remove_entry(&frame.id) {
                for child in &f.child_frames {
                    self.remove_frames_recursively(child);
                }
                // this is necessary since we can't borrow mut and then remove recursively
                f.child_frames.clear();
                f.clear_contexts();
                self.context_ids.retain(|_, frame_id| frame_id != &id);
                f.navigated(frame);
                Self::assign_frame_owner(&self.main_session_id, &mut f, session_id);
                self.frames.insert(id, f);
            } else {
                self.on_frame_attached_in_session(
                    frame.id.clone(),
                    frame.parent_id.clone(),
                    session_id,
                );
                if let Some(f) = self.frames.get_mut(&frame.id) {
                    f.navigated(frame);
                }
            }
        } else {
            let mut f = if let Some(main) = self.main_frame.take() {
                // update main frame
                let mut main_frame = self.frames.remove(&main).expect("Main frame is tracked.");
                for child in &main_frame.child_frames {
                    self.remove_frames_recursively(child);
                }
                // this is necessary since we can't borrow mut and then remove recursively
                main_frame.child_frames.clear();
                main_frame.id = frame.id.clone();
                main_frame.clear_contexts();
                main_frame
            } else {
                // initial main frame navigation
                Frame::new(frame.id.clone())
            };
            f.navigated(frame);
            Self::assign_frame_owner(&self.main_session_id, &mut f, session_id);
            self.main_frame = Some(f.id.clone());
            self.frames.insert(f.id.clone(), f);
        }
    }

    fn frame_owner_accepts(
        main_session_id: &Option<SessionId>,
        frame: &Frame,
        session_id: &SessionId,
    ) -> bool {
        if let Some(previous_session) = frame.migration_from_session.as_ref() {
            return previous_session != session_id;
        }
        let may_move_from_main = frame.session_id.as_ref() == main_session_id.as_ref()
            && main_session_id.as_ref() != Some(session_id);
        frame.session_id.is_none()
            || frame.session_id.as_ref() == Some(session_id)
            || may_move_from_main
    }

    fn assign_frame_owner(
        main_session_id: &Option<SessionId>,
        frame: &mut Frame,
        session_id: &SessionId,
    ) -> bool {
        if !Self::frame_owner_accepts(main_session_id, frame, session_id) {
            return false;
        }
        if frame.session_id.as_ref() != Some(session_id) {
            frame.clear_contexts();
            frame.session_id = Some(session_id.clone());
        }
        frame.migration_from_session = None;
        true
    }

    pub fn on_frame_navigated_within_document_in_session(
        &mut self,
        event: &EventNavigatedWithinDocument,
        session_id: &SessionId,
    ) {
        let mut accepted = false;
        if let Some(frame) = self.frames.get_mut(&event.frame_id) {
            if Self::assign_frame_owner(&self.main_session_id, frame, session_id) {
                frame.navigated_within_url(event.url.clone());
                accepted = true;
            }
        }
        if accepted && let Some((watcher, _)) = self.navigation.as_mut() {
            watcher.on_frame_navigated_within_document(event);
        }
    }

    pub fn on_frame_stopped_loading_in_session(
        &mut self,
        event: &EventFrameStoppedLoading,
        session_id: &SessionId,
    ) {
        if let Some(frame) = self.frames.get_mut(&event.frame_id) {
            if frame.session_id.as_ref() == Some(session_id) {
                frame.on_loading_stopped();
            }
        }
    }

    /// Fired when frame has started loading.
    pub fn on_frame_started_loading_in_session(
        &mut self,
        event: &EventFrameStartedLoading,
        session_id: &SessionId,
    ) {
        if let Some(frame) = self.frames.get_mut(&event.frame_id) {
            if frame.session_id.as_ref() == Some(session_id) {
                frame.on_loading_started();
            }
        }
    }

    /// Notification is issued every time when binding is called
    pub fn on_runtime_binding_called(&mut self, _ev: &EventBindingCalled) {}

    /// Issued when new execution context is created
    pub fn on_frame_execution_context_created_in_session(
        &mut self,
        event: &EventExecutionContextCreated,
        session_id: &SessionId,
    ) {
        if let Some(frame_id) = event
            .context
            .aux_data
            .as_ref()
            .and_then(|v| v["frameId"].as_str())
        {
            if let Some(frame) = self.frames.get_mut(frame_id) {
                if !Self::assign_frame_owner(&self.main_session_id, frame, session_id) {
                    return;
                }
                if event
                    .context
                    .aux_data
                    .as_ref()
                    .and_then(|v| v["isDefault"].as_bool())
                    .unwrap_or_default()
                {
                    frame
                        .main_world
                        .set_context(event.context.id, event.context.unique_id.clone());
                } else if event.context.name == UTILITY_WORLD_NAME
                    && frame.secondary_world.execution_context().is_none()
                {
                    frame
                        .secondary_world
                        .set_context(event.context.id, event.context.unique_id.clone());
                }
                self.context_ids.insert(
                    (session_id.clone(), event.context.unique_id.clone()),
                    frame.id.clone(),
                );
            }
        }
        if event
            .context
            .aux_data
            .as_ref()
            .filter(|v| v["type"].as_str() == Some("isolated"))
            .is_some()
        {
            self.isolated_worlds.insert(event.context.name.clone());
        }
    }

    /// Issued when execution context is destroyed
    pub fn on_frame_execution_context_destroyed_in_session(
        &mut self,
        event: &EventExecutionContextDestroyed,
        session_id: &SessionId,
    ) {
        if let Some(id) = self.context_ids.remove(&(
            session_id.clone(),
            event.execution_context_unique_id.clone(),
        )) {
            if let Some(frame) = self.frames.get_mut(&id) {
                frame.destroy_context(&event.execution_context_unique_id);
            }
        }
    }

    /// Issued when all executionContexts were cleared
    pub fn on_execution_contexts_cleared_in_session(&mut self, session_id: &SessionId) {
        let frame_ids = self
            .context_ids
            .iter()
            .filter(|((owner, _), _)| owner == session_id)
            .map(|(_, frame_id)| frame_id.clone())
            .collect::<HashSet<_>>();
        for frame_id in frame_ids {
            if let Some(frame) = self.frames.get_mut(&frame_id)
                && frame.session_id.as_ref() == Some(session_id)
            {
                frame.clear_contexts();
            }
        }
        self.context_ids.retain(|(owner, _), _| owner != session_id);
    }

    /// Fired for top level page lifecycle events (nav, load, paint, etc.)
    pub fn on_page_lifecycle_event_in_session(
        &mut self,
        event: &EventLifecycleEvent,
        session_id: &SessionId,
    ) {
        if let Some(frame) = self.frames.get_mut(&event.frame_id) {
            if frame.session_id.as_ref() != Some(session_id) {
                return;
            }
            if event.name == "init" {
                frame.loader_id = Some(event.loader_id.clone());
                frame.lifecycle_events.clear();
            }
            frame.lifecycle_events.insert(event.name.clone().into());
        }
    }

    /// Detach all child frames
    fn remove_frames_recursively(&mut self, id: &FrameId) -> Option<Frame> {
        if let Some(mut frame) = self.frames.remove(id) {
            for child in &frame.child_frames {
                self.remove_frames_recursively(child);
            }
            if let Some(parent_id) = frame.parent_frame.take() {
                if let Some(parent) = self.frames.get_mut(&parent_id) {
                    parent.child_frames.remove(&frame.id);
                }
            }
            self.context_ids.retain(|_, frame_id| frame_id != id);
            Some(frame)
        } else {
            None
        }
    }

    pub fn ensure_isolated_world(&mut self, world_name: &str) -> Option<CommandChain> {
        if self.isolated_worlds.contains(world_name) {
            return None;
        }
        self.isolated_worlds.insert(world_name.to_string());
        let cmd = AddScriptToEvaluateOnNewDocumentParams::builder()
            .source(format!("//# sourceURL={EVALUATION_SCRIPT_URL}"))
            .world_name(world_name)
            .build()
            .unwrap();

        let mut cmds = Vec::with_capacity(self.frames.len() + 1);

        cmds.push((cmd.identifier(), serde_json::to_value(cmd).unwrap()));

        cmds.extend(self.frames.keys().map(|id| {
            let cmd = CreateIsolatedWorldParams::builder()
                .frame_id(id.clone())
                .grant_univeral_access(true)
                .world_name(world_name)
                .build()
                .unwrap();
            (cmd.identifier(), serde_json::to_value(cmd).unwrap())
        }));
        Some(CommandChain::new(cmds, self.request_timeout))
    }
}

#[derive(Debug)]
pub enum FrameEvent {
    /// A previously submitted navigation has finished
    NavigationResult(Result<NavigationOk, NavigationError>),
    /// A new navigation request needs to be submitted
    NavigationRequest(NavigationId, Request),
    /* /// The initial page of the target has been loaded
     * InitialPageLoadFinished */
}

#[derive(Debug)]
pub enum NavigationError {
    Timeout {
        id: NavigationId,
        err: DeadlineExceeded,
    },
    FrameNotFound {
        id: NavigationId,
        frame: FrameId,
    },
}

impl NavigationError {
    pub fn navigation_id(&self) -> &NavigationId {
        match self {
            NavigationError::Timeout { id, .. } => id,
            NavigationError::FrameNotFound { id, .. } => id,
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum NavigationOk {
    SameDocumentNavigation(NavigationId),
    NewDocumentNavigation(NavigationId),
}

impl NavigationOk {
    pub fn navigation_id(&self) -> &NavigationId {
        match self {
            NavigationOk::SameDocumentNavigation(id) => id,
            NavigationOk::NewDocumentNavigation(id) => id,
        }
    }
}

/// Tracks the progress of an issued `Page.navigate` request until completion.
#[derive(Debug)]
pub struct NavigationWatcher {
    id: NavigationId,
    expected_lifecycle: HashSet<MethodId>,
    frame_id: FrameId,
    loader_id: Option<LoaderId>,
    /// Once we receive the response to the issued `Page.navigate` request we
    /// can detect whether we were navigating withing the same document or were
    /// navigating to a new document by checking if a loader was included in the
    /// response.
    same_document_navigation: bool,
}

impl NavigationWatcher {
    pub fn until_page_load(id: NavigationId, frame: FrameId, loader_id: Option<LoaderId>) -> Self {
        Self {
            id,
            expected_lifecycle: std::iter::once("load".into()).collect(),
            loader_id,
            frame_id: frame,
            same_document_navigation: false,
        }
    }

    /// Checks whether the navigation was completed
    pub fn is_lifecycle_complete(&self) -> bool {
        self.expected_lifecycle.is_empty()
    }

    fn on_frame_navigated_within_document(&mut self, ev: &EventNavigatedWithinDocument) {
        if self.frame_id == ev.frame_id {
            self.same_document_navigation = true;
        }
    }
}

/// An identifier for an ongoing navigation
#[derive(Debug, Copy, Clone, Hash, Eq, PartialEq)]
pub struct NavigationId(pub usize);

/// Represents a the request for a navigation
#[derive(Debug)]
pub struct FrameNavigationRequest {
    /// The internal identifier
    pub id: NavigationId,
    /// the cdp request that will trigger the navigation
    pub req: Request,
    /// The timeout after which the request will be considered timed out
    pub timeout: Duration,
}

impl FrameNavigationRequest {
    pub fn new(id: NavigationId, req: Request) -> Self {
        Self {
            id,
            req,
            timeout: Duration::from_millis(REQUEST_TIMEOUT),
        }
    }

    /// This will set the id of the frame into the `params` `frameId` field.
    pub fn set_frame_id(&mut self, frame_id: FrameId) {
        if let Some(params) = self.req.params.as_object_mut() {
            if let Entry::Vacant(entry) = params.entry("frameId") {
                entry.insert(serde_json::Value::String(frame_id.into()));
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum LifecycleEvent {
    #[default]
    Load,
    DomcontentLoaded,
    NetworkIdle,
    NetworkAlmostIdle,
}

impl AsRef<str> for LifecycleEvent {
    fn as_ref(&self) -> &str {
        match self {
            LifecycleEvent::Load => "load",
            LifecycleEvent::DomcontentLoaded => "DOMContentLoaded",
            LifecycleEvent::NetworkIdle => "networkIdle",
            LifecycleEvent::NetworkAlmostIdle => "networkAlmostIdle",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(value: &str) -> FrameId {
        FrameId::new(value.to_owned())
    }

    fn session(value: &str) -> SessionId {
        SessionId::from(value.to_owned())
    }

    #[test]
    fn swap_rejects_stale_session_and_accepts_replacement() {
        let main_session = session("main");
        let old_child_session = session("child-old");
        let new_child_session = session("child-new");
        let main_frame = frame("main-frame");
        let child_frame = frame("child-frame");
        let mut manager = FrameManager::new(Duration::from_secs(1));
        manager.set_main_session_id(main_session.clone());
        manager.on_frame_attached_in_session(main_frame.clone(), None, &main_session);
        manager.on_frame_attached_in_session(
            child_frame.clone(),
            Some(main_frame.clone()),
            &main_session,
        );
        manager.set_frame_owner(&child_frame, old_child_session.clone(), true);

        manager.on_frame_detached_in_session(
            &EventFrameDetached {
                frame_id: child_frame.clone(),
                reason: FrameDetachedReason::Swap,
            },
            &old_child_session,
        );
        assert!(manager.session_for_frame(&child_frame).is_none());

        manager.on_frame_attached_in_session(
            child_frame.clone(),
            Some(main_frame.clone()),
            &old_child_session,
        );
        assert!(manager.session_for_frame(&child_frame).is_none());

        manager.on_frame_attached_in_session(
            child_frame.clone(),
            Some(main_frame),
            &new_child_session,
        );
        assert_eq!(
            manager.session_for_frame(&child_frame),
            Some(&new_child_session)
        );
    }

    #[test]
    fn swap_back_to_main_session_keeps_frame_identity() {
        let main_session = session("main");
        let child_session = session("child");
        let main_frame = frame("main-frame");
        let child_frame = frame("child-frame");
        let mut manager = FrameManager::new(Duration::from_secs(1));
        manager.set_main_session_id(main_session.clone());
        manager.on_frame_attached_in_session(main_frame.clone(), None, &main_session);
        manager.on_frame_attached_in_session(
            child_frame.clone(),
            Some(main_frame.clone()),
            &child_session,
        );

        manager.detach_session(&child_session);
        manager.on_frame_attached_in_session(child_frame.clone(), Some(main_frame), &main_session);

        assert_eq!(manager.session_for_frame(&child_frame), Some(&main_session));
    }
}
