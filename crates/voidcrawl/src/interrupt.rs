//! Explicit, caller-declared browser interruption lifecycle.
//!
//! This module deliberately has no login, CAPTCHA, or policy inference. A
//! caller declares an interruption for one CDP target and the owning
//! [`BrowserSession`](crate::BrowserSession) keeps that target parked until it
//! is resumed, released, or expires.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};

use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{Result, VoidCrawlError};

/// State of a caller-declared interrupt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InterruptState {
    Interrupted,
    Resumed,
    Released,
    Expired,
}

impl InterruptState {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Interrupted => "interrupted",
            Self::Resumed => "resumed",
            Self::Released => "released",
            Self::Expired => "expired",
        }
    }

    const fn terminal(self) -> bool {
        !matches!(self, Self::Interrupted)
    }
}

/// Non-secret metadata supplied when a caller parks a page.
#[derive(Debug, Clone)]
pub struct InterruptRequest {
    pub code: String,
    pub summary: String,
    pub ttl: Duration,
}

impl InterruptRequest {
    /// Validate a request before any browser state is changed.
    pub fn validate(&self) -> Result<()> {
        let code = self.code.as_bytes();
        let valid_code = !code.is_empty()
            && code.len() <= 128
            && code
                .first()
                .is_some_and(|byte| matches!(byte, b'a'..=b'z' | b'0'..=b'9'))
            && code
                .iter()
                .all(|byte| matches!(byte, b'a'..=b'z' | b'0'..=b'9' | b'.' | b'_' | b'-'));
        if !valid_code {
            return Err(VoidCrawlError::InvalidInterruptRequest(
                "code must be 1-128 lowercase policy characters".into(),
            ));
        }
        if self.summary.trim().is_empty() || self.summary.chars().count() > 512 {
            return Err(VoidCrawlError::InvalidInterruptRequest(
                "summary must be 1-512 non-blank characters".into(),
            ));
        }
        if self.ttl.is_zero() || self.ttl > Duration::from_secs(3600) {
            return Err(VoidCrawlError::InvalidInterruptRequest(
                "ttl must be between one second and one hour".into(),
            ));
        }
        Ok(())
    }
}

/// Redacted interrupt metadata safe to return to an operator.
#[derive(Debug, Clone)]
pub struct InterruptInfo {
    pub interrupt_id: String,
    pub target_id: String,
    pub code: String,
    pub summary: String,
    pub state: InterruptState,
    pub expires_in: Duration,
}

#[derive(Debug, Clone)]
struct InterruptRecord {
    info: InterruptInfo,
    expires_at: Instant,
}

/// Shared per-browser registry. Pages keep an `Arc` to this registry, so a
/// pause is observed by every page handle created by the owning session.
#[derive(Debug, Default)]
pub struct InterruptRegistry {
    records: Mutex<HashMap<String, InterruptRecord>>,
}

impl InterruptRegistry {
    #[must_use]
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    pub async fn interrupt(
        &self,
        target_id: String,
        request: InterruptRequest,
    ) -> Result<InterruptInfo> {
        request.validate()?;
        let mut records = self.records.lock().await;
        Self::expire_due(&mut records);
        if records.values().any(|record| {
            record.info.target_id == target_id && record.info.state == InterruptState::Interrupted
        }) {
            return Err(VoidCrawlError::InterruptAlreadyActive { target_id });
        }

        let expires_at = Instant::now().checked_add(request.ttl).ok_or_else(|| {
            VoidCrawlError::InvalidInterruptRequest("ttl exceeds the monotonic clock range".into())
        })?;
        let info = InterruptInfo {
            interrupt_id: Uuid::new_v4().to_string(),
            target_id,
            code: request.code,
            summary: request.summary,
            state: InterruptState::Interrupted,
            expires_in: request.ttl,
        };
        records.insert(
            info.interrupt_id.clone(),
            InterruptRecord {
                info: info.clone(),
                expires_at,
            },
        );
        drop(records);
        Ok(info)
    }

    pub async fn status(&self, interrupt_id: &str) -> Result<InterruptInfo> {
        let mut records = self.records.lock().await;
        Self::expire_due(&mut records);
        let record =
            records
                .get(interrupt_id)
                .ok_or_else(|| VoidCrawlError::InterruptNotFound {
                    interrupt_id: interrupt_id.into(),
                })?;
        let mut info = record.info.clone();
        if info.state == InterruptState::Interrupted {
            info.expires_in = record.expires_at.saturating_duration_since(Instant::now());
        }
        drop(records);
        Ok(info)
    }

    pub async fn resume(&self, interrupt_id: &str) -> Result<InterruptInfo> {
        self.transition(interrupt_id, InterruptState::Resumed).await
    }

    pub async fn release(&self, interrupt_id: &str) -> Result<InterruptInfo> {
        self.transition(interrupt_id, InterruptState::Released)
            .await
    }

    pub async fn page_is_active(&self, target_id: &str) -> Result<()> {
        let mut records = self.records.lock().await;
        Self::expire_due(&mut records);
        if let Some(record) = records.values().find(|record| {
            record.info.target_id == target_id && record.info.state == InterruptState::Interrupted
        }) {
            return Err(VoidCrawlError::SessionInterrupted {
                interrupt_id: record.info.interrupt_id.clone(),
            });
        }
        if let Some(record) = records.values().find(|record| {
            record.info.target_id == target_id && record.info.state == InterruptState::Expired
        }) {
            return Err(VoidCrawlError::InterruptExpired {
                interrupt_id: record.info.interrupt_id.clone(),
            });
        }
        drop(records);
        Ok(())
    }

    async fn transition(&self, interrupt_id: &str, next: InterruptState) -> Result<InterruptInfo> {
        let mut records = self.records.lock().await;
        Self::expire_due(&mut records);
        let record =
            records
                .get_mut(interrupt_id)
                .ok_or_else(|| VoidCrawlError::InterruptNotFound {
                    interrupt_id: interrupt_id.into(),
                })?;
        if record.info.state == InterruptState::Expired {
            return Err(VoidCrawlError::InterruptExpired {
                interrupt_id: interrupt_id.into(),
            });
        }
        if record.info.state.terminal() {
            return Err(VoidCrawlError::InterruptTerminal {
                interrupt_id: interrupt_id.into(),
                state: record.info.state.as_str().into(),
            });
        }
        record.info.state = next;
        record.info.expires_in = Duration::ZERO;
        let info = record.info.clone();
        drop(records);
        Ok(info)
    }

    fn expire_due(records: &mut HashMap<String, InterruptRecord>) {
        let now = Instant::now();
        for record in records.values_mut() {
            if record.info.state == InterruptState::Interrupted && now >= record.expires_at {
                record.info.state = InterruptState::Expired;
                record.info.expires_in = Duration::ZERO;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use tokio::time::{Instant, sleep_until};

    use super::{InterruptRegistry, InterruptRequest, InterruptState};
    use crate::VoidCrawlError;

    #[tokio::test]
    async fn resume_reactivates_target_without_dropping_record() -> crate::Result<()> {
        let registry = InterruptRegistry::new();
        let info = registry
            .interrupt(
                "target-1".into(),
                InterruptRequest {
                    code: "policy.review".into(),
                    summary: "Review required".into(),
                    ttl: Duration::from_secs(1),
                },
            )
            .await?;
        if registry.page_is_active("target-1").await.is_ok() {
            return Err(VoidCrawlError::Other("target should be interrupted".into()));
        }
        let resumed = registry.resume(&info.interrupt_id).await?;
        if resumed.state != InterruptState::Resumed {
            return Err(VoidCrawlError::Other("interrupt did not resume".into()));
        }
        if registry.page_is_active("target-1").await.is_err() {
            return Err(VoidCrawlError::Other(
                "resumed target should be active".into(),
            ));
        }
        if registry.resume(&info.interrupt_id).await.is_ok() {
            return Err(VoidCrawlError::Other(
                "terminal interrupt resumed unexpectedly".into(),
            ));
        }
        Ok(())
    }

    #[tokio::test]
    async fn expires_parked_target() -> crate::Result<()> {
        let registry = InterruptRegistry::new();
        let info = registry
            .interrupt(
                "target-1".into(),
                InterruptRequest {
                    code: "policy.review".into(),
                    summary: "Review required".into(),
                    ttl: Duration::from_millis(1),
                },
            )
            .await?;
        sleep_until(Instant::now() + Duration::from_millis(5)).await;
        let expired = registry.status(&info.interrupt_id).await?;
        if expired.state != InterruptState::Expired {
            return Err(VoidCrawlError::Other("interrupt did not expire".into()));
        }
        if !matches!(
            registry.page_is_active("target-1").await,
            Err(VoidCrawlError::InterruptExpired { .. })
        ) {
            return Err(VoidCrawlError::Other(
                "expired interrupt was not reported".into(),
            ));
        }
        if registry.resume(&info.interrupt_id).await.is_ok() {
            return Err(VoidCrawlError::Other(
                "expired interrupt resumed unexpectedly".into(),
            ));
        }
        Ok(())
    }

    #[tokio::test]
    async fn rejects_invalid_policy_code_and_unbounded_ttl() {
        let registry = InterruptRegistry::new();
        assert!(
            registry
                .interrupt(
                    "target-1".into(),
                    InterruptRequest {
                        code: "Policy Review".into(),
                        summary: "Review required".into(),
                        ttl: Duration::from_secs(1),
                    },
                )
                .await
                .is_err()
        );
        assert!(
            registry
                .interrupt(
                    "target-1".into(),
                    InterruptRequest {
                        code: "policy.review".into(),
                        summary: "Review required".into(),
                        ttl: Duration::from_secs(3601),
                    },
                )
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn rejects_blank_request_before_creating_interrupt() {
        let registry = InterruptRegistry::new();
        assert!(
            registry
                .interrupt(
                    "target-1".into(),
                    InterruptRequest {
                        code: " ".into(),
                        summary: "Review required".into(),
                        ttl: Duration::from_secs(1),
                    },
                )
                .await
                .is_err()
        );
    }
}
