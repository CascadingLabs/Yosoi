//! Operational state for policy.respectfulness, stored through Registry CAS.

use std::{
    collections::BTreeMap,
    future::pending,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crate::internal::types::Sha256Digest;
use chrono::DateTime;
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::{
    task::spawn_blocking,
    time::{Instant, timeout_at},
};
use tokio_util::sync::CancellationToken;
use url::Url;
use uuid::Uuid;

use crate::{
    policy::respectfulness::{Group, Respectfulness, Unmatched},
    registry::{Change, Registry, RegistryError, Reservation, Snapshot, TransactionContext},
};

/// Why matching traffic cannot start. These reasons never authorize dispatch.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LimitReason {
    /// The group is explicitly blocked by policy.
    Blocked,
    /// A response-driven cooldown has not elapsed.
    Cooldown,
    /// Too many requests still hold unexpired leases.
    Concurrency,
    /// The next permitted start has not arrived.
    Spacing,
    /// At least one rolling-window budget is exhausted.
    RateBudget,
}

/// Failures in matching, coordination or admission. No automatic registry
/// fallback or unchecked send occurs after one of these errors.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize, Error)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RespectfulnessError {
    /// A matched constraint rejected dispatch; an absent time means an authored block.
    #[error("respectfulness group {group} rejected dispatch: {reason:?}")]
    Limited {
        /// Stable group ID, without retaining the requested URL.
        group: String,
        /// Constraint requiring the rejection.
        reason: LimitReason,
        /// Earliest known eligibility in Unix milliseconds; concurrent calls may consume it.
        next_eligible_at_ms: Option<u64>,
    },
    /// Policy requires explicit pattern coverage and no group matched.
    #[error("URL matches no respectfulness group")]
    Unmatched,
    /// A supported pre-dispatch interception boundary is unavailable.
    #[error("browser per-request respectfulness enforcement is unavailable")]
    UnsupportedBrowser,
    /// A stable group ID was reused with different settings in shared state.
    #[error("respectfulness group {group} has a different registered configuration")]
    ConfigurationMismatch {
        /// Group whose stored configuration must be reviewed, not reset silently.
        group: String,
    },
    /// Backend failures remain distinct from exhausted traffic budgets.
    #[error("respectfulness registry failure ({variant}): {message}")]
    Registry {
        /// Original Registry error variant, including Busy and Conflict.
        variant: String,
        /// Source error description, retained without a request URL.
        message: String,
    },
    /// Persisted operational DTOs are malformed or incompatible.
    #[error("invalid respectfulness registry state")]
    InvalidState,
    /// Invalid runtime policy, clock, expiry or arithmetic bound.
    #[error("respectfulness setup failed: {message}")]
    Setup {
        /// Concrete setup error, without a requested URL.
        message: String,
    },
}

impl From<RegistryError> for RespectfulnessError {
    fn from(error: RegistryError) -> Self {
        let variant = match &error {
            RegistryError::Conflict => "Conflict",
            RegistryError::Busy => "Busy",
            RegistryError::InvalidKey => "InvalidKey",
            RegistryError::InvalidState => "InvalidState",
            RegistryError::CapacityExceeded => "CapacityExceeded",
            RegistryError::NoGlobalLocation => "NoGlobalLocation",
            RegistryError::Io(_) => "Io",
            RegistryError::Json(_) => "Json",
        }
        .to_owned();
        Self::Registry {
            variant,
            message: error.to_string(),
        }
    }
}

#[derive(Clone, Debug)]
struct CompiledGroup {
    group: Group,
    patterns: Vec<Regex>,
    identity: String,
}

#[derive(Debug)]
struct Inner {
    policy: Respectfulness,
    groups: Vec<CompiledGroup>,
    registry: Registry,
}

#[derive(Clone, Debug)]
pub struct Runtime(Arc<Inner>);

impl PartialEq for Runtime {
    fn eq(&self, other: &Self) -> bool {
        self.0.policy == other.0.policy
            && self.0.registry.caller() == other.0.registry.caller()
            && self.0.registry.path() == other.0.registry.path()
    }
}
impl Eq for Runtime {}

/// Content-free traffic accounting retained with a Request response.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    /// Transition observed at the admission/transport boundary.
    pub kind: EventKind,
    /// Applicable stable group IDs; no URL, query or credentials are retained.
    pub groups: Vec<String>,
    /// Logical Registry identity when admission accessed shared state.
    pub registry_id: Option<String>,
    /// HTTP response status, when a head was observed.
    pub status: Option<u16>,
    /// Detailed rejection/backend failure, if present.
    pub error: Option<RespectfulnessError>,
}

/// Admission, feedback and cleanup transitions, distinct from provider outcomes.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    /// A start was charged before dispatch; cancellation does not refund it.
    Admitted,
    /// A response head was observed and feedback was processed.
    Response,
    /// An explicit policy retry will seek fresh admission.
    Retry,
    /// Active capacity was released after transport/body completion.
    Released,
    /// No unchecked send is permitted following this error.
    Rejected,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct State {
    identity: String,
    observed_at_ms: u64,
    next_start_ms: u64,
    cooldown_until_ms: u64,
    starts: Vec<u64>,
    leases: BTreeMap<String, u64>,
}

/// A reservation is held until response-body completion or transport shutdown.
///
/// Explicit finish reports release errors. Abandoned futures leave a bounded
/// lease, recovered after expiry; no asynchronous work is started from Drop.
#[derive(Clone, Debug)]
pub struct Permit {
    runtime: Runtime,
    id: String,
    groups: Vec<String>,
    pub registry_id: Option<String>,
    pub expires_at_ms: u64,
}

/// A decision against one snapshot, committed by the consumer before dispatch.
#[derive(Debug)]
pub struct AdmissionPlan {
    pub changes: Vec<Change>,
    pub context: TransactionContext,
    pub permit: Permit,
}

impl Runtime {
    pub fn new(policy: Respectfulness, registry: Registry) -> Result<Self, RespectfulnessError> {
        policy
            .validate()
            .map_err(|error| setup(error.to_string()))?;
        let groups = policy
            .groups
            .iter()
            .map(|group| {
                let patterns = group
                    .patterns
                    .iter()
                    .map(|pattern| {
                        RegexBuilder::new(pattern)
                            .size_limit(1024 * 1024)
                            .build()
                            .map_err(|_| setup("invalid URL regex"))
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                let encoded =
                    serde_json::to_vec(group).map_err(|_| RespectfulnessError::InvalidState)?;
                let identity = Sha256Digest::from_bytes(Sha256::digest(encoded).into()).to_string();
                Ok(CompiledGroup {
                    group: group.clone(),
                    patterns,
                    identity,
                })
            })
            .collect::<Result<Vec<_>, RespectfulnessError>>()?;
        Ok(Self(Arc::new(Inner {
            policy,
            groups,
            registry,
        })))
    }

    pub fn policy(&self) -> &Respectfulness {
        &self.0.policy
    }

    fn matched(&self, target: &str) -> Result<Vec<&CompiledGroup>, RespectfulnessError> {
        let url = canonical_url(target)?;
        let groups: Vec<_> = self
            .0
            .groups
            .iter()
            .filter(|group| group.patterns.iter().any(|pattern| pattern.is_match(&url)))
            .collect();
        if groups.is_empty() && self.0.policy.unmatched == Unmatched::Reject {
            return Err(RespectfulnessError::Unmatched);
        }
        Ok(groups)
    }

    pub fn reserve_at(
        &self,
        target: &str,
        now_ms: u64,
        expires_at_ms: u64,
    ) -> Result<Permit, RespectfulnessError> {
        // A Conflict proves the revision changed. Reevaluate all constraints;
        // this never polls unchanged state or starts an HTTP retry.
        for _ in 0..8 {
            match self.reserve_once(target, now_ms, expires_at_ms) {
                Err(error) if registry_conflict(&error) => {}
                result => return result,
            }
        }
        Err(setup(
            "registry admission contention exceeded its bounded reevaluation budget",
        ))
    }

    fn reserve_once(
        &self,
        target: &str,
        now_ms: u64,
        expires_at_ms: u64,
    ) -> Result<Permit, RespectfulnessError> {
        if expires_at_ms <= now_ms {
            return Err(setup("reservation deadline has elapsed"));
        }
        if self.matched(target)?.is_empty() {
            return Ok(Permit {
                runtime: self.clone(),
                id: Uuid::new_v4().to_string(),
                groups: Vec::new(),
                registry_id: None,
                expires_at_ms,
            });
        }
        let snapshot = self.0.registry.snapshot()?;
        let plan = self.plan_at(&snapshot, target, now_ms, expires_at_ms)?;
        self.0
            .registry
            .commit_with_context(&snapshot.revision, &plan.changes, &plan.context)?;
        Ok(plan.permit)
    }

    pub fn plan_at(
        &self,
        snapshot: &Snapshot,
        target: &str,
        now_ms: u64,
        expires_at_ms: u64,
    ) -> Result<AdmissionPlan, RespectfulnessError> {
        if expires_at_ms <= now_ms {
            return Err(setup("reservation deadline has elapsed"));
        }
        let groups = self.matched(target)?;
        let id = Uuid::new_v4().to_string();
        if groups.is_empty() {
            return Ok(AdmissionPlan {
                changes: Vec::new(),
                context: TransactionContext::default(),
                permit: Permit {
                    runtime: self.clone(),
                    id,
                    groups: Vec::new(),
                    registry_id: None,
                    expires_at_ms,
                },
            });
        }
        let mut changes = Vec::new();
        for compiled in &groups {
            let mut state = load_state(snapshot.entries.get(&key(&compiled.group.id)), compiled)?;
            let now = now_ms.max(state.observed_at_ms);
            if expires_at_ms <= now {
                return Err(setup("clock rollback exceeds the request lease"));
            }
            state.observed_at_ms = now;
            state.leases.retain(|_, until| *until > now);
            let group = &compiled.group;
            let limited = |reason, next_eligible_at_ms| RespectfulnessError::Limited {
                group: group.id.clone(),
                reason,
                next_eligible_at_ms,
            };
            if group.blocked {
                return Err(limited(LimitReason::Blocked, None));
            }
            if state.cooldown_until_ms > now {
                return Err(limited(
                    LimitReason::Cooldown,
                    Some(state.cooldown_until_ms),
                ));
            }
            if let Some(limit) = group.concurrency
                && state.leases.len()
                    >= usize::try_from(limit).map_err(|_| setup("invalid concurrency"))?
            {
                return Err(limited(
                    LimitReason::Concurrency,
                    state.leases.values().min().copied(),
                ));
            }
            if state.next_start_ms > now {
                return Err(limited(LimitReason::Spacing, Some(state.next_start_ms)));
            }
            let longest_window = group
                .budgets
                .iter()
                .map(|budget| budget.window_ms)
                .max()
                .unwrap_or(0);
            state
                .starts
                .retain(|start| start.saturating_add(longest_window) > now);
            for budget in &group.budgets {
                let starts: Vec<_> = state
                    .starts
                    .iter()
                    .copied()
                    .filter(|start| start.saturating_add(budget.window_ms) > now)
                    .collect();
                if starts.len()
                    >= usize::try_from(budget.requests).map_err(|_| setup("invalid budget"))?
                {
                    return Err(limited(
                        LimitReason::RateBudget,
                        starts
                            .first()
                            .and_then(|first| first.checked_add(budget.window_ms)),
                    ));
                }
            }
            if state.leases.len() >= 128 {
                return Err(setup("respectfulness lease storage is full"));
            }
            if longest_window > 0 {
                state.starts.push(now);
            }
            state.next_start_ms = now
                .checked_add(group.spacing_ms.unwrap_or(0))
                .ok_or_else(|| setup("spacing overflow"))?;
            state.leases.insert(id.clone(), expires_at_ms);
            changes.push(Change::Put {
                key: key(&group.id),
                value: serde_json::to_value(state)
                    .map_err(|_| RespectfulnessError::InvalidState)?,
            });
        }
        let context = TransactionContext {
            operation: "respectfulness.reserve".to_owned(),
            resources: groups.iter().map(|group| key(&group.group.id)).collect(),
            reservation: Some(reservation(&id, expires_at_ms)?),
        };
        Ok(AdmissionPlan {
            changes,
            context,
            permit: Permit {
                runtime: self.clone(),
                id,
                groups: groups.iter().map(|g| g.group.id.clone()).collect(),
                registry_id: Some(snapshot.revision.registry_id.clone()),
                expires_at_ms,
            },
        })
    }
}

impl Permit {
    /// Release all matching scopes and record feedback in one CAS transaction.
    /// No start budget or pacing is refunded, including caller cancellation.
    pub fn finish_at(
        self,
        now_ms: u64,
        status: Option<u16>,
        retry_after: Option<&str>,
        transport_error: bool,
    ) -> Result<(), RespectfulnessError> {
        self.update_at(now_ms, status, retry_after, transport_error, true)
    }

    pub fn observe_at(
        &self,
        now_ms: u64,
        status: Option<u16>,
        retry_after: Option<&str>,
        transport_error: bool,
    ) -> Result<(), RespectfulnessError> {
        self.update_at(now_ms, status, retry_after, transport_error, false)
    }

    fn update_at(
        &self,
        now_ms: u64,
        status: Option<u16>,
        retry_after: Option<&str>,
        transport_error: bool,
        release: bool,
    ) -> Result<(), RespectfulnessError> {
        for _ in 0..8 {
            match self.update_once(now_ms, status, retry_after, transport_error, release) {
                Err(error) if registry_conflict(&error) => {}
                result => return result,
            }
        }
        Err(setup(
            "registry feedback contention exceeded its bounded reevaluation budget",
        ))
    }

    fn update_once(
        &self,
        now_ms: u64,
        status: Option<u16>,
        retry_after: Option<&str>,
        transport_error: bool,
        release: bool,
    ) -> Result<(), RespectfulnessError> {
        if self.groups.is_empty() {
            return Ok(());
        }
        let snapshot = self.runtime.0.registry.snapshot()?;
        let mut changes = Vec::new();
        for id in &self.groups {
            let compiled = self
                .runtime
                .0
                .groups
                .iter()
                .find(|group| &group.group.id == id)
                .ok_or(RespectfulnessError::InvalidState)?;
            let mut state = load_state(snapshot.entries.get(&key(id)), compiled)?;
            let now = now_ms.max(state.observed_at_ms);
            state.observed_at_ms = now;
            if release {
                state.leases.remove(&self.id);
            }
            if let Some(cooldown) = &compiled.group.cooldown
                && (status.is_some_and(|code| cooldown.statuses.contains(&code))
                    || (transport_error && cooldown.transport_errors))
            {
                let until = match retry_after.and_then(|value| retry_after_at(value, now)) {
                    Some(until) => until,
                    None => now
                        .checked_add(cooldown.fallback_ms)
                        .ok_or_else(|| setup("cooldown overflow"))?,
                };
                state.cooldown_until_ms = state.cooldown_until_ms.max(until);
            }
            changes.push(Change::Put {
                key: key(id),
                value: serde_json::to_value(state)
                    .map_err(|_| RespectfulnessError::InvalidState)?,
            });
        }
        let context = TransactionContext {
            operation: if release {
                "respectfulness.release"
            } else {
                "respectfulness.feedback"
            }
            .to_owned(),
            resources: self.groups.iter().map(|group| key(group)).collect(),
            reservation: Some(reservation(&self.id, self.expires_at_ms)?),
        };
        self.runtime
            .0
            .registry
            .commit_with_context(&snapshot.revision, &changes, &context)?;
        Ok(())
    }
}

mod operation;
pub use operation::Operation;

pub async fn resolve_registry(
    policy: Option<&Respectfulness>,
    registry: Option<&Registry>,
    cancellation: &CancellationToken,
    deadline: Option<Instant>,
) -> Result<Option<Registry>, RespectfulnessError> {
    if cancellation.is_cancelled() || deadline.is_some_and(|at| Instant::now() >= at) {
        return Ok(None);
    }
    if let Some(registry) = registry {
        return Ok(Some(registry.clone()));
    }
    let path = policy.and_then(|policy| policy.registry_path.clone());
    let mut task = spawn_blocking(move || path.map_or_else(Registry::new, Registry::jsonl));
    let deadline_signal = async {
        if let Some(at) = deadline {
            let _ = timeout_at(at, pending::<()>()).await;
        } else {
            pending::<()>().await;
        }
    };
    tokio::select! {
        biased;
        () = cancellation.cancelled() => { task.abort(); Ok(None) },
        () = deadline_signal => { task.abort(); Ok(None) },
        result = &mut task => result
            .map_err(|error| setup(format!("registry setup task failed: {error}")))?
            .map(Some).map_err(RespectfulnessError::from),
    }
}

fn reservation(id: &str, expires_at_ms: u64) -> Result<Reservation, RespectfulnessError> {
    let id = Uuid::parse_str(id).map_err(|_| RespectfulnessError::InvalidState)?;
    let timestamp = i64::try_from(expires_at_ms).map_err(|_| setup("lease timestamp overflow"))?;
    let expires_at = DateTime::from_timestamp_millis(timestamp)
        .ok_or_else(|| setup("invalid lease timestamp"))?;
    Ok(Reservation { id, expires_at })
}

fn key(id: &str) -> String {
    format!("respectfulness/v1/group/{id}")
}

fn load_state(
    value: Option<&serde_json::Value>,
    group: &CompiledGroup,
) -> Result<State, RespectfulnessError> {
    let state = match value {
        Some(value) => serde_json::from_value::<State>(value.clone())
            .map_err(|_| RespectfulnessError::InvalidState)?,
        None => State {
            identity: group.identity.clone(),
            ..State::default()
        },
    };
    if state.identity != group.identity {
        return Err(RespectfulnessError::ConfigurationMismatch {
            group: group.group.id.clone(),
        });
    }
    if state.starts.len() > 512 || state.leases.len() > 128 {
        return Err(RespectfulnessError::InvalidState);
    }
    Ok(state)
}

fn setup(message: impl Into<String>) -> RespectfulnessError {
    RespectfulnessError::Setup {
        message: message.into(),
    }
}

pub fn now_ms() -> Result<u64, RespectfulnessError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| setup("clock precedes Unix epoch"))?;
    u64::try_from(elapsed.as_millis()).map_err(|_| setup("clock exceeds supported range"))
}

pub fn expiry(now: u64, remaining: Duration) -> Result<u64, RespectfulnessError> {
    let duration = u64::try_from(remaining.as_millis().saturating_add(1))
        .map_err(|_| setup("deadline exceeds supported range"))?;
    now.checked_add(duration.max(1))
        .ok_or_else(|| setup("deadline overflow"))
}

pub fn canonical_url(target: &str) -> Result<String, RespectfulnessError> {
    let mut url = Url::parse(target).map_err(|_| setup("invalid HTTP URL"))?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(setup("canonical HTTP URL without credentials is required"));
    }
    if let Some(host) = url.host_str() {
        let canonical = host.trim_end_matches('.').to_owned();
        url.set_host(Some(&canonical))
            .map_err(|_| setup("invalid hostname"))?;
    }
    url.set_fragment(None);
    Ok(url.into())
}

pub fn retry_after_at(value: &str, now: u64) -> Option<u64> {
    if let Ok(seconds) = value.trim().parse::<u64>() {
        return now.checked_add(seconds.checked_mul(1000)?);
    }
    let parsed = DateTime::parse_from_rfc2822(value.trim())
        .ok()?
        .timestamp_millis();
    Some(u64::try_from(parsed).ok()?.max(now))
}

#[cfg(test)]
mod tests;

fn registry_conflict(error: &RespectfulnessError) -> bool {
    matches!(error, RespectfulnessError::Registry { variant, .. } if variant == "Conflict")
}
