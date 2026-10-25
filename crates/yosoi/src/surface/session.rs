use super::{
    ArchiveLimits, ArchivePolicy, Budget, Continuation, Inspection, Page, Reference, Surface,
    SurfaceError,
};
use crate::automation_record::OperationStatus;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, VecDeque},
    fmt::{self, Debug, Formatter},
    sync::{Arc, Mutex, MutexGuard},
};

/// Policy bounds shared across all cursors in one surface session.
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SessionPolicy {
    /// Evidence retention for explicit Archive persistence; disabled by default.
    pub archive: ArchivePolicy,
    /// Retained outcome bounds, independent of cursor history and reply budgets.
    pub archive_limits: ArchiveLimits,
    /// Total logical cursors, including the hot owner. Defaults to one.
    pub cursors: usize,
    /// Maximum region watches across all cursors.
    pub watches: usize,
    /// Number of immutable captures retained for historical inspection.
    pub captures: usize,
    /// Bounded event history; readers are told when they missed events.
    pub events: usize,
}
impl Default for SessionPolicy {
    fn default() -> Self {
        Self {
            archive: ArchivePolicy::Off,
            archive_limits: ArchiveLimits::default(),
            cursors: 1,
            watches: 8,
            captures: 2,
            events: 128,
        }
    }
}

/// Session-local opaque cursor identity.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq, Ord, PartialOrd)]
pub struct CursorId(u64);
impl CursorId {
    /// Returns the identity for diagnostics; not a portable capability.
    pub const fn get(self) -> u64 {
        self.0
    }
}
/// Session-local opaque subscription identity.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq, Ord, PartialOrd)]
pub struct WatchId(u64);
impl WatchId {
    /// Returns the subscription identity for diagnostics.
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Independent exploration position for one logical cursor.
#[derive(Clone, Debug, Default, Serialize)]
pub struct Position {
    /// Most recently expanded region, which may belong to an older capture.
    pub scope: Option<Reference>,
    /// Most recently inspected or explicitly focused evidence.
    pub focus: Option<Reference>,
    /// Continuation of the last bounded read; does not grant action authority.
    pub continuation: Option<Continuation>,
}

/// Freshness of a saved position relative to the session's current evidence.
#[derive(Clone, Copy, Debug, Serialize, Eq, PartialEq)]
pub enum Freshness {
    /// No position is selected.
    Unfocused,
    /// The exact complete capture is current.
    Current,
    /// The saved position belongs to a retained older capture.
    Stale,
    /// The saved capture has left bounded history.
    Evicted,
    /// Capture is pending, observation failed, or source coverage is incomplete.
    Unknown,
}

/// Observable state of one logical region subscription.
#[derive(Clone, Debug, Serialize)]
pub struct WatchState {
    /// Subscription identity scoped to this session.
    pub id: WatchId,
    /// Last explicitly selected captured region.
    pub reference: Reference,
    /// Whether the provider/caller must reconcile the region before claiming it unchanged.
    pub needs_reconciliation: bool,
}

/// Inspectable cursor state for debugging, demos, and external harnesses.
#[derive(Clone, Debug, Serialize)]
pub struct CursorState {
    /// Cursor identity.
    pub id: CursorId,
    /// Whether an external observation provider is attached.
    pub live: bool,
    /// Whether this cursor owns the single hot capability.
    pub hot: bool,
    /// Exact current session capture.
    pub current_capture: String,
    /// Independent navigation state.
    pub position: Position,
    /// Freshness of inspected/selected evidence.
    pub focus_freshness: Freshness,
    /// Freshness of the expanded region.
    pub scope_freshness: Freshness,
    /// Subscriptions, which do not move when scope/focus moves.
    pub subscriptions: Vec<WatchState>,
    /// Whether this cursor has an effect lease outstanding.
    pub action_in_flight: bool,
}

/// Event classes; none imply that arbitrary application memory was observed.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub enum EventKind {
    /// New immutable evidence became current.
    Published,
    /// A region needs explicit reconciliation against current evidence.
    Stale,
    /// Caller-selected replacement evidence differs from prior evidence.
    Changed,
    /// Caller-selected replacement evidence has identical complete serialization.
    Unchanged,
    /// Evidence, coverage, or retained history cannot support comparison.
    Unknown,
    /// Observation detached and hot authority was revoked.
    Detached,
    /// An action lease finished or was dropped with a recorded outcome.
    ActionFinished,
}

/// Bounded session event, optionally addressed to a reader and region watch.
#[derive(Clone, Debug, Serialize)]
pub struct Event {
    /// Monotonic session-local sequence number.
    pub sequence: u64,
    /// Event's evidence or lifecycle meaning.
    pub kind: EventKind,
    /// Recipient, or `None` for a session-wide observation event.
    pub cursor: Option<CursorId>,
    /// Affected subscription, if any.
    pub watch: Option<WatchId>,
    /// Previously addressed evidence, if retained.
    pub before: Option<Reference>,
    /// Newly selected evidence, if known.
    pub after: Option<Reference>,
    /// Structural explanation, not inferred application causality.
    pub note: String,
}

/// One reader's independently consumed event window.
#[derive(Clone, Debug, Serialize)]
pub struct EventBatch {
    /// Available events belonging to this cursor or the whole session.
    pub events: Vec<Event>,
    /// Whether bounded history discarded events since this cursor last read it.
    pub lost: bool,
}

/// External adapter's reported action outcome.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub enum ActionStatus {
    /// Rejected before an effect was dispatched.
    Rejected,
    /// Adapter reports its postcondition was observed after dispatch.
    Confirmed,
    /// Dispatch or observation occurred without a confirmed postcondition.
    Unconfirmed,
}

/// Receipt preserving dispatch separately from a claimed postcondition.
#[derive(Clone, Debug, Serialize)]
pub struct ActionReceipt {
    /// Cursor that owned the action lease.
    pub cursor: CursorId,
    /// Exact pre-action target reference.
    pub target: Reference,
    /// Whether the external adapter marked the effect as dispatched.
    pub dispatched: bool,
    /// Adapter-reported result; the SDK does not execute or infer effects.
    pub status: ActionStatus,
    /// Current capture when the lease finished, if any.
    pub after_capture: Option<String>,
    /// Provider's evidence/uncertainty explanation.
    pub note: String,
}

#[derive(Default)]
struct Reader {
    position: Position,
    last_event: u64,
}
struct Watch {
    cursor: CursorId,
    reference: Reference,
    pending: bool,
}
struct State {
    outcome: Option<super::Outcome>,
    closed: bool,
    policy: SessionPolicy,
    live: bool,
    uncertain: bool,
    captures: VecDeque<Surface>,
    readers: BTreeMap<CursorId, Reader>,
    watches: BTreeMap<WatchId, Watch>,
    hot: Option<CursorId>,
    flight: Option<(CursorId, u64)>,
    next: u64,
    revision: u64,
    event_sequence: u64,
    events: VecDeque<Event>,
}
impl State {
    fn allocate(&mut self) -> Result<u64, SurfaceError> {
        let id = self.next;
        self.next = self
            .next
            .checked_add(1)
            .ok_or(SurfaceError::Limit("session identity"))?;
        Ok(id)
    }
    fn current(&self) -> Result<&Surface, SurfaceError> {
        self.captures.back().ok_or(SurfaceError::Unknown)
    }
    fn index(&self, reference: &Reference) -> Result<Surface, SurfaceError> {
        self.captures
            .iter()
            .find(|index| index.identity() == reference.capture)
            .cloned()
            .ok_or(SurfaceError::Unknown)
    }
    fn emit(
        &mut self,
        kind: EventKind,
        cursor: Option<CursorId>,
        watch: Option<WatchId>,
        before: Option<Reference>,
        after: Option<Reference>,
        note: &str,
    ) -> Result<(), SurfaceError> {
        self.event_sequence = self
            .event_sequence
            .checked_add(1)
            .ok_or(SurfaceError::Limit("event sequence"))?;
        self.events.push_back(Event {
            sequence: self.event_sequence,
            kind,
            cursor,
            watch,
            before,
            after,
            note: note.chars().take(512).collect(),
        });
        if let Some(outcome) = &mut self.outcome {
            let status = match kind {
                EventKind::Unknown => OperationStatus::Unknown,
                _ => OperationStatus::Observed,
            };
            outcome.receipt("surface.event", status, serde_json::json!({"kind":kind,"cursor":cursor,"watch":watch,"note":note.chars().take(512).collect::<String>()}));
        }
        while self.events.len() > self.policy.events {
            self.events.pop_front();
        }
        Ok(())
    }
}

/// Thread-safe session coordinating immutable evidence and one hot action owner.
/// Live means an external capture adapter is attached, not that this object launches a browser.
#[derive(Clone)]
pub struct Session {
    state: Arc<Mutex<State>>,
}
impl Debug for Session {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        f.debug_struct("IndexSession").finish_non_exhaustive()
    }
}
impl Session {
    /// Creates a detached session with bounded history and no implicit cursors.
    pub fn new(index: Surface, policy: SessionPolicy) -> Result<Self, SurfaceError> {
        policy.archive_limits.validate()?;
        if policy.cursors == 0
            || policy.cursors > 256
            || policy.watches > 1024
            || policy.captures == 0
            || policy.captures > 32
            || policy.events == 0
            || policy.events > 4096
        {
            return Err(SurfaceError::Invalid(
                "invalid session policy bounds".into(),
            ));
        }
        let outcome = if policy.archive == ArchivePolicy::Enabled {
            let mut outcome = super::Outcome::new(
                format!("surface-{}", uuid::Uuid::new_v4()),
                policy.archive_limits,
            )?;
            outcome.retain(super::ArchivedSource::capture(index.identity(), &index)?)?;
            Some(outcome)
        } else {
            None
        };
        Ok(Self {
            state: Arc::new(Mutex::new(State {
                outcome,
                closed: false,
                policy,
                live: false,
                uncertain: false,
                captures: VecDeque::from([index]),
                readers: BTreeMap::new(),
                watches: BTreeMap::new(),
                hot: None,
                flight: None,
                next: 1,
                revision: 0,
                event_sequence: 0,
                events: VecDeque::new(),
            })),
        })
    }
    fn lock(&self) -> Result<MutexGuard<'_, State>, SurfaceError> {
        let state = self.state.lock().map_err(|_| SurfaceError::Poisoned)?;
        if state.closed {
            return Err(SurfaceError::Unknown);
        }
        Ok(state)
    }
    /// Returns retained evidence without closing this session, or `None` when policy is off.
    /// An in-flight action makes the snapshot unsealed; saved data never grants live authority.
    pub fn outcome(&self) -> Result<Option<super::Outcome>, SurfaceError> {
        Ok(self
            .state
            .lock()
            .map_err(|_| SurfaceError::Poisoned)?
            .outcome
            .clone())
    }
    /// Closes logical readers and revokes authority, preserving a final policy outcome.
    /// The caller still owns external browser/provider cleanup. Outstanding effects remain unknown.
    /// Repeated close calls are harmless; closed sessions cannot be attached again.
    pub fn close(&self) -> Result<Option<super::Outcome>, SurfaceError> {
        let mut state = self.state.lock().map_err(|_| SurfaceError::Poisoned)?;
        if !state.closed {
            let pending = state.flight.take().is_some();
            if pending {
                state.emit(
                    EventKind::Unknown,
                    None,
                    None,
                    None,
                    None,
                    "closed with an outstanding action; effect unknown",
                )?;
            }
            state.emit(
                EventKind::Detached,
                None,
                None,
                None,
                None,
                "logical session closed; external cleanup remains adapter-owned",
            )?;
            state.live = false;
            state.hot = None;
            state.readers.clear();
            state.watches.clear();
            state.closed = true;
            if let Some(outcome) = &mut state.outcome {
                outcome.sealed = true;
            }
        }
        Ok(state.outcome.clone())
    }

    fn record_read<T: Serialize>(
        &self,
        command: &serde_json::Value,
        result: &Result<T, SurfaceError>,
    ) -> Result<(), SurfaceError> {
        let mut state = self.lock()?;
        if let Some(outcome) = &mut state.outcome {
            let (status, value) = match result {
                Ok(value) => (
                    OperationStatus::Observed,
                    serde_json::to_value(value)
                        .map_err(|error| SurfaceError::Parse(error.to_string()))?,
                ),
                Err(error) => (
                    OperationStatus::Rejected,
                    serde_json::json!({"error":error.to_string()}),
                ),
            };
            outcome.receipt(
                "surface.read",
                status,
                serde_json::json!({"command":command,"outcome":value}),
            );
        }
        drop(state);
        Ok(())
    }
    /// Opens another independent reader, subject to the session cursor limit.
    pub fn cursor(&self) -> Result<Cursor, SurfaceError> {
        let mut state = self.lock()?;
        if state.readers.len() >= state.policy.cursors {
            return Err(SurfaceError::Limit("cursor count"));
        }
        let id = CursorId(state.allocate()?);
        let last_event = state.event_sequence;
        state.readers.insert(
            id,
            Reader {
                last_event,
                ..Reader::default()
            },
        );
        drop(state);
        Ok(Cursor {
            session: self.clone(),
            id,
        })
    }
    /// Marks the external observation adapter attached; readers gain no action authority.
    pub fn attach(&self) -> Result<(), SurfaceError> {
        self.lock()?.live = true;
        Ok(())
    }
    /// Marks live evidence uncertain as soon as an event or capture failure is known.
    /// Hot ownership remains, but actions are blocked until a successful `publish`.
    pub fn invalidate(&self, reason: &str) -> Result<(), SurfaceError> {
        let mut state = self.lock()?;
        if !state.live {
            return Err(SurfaceError::Detached);
        }
        state.uncertain = true;
        state.revision = state
            .revision
            .checked_add(1)
            .ok_or(SurfaceError::Limit("session revision"))?;
        for watch in state.watches.values_mut() {
            watch.pending = true;
        }
        state.emit(EventKind::Unknown, None, None, None, None, reason)
    }
    /// Detaches observation and revokes hot ownership; an already dispatched effect is not undone.
    pub fn detach(&self) -> Result<(), SurfaceError> {
        let mut state = self.lock()?;
        state.live = false;
        state.uncertain = true;
        state.hot = None;
        state.revision = state
            .revision
            .checked_add(1)
            .ok_or(SurfaceError::Limit("session revision"))?;
        state.emit(
            EventKind::Detached,
            None,
            None,
            None,
            None,
            "external observer detached; hot ownership revoked",
        )
    }
    /// Returns the current immutable index for concurrent, lock-free evidence reads.
    pub fn current(&self) -> Result<Surface, SurfaceError> {
        Ok(self.lock()?.current()?.clone())
    }
    /// Returns the current hot owner, if any; readers and watches remain independent.
    pub fn hot_owner(&self) -> Result<Option<CursorId>, SurfaceError> {
        Ok(self.lock()?.hot)
    }
    /// Publishes externally captured evidence, preserving old cursor positions.
    /// Watches become stale until explicit reconciliation; snapshots are not silently matched.
    pub fn publish(&self, index: Surface) -> Result<(), SurfaceError> {
        let mut state = self.lock()?;
        if !state.live {
            return Err(SurfaceError::Detached);
        }
        state.revision = state
            .revision
            .checked_add(1)
            .ok_or(SurfaceError::Limit("session revision"))?;
        let changed = state.current()?.identity() != index.identity();
        if let Some(outcome) = &mut state.outcome {
            let retained = super::ArchivedSource::capture(index.identity(), &index)
                .and_then(|source| outcome.retain(source));
            if let Err(error) = retained {
                outcome.complete = false;
                state.uncertain = true;
                return Err(error);
            }
        }
        state.uncertain = false;
        if changed {
            state.captures.push_back(index);
            while state.captures.len() > state.policy.captures {
                state.captures.pop_front();
            }
        }
        state.emit(
            EventKind::Published,
            None,
            None,
            None,
            None,
            "external adapter published captured evidence; no causal attribution",
        )?;
        if changed {
            let mut stale = Vec::new();
            for (id, watch) in &mut state.watches {
                watch.pending = true;
                stale.push((*id, watch.cursor, watch.reference.clone()));
            }
            for (id, cursor, reference) in stale {
                state.emit(
                    EventKind::Stale,
                    Some(cursor),
                    Some(id),
                    Some(reference),
                    None,
                    "watch needs explicit selection/reconciliation in the new capture",
                )?;
            }
        }
        drop(state);
        Ok(())
    }
}

/// Logical exploration cursor; cloning refers to the same position and reader identity.
#[derive(Clone, Debug)]
pub struct Cursor {
    session: Session,
    id: CursorId,
}
impl Cursor {
    /// Returns the cursor's session-local identity.
    pub const fn id(&self) -> CursorId {
        self.id
    }
    fn index(&self, reference: &Reference) -> Result<Surface, SurfaceError> {
        let state = self.session.lock()?;
        if !state.readers.contains_key(&self.id) {
            return Err(SurfaceError::Unknown);
        }
        state.index(reference)
    }
    /// Returns this reader's independent scope, focus, and continuation.
    pub fn position(&self) -> Result<Position, SurfaceError> {
        Ok(self
            .session
            .lock()?
            .readers
            .get(&self.id)
            .ok_or(SurfaceError::Unknown)?
            .position
            .clone())
    }
    /// Returns observation, authority, positions, and subscriptions without inferring page state.
    pub fn status(&self) -> Result<CursorState, SurfaceError> {
        let state = self.session.lock()?;
        let reader = state.readers.get(&self.id).ok_or(SurfaceError::Unknown)?;
        let current = state.current()?;
        let freshness = |reference: &Option<Reference>| match reference {
            None => Freshness::Unfocused,
            Some(_) if state.uncertain || !current.coverage().complete => Freshness::Unknown,
            Some(reference) if reference.capture == current.identity() => Freshness::Current,
            Some(reference) if state.index(reference).is_ok() => Freshness::Stale,
            Some(_) => Freshness::Evicted,
        };
        let result = CursorState {
            id: self.id,
            live: state.live,
            hot: state.hot == Some(self.id),
            current_capture: current.identity().into(),
            position: reader.position.clone(),
            focus_freshness: freshness(&reader.position.focus),
            scope_freshness: freshness(&reader.position.scope),
            subscriptions: state
                .watches
                .iter()
                .filter(|(_, watch)| watch.cursor == self.id)
                .map(|(id, watch)| WatchState {
                    id: *id,
                    reference: watch.reference.clone(),
                    needs_reconciliation: watch.pending,
                })
                .collect(),
            action_in_flight: state.flight.is_some_and(|(owner, _)| owner == self.id),
        };
        drop(state);
        Ok(result)
    }
    /// Reads a current overview without moving saved scope or focus.
    pub fn overview(
        &self,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        let index = self.session.current()?;
        let result = index.overview(token, budget);
        self.session.record_read(
            &serde_json::json!({"op":"overview","token":token,"budget":budget}),
            &result,
        )?;
        let page = result?;
        self.save(None, None, page.next.clone())?;
        Ok(page)
    }
    /// Performs literal search in the current capture without granting action permission.
    pub fn find(
        &self,
        query: &str,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        let index = self.session.current()?;
        let result = index.find(query, token, budget);
        self.session.record_read(
            &serde_json::json!({"op":"find","query":query,"token":token,"budget":budget}),
            &result,
        )?;
        let page = result?;
        self.save(None, None, page.next.clone())?;
        Ok(page)
    }
    /// Expands a retained region and makes it this cursor's exploration scope.
    pub fn expand(
        &self,
        reference: &Reference,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        let result = self
            .index(reference)
            .and_then(|index| index.expand(reference, token, budget));
        self.session.record_read(
            &serde_json::json!({"op":"expand","reference":reference,"token":token,"budget":budget}),
            &result,
        )?;
        let page = result?;
        self.save(Some(reference.clone()), None, page.next.clone())?;
        Ok(page)
    }
    /// Inspects retained evidence and focuses it, even when it is historical.
    pub fn inspect(
        &self,
        reference: &Reference,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Inspection, SurfaceError> {
        let result = self
            .index(reference)
            .and_then(|index| index.inspect(reference, token, budget));
        self.session.record_read(
            &serde_json::json!({"op":"inspect","reference":reference,"token":token,"budget":budget}),
            &result,
        )?;
        let detail = result?;
        self.save(None, Some(reference.clone()), detail.next.clone())?;
        Ok(detail)
    }
    /// Selects validated retained evidence without reading it or acquiring action authority.
    pub fn focus(&self, reference: &Reference) -> Result<(), SurfaceError> {
        self.index(reference)?.validate(reference)?;
        self.save(None, Some(reference.clone()), None)
    }
    fn save(
        &self,
        scope: Option<Reference>,
        focus: Option<Reference>,
        continuation: Option<Continuation>,
    ) -> Result<(), SurfaceError> {
        let mut state = self.session.lock()?;
        let reader = state
            .readers
            .get_mut(&self.id)
            .ok_or(SurfaceError::Unknown)?;
        if scope.is_some() {
            reader.position.scope = scope;
        }
        if focus.is_some() {
            reader.position.focus = focus;
        }
        reader.position.continuation = continuation;
        drop(state);
        Ok(())
    }
    /// Subscribes to one captured region, independently of scope and focus.
    /// This registers a logical watch; the external adapter owns event collection.
    pub fn subscribe(&self, reference: &Reference) -> Result<WatchId, SurfaceError> {
        let mut state = self.session.lock()?;
        state.index(reference)?.validate(reference)?;
        if !state.readers.contains_key(&self.id) {
            return Err(SurfaceError::Unknown);
        }
        if state.watches.len() >= state.policy.watches {
            return Err(SurfaceError::Limit("watch count"));
        }
        let pending = reference.capture != state.current()?.identity();
        let id = WatchId(state.allocate()?);
        state.watches.insert(
            id,
            Watch {
                cursor: self.id,
                reference: reference.clone(),
                pending,
            },
        );
        drop(state);
        Ok(id)
    }
    /// Explicitly compares a caller-selected replacement region with the watched evidence.
    /// Selection is not proof of entity identity. Missing history or coverage emits `Unknown`.
    pub fn reconcile(
        &self,
        watch_id: WatchId,
        replacement: &Reference,
    ) -> Result<EventKind, SurfaceError> {
        let mut state = self.session.lock()?;
        if state.uncertain {
            return Err(SurfaceError::Uncertain);
        }
        let current = state.current()?.clone();
        current.validate(replacement)?;
        let watch = state
            .watches
            .get(&watch_id)
            .filter(|watch| watch.cursor == self.id)
            .ok_or(SurfaceError::Unknown)?;
        let previous = watch.reference.clone();
        let kind = match state.index(&previous) {
            Ok(old) if old.coverage().complete && current.coverage().complete => {
                let previous_content = old.comparison_digest(previous.node)?;
                let replacement_content = current.comparison_digest(replacement.node)?;
                if old.representation() == current.representation()
                    && previous_content == replacement_content
                {
                    EventKind::Unchanged
                } else {
                    EventKind::Changed
                }
            }
            _ => EventKind::Unknown,
        };
        let watch = state
            .watches
            .get_mut(&watch_id)
            .ok_or(SurfaceError::Unknown)?;
        watch.reference = replacement.clone();
        watch.pending = false;
        state.emit(kind,Some(self.id),Some(watch_id),Some(previous),Some(replacement.clone()),"caller-selected region reconciliation; equality compares captured content, not durable entity identity")?;
        drop(state);
        Ok(kind)
    }
    /// Removes this cursor's subscription without moving its position.
    pub fn unsubscribe(&self, watch: WatchId) -> Result<(), SurfaceError> {
        let mut state = self.session.lock()?;
        if state
            .watches
            .get(&watch)
            .is_none_or(|watch| watch.cursor != self.id)
        {
            return Err(SurfaceError::Unknown);
        }
        state.watches.remove(&watch);
        drop(state);
        Ok(())
    }
    /// Reads this cursor's event window without consuming another reader's events.
    pub fn events(&self) -> Result<EventBatch, SurfaceError> {
        let mut state = self.session.lock()?;
        let last = state
            .readers
            .get(&self.id)
            .ok_or(SurfaceError::Unknown)?
            .last_event;
        let lost = state
            .events
            .front()
            .is_some_and(|first| first.sequence > last.saturating_add(1));
        let events = state
            .events
            .iter()
            .filter(|event| {
                event.sequence > last && (event.cursor.is_none() || event.cursor == Some(self.id))
            })
            .cloned()
            .collect();
        let latest = state.event_sequence;
        state
            .readers
            .get_mut(&self.id)
            .ok_or(SurfaceError::Unknown)?
            .last_event = latest;
        drop(state);
        Ok(EventBatch { events, lost })
    }
    /// Acquires the single hot capability. Final target validation still belongs to the effect adapter.
    pub fn promote(&self) -> Result<(), SurfaceError> {
        let mut state = self.session.lock()?;
        if !state.live {
            return Err(SurfaceError::Detached);
        }
        if !state.readers.contains_key(&self.id) {
            return Err(SurfaceError::Unknown);
        }
        if state.flight.is_some() {
            return Err(SurfaceError::ActionInFlight);
        }
        if state.hot.is_some_and(|owner| owner != self.id) {
            return Err(SurfaceError::HotOwned);
        }
        state.hot = Some(self.id);
        drop(state);
        Ok(())
    }
    /// Releases hot ownership, retaining subscriptions and reading position.
    pub fn cool(&self) -> Result<(), SurfaceError> {
        let mut state = self.session.lock()?;
        if state.flight.is_some() {
            return Err(SurfaceError::ActionInFlight);
        }
        if state.hot != Some(self.id) {
            return Err(SurfaceError::ReaderOnly);
        }
        state.hot = None;
        drop(state);
        Ok(())
    }
    /// Opens an exclusive effect lease after current-capture and coverage checks.
    /// Call `revalidate` immediately before the external effect; this SDK does not click.
    pub fn begin_action(&self) -> Result<ActionLease, SurfaceError> {
        let mut state = self.session.lock()?;
        if !state.live {
            return Err(SurfaceError::Detached);
        }
        if state.hot != Some(self.id) {
            return Err(SurfaceError::ReaderOnly);
        }
        if state.flight.is_some() {
            return Err(SurfaceError::ActionInFlight);
        }
        if state.uncertain {
            return Err(SurfaceError::Uncertain);
        }
        let target = state
            .readers
            .get(&self.id)
            .and_then(|reader| reader.position.focus.clone())
            .ok_or(SurfaceError::Unknown)?;
        let current = state.current()?;
        if current.identity() != target.capture {
            return Err(SurfaceError::Stale);
        }
        current.validate(&target)?;
        if !current.coverage().complete {
            return Err(SurfaceError::Uncertain);
        }
        let action = state.allocate()?;
        let revision = state.revision;
        state.flight = Some((self.id, action));
        drop(state);
        Ok(ActionLease {
            session: self.session.clone(),
            cursor: self.id,
            action,
            revision,
            target,
            dispatched: false,
            finished: false,
        })
    }
    /// Closes this logical cursor and its watches; clones then return `Unknown`.
    pub fn close(&self) -> Result<(), SurfaceError> {
        let mut state = self.session.lock()?;
        if state.flight.is_some_and(|(owner, _)| owner == self.id) {
            return Err(SurfaceError::ActionInFlight);
        }
        state
            .readers
            .remove(&self.id)
            .ok_or(SurfaceError::Unknown)?;
        state.watches.retain(|_, watch| watch.cursor != self.id);
        if state.hot == Some(self.id) {
            state.hot = None;
        }
        drop(state);
        Ok(())
    }
}

/// Exclusive action lifetime; dropping it preserves uncertainty rather than claiming success.
#[derive(Debug)]
pub struct ActionLease {
    session: Session,
    cursor: CursorId,
    action: u64,
    revision: u64,
    target: Reference,
    dispatched: bool,
    finished: bool,
}
impl ActionLease {
    /// Rechecks SDK authority and exact capture freshness before an external effect.
    /// The adapter must additionally check its live node, visibility, and eligibility.
    pub fn revalidate(&self) -> Result<&Reference, SurfaceError> {
        let state = self.session.lock()?;
        if !state.live {
            return Err(SurfaceError::Detached);
        }
        if state.uncertain {
            return Err(SurfaceError::Uncertain);
        }
        if state.hot != Some(self.cursor) {
            return Err(SurfaceError::ReaderOnly);
        }
        if state.flight != Some((self.cursor, self.action)) {
            return Err(SurfaceError::Stale);
        }
        if state
            .readers
            .get(&self.cursor)
            .and_then(|reader| reader.position.focus.as_ref())
            != Some(&self.target)
        {
            return Err(SurfaceError::Stale);
        }
        if state.revision != self.revision || state.current()?.identity() != self.target.capture {
            return Err(SurfaceError::Stale);
        }
        drop(state);
        Ok(&self.target)
    }
    /// Records dispatch before calling the effect adapter, conservatively preserving uncertainty.
    pub fn mark_dispatched(&mut self) -> Result<(), SurfaceError> {
        self.revalidate()?;
        if self.dispatched {
            return Err(SurfaceError::Invalid(
                "effect already marked dispatched".into(),
            ));
        }
        self.dispatched = true;
        if let Some(outcome) = &mut self.session.lock()?.outcome {
            outcome.receipt(
                "surface.dispatch",
                OperationStatus::Unknown,
                serde_json::json!({"target":self.target,"cursor":self.cursor,"dispatched":true}),
            );
        }
        Ok(())
    }
    /// Finishes with an adapter-reported outcome. A dispatched action cannot become `Rejected`.
    pub fn finish(
        mut self,
        status: ActionStatus,
        note: impl Into<String>,
    ) -> Result<ActionReceipt, SurfaceError> {
        if status == ActionStatus::Confirmed && !self.dispatched
            || status == ActionStatus::Rejected && self.dispatched
        {
            return Err(SurfaceError::Invalid(
                "status contradicts dispatch evidence".into(),
            ));
        }
        let note = note.into();
        let mut state = self.session.lock()?;
        let receipt = ActionReceipt {
            cursor: self.cursor,
            target: self.target.clone(),
            dispatched: self.dispatched,
            status,
            after_capture: state.current().ok().map(|index| index.identity().into()),
            note: note.clone(),
        };
        if let Some(outcome) = &mut state.outcome {
            let certainty = match status {
                ActionStatus::Confirmed => OperationStatus::Observed,
                ActionStatus::Rejected => OperationStatus::Rejected,
                ActionStatus::Unconfirmed => OperationStatus::Unknown,
            };
            outcome.receipt(
                "surface.action",
                certainty,
                serde_json::to_value(&receipt)
                    .map_err(|error| SurfaceError::Parse(error.to_string()))?,
            );
        }
        if state.flight == Some((self.cursor, self.action)) {
            state.flight = None;
        }
        state.emit(
            EventKind::ActionFinished,
            Some(self.cursor),
            None,
            Some(self.target.clone()),
            None,
            &format!("{status:?}; dispatched={}; {note}", self.dispatched),
        )?;
        self.finished = true;
        drop(state);
        Ok(receipt)
    }
}
impl Drop for ActionLease {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        if let Ok(mut state) = self.session.state.lock()
            && state.flight == Some((self.cursor, self.action))
        {
            state.flight = None;
            let note = if self.dispatched {
                "lease dropped after dispatch; outcome unconfirmed"
            } else {
                "lease abandoned before recorded dispatch"
            };
            if let Some(outcome) = &mut state.outcome {
                let certainty = if self.dispatched {
                    OperationStatus::Unknown
                } else {
                    OperationStatus::Rejected
                };
                outcome.receipt("surface.action", certainty, serde_json::json!({"target":self.target,"cursor":self.cursor,"dispatched":self.dispatched,"note":note}));
            }
            let _ = state.emit(
                EventKind::ActionFinished,
                Some(self.cursor),
                None,
                Some(self.target.clone()),
                None,
                note,
            );
        }
    }
}
