//! Semantic acquisition requests independent of concrete providers.
mod transport_profile;
pub use transport_profile::{
    HttpBrowserImpersonationProfile, HttpBrowserImpersonationProfileError,
};

use std::num::NonZeroU32;

use crate::internal::types::{ActivityId, CaptureId};
use serde::{Deserialize, Serialize};

use crate::internal::web_capture::{RequestedWebTarget, UserAgent};

/// A complete request for one concrete web capture attempt.
///
/// Adaptive fallback is deliberately not represented here. An orchestrator
/// that tries another strategy creates another request and another capture
/// occurrence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WebCaptureRequest {
    capture_id: CaptureId,
    target: RequestedWebTarget,
    strategy: WebAcquisitionStrategy,
}

impl WebCaptureRequest {
    /// Creates a request for one freshly allocated capture occurrence.
    pub const fn new(
        capture_id: CaptureId,
        target: RequestedWebTarget,
        strategy: WebAcquisitionStrategy,
    ) -> Self {
        Self {
            capture_id,
            target,
            strategy,
        }
    }

    /// Returns the occurrence allocated for this concrete attempt.
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }

    /// Returns the caller's original validated target.
    pub const fn target(&self) -> &RequestedWebTarget {
        &self.target
    }

    /// Returns the semantic acquisition strategy requested for this attempt.
    pub const fn strategy(&self) -> &WebAcquisitionStrategy {
        &self.strategy
    }
}

/// Semantic mechanism used for one acquisition attempt.
///
/// Variants name observable execution semantics, not implementation libraries.
/// `wreq`, a browser driver, or another adapter is recorded as producer
/// provenance rather than becoming a variant here.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "configuration", rename_all = "snake_case")]
pub enum WebAcquisitionStrategy {
    /// A non-browser HTTP stack owns the request and response.
    DirectHttp(DirectHttpAcquisition),
    /// An HTTP API client shares selected state with a browser context.
    ContextBoundHttp(ContextBoundHttpAcquisition),
    /// Fetch or XHR executes inside an existing page context.
    PageContextFetch(PageContextFetchAcquisition),
    /// A browser navigates a top-level document or frame.
    DocumentNavigation(DocumentNavigationAcquisition),
}

/// Configuration for a native, non-browser HTTP acquisition.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DirectHttpAcquisition {
    transport_profile: DirectHttpTransportProfile,
    session: HttpSessionUse,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    user_agent: Option<UserAgent>,
}

impl DirectHttpAcquisition {
    /// Creates a direct HTTP strategy.
    pub const fn new(
        transport_profile: DirectHttpTransportProfile,
        session: HttpSessionUse,
    ) -> Self {
        Self {
            transport_profile,
            session,
            user_agent: None,
        }
    }

    /// Uses this exact user-agent value for the HTTP request and capture
    /// environment. When absent, the transport keeps its ordinary default.
    pub fn with_user_agent(mut self, user_agent: UserAgent) -> Self {
        self.user_agent = Some(user_agent);
        self
    }

    /// Returns the declared network profile.
    pub const fn transport_profile(&self) -> &DirectHttpTransportProfile {
        &self.transport_profile
    }

    /// Returns whether this attempt uses isolated or runtime-provided state.
    pub const fn session(&self) -> HttpSessionUse {
        self.session
    }

    /// Returns the explicit user-agent value, when one was requested.
    pub const fn user_agent(&self) -> Option<&UserAgent> {
        self.user_agent.as_ref()
    }
}

/// Network behavior requested from a direct HTTP provider.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "profile", rename_all = "snake_case")]
pub enum DirectHttpTransportProfile {
    /// Use the provider's ordinary, explicitly versioned HTTP behavior.
    Standard,
    /// Ask the provider to emulate a named browser network profile.
    ///
    /// This does not assert that a browser, DOM, or JavaScript runtime exists.
    BrowserImpersonation(HttpBrowserImpersonationProfile),
}

/// Whether direct HTTP state is isolated or supplied by the runtime.
///
/// `RuntimeProvided` records the semantic fact without serializing cookie jars,
/// credentials, storage paths, or process-local handles.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HttpSessionUse {
    /// Start with isolated provider state.
    Isolated,
    /// Use state explicitly bound by the runtime.
    RuntimeProvided,
}

/// Stable, secret-safe reference to a runtime browser context.
///
/// The activity identifies the occurrence that allocated the context; the
/// non-zero ordinal distinguishes multiple contexts allocated by that activity.
/// It is not a profile path, cookie jar, or provider process handle. The
/// referenced activity is an input dependency and is not expected to equal the
/// new capture attempt that consumes the context.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserContextRef {
    activity_id: ActivityId,
    local_id: NonZeroU32,
}

impl BrowserContextRef {
    /// Creates a browser-context reference.
    pub const fn new(activity_id: ActivityId, local_id: NonZeroU32) -> Self {
        Self {
            activity_id,
            local_id,
        }
    }

    /// Returns the activity that allocated the runtime context.
    pub const fn activity_id(self) -> ActivityId {
        self.activity_id
    }

    /// Returns the context's activity-local ordinal.
    pub const fn local_id(self) -> NonZeroU32 {
        self.local_id
    }
}

/// Stable reference to a live page or frame established by a source capture.
///
/// This is an input dependency, not a claim that the page is owned by the new
/// capture consuming it. Runtimes must resolve it to a live context separately.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PageContextRef {
    capture_id: CaptureId,
    frame_id: NonZeroU32,
}

impl PageContextRef {
    /// Creates a page-context reference from its source capture and frame.
    pub const fn new(capture_id: CaptureId, frame_id: NonZeroU32) -> Self {
        Self {
            capture_id,
            frame_id,
        }
    }

    /// Returns the capture that established the page context.
    pub const fn capture_id(self) -> CaptureId {
        self.capture_id
    }

    /// Returns the source capture's frame-local ordinal.
    pub const fn frame_id(self) -> NonZeroU32 {
        self.frame_id
    }
}

/// Configuration for HTTP that is associated with browser-context state.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContextBoundHttpAcquisition {
    context: BrowserContextRef,
    cookie_sync: CookieSync,
}

impl ContextBoundHttpAcquisition {
    /// Creates a context-bound HTTP strategy.
    pub const fn new(context: BrowserContextRef, cookie_sync: CookieSync) -> Self {
        Self {
            context,
            cookie_sync,
        }
    }

    /// Returns the browser context supplying state.
    pub const fn context(self) -> BrowserContextRef {
        self.context
    }

    /// Returns how cookies flow between the HTTP client and browser context.
    pub const fn cookie_sync(self) -> CookieSync {
        self.cookie_sync
    }
}

/// Cookie flow for a context-bound HTTP client.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CookieSync {
    /// Read a snapshot of context cookies without writing response cookies back.
    ReadOnlySnapshot,
    /// Read context cookies and apply response cookie changes back to it.
    Bidirectional,
}

/// Configuration for Fetch or XHR executed by page script.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PageContextFetchAcquisition {
    context: PageContextRef,
    mode: FetchMode,
    credentials: FetchCredentials,
}

impl PageContextFetchAcquisition {
    /// Creates a page-context Fetch strategy.
    pub const fn new(
        context: PageContextRef,
        mode: FetchMode,
        credentials: FetchCredentials,
    ) -> Self {
        Self {
            context,
            mode,
            credentials,
        }
    }

    /// Returns the page or frame that initiates Fetch.
    pub const fn context(self) -> PageContextRef {
        self.context
    }

    /// Returns the requested web-platform Fetch mode.
    pub const fn mode(self) -> FetchMode {
        self.mode
    }

    /// Returns the requested web-platform credential policy.
    pub const fn credentials(self) -> FetchCredentials {
        self.credentials
    }
}

/// Web-platform Fetch request mode.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FetchMode {
    /// Apply CORS to cross-origin requests.
    Cors,
    /// Reject cross-origin requests.
    SameOrigin,
    /// Permit a restricted request whose response may be opaque.
    NoCors,
}

/// Web-platform Fetch credential policy.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FetchCredentials {
    /// Never include credentials or apply response credentials.
    Omit,
    /// Include credentials only for same-origin requests.
    SameOrigin,
    /// Include credentials when allowed by browser and server policy.
    Include,
}

/// Configuration for browser document navigation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DocumentNavigationAcquisition {
    context: NavigationContext,
}

impl DocumentNavigationAcquisition {
    /// Creates a document-navigation strategy.
    pub const fn new(context: NavigationContext) -> Self {
        Self { context }
    }

    /// Returns the browser context or existing frame to navigate.
    pub const fn context(self) -> NavigationContext {
        self.context
    }
}

/// Runtime context in which a browser navigation occurs.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "scope", content = "context", rename_all = "snake_case")]
pub enum NavigationContext {
    /// Allocate a fresh isolated browser context for this navigation.
    FreshTopLevel,
    /// Create or navigate a top-level page in the referenced browser context.
    TopLevel(BrowserContextRef),
    /// Navigate an existing runtime-bound frame.
    Frame(PageContextRef),
}

#[cfg(test)]
mod direct_http_user_agent_tests {
    use super::{DirectHttpAcquisition, DirectHttpTransportProfile, HttpSessionUse};
    use crate::internal::web_capture::UserAgent;
    use std::error::Error;

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions report policy wire round-trip test failures."
    )]
    fn direct_http_user_agent_is_optional_and_round_trips() -> Result<(), Box<dyn Error>> {
        let ordinary = DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        );
        assert_eq!(ordinary.user_agent(), None);
        assert_eq!(
            serde_json::to_value(&ordinary)?,
            serde_json::json!({
                "transport_profile": {"kind": "standard"},
                "session": "isolated"
            })
        );

        let legacy: DirectHttpAcquisition = serde_json::from_value(serde_json::json!({
            "transport_profile": {"kind": "standard"},
            "session": "isolated"
        }))?;
        assert_eq!(legacy.user_agent(), None);

        let user_agent = UserAgent::new("YosoiMap/1.0 (+https://example.test/bot)")?;
        let configured = ordinary.with_user_agent(user_agent.clone());
        assert_eq!(configured.user_agent(), Some(&user_agent));
        assert_eq!(
            serde_json::to_value(&configured)?,
            serde_json::json!({
                "transport_profile": {"kind": "standard"},
                "session": "isolated",
                "user_agent": "YosoiMap/1.0 (+https://example.test/bot)"
            })
        );
        Ok(())
    }
}
