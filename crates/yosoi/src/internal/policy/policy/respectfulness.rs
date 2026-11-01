//! Declarative traffic matching and constraints; mutable state belongs to Registry.

use std::{collections::BTreeSet, path::PathBuf};

use regex::RegexBuilder;
use serde::{Deserialize, Serialize};

use crate::internal::policy::PolicyError;

/// Traffic rules applied by Requests and Search when explicitly supplied.
///
/// Any pattern within a group matches; every matching group constrains the
/// outgoing request. Groups share a budget across all their matching URLs.
/// No provider searches or health probes are performed to establish eligibility.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Respectfulness {
    /// JSONL registry file; absent selects the standard per-user state file.
    /// An explicitly bound runtime Registry overrides this location.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub registry_path: Option<PathBuf>,
    /// Stable named groups; identity/configuration changes are explicit.
    pub groups: Vec<Group>,
    /// Treatment of canonical URLs that match no group.
    #[serde(default)]
    pub unmatched: Unmatched,
    /// Explicit bounded HTTP retries, each subject to fresh admission.
    #[serde(default)]
    pub retry: Retry,
}

impl Respectfulness {
    /// Creates and validates groups with unmatched URLs allowed and no retries.
    pub fn new(groups: Vec<Group>) -> Result<Self, PolicyError> {
        let policy = Self {
            registry_path: None,
            groups,
            unmatched: Unmatched::Allow,
            retry: Retry::default(),
        };
        policy.validate()?;
        Ok(policy)
    }

    pub(crate) fn validate(&self) -> Result<(), PolicyError> {
        let invalid = |message: &str| PolicyError::InvalidRespectfulness(message.to_owned());
        if self
            .registry_path
            .as_ref()
            .is_some_and(|path| path.as_os_str().is_empty())
        {
            return Err(invalid("registry path must not be empty"));
        }
        if self.groups.is_empty() || self.groups.len() > 32 {
            return Err(invalid("respectfulness requires 1..=32 groups"));
        }
        let mut names = BTreeSet::new();
        for group in &self.groups {
            if group.id.is_empty()
                || group.id.len() > 128
                || group.id.chars().any(char::is_control)
                || !names.insert(&group.id)
            {
                return Err(invalid(
                    "group IDs must be distinct, nonempty, bounded and free of controls",
                ));
            }
            if group.patterns.is_empty() || group.patterns.len() > 8 {
                return Err(invalid("groups require 1..=8 URL regexes"));
            }
            for pattern in &group.patterns {
                if pattern.is_empty() || pattern.len() > 2048 {
                    return Err(invalid("URL regex must contain 1..=2048 UTF-8 bytes"));
                }
                RegexBuilder::new(pattern)
                    .size_limit(1024 * 1024)
                    .build()
                    .map_err(|_| invalid("invalid or oversized URL regex"))?;
            }
            if group
                .concurrency
                .is_some_and(|value| value == 0 || value > 128)
                || group
                    .spacing_ms
                    .is_some_and(|value| value == 0 || value > DAY_MS)
                || group.budgets.len() > 8
            {
                return Err(invalid(
                    "concurrency must be 1..=128, spacing 1ms..=1 day, and at most 8 budgets",
                ));
            }
            for budget in &group.budgets {
                if budget.requests == 0
                    || budget.requests > 512
                    || budget.window_ms == 0
                    || budget.window_ms > DAY_MS
                {
                    return Err(invalid(
                        "rolling budgets require 1..=512 starts in a window of 1ms..=1 day",
                    ));
                }
            }
            if let Some(cooldown) = &group.cooldown
                && (cooldown.fallback_ms == 0
                    || cooldown.fallback_ms > DAY_MS
                    || cooldown.statuses.is_empty()
                    || cooldown.statuses.len() > 32
                    || cooldown
                        .statuses
                        .iter()
                        .any(|status| !(400..=599).contains(status)))
            {
                return Err(invalid(
                    "cooldown requires error statuses and a fallback of 1ms..=1 day",
                ));
            }
            if !group.blocked
                && group.concurrency.is_none()
                && group.spacing_ms.is_none()
                && group.budgets.is_empty()
                && group.cooldown.is_none()
            {
                return Err(invalid(
                    "each group must declare a constraint or cooldown reaction",
                ));
            }
        }
        if self.retry.max_attempts == 0
            || self.retry.max_attempts > 8
            || self.retry.backoff_ms > DAY_MS
            || self
                .retry
                .statuses
                .iter()
                .any(|status| !(400..=599).contains(status))
            || self.retry.statuses.len() > 32
            || (self.retry.max_attempts > 1
                && (self.retry.backoff_ms == 0
                    || (self.retry.statuses.is_empty() && !self.retry.transport_errors)))
        {
            return Err(invalid(
                "retry requires 1..=8 attempts and explicit bounded backoff/error conditions",
            ));
        }
        Ok(())
    }
}

pub const DAY_MS: u64 = 86_400_000;

/// Treatment of requests that match none of the authored URL patterns.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Unmatched {
    /// Permit the request without creating group reservations.
    #[default]
    Allow,
    /// Reject before dispatch, making regex coverage explicit.
    Reject,
}

/// One shared budget for a named set of canonical URL regexes.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Group {
    /// Stable nonsensitive ID used as a Registry key; not a URL or query log.
    pub id: String,
    /// Rust regexes over canonical HTTP(S) URLs, with query retained and fragment removed.
    pub patterns: Vec<String>,
    /// Maximum active requests across matching destinations, at most 128.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub concurrency: Option<u32>,
    /// Minimum interval between starts, in positive milliseconds.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spacing_ms: Option<u64>,
    /// Simultaneous rolling-window start budgets; spacing controls burstiness separately.
    #[serde(default)]
    pub budgets: Vec<RateBudget>,
    /// Reactions to observed HTTP/transport failures; no invented provider defaults.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cooldown: Option<Cooldown>,
    /// Authored unconditional block for matching URLs.
    #[serde(default)]
    pub blocked: bool,
}

impl Group {
    /// Starts an unvalidated group. Author at least one constraint before using
    /// it in Respectfulness; complete Policy validation checks the whole value.
    pub fn new(
        id: impl Into<String>,
        patterns: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        Self {
            id: id.into(),
            patterns: patterns.into_iter().map(Into::into).collect(),
            concurrency: None,
            spacing_ms: None,
            budgets: Vec::new(),
            cooldown: None,
            blocked: false,
        }
    }
}

/// Maximum starts within the preceding window, including retries and redirects.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RateBudget {
    /// Positive permitted starts, capped at 512 to bound persisted history.
    pub requests: u32,
    /// Rolling duration in milliseconds, from 1ms through one day.
    pub window_ms: u64,
}

/// A temporary admission stop caused by observed server/transport feedback.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Cooldown {
    /// HTTP error statuses that trigger this group's cooldown, for example 429.
    pub statuses: Vec<u16>,
    /// Positive fallback milliseconds when no supported Retry-After is present.
    pub fallback_ms: u64,
    /// Also apply fallback after transport failures, excluding caller cancellation.
    #[serde(default)]
    pub transport_errors: bool,
}

/// Explicit retry behavior. The default makes one attempt, with no retry.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Retry {
    /// Total sends per URL, including the original, from 1 through 8.
    pub max_attempts: u8,
    /// HTTP error statuses eligible for another send.
    pub statuses: Vec<u16>,
    /// Constant backoff before another send, in milliseconds; required for retries.
    pub backoff_ms: u64,
    /// Permit retries after transport failures; cancellation/deadlines never retry.
    pub transport_errors: bool,
}

impl Default for Retry {
    fn default() -> Self {
        Self {
            max_attempts: 1,
            statuses: Vec::new(),
            backoff_ms: 0,
            transport_errors: false,
        }
    }
}
