use crate::internal::types as yosoi_types;

use crate::internal::browser::{
    active_navigation::NavigationState,
    context_isolation::BrowserStateBinding,
    environment::{EnvironmentObservation, RenderingPreferences},
    interrupt::InterruptRegistry,
    viewport::Viewport,
};
use chromiumoxide::{CdpMode, Page as CdpPage, cdp::browser_protocol::browser::BrowserContextId};
use std::time::Duration;
use std::{
    fmt,
    sync::{Arc, Mutex, atomic::AtomicBool},
};
use tokio::sync::Mutex as AsyncMutex;
const EXECUTION_CONTEXT_WAIT: Duration = Duration::from_secs(1);
const FRAME_NAVIGATION_WAIT: Duration = Duration::from_secs(10);

mod accessibility;
mod accessibility_frame;
mod document;
mod download_types;
mod downloads;
mod emulation;
mod frame_actions;
mod frame_geometry;
mod frames;
mod identity;
mod input;
mod instrumentation;
mod lifecycle;
mod navigation;
mod navigation_capture;
mod navigation_response;
mod network;
mod screenshot;
mod screenshot_types;
mod shared;
mod targets;
mod viewport;
mod visual_snapshot;

#[path = "page/document_identity.rs"]
mod document_identity;
#[path = "page/validation.rs"]
mod validation;

pub(in crate::internal::browser) use document_identity::{
    CdpDocumentIdentity, DocumentIdentityState,
};
pub use download_types::{DownloadCapture, DownloadOutcome};
pub use navigation_response::{ENDPOINT_SANITIZER_VERSION, PageResponse, safe_endpoint};
pub use screenshot_types::{Bbox, ScreenshotOptions, ScreenshotOutput};

/// Per-tab CDP instrumentation state.
///
/// Tabs start in a human-first, low-CDP state. Calling network-heavy helpers
/// lazily enables the required CDP domains on that tab and flips these flags;
/// use this state to route sensitive challenge traversal away from tabs that
/// have already escalated into instrumentation.
#[derive(Debug, Clone, PartialEq, Eq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "state snapshot intentionally exposes independent routing flags"
)]
pub struct TabInstrumentationState {
    /// `true` while the tab has not enabled higher-signal CDP domains.
    pub low_cdp: bool,
    /// `true` after `Network.enable` has been sent for this target.
    pub network_enabled: bool,
    /// `true` after `Runtime.enable` has been sent for frame-scoped JS.
    /// `eval_js` uses one-shot `Runtime.evaluate` without enabling the Runtime
    /// domain.
    pub runtime_enabled: bool,
    /// Reserved for future isolated utility-world escalation tracking.
    pub utility_world_enabled: bool,
    /// `true` if VoidCrawl applied UA/viewport pre-navigation stealth to this
    /// tab.
    pub pre_navigation_stealth: bool,
}

/// Provider browser-context identity retained only for context-scoped CDP
/// commands. Its debug representation deliberately never exposes the raw id.
#[derive(Clone)]
struct ProviderBrowserContextIdentity(BrowserContextId);

impl fmt::Debug for ProviderBrowserContextIdentity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ProviderBrowserContextIdentity(<redacted>)")
    }
}

/// Thin wrapper over `chromiumoxide::Page` exposing a clean async API.
#[derive(Debug)]
pub struct Page {
    inner: CdpPage,
    browser_mode: EnvironmentObservation<yosoi_types::BrowserMode>,
    cdp_mode: CdpMode,
    attached_browser: bool,
    state_binding: BrowserStateBinding,
    provider_context: Option<ProviderBrowserContextIdentity>,
    interrupts: Arc<InterruptRegistry>,
    /// `true` between [`Page::arm_download`] / a `download_to_dir` in flight
    /// and the matching reset, exposing whether download behavior is armed.
    download_armed: AtomicBool,
    /// Last virtual cursor position (CSS px), so a humanized move starts from
    /// where the pointer actually is. Defaults to the top-left.
    cursor: Mutex<(f64, f64)>,
    /// Shared with every other `Page` from the same `BrowserSession`.
    /// Headless Chrome only reliably composites frames for the foregrounded
    /// tab, so `screenshot()` holds this while it brings itself to front and
    /// captures — serializing just that instant across tabs on one browser,
    /// not the tabs' navigation/JS work.
    capture_lock: Arc<AsyncMutex<()>>,
    /// The viewport/device override currently in effect via
    /// [`Page::set_viewport`], or `None` when using the session's launch-time
    /// default. `screenshot()`'s one-shot `viewport` option snapshots and
    /// restores this so a temporary override never leaks to later calls on the
    /// same page.
    viewport_override: Mutex<Option<Viewport>>,
    rendering_preferences: AsyncMutex<RenderingPreferences>,
    network_enabled: AtomicBool,
    runtime_enabled: AtomicBool,
    pre_navigation_stealth: AtomicBool,
    pub(in crate::internal::browser) document_identity: Arc<DocumentIdentityState>,
    pub(in crate::internal::browser) navigation_state: Arc<NavigationState>,
    pub(in crate::internal::browser) closed: Arc<AtomicBool>,
    pub(in crate::internal::browser) browser_closing: Arc<AtomicBool>,
}

#[cfg(test)]
#[path = "page/page_tests.rs"]
mod page_tests;
