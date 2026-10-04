//! Neutral challenge escalation contracts.
//!
//! DOM challenge evidence and attach coordinates for explicit resolvers.

use serde::Serialize;

use crate::captcha::{CaptchaInfo, CaptchaKind, WidgetRect};

/// Current lifecycle state for a challenge event.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ChallengeStatus {
    Active,
    Resolved,
    Failed,
}

/// Resolver implementations known to the contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResolverType {
    ManualVnc,
    YosoiRecipe,
    OpenSesameSessionActor,
    AgentMcp,
    RotateIdentity,
    Fail,
}

/// CDP and operator handles that let a resolver act on the same tab.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Default)]
pub struct AttachCoordinates {
    pub websocket_url: Option<String>,
    pub target_id: Option<String>,
    pub session_id: Option<String>,
    pub vnc_url: Option<String>,
    pub novnc_url: Option<String>,
}

/// Captcha-side evidence normalized for challenge events.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DomCaptchaSnapshot {
    pub kind: String,
    pub sitekey: Option<String>,
    pub widget_selector: Option<String>,
    pub widget_rect: Option<WidgetRect>,
    pub widget_rendered: bool,
    pub response_field_selector: Option<String>,
    pub existing_token_present: bool,
    pub action: Option<String>,
    pub cdata: Option<String>,
    pub page_url: String,
    /// True only when the DOM signal represents an active wall that should
    /// create a blocking event. Runtime-only presence stays telemetry.
    pub active: bool,
}

impl From<CaptchaInfo> for DomCaptchaSnapshot {
    fn from(info: CaptchaInfo) -> Self {
        let active = captcha_is_active(&info);
        Self {
            kind: info.kind.as_str().to_string(),
            sitekey: info.sitekey,
            widget_selector: info.widget_selector,
            widget_rect: info.widget_rect,
            widget_rendered: info.widget_rendered,
            response_field_selector: info.response_field_selector,
            existing_token_present: info
                .existing_token
                .as_ref()
                .is_some_and(|token| !token.is_empty()),
            action: info.action,
            cdata: info.cdata,
            page_url: info.page_url,
            active,
        }
    }
}

/// The event payload shared by MCP, Python adapters, and future resolvers.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ChallengeSnapshot {
    pub event_id: String,
    pub url: String,
    pub status_code: Option<u16>,
    pub status: ChallengeStatus,
    pub dom_captcha: Option<DomCaptchaSnapshot>,
    pub evidence_corpus_versions: Vec<String>,
    pub screenshot_handle: Option<String>,
    pub ax_summary_handle: Option<String>,
    pub attach_coordinates: AttachCoordinates,
}

impl ChallengeSnapshot {
    pub fn is_blocking(&self) -> bool {
        self.dom_captcha.as_ref().is_some_and(|c| c.active)
    }
}

/// Request from an orchestrator to a resolver.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ResolutionRequest {
    pub event_id: String,
    pub resolver: ResolverType,
    pub timeout_secs: Option<u64>,
    pub note: Option<String>,
}

/// Resolver result recorded after a human or automated actor attempts the wall.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ResolutionOutcome {
    pub event_id: String,
    pub resolver: ResolverType,
    pub status: ChallengeStatus,
    pub elapsed_ms: Option<u64>,
    pub note: Option<String>,
}

/// Active DOM challenges create blocking events. Runtime-only Turnstile
/// presence is useful telemetry, but a resolver has nothing concrete to clear.
pub fn captcha_is_active(info: &CaptchaInfo) -> bool {
    if info
        .existing_token
        .as_ref()
        .is_some_and(|token| !token.is_empty())
    {
        return false;
    }
    match info.kind {
        CaptchaKind::Turnstile | CaptchaKind::Recaptcha | CaptchaKind::Hcaptcha => {
            info.widget_rendered
        }
        CaptchaKind::CloudflareChallenge | CaptchaKind::DatadomeBlock => true,
        CaptchaKind::Unknown(_) => info.widget_rendered,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::captcha::CaptchaInfo;

    fn captcha(kind: CaptchaKind, rendered: bool, token: Option<&str>) -> CaptchaInfo {
        CaptchaInfo {
            kind,
            sitekey: None,
            widget_selector: None,
            widget_rect: None,
            widget_rendered: rendered,
            response_field_selector: None,
            existing_token: token.map(str::to_string),
            action: None,
            cdata: None,
            page_url: "https://example.test".to_string(),
        }
    }

    #[test]
    fn runtime_only_turnstile_is_not_blocking() {
        assert!(!captcha_is_active(&captcha(
            CaptchaKind::Turnstile,
            false,
            None
        )));
    }

    #[test]
    fn rendered_widget_is_blocking_until_token_exists() {
        assert!(captcha_is_active(&captcha(
            CaptchaKind::Recaptcha,
            true,
            None
        )));
        assert!(!captcha_is_active(&captcha(
            CaptchaKind::Recaptcha,
            true,
            Some("token")
        )));
    }

    #[test]
    fn interstitial_kind_is_blocking_without_widget_rect() {
        assert!(captcha_is_active(&captcha(
            CaptchaKind::CloudflareChallenge,
            false,
            None
        )));
    }
}
