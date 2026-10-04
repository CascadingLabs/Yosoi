//! High-level wrapper around a `chromiumoxide::Page`.

use std::{
    collections::{HashMap, HashSet},
    fmt, fs, future,
    num::NonZeroUsize,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use crate::{
    active_navigation::NavigationState,
    ax::compact_outline,
    context_isolation::BrowserStateBinding,
    document_snapshot::{
        AccessibilitySnapshot, AccessibilitySnapshotOptions, DocumentFrameScope, DocumentScope,
        RenderedDomSnapshot, SnapshotUnavailableReason, accessibility, rendered_dom,
        unavailable_accessibility,
    },
    environment::{
        BrowserCaptureCapabilities, BrowserEnvironmentSnapshot, ControllerVersion,
        ENVIRONMENT_SNAPSHOT_JS, EnvironmentObservation, InstrumentationSnapshot, RendererVersion,
        RenderingPreferences, rendering_environment,
    },
    error::{Result, VoidCrawlError},
    input::{HumanizeOptions, Rng, humanized_path},
    interrupt::InterruptRegistry,
    navigation_capture::{NavigationCapture, NavigationCaptureOptions},
    observation::{ObservationOptions, ObservationScope},
    response::{ResponseCapture, ResponseCaptureLimits},
    selector::{self, BrowserTarget, BrowserTargetKind, RawRect, TargetResolution},
    stealth::{NavigatorWebdriverPolicy, StealthConfig},
    viewport::{ScrollTarget, Viewport},
    visual_snapshot::{
        ContentSizeMetrics, LayoutSnapshot, LayoutViewportMetrics, PairedLayoutVisualSnapshot,
        VisualCaptureRegion, VisualSnapshot, VisualViewportMetrics, visual_snapshot,
    },
};
use chromiumoxide::{
    CdpMode, Page as CdpPage,
    cdp::{
        browser_protocol::{
            accessibility::{AxNode, AxValue, GetFullAxTreeParams, QueryAxTreeParams},
            browser::{
                BrowserContextId, GetVersionParams, GetWindowForTargetParams, PermissionDescriptor,
                PermissionSetting, SetDownloadBehaviorBehavior, SetDownloadBehaviorParams,
                SetPermissionParams,
            },
            dom::{
                BackendNodeId, GetBoxModelParams, GetDocumentParams, GetFrameOwnerParams,
                ResolveNodeParams,
            },
            emulation::{
                ClearDeviceMetricsOverrideParams, MediaFeature, SetDeviceMetricsOverrideParams,
                SetEmulatedMediaParams, SetGeolocationOverrideParams, SetLocaleOverrideParams,
                SetTimezoneOverrideParams, SetTouchEmulationEnabledParams,
                SetUserAgentOverrideParams, UserAgentBrandVersion, UserAgentMetadata,
            },
            input::{
                DispatchKeyEventParams, DispatchKeyEventType, DispatchMouseEventParams,
                DispatchMouseEventType, MouseButton,
            },
            network::{
                Cookie, CookieParam, DeleteCookiesParams, EnableParams as NetworkEnableParams,
                EventRequestWillBeSent, EventResponseReceived, Headers, ResourceType,
                SetExtraHttpHeadersParams,
            },
            page::{
                AddScriptToEvaluateOnNewDocumentParams, CaptureScreenshotFormat,
                EventFrameNavigated, EventLifecycleEvent, EventNavigatedWithinDocument, FrameId,
                GetFrameTreeParams, GetLayoutMetricsParams, NavigateParams as PageNavigateParams,
                PrintToPdfParams, StopLoadingParams, Viewport as CdpClipViewport,
            },
            target::{GetTargetsParams, SessionId},
        },
        js_protocol::runtime::{
            CallFunctionOnParams, EvaluateParams, EventExecutionContextCreated, ExecutionContextId,
        },
    },
    error::CdpError as ChromiumoxideError,
    listeners::{EventDelivery, EventListenerConfig, EventOverflowPolicy},
    page::ScreenshotParams,
};
use futures::StreamExt;
use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use serde_json::Value;
use tokio::{
    sync::{Mutex as AsyncMutex, mpsc},
    time,
};

#[path = "page/document_identity.rs"]
mod document_identity;
use document_identity::identity_in_tree;
pub(crate) use document_identity::{CdpDocumentIdentity, DocumentIdentityState};
#[path = "page/validation.rs"]
mod validation;
use validation::{event_overflow, positive_u32, validate_accessibility_options};

const EXECUTION_CONTEXT_WAIT: Duration = Duration::from_secs(1);
const FRAME_NAVIGATION_WAIT: Duration = Duration::from_secs(10);

fn event_listener_config(capacity: usize, overflow: EventOverflowPolicy) -> EventListenerConfig {
    EventListenerConfig::new(
        NonZeroUsize::new(capacity).unwrap_or(NonZeroUsize::MIN),
        overflow,
    )
}

fn unix_millis_now() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

#[derive(Debug, Clone, Copy)]
struct BoxQuad {
    x: [f64; 4],
    y: [f64; 4],
}

impl BoxQuad {
    const fn from_cdp(values: &[f64]) -> Option<Self> {
        let [x1, y1, x2, y2, x3, y3, x4, y4, ..] = values else {
            return None;
        };
        Some(Self {
            x: [*x1, *x2, *x3, *x4],
            y: [*y1, *y2, *y3, *y4],
        })
    }

    fn center(self) -> (f64, f64) {
        (
            self.x.iter().sum::<f64>() / 4.0,
            self.y.iter().sum::<f64>() / 4.0,
        )
    }

    fn map_into_parent(
        mut self,
        owner: Self,
        page_x: f64,
        page_y: f64,
        width: f64,
        height: f64,
    ) -> Option<Self> {
        if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
            return None;
        }
        let [owner_x0, owner_x1, _, owner_x3] = owner.x;
        let [owner_y0, owner_y1, _, owner_y3] = owner.y;
        let x_axis = (owner_x1 - owner_x0, owner_y1 - owner_y0);
        let y_axis = (owner_x3 - owner_x0, owner_y3 - owner_y0);
        for (x, y) in self.x.iter_mut().zip(self.y.iter_mut()) {
            let horizontal = (*x - page_x) / width;
            let vertical = (*y - page_y) / height;
            *x = vertical.mul_add(y_axis.0, horizontal.mul_add(x_axis.0, owner_x0));
            *y = vertical.mul_add(y_axis.1, horizontal.mul_add(x_axis.1, owner_y0));
        }
        Some(self)
    }

    fn bounding_rect(self) -> RawRect {
        let left = self.x.into_iter().fold(f64::INFINITY, f64::min);
        let top = self.y.into_iter().fold(f64::INFINITY, f64::min);
        let right = self.x.into_iter().fold(f64::NEG_INFINITY, f64::max);
        let bottom = self.y.into_iter().fold(f64::NEG_INFINITY, f64::max);
        RawRect {
            x: left,
            y: top,
            width: right - left,
            height: bottom - top,
        }
    }
}

/// Classify the in-page selector-wait status without inspecting provider error
/// text. A rejected promise/CDP failure is handled separately as `JsEvalError`.
fn selector_wait_status(status: Option<&Value>, selector: &str, timeout_ms: u64) -> Result<()> {
    match status.and_then(Value::as_bool) {
        Some(true) => Ok(()),
        Some(false) => Err(VoidCrawlError::Timeout(format!(
            "selector {selector:?} did not appear within {timeout_ms}ms"
        ))),
        None => Err(VoidCrawlError::JsEvalError(
            "wait_for_selector returned a non-boolean status".into(),
        )),
    }
}

/// Wall-clock-derived seed for live humanized pointer paths. Tests seed the
/// generator explicitly for determinism; production just wants variety.
fn runtime_seed() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0x1234_5678_9ABC_DEF0, |d| {
            d.as_secs() ^ u64::from(d.subsec_nanos()).rotate_left(32)
        })
}

/// The result of a [`Page::goto_and_wait_for_idle`] call.
///
/// Bundles the final HTML, URL, and HTTP response metadata captured during
/// navigation.  `status_code` is `None` when the page was served from a
/// service worker, disk cache, or the browser failed to capture a network
/// response (e.g. `file://` URLs).
#[derive(Debug, Clone)]
pub struct PageResponse {
    /// Outer HTML of `<html>` after the page reached network idle.
    pub html: String,
    /// Final URL after any redirects.
    pub url: String,
    /// HTTP status code of the last response in the navigation chain.
    pub status_code: Option<u16>,
    /// `true` when at least one HTTP redirect occurred before the final URL.
    pub redirected: bool,
    /// Response headers of the final Document response (`name`, `value`),
    /// lowercased names, in arrival order. Empty when no network response was
    /// captured (cache/service-worker/`file://`). Feeds downstream response
    /// classification and replay-grade provenance (`cf-ray`, `x-cache`, …).
    pub headers: Vec<(String, String)>,
    /// Data-plane network endpoints (XHR + Fetch request URLs) observed during
    /// navigation — a sorted, deduplicated set of `scheme://host[:port]/path`
    /// strings with query/fragment/userinfo stripped and secret-like path
    /// segments redacted at the source (a replay-grade archive must never
    /// persist a token; see [`safe_endpoint`] and
    /// `ENDPOINT_SANITIZER_VERSION`). `None` when capture was not requested
    /// (opt-in); `Some(empty)` when requested but the page made no
    /// XHR/fetch calls. The *consumer* templatizes id-bearing path segments
    /// — this stays a generic, faithful observation.
    pub endpoints: Option<Vec<String>>,
    /// `true` when the captured endpoint set hit its cap and further endpoints
    /// were dropped — so a consumer can tell "made few calls" from "we stopped
    /// counting". Always `false` when `endpoints` is `None`.
    pub endpoints_truncated: bool,
    /// The [`ENDPOINT_SANITIZER_VERSION`] the `endpoints` were redacted under,
    /// so a long-term archive can reproduce/audit exactly which rules produced
    /// the set. `None` iff
    /// `endpoints` is `None` (capture was not requested).
    pub endpoint_sanitizer_version: Option<&'static str>,
}

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

/// Version of the endpoint-sanitization rules ([`safe_endpoint`]).
///
/// Bump on any change to the redaction patterns so a captured set is
/// reproducible/auditable at replay time.
pub const ENDPOINT_SANITIZER_VERSION: &str = "ep-2026.06.06";

/// Largest distinct-endpoint set kept per navigation; past this, capture stops
/// and `PageResponse::endpoints_truncated` is set. Bounds memory on chatty
/// SPAs.
const MAX_ENDPOINTS: usize = 256;

/// Reduce a raw request URL to a `scheme://host[:port]/path` key with secrets
/// removed, or `None` if it must not be archived at all.
///
/// A replay-grade archive cannot retroactively un-persist a secret, so this
/// strips at the source — BEFORE the string is ever stored — and is
/// **redact-by-default** on the path (deny-unknown, not allow-unknown):
///   * query string + fragment removed (where tokens/PII/cache-busters live),
///   * userinfo (`user:pass@`) removed,
///   * non-`http(s)` schemes and loopback/private/CGNAT/`.local` hosts dropped
///     entirely (an operator-environment leak, not page signal),
///   * a path segment is KEPT only when it is clearly a short, low-entropy
///     template token ([`is_safe_segment`]); ANYTHING else — long blobs
///     (JWT/signed-URL/hash), kv/matrix markers (`;`/`=`/`%`), emails, long
///     digit runs — becomes `:redacted`.
///
/// This is a best-effort *security* filter, not a proof: a short high-entropy
/// secret can still resemble a word. It deliberately does NOT templatize
/// ordinary id segments (`/users/123/` keeps `123`) — that semantic
/// normalization is the *consumer's* fingerprint concern; this function's job
/// is only to keep secrets out while staying a faithful, generic observation.
pub fn safe_endpoint(raw_url: &str) -> Option<String> {
    // Cut everything from the first `?` or `#` — query and fragment never
    // enter.
    let head = raw_url.split(['?', '#']).next().unwrap_or("");

    let (scheme, rest) = head.split_once("://")?;
    let scheme = scheme.to_ascii_lowercase();
    if scheme != "http" && scheme != "https" {
        return None;
    }

    // Authority is everything up to the first `/`; the rest is the path.
    let (authority, path) = match rest.split_once('/') {
        Some((a, p)) => (a, format!("/{p}")),
        None => (rest, String::new()),
    };
    // Drop userinfo (`user:pass@host`) — embedded credentials — then lowercase
    // the host:port ONCE (the single source of truth for both the local-host
    // guard and the emitted key).
    let host_port = authority
        .rsplit_once('@')
        .map_or(authority, |(_, hp)| hp)
        .to_ascii_lowercase();
    let host = bare_host(&host_port);
    if host.is_empty() || is_local_host(host) {
        return None;
    }

    let safe_path: String = path
        .split('/')
        .map(|seg| {
            if is_safe_segment(seg) {
                seg
            } else {
                ":redacted"
            }
        })
        .collect::<Vec<_>>()
        .join("/");

    Some(format!("{scheme}://{host_port}{safe_path}"))
}

/// The bare host from a (already-lowercased) `host[:port]` authority, handling
/// the bracketed IPv6 form `[::1]:9000` → `::1` (a plain `split(':')` would
/// return `"["` and let loopback IPv6 slip past [`is_local_host`]).
fn bare_host(host_port: &str) -> &str {
    if let Some(after) = host_port.strip_prefix('[') {
        return after.split(']').next().unwrap_or("");
    }
    host_port.split(':').next().unwrap_or("")
}

/// Loopback / private / CGNAT / link-local / mDNS hosts — never archive these
/// (they describe the crawl operator's machine/network, not the page). `host`
/// is the bare, lowercased host (no brackets, no port).
fn is_local_host(host: &str) -> bool {
    // IPv6 loopback / unspecified / link-local / unique-local (fc00::/7).
    if host == "::1"
        || host == "::"
        || host.starts_with("fe80:")
        || host.starts_with("fc")
        || host.starts_with("fd")
    {
        return true;
    }
    // mDNS `*.local` (compare the final label, not via ends_with — that trips
    // clippy's file-extension lint and would also match a bare "local").
    let mdns_local = host.rsplit_once('.').is_some_and(|(_, tld)| tld == "local");
    if host == "localhost" || host == "0.0.0.0" || mdns_local {
        return true;
    }
    if host.starts_with("127.")
        || host.starts_with("10.")
        || host.starts_with("192.168.")
        || host.starts_with("169.254.")
    {
        return true;
    }
    // RFC-1918 172.16.0.0/12 and RFC-6598 CGNAT 100.64.0.0/10.
    let second_octet = |s: &str| s.split('.').nth(1).and_then(|o| o.parse::<u8>().ok());
    if host.starts_with("172.") {
        return second_octet(host).is_some_and(|o| (16..=31).contains(&o));
    }
    if host.starts_with("100.") {
        return second_octet(host).is_some_and(|o| (64..=127).contains(&o));
    }
    false
}

/// True when a path segment is clearly a SAFE template token worth keeping —
/// the allow-list half of the redact-by-default policy. Conservative: anything
/// that isn't obviously a short, low-entropy lexical/id token is redacted.
///
/// Keeps: `finance`, `quoteSummary`, `v10`, `users`, `123`, `AAPL` (the
/// consumer templatizes ordinary ids). Redacts: JWTs/signed-URLs/hashes (long
/// or high-entropy), emails / kv / matrix params (`@`/`=`/`;`/`%`), and long
/// digit runs (card/SSN/phone).
fn is_safe_segment(seg: &str) -> bool {
    // Empty (a `//` or trailing `/`) is structure, not content — keep it.
    if seg.is_empty() {
        return true;
    }
    // Any kv / matrix / userinfo / percent-encoding marker → not a plain token.
    if seg.contains(['@', '=', ';', '%', ':']) {
        return false;
    }
    // Only ordinary url-path token characters.
    if !seg
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '~'))
    {
        return false;
    }
    // Long segments are tokens/blobs, not template words (`recommendations` is
    // 15).
    if seg.len() > 15 {
        return false;
    }
    let digits = seg.chars().filter(char::is_ascii_digit).count();
    // 9+ digits → SSN / card / phone range (ordinary numeric ids are shorter).
    if digits >= 9 {
        return false;
    }
    // A 12+ char all-hex blob is a hash/token, never a word.
    if seg.len() >= 12 && seg.chars().all(|c| c.is_ascii_hexdigit()) {
        return false;
    }
    // A 12+ char segment spanning 3 character classes (lower AND upper AND
    // digit) is an opaque mixed-case token, not a template word — `oAuth2…`-
    // style names are rare in paths and over-redacting them is the safe trade.
    if seg.len() >= 12 {
        let has_lower = seg.chars().any(|c| c.is_ascii_lowercase());
        let has_upper = seg.chars().any(|c| c.is_ascii_uppercase());
        let has_digit = seg.chars().any(|c| c.is_ascii_digit());
        if has_lower && has_upper && has_digit {
            return false;
        }
    }
    true
}

/// Turn the in-loop deduped endpoint set into the final field value: `None`
/// when capture was off, else a SORTED `Vec` (a stable set — arrival order is a
/// session/timing tell, and the consumer set-ifies anyway).
fn finalize_endpoints(seen: &HashSet<String>, capture: bool) -> Option<Vec<String>> {
    if !capture {
        return None;
    }
    let mut v: Vec<String> = seen.iter().cloned().collect();
    v.sort();
    Some(v)
}

/// Flatten CDP's `Network.Response.headers` (a JSON object of name → string
/// value) into ordered `(lowercased-name, value)` pairs. Non-string values are
/// skipped; an unexpected non-object yields an empty list.
fn flatten_headers(value: &serde_json::Value) -> Vec<(String, String)> {
    value
        .as_object()
        .map(|map| {
            map.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.to_lowercase(), s.to_string())))
                .collect()
        })
        .unwrap_or_default()
}

/// Rectangular crop in CSS pixels for [`ScreenshotOptions::bbox`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub struct Bbox {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

/// Options for [`Page::screenshot`].
#[derive(Debug, Clone)]
pub struct ScreenshotOptions {
    /// Write PNG to this path instead of returning bytes.
    pub path: Option<PathBuf>,
    /// Crop to this CSS-pixel region. Takes precedence over `full_page`.
    /// With `scroll` set, coordinates are relative to wherever that scroll
    /// lands rather than the top of the document.
    pub bbox: Option<Bbox>,
    /// Crop to a VoidCrawl browser target's resolved rectangle instead of an
    /// explicit `bbox`. Mutually exclusive with `bbox`: setting both is an
    /// error.
    /// A non-[`Resolved`](crate::selector::TargetResolution::Resolved)
    /// outcome (nothing matched, hidden/zero-area target, ambiguous match,
    /// or a non-visual kind like `jsonld`/`regex`) becomes an actionable
    /// `Err` here — see [`Page::resolve_target`] for a version that
    /// returns the typed outcome instead of erroring.
    pub selector: Option<BrowserTarget>,
    /// Apply this viewport/device override for just this capture, then
    /// restore whatever was active before (even on error). See
    /// [`Page::set_viewport`] for a persistent version.
    pub viewport: Option<Viewport>,
    /// Scroll to this position before capturing, then restore the original
    /// scroll position after (even on error). Combine with `bbox` to crop a
    /// specific on-screen region after paging down a fixed viewport, or use
    /// alone with `full_page: false` to capture whatever's scrolled into
    /// view without cropping.
    pub scroll: Option<ScrollTarget>,
    /// Capture the full scrollable page (default `true`) vs just what's
    /// currently visible in the viewport. Ignored when `bbox` is set — a
    /// crop always wins. Set `false` via [`ScreenshotOptions::viewport_only`]
    /// to capture only the visible fold: cheaper, and the right choice when
    /// "screenshot this page" really means "what does a visitor see first,"
    /// not the whole scroll history.
    pub full_page: bool,
}

impl Default for ScreenshotOptions {
    fn default() -> Self {
        Self {
            path: None,
            bbox: None,
            selector: None,
            viewport: None,
            scroll: None,
            full_page: true,
        }
    }
}

impl ScreenshotOptions {
    pub fn with_path(mut self, path: impl Into<PathBuf>) -> Self {
        self.path = Some(path.into());
        self
    }

    pub const fn with_bbox(mut self, bbox: Bbox) -> Self {
        self.bbox = Some(bbox);
        self
    }

    pub fn with_selector(mut self, selector: BrowserTarget) -> Self {
        self.selector = Some(selector);
        self
    }

    pub fn with_viewport(mut self, viewport: Viewport) -> Self {
        self.viewport = Some(viewport);
        self
    }

    pub const fn with_scroll(mut self, scroll: ScrollTarget) -> Self {
        self.scroll = Some(scroll);
        self
    }

    /// Capture only the currently visible viewport instead of the full
    /// scrollable page.
    pub const fn viewport_only(mut self) -> Self {
        self.full_page = false;
        self
    }
}

/// Return type of [`Page::screenshot`].
#[derive(Debug)]
pub enum ScreenshotOutput {
    /// PNG bytes held in memory (no path supplied).
    Bytes(Vec<u8>),
    /// Path the PNG was written to.
    Path(PathBuf),
}

/// Outcome of [`Page::download_to_dir`]: the file that landed on disk.
#[derive(Debug, Clone)]
pub struct DownloadOutcome {
    /// Absolute path to the downloaded file inside the target directory.
    pub path: PathBuf,
    /// Size of the downloaded file in bytes.
    pub bytes: u64,
    /// The `Content-Type` the server sent for the download (parameters
    /// stripped), if any — fed to the scanner to catch disguised payloads.
    /// `None` for action-captured downloads (see [`Page::arm_download`]), where
    /// Chrome streams to disk and the header isn't observed.
    pub content_type: Option<String>,
}

/// A primed capture for an **action-triggered** download — created by
/// [`Page::arm_download`], consumed by [`DownloadCapture::wait`].
///
/// Use this when the download is started by a page action (clicking a
/// "Download" button, a generated/redirected/cross-origin URL) rather than a
/// URL you already hold — e.g. Google Drive. The flow is *arm → act → await*:
///
/// ```no_run
/// # async fn f(page: &void_crawl_core::Page) -> void_crawl_core::Result<()> {
/// # use std::{path::Path, time::Duration};
/// let cap = page.arm_download(Path::new("/tmp/dl"), 100 << 20).await?;
/// page.click_by_role("button", "Download all", 0, false).await?; // the triggering action
/// let file = cap.wait(page, Duration::from_secs(120)).await?;
/// # Ok(()) }
/// ```
///
/// `arm_download` snapshots the directory's existing files, so `wait` only
/// accepts a file that appears *after* arming. Not `Clone` — a capture is
/// consumed exactly once.
#[derive(Debug)]
pub struct DownloadCapture {
    dir: PathBuf,
    before: HashSet<PathBuf>,
    max_bytes: u64,
    _watcher: RecommendedWatcher,
    events: mpsc::UnboundedReceiver<notify::Result<Event>>,
}

impl DownloadCapture {
    /// Wait for a new completed download to settle in the armed directory, then
    /// reset `page`'s download behavior. `page` must be the page that armed
    /// this capture.
    ///
    /// The size cap is enforced *after* the file lands (Chrome streams a native
    /// download straight to disk — it can't be aborted mid-stream the way
    /// [`Page::download_to_dir`] aborts its in-page fetch). An oversized file
    /// is deleted and an error returned.
    pub async fn wait(mut self, page: &Page, timeout: Duration) -> Result<DownloadOutcome> {
        let result = self.wait_without_reset(timeout).await;
        page.reset_download_behavior().await;
        result
    }

    /// Wait for the download **without** touching the page, so a caller holding
    /// the page lock elsewhere doesn't hold it for the whole wait. Does NOT
    /// reset download behavior — pair with [`Page::reset_download_behavior`].
    pub async fn wait_without_reset(&mut self, timeout: Duration) -> Result<DownloadOutcome> {
        wait_for_new_download(
            &self.dir,
            &self.before,
            self.max_bytes,
            &mut self.events,
            timeout,
        )
        .await
    }
}

const DOCUMENT_SNAPSHOT_JS: &str = r#"
(() => {
  const MAX = {
    headings: 80,
    textBlocks: 240,
    links: 160,
    controls: 160,
    forms: 60,
    formControls: 30,
    textChars: 700,
    smallChars: 220
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const clip = (value, limit) => {
    const text = clean(value);
    return text.length > limit ? text.slice(0, Math.max(0, limit - 3)) + '...' : text;
  };
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const attr = (el, name) => {
    const value = el.getAttribute(name);
    return value == null || value === '' ? null : clip(value, MAX.smallChars);
  };
  const labelText = (el) => {
    const id = el.id ? CSS.escape(el.id) : null;
    const label = id ? document.querySelector(`label[for="${id}"]`) : null;
    return clip(
      el.getAttribute('aria-label')
        || el.getAttribute('title')
        || el.getAttribute('placeholder')
        || (label && label.textContent)
        || el.value
        || el.textContent
        || el.name
        || '',
      MAX.smallChars
    );
  };
  const control = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: attr(el, 'type'),
    role: attr(el, 'role'),
    name: labelText(el) || null,
    placeholder: attr(el, 'placeholder'),
    disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true')
  });
  const all = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
  const unique = (items) => Array.from(new Set(items));

  const headingNodes = all('h1,h2,h3,h4,h5,h6');
  const headings = headingNodes.slice(0, MAX.headings).map((el) => ({
    level: Number(el.tagName.slice(1)),
    text: clip(el.textContent, MAX.smallChars)
  })).filter((h) => h.text);

  const textNodes = unique([
    ...all('main p, main li, article p, article li, section p, blockquote, body > p, td, th'),
    ...all('[role="main"] p, [role="article"] p')
  ]).filter((el) => clean(el.textContent).length >= 20);
  const text_blocks = textNodes.slice(0, MAX.textBlocks).map((el) => ({
    tag: el.tagName.toLowerCase(),
    text: clip(el.textContent, MAX.textChars)
  })).filter((b) => b.text);

  const linkNodes = all('a[href]');
  const links = linkNodes.slice(0, MAX.links).map((el) => ({
    text: clip(el.textContent || el.getAttribute('aria-label') || el.href, MAX.smallChars),
    href: clip(el.href, MAX.smallChars)
  })).filter((l) => l.href);

  const controlNodes = all('button,input,select,textarea,[role="button"],[role="link"],[role="textbox"],[role="combobox"],[contenteditable="true"]');
  const controls = controlNodes.slice(0, MAX.controls).map(control);

  const formNodes = all('form');
  const forms = formNodes.slice(0, MAX.forms).map((form) => {
    const fields = Array.from(form.querySelectorAll('button,input,select,textarea,[role="button"],[role="textbox"],[role="combobox"]'))
      .filter(visible)
      .slice(0, MAX.formControls)
      .map(control);
    return {
      action: attr(form, 'action') || (form.action ? clip(form.action, MAX.smallChars) : null),
      method: clip(form.method || 'get', 20).toLowerCase(),
      controls: fields
    };
  });

  return {
    url: location.href,
    title: document.title || null,
    headings,
    text_blocks,
    links,
    controls,
    forms,
    total: {
      headings: headingNodes.length,
      text_blocks: textNodes.length,
      links: linkNodes.length,
      controls: controlNodes.length,
      forms: formNodes.length
    }
  };
})()
"#;

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
    pub(crate) document_identity: Arc<DocumentIdentityState>,
    pub(crate) navigation_state: Arc<NavigationState>,
    pub(crate) closed: Arc<AtomicBool>,
    pub(crate) browser_closing: Arc<AtomicBool>,
}

impl Page {
    /// Wrap an existing CDP page. `capture_lock` and `interrupts` are shared
    /// by every page created from the same `BrowserSession`.
    #[allow(clippy::too_many_arguments, reason = "retains page construction facts")]
    pub(crate) fn new(
        inner: CdpPage,
        capture_lock: Arc<AsyncMutex<()>>,
        interrupts: Arc<InterruptRegistry>,
        browser_mode: EnvironmentObservation<yosoi_types::BrowserMode>,
        cdp_mode: CdpMode,
        attached_browser: bool,
        browser_closing: Arc<AtomicBool>,
        state_binding: BrowserStateBinding,
        provider_context_id: Option<BrowserContextId>,
    ) -> Self {
        Self {
            inner,
            browser_mode,
            cdp_mode,
            attached_browser,
            state_binding,
            provider_context: provider_context_id.map(ProviderBrowserContextIdentity),
            interrupts,
            download_armed: AtomicBool::new(false),
            cursor: Mutex::new((0.0, 0.0)),
            network_enabled: AtomicBool::new(false),
            runtime_enabled: AtomicBool::new(false),
            pre_navigation_stealth: AtomicBool::new(false),
            document_identity: Arc::new(DocumentIdentityState::new(attached_browser)),
            navigation_state: Arc::new(NavigationState::default()),
            closed: Arc::new(AtomicBool::new(false)),
            browser_closing,
            capture_lock,
            viewport_override: Mutex::new(None),
            rendering_preferences: AsyncMutex::new(RenderingPreferences::default()),
        }
    }

    /// The underlying CDP page, for sibling modules that need to issue raw
    /// protocol commands (see [`crate::recording`], which drives the
    /// `Page.startScreencast` domain directly).
    pub(crate) const fn cdp(&self) -> &CdpPage {
        &self.inner
    }

    /// A second handle on the same tab, sharing the browser's capture lock and
    /// interrupt registry.
    ///
    /// For background tasks that need to *query* a page the caller still owns —
    /// [`crate::recording`]'s mask tracker re-resolves selectors on a timer
    /// while the original `Page` stays behind its own lock. Deliberately not
    /// `Clone`: the per-page state that isn't shared (virtual cursor position,
    /// one-shot viewport override) resets on the new handle, so this is only
    /// safe for read-only work like [`Page::resolve_target`].
    pub(crate) fn clone_handle(&self) -> Self {
        let mut clone = Self::new(
            self.inner.clone(),
            Arc::clone(&self.capture_lock),
            Arc::clone(&self.interrupts),
            self.browser_mode.clone(),
            self.cdp_mode,
            self.attached_browser,
            Arc::clone(&self.browser_closing),
            self.state_binding,
            self.provider_context
                .as_ref()
                .map(|context| context.0.clone()),
        );
        clone.document_identity = Arc::clone(&self.document_identity);
        clone.navigation_state = Arc::clone(&self.navigation_state);
        clone.closed = Arc::clone(&self.closed);
        clone.browser_closing = Arc::clone(&self.browser_closing);
        clone
    }

    /// The browser-wide capture lock this page shares with its siblings.
    /// Cloned rather than borrowed so a caller can hold it across an await
    /// without borrowing the page for that whole span.
    pub(crate) fn capture_lock(&self) -> Arc<AsyncMutex<()>> {
        Arc::clone(&self.capture_lock)
    }

    /// The id of the browser window this tab lives in.
    ///
    /// Chrome composites only the frontmost tab *of a window*, so two pages
    /// sharing a window id cannot both paint — the constraint behind
    /// [`Page::screenshot`]'s capture lock and
    /// [`RecordingOptions::foreground`](crate::RecordingOptions::foreground).
    /// Use this to check that a page intended for concurrent recording really
    /// is alone in its window.
    pub async fn window_id(&self) -> Result<i64> {
        let params = GetWindowForTargetParams::builder()
            .target_id(self.inner.target_id().clone())
            .build();
        let result = self
            .inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(format!("getWindowForTarget: {e}")))?;
        Ok(result.result.window_id.inner().to_owned())
    }

    /// Whether this tab is the only one in its browser window.
    ///
    /// Chrome composites only a window's frontmost tab, so a page that shares
    /// its window with others cannot paint while a sibling is active. A page
    /// that is alone in its window keeps painting regardless of what other
    /// windows do — which is what makes a concurrent, non-foregrounded
    /// [`recording`](crate::recording) possible.
    ///
    /// Costs one `Target.getTargets` plus one `Browser.getWindowForTarget`
    /// per page target, so it's a per-operation check, not a per-frame one.
    pub async fn alone_in_window(&self) -> Result<bool> {
        let mine = self.window_id().await?;
        let targets = self
            .inner
            .execute(GetTargetsParams::default())
            .await
            .map_err(|e| VoidCrawlError::PageError(format!("getTargets: {e}")))?;

        let own_target = self.target_id();
        for info in &targets.result.target_infos {
            // Only page targets occupy a window's tab strip; workers and
            // iframes report a window but never occlude anything.
            if info.r#type != "page" || info.target_id.inner() == &own_target {
                continue;
            }
            let params = GetWindowForTargetParams::builder()
                .target_id(info.target_id.clone())
                .build();
            // A target can die between enumeration and lookup; a target we
            // can't place can't be proven to share this window.
            if let Ok(result) = self.inner.execute(params).await
                && *result.result.window_id.inner() == mine
            {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// Reject a mutation while this target is parked by an explicit interrupt.
    pub async fn ensure_active(&self) -> Result<()> {
        if self.closed.load(Ordering::Acquire) || self.browser_closing.load(Ordering::Acquire) {
            return Err(VoidCrawlError::BrowserClosed);
        }
        if self.inner.is_renderer_crashed() {
            return Err(VoidCrawlError::RendererCrashed);
        }
        self.navigation_state.ensure_usable()?;
        self.interrupts.page_is_active(&self.target_id()).await
    }

    pub(crate) fn belongs_to_interrupt_registry(&self, registry: &Arc<InterruptRegistry>) -> bool {
        Arc::ptr_eq(&self.interrupts, registry)
    }

    /// Whether a download is currently armed on this page (set by
    /// `arm_download` / `download_to_dir`, cleared by
    /// `reset_download_behavior`).
    pub fn is_download_armed(&self) -> bool {
        self.download_armed.load(Ordering::Relaxed)
    }

    /// The CDP target id used for internal browser bookkeeping.
    pub(crate) fn target_id(&self) -> String {
        self.inner.target_id().inner().clone()
    }

    /// Wait until Chromium removes this page target from the controller.
    ///
    /// The notification is sticky and contains no provider target or session
    /// identifiers, so callers can coordinate cleanup without polling.
    pub async fn wait_until_closed(&self) {
        self.inner.wait_for_close().await;
    }

    /// Mutable browser-state boundary this page belongs to.
    #[must_use]
    pub const fn state_binding(&self) -> BrowserStateBinding {
        self.state_binding
    }

    async fn wait_for_main_execution_context(&self) -> Result<()> {
        let mut created = self
            .inner
            .event_listener::<EventExecutionContextCreated>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        time::timeout(EXECUTION_CONTEXT_WAIT, async {
            loop {
                if self
                    .inner
                    .execution_context()
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                    .is_some()
                {
                    return Ok(());
                }
                match created.next().await {
                    Some(EventDelivery::Event(_)) => {}
                    Some(EventDelivery::Lagged { .. }) => {
                        return Err(event_overflow("wait_for_main_execution_context"));
                    }
                    None => return Err(VoidCrawlError::BrowserClosed),
                }
            }
        })
        .await
        .map_err(|_| VoidCrawlError::Timeout("main execution context was not ready".into()))?
    }

    /// Observe the effective browser environment and active VoidCrawl capture
    /// primitives for this page.
    ///
    /// Representation-affecting values are read from the page's main world;
    /// they are not copied from requested launch configuration. The result is
    /// owned, secret-safe provider data and contains no live CDP handles,
    /// profile paths, cookies, credentials, or request headers.
    pub async fn environment_snapshot(&self) -> Result<BrowserEnvironmentSnapshot> {
        let renderer = self
            .inner
            .execute(GetVersionParams::default())
            .await
            .map(|response| RendererVersion::from(response.result))
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        // A newly created headful target can be visible before its main world
        // exists. Normal mode receives Runtime execution-context events, so
        // wait for one instead of timing a retry. Minimal deliberately leaves
        // Runtime disabled; it receives no such events, while `evaluate` can
        // issue its one-shot main-world command without a cached context.
        if matches!(self.cdp_mode, CdpMode::Normal) {
            self.wait_for_main_execution_context().await?;
        }
        let result = self
            .inner
            .evaluate(ENVIRONMENT_SNAPSHOT_JS)
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        let value = result.value().cloned().unwrap_or(Value::Null);
        let instrumentation = InstrumentationSnapshot::for_page(
            self.cdp_mode,
            self.network_enabled.load(Ordering::Relaxed),
            self.runtime_enabled.load(Ordering::Relaxed),
            self.pre_navigation_stealth.load(Ordering::Relaxed),
            self.attached_browser,
        );
        let capabilities = BrowserCaptureCapabilities::from_instrumentation(instrumentation);

        Ok(BrowserEnvironmentSnapshot {
            controller: ControllerVersion::current(),
            renderer,
            mode: self.browser_mode.clone(),
            rendering: rendering_environment(&value),
            instrumentation,
            capabilities,
        })
    }

    /// Snapshot this tab's instrumentation state for routing/debugging.
    pub fn instrumentation_state(&self) -> TabInstrumentationState {
        let network_enabled = self.network_enabled.load(Ordering::Relaxed);
        let runtime_enabled = self.runtime_enabled.load(Ordering::Relaxed);
        let pre_navigation_stealth = self.pre_navigation_stealth.load(Ordering::Relaxed);
        TabInstrumentationState {
            low_cdp: !(network_enabled || runtime_enabled),
            network_enabled,
            runtime_enabled,
            utility_world_enabled: false,
            pre_navigation_stealth,
        }
    }

    async fn ensure_network_enabled(&self) -> Result<()> {
        if !self.network_enabled.load(Ordering::Relaxed) {
            self.inner
                .execute(NetworkEnableParams::default())
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            self.network_enabled.store(true, Ordering::Relaxed);
        }
        Ok(())
    }

    async fn ensure_runtime_enabled(&self) -> Result<()> {
        if !self.runtime_enabled.load(Ordering::Relaxed) {
            self.inner
                .enable_runtime()
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            self.runtime_enabled.store(true, Ordering::Relaxed);
        }
        Ok(())
    }

    async fn frame_execution_context_with_runtime(
        &self,
        frame_id: FrameId,
        frame_url_pattern: &str,
    ) -> Result<(Option<ExecutionContextId>, SessionId)> {
        self.ensure_runtime_enabled().await?;
        let owning_session = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let can_use_default_context = self
            .inner
            .frame_is_session_root(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?
            .unwrap_or(false);
        let mut created = self
            .inner
            .event_listener::<EventExecutionContextCreated>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        time::timeout(EXECUTION_CONTEXT_WAIT, async {
            loop {
                if let Some(context_id) = self
                    .inner
                    .frame_execution_context_with_session(frame_id.clone())
                    .await
                    .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?
                {
                    return Ok((Some(context_id.0), context_id.1));
                }
                if &owning_session != self.inner.session_id() && can_use_default_context {
                    return Ok((None, owning_session));
                }
                match created.next().await {
                    Some(EventDelivery::Event(_)) => {}
                    Some(EventDelivery::Lagged { .. }) => {
                        return Err(event_overflow("frame_execution_context"));
                    }
                    None => return Err(VoidCrawlError::BrowserClosed),
                }
            }
        })
        .await
        .map_err(|_| {
            VoidCrawlError::FrameNotFound(format!(
                "{frame_url_pattern:?}: matched frame has no scriptable execution context \
                 (sandboxed without allow-scripts, cross-process, or detached)"
            ))
        })?
    }

    /// Apply stealth settings to this page.
    pub(crate) async fn apply_stealth(&self, cfg: &StealthConfig) -> Result<()> {
        self.pre_navigation_stealth.store(true, Ordering::Relaxed);
        match cfg.navigator_webdriver {
            NavigatorWebdriverPolicy::BrowserReported => {}
        }
        // Probe the browser's real UA and strip only its "Headless" token.
        // Applying the override even when nothing was stripped keeps
        // navigator.platform and Client Hints coupled to the same exact
        // browser product rather than allowing empty or stale metadata.
        let identity = probe_browser_identity(&self.inner).await?;
        let mut builder = SetUserAgentOverrideParams::builder()
            .user_agent(dehead(&identity.user_agent))
            .accept_language(&cfg.locale)
            .platform(identity.platform);
        if let Some(metadata) = identity.metadata {
            builder = builder.user_agent_metadata(metadata);
        }
        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;

        // Viewport / device metrics — through `set_viewport` (not a raw
        // CDP call) so `viewport_override` reflects this as the page's
        // baseline. Otherwise a later one-shot `screenshot(viewport: ...)`
        // would see `current_viewport() == None`, "restore" by calling
        // `clear_viewport`, and wipe this launch-time override instead of
        // putting it back.
        self.set_viewport(Viewport::custom(cfg.viewport_width, cfg.viewport_height))
            .await?;

        Ok(())
    }

    /// Install JavaScript that runs before every subsequent document in this
    /// tab. The script is registered through CDP; it does not modify fetch,
    /// XHR, or request interception.
    pub async fn add_init_script(&self, script: &str) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .execute(AddScriptToEvaluateOnNewDocumentParams::new(
                script.to_string(),
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Arm bounded main-document source and resource-graph capture before
    /// navigation.
    pub async fn arm_navigation_capture(
        &self,
        options: NavigationCaptureOptions,
    ) -> Result<NavigationCapture> {
        self.ensure_active().await?;
        let options = options.validate()?;
        self.ensure_network_enabled().await?;
        NavigationCapture::arm(self.inner.clone(), options).await
    }

    /// Arm bounded, secret-safe CDP lifecycle observation before navigation.
    ///
    /// Requested event listeners are registered before this method returns, so
    /// a subsequent [`Page::navigate`] cannot race the initial document
    /// request or synchronous first-script console/runtime events. Artifact
    /// payload collectors are deliberately separate from this lifecycle scope.
    /// Renderer crashes wake the scope in normal CDP mode, where stable
    /// `Target.targetCrashed` events are enabled by target discovery. Minimal
    /// mode does not enable discovery and remains bounded by its deadline or a
    /// disconnect signal.
    pub async fn arm_observation(&self, options: ObservationOptions) -> Result<ObservationScope> {
        self.ensure_active().await?;
        let options = options.validate()?;
        if options.collect_network {
            self.ensure_network_enabled().await?;
        }
        if options.collect_console || options.collect_exceptions {
            self.ensure_runtime_enabled().await?;
        }
        ObservationScope::arm(self.inner.clone(), options).await
    }

    /// Arm a passive response-body capture before performing a triggering
    /// action. Every `(name, pattern)` must be fulfilled once.
    pub async fn expect_responses(
        &self,
        patterns: Vec<(String, String)>,
        timeout: Duration,
        limits: ResponseCaptureLimits,
    ) -> Result<ResponseCapture> {
        ResponseCapture::arm(self.inner.clone(), patterns, timeout, limits).await
    }

    // ── Navigation ──────────────────────────────────────────────────────

    /// Stop an in-progress document load.
    pub async fn stop_loading(&self) -> Result<()> {
        self.inner
            .execute(StopLoadingParams::default())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    /// Navigate to `url` and wait for the CDP response.
    pub async fn navigate(&self, url: &str) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .goto(url)
            .await
            .map_err(|e| VoidCrawlError::NavigationFailed(e.to_string()))?;
        let identity = self.top_level_document_identity().await?;
        self.observe_document_identity(&identity, true)?;
        Ok(())
    }

    /// Navigate to `url` and wait for network idle, returning a
    /// [`PageResponse`].
    ///
    /// Subscribes to both `Page.lifecycleEvent` and `Network.responseReceived`
    /// **before** navigation starts so that no events are missed.  The
    /// `networkIdle` terminates the wait; reaching the deadline raises a
    /// structured navigation timeout.
    ///
    /// Equivalent to Playwright's `page.goto(url, wait_until='networkidle')`.
    pub async fn goto_and_wait_for_idle(
        &self,
        url: &str,
        timeout: Duration,
    ) -> Result<PageResponse> {
        self.goto_and_wait_for_idle_with_capture(url, timeout, false)
            .await
    }

    /// Like [`Page::goto_and_wait_for_idle`], but when `capture_endpoints` is
    /// `true` also records the page's data-plane network endpoint set (XHR +
    /// Fetch request URLs) onto [`PageResponse::endpoints`].
    ///
    /// Capture is **opt-in** so the default fetch path pays no extra cost: the
    /// `Network.requestWillBeSent` listener is only subscribed when requested.
    /// It is passive (listen-only — no request interception, invisible to the
    /// site) and the endpoints are PII-stripped at the source via
    /// [`safe_endpoint`]. The listener is function-local and dropped on return,
    /// so nothing leaks into a later navigation.
    #[allow(
        clippy::cognitive_complexity,
        reason = "a single navigate select-loop reads more clearly inline than split across helpers"
    )]
    pub async fn goto_and_wait_for_idle_with_capture(
        &self,
        url: &str,
        timeout: Duration,
        capture_endpoints: bool,
    ) -> Result<PageResponse> {
        self.ensure_active().await?;
        self.ensure_network_enabled().await?;
        let started = Instant::now();
        // Subscribe to ALL event streams BEFORE navigation so no events slip
        // through the gap between goto() and the listener setup.
        let mut lifecycle = self
            .inner
            .event_listener::<EventLifecycleEvent>(event_listener_config(
                256,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let mut network = self
            .inner
            .event_listener::<EventResponseReceived>(event_listener_config(
                1_024,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        // Request listener is gated on the opt-in so the wire/decode cost is
        // only paid when a caller wants the endpoint set.
        let mut requests = if capture_endpoints {
            Some(
                self.inner
                    .event_listener::<EventRequestWillBeSent>(event_listener_config(
                        1_024,
                        EventOverflowPolicy::Close,
                    ))
                    .await
                    .map_err(|e| VoidCrawlError::PageError(e.to_string()))?,
            )
        } else {
            None
        };

        // Start navigation (non-blocking CDP command)
        self.inner
            .goto(url)
            .await
            .map_err(|e| VoidCrawlError::NavigationFailed(e.to_string()))?;

        let deadline = time::sleep(timeout);
        tokio::pin!(deadline);

        let mut status_code: Option<u16> = None;
        let mut redirect_count: u32 = 0;
        // Headers of the final (non-redirect) Document response. Overwritten if
        // a later navigation supersedes it, mirroring `status_code`.
        let mut headers: Vec<(String, String)> = Vec::new();
        // Deduped data-plane endpoint set (only populated when capturing).
        let mut endpoints: HashSet<String> = HashSet::new();
        let mut endpoints_truncated = false;

        loop {
            tokio::select! {
                biased;
                maybe_lifecycle = lifecycle.next() => {
                    match maybe_lifecycle {
                        Some(EventDelivery::Event(event)) if event.name == "networkIdle" => break,
                        Some(EventDelivery::Event(_)) => {}
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("goto_and_wait_for_idle"));
                        }
                        None => break,
                    }
                }
                maybe_network = network.next() => {
                    if let Some(EventDelivery::Event(event)) = maybe_network {
                        // Only the Document response carries the page's actual
                        // status code. Sub-resources (images, scripts, XHRs)
                        // are ignored so a 404 favicon doesn't overwrite a 200
                        // document status.
                        if event.r#type == ResourceType::Document {
                            // Status is i64 in the CDP spec. Ignore malformed
                            // out-of-range provider values rather than truncating.
                            let Ok(code) = u16::try_from(event.response.status) else {
                                continue;
                            };
                            if (300..400).contains(&code) {
                                // Redirect in the navigation chain.
                                redirect_count = redirect_count.saturating_add(1);
                            } else if code != 0 {
                                // Chrome emits 0 for cancelled/intercepted
                                // requests — treat as "no network response".
                                status_code = Some(code);
                                headers = flatten_headers(event.response.headers.inner());
                            }
                        }
                    } else if matches!(maybe_network, Some(EventDelivery::Lagged { .. })) {
                        return Err(event_overflow("goto_and_wait_for_idle"));
                    }
                }
                // Endpoint capture — only polled when capturing (guard ensures
                // `requests` is Some). Sits BELOW lifecycle so a chatty request
                // stream can never starve the networkIdle break.
                //
                // select! evaluates every branch's future expression even when
                // its `if` guard is false, so the `None` branch must still yield
                // a same-typed future that never resolves — pending() parks it
                // harmlessly (it's unreachable in practice: requests is Some iff
                // capture_endpoints).
                maybe_request = async {
                    match requests.as_mut() {
                        Some(s) => s.next().await,
                        None => future::pending().await,
                    }
                }, if capture_endpoints => {
                    match maybe_request {
                        Some(EventDelivery::Event(event))
                            if matches!(event.r#type, Some(ResourceType::Xhr | ResourceType::Fetch)) =>
                        {
                            if let Some(ep) = safe_endpoint(&event.request.url) {
                                // A duplicate (already counted) applies no cap
                                // pressure; only a NEW endpoint past the cap
                                // flips the truncated flag.
                                if endpoints.len() < MAX_ENDPOINTS {
                                    endpoints.insert(ep);
                                } else if !endpoints.contains(&ep) {
                                    endpoints_truncated = true;
                                }
                            }
                        }
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("goto_and_wait_for_idle"));
                        }
                        Some(EventDelivery::Event(_)) | None => {}
                    }
                }
                () = &mut deadline => {
                    return Err(VoidCrawlError::NavigationTimeout {
                        url: url.to_string(),
                        wait_phase: "networkidle".to_string(),
                        timeout_secs: timeout.as_secs_f64(),
                        elapsed_secs: started.elapsed().as_secs_f64(),
                    });
                }
            }
        }

        let html = self.content().await?;
        let final_url = self.url().await?.unwrap_or_default();
        let identity = self.top_level_document_identity().await?;
        self.observe_document_identity(&identity, true)?;
        Ok(PageResponse {
            html,
            url: final_url,
            status_code,
            redirected: redirect_count > 0,
            headers,
            endpoints: finalize_endpoints(&endpoints, capture_endpoints),
            endpoints_truncated,
            endpoint_sanitizer_version: capture_endpoints.then_some(ENDPOINT_SANITIZER_VERSION),
        })
    }

    /// Wait for the in-flight navigation to finish.
    pub async fn wait_for_navigation(&self) -> Result<()> {
        self.inner
            .wait_for_navigation()
            .await
            .map_err(|e| VoidCrawlError::NavigationFailed(e.to_string()))?;
        Ok(())
    }

    /// Event-driven wait for the network to become idle.
    ///
    /// Subscribes to `Page.lifecycleEvent` and waits for one of these
    /// events (in priority order):
    ///
    /// 1. **`networkIdle`** — 0 in-flight requests for 500 ms (best signal)
    /// 2. **`networkAlmostIdle`** — ≤ 2 in-flight requests for 500 ms (fallback
    ///    when analytics / long-polls prevent true idle)
    ///
    /// Returns the name of the lifecycle event that resolved the wait
    /// (`"networkIdle"` or `"networkAlmostIdle"`), or `None` if the
    /// timeout was reached without either event firing.
    ///
    /// This is fully async and event-driven — **no polling**.
    pub async fn wait_for_network_idle(&self, timeout: Duration) -> Result<Option<String>> {
        self.ensure_network_enabled().await?;
        let mut events = self
            .inner
            .event_listener::<EventLifecycleEvent>(event_listener_config(
                256,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let deadline = time::sleep(timeout);
        tokio::pin!(deadline);

        // Track the best event we've seen so far
        let mut got_almost_idle = false;

        loop {
            tokio::select! {
                biased;
                maybe_event = events.next() => {
                    match maybe_event {
                        Some(EventDelivery::Event(event)) => {
                            match event.name.as_str() {
                                "networkIdle" => return Ok(Some("networkIdle".into())),
                                "networkAlmostIdle" => { got_almost_idle = true; }
                                _ => {} // DOMContentLoaded, load, etc — ignore
                            }
                        }
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("wait_for_network_idle"));
                        }
                        None => break, // stream closed
                    }
                }
                () = &mut deadline => break,
            }
        }

        // Timeout reached — return best fallback
        if got_almost_idle {
            Ok(Some("networkAlmostIdle".into()))
        } else {
            Ok(None)
        }
    }

    /// Wait until `document.querySelector(selector)` matches an element,
    /// driven by a `MutationObserver` inside the page — no Rust-side polling.
    /// Resolves immediately if the element is already present. The in-page
    /// promise returns a typed timeout status after `timeout`; CDP/JS failures
    /// remain [`VoidCrawlError::JsEvalError`].
    pub async fn wait_for_selector(&self, selector: &str, timeout: Duration) -> Result<()> {
        let sel_lit = serde_json::to_string(selector)
            .map_err(|e| VoidCrawlError::Other(format!("selector encode: {e}")))?;
        let timeout_ms = u64::try_from(timeout.as_millis()).unwrap_or(u64::MAX);
        let js = format!(
            "new Promise((resolve) => {{\
              const sel = {sel_lit};\
              if (document.querySelector(sel)) return resolve(true);\
              const root = document.documentElement || document.body;\
              const obs = new MutationObserver(() => {{\
                if (document.querySelector(sel)) {{\
                  obs.disconnect();\
                  clearTimeout(t);\
                  resolve(true);\
                }}\
              }});\
              obs.observe(root, {{ childList: true, subtree: true }});\
              const t = setTimeout(() => {{\
                obs.disconnect();\
                resolve(false);\
              }}, {timeout_ms});\
            }})"
        );
        let params = EvaluateParams::builder()
            .expression(js)
            .return_by_value(true)
            .await_promise(true)
            .build()
            .map_err(VoidCrawlError::JsEvalError)?;
        let result = self
            .inner
            .evaluate_expression(params)
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        selector_wait_status(result.value(), selector, timeout_ms)
    }

    // ── Content ─────────────────────────────────────────────────────────

    /// Return the full HTML of the page (outer HTML of `<html>`).
    pub async fn content(&self) -> Result<String> {
        self.inner
            .content()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Capture the current rendered DOM as bounded UTF-8 bytes.
    ///
    /// This serializes the live DOM after page execution. It is deliberately
    /// distinct from [`MainDocumentSource`](crate::MainDocumentSource), which
    /// contains the browser-observed response representation.
    pub async fn rendered_dom_snapshot(&self, max_bytes: usize) -> Result<RenderedDomSnapshot> {
        if max_bytes == 0 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "rendered_dom_snapshot",
                reason: "max_bytes must be positive",
            });
        }
        for attempt in 0..2 {
            let before = self.top_level_document_identity().await?;
            let html = self.content().await?;
            let after = self.top_level_document_identity().await?;
            if before.same_document(&after) {
                let scope = self.scope_for_identity(&after, false)?;
                return rendered_dom(html, scope, max_bytes).map_err(|_| {
                    VoidCrawlError::InvalidInput {
                        operation: "rendered_dom_snapshot",
                        reason: "max_bytes does not fit browser byte accounting",
                    }
                });
            }
            // Record the newly observed document even when this attempt raced,
            // so a subsequent snapshot receives the advanced epoch.
            self.observe_document_identity(&after, false)?;
            if attempt == 1 {
                return Err(VoidCrawlError::PageError(
                    "document changed during rendered DOM capture".into(),
                ));
            }
        }
        Err(VoidCrawlError::PageError(
            "document changed during rendered DOM capture".into(),
        ))
    }

    /// Capture the current rendered DOM using a validated browser byte limit.
    pub async fn rendered_dom_snapshot_with_limit(
        &self,
        max_bytes: yosoi_types::ByteLimit,
    ) -> Result<RenderedDomSnapshot> {
        let max_bytes = max_bytes
            .as_usize()
            .map_err(|_| VoidCrawlError::InvalidInput {
                operation: "rendered_dom_snapshot",
                reason: "max_bytes does not fit in usize",
            })?;
        self.rendered_dom_snapshot(max_bytes).await
    }

    /// Return the page title.
    pub async fn title(&self) -> Result<Option<String>> {
        self.inner
            .get_title()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Return the current URL.
    pub async fn url(&self) -> Result<Option<String>> {
        self.inner
            .url()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Collect Yosoi's fixed, read-only document snapshot.
    ///
    /// This deliberately bypasses [`Self::ensure_active`]: the script is
    /// internal, has no caller-provided input, and only reads the current DOM.
    /// Arbitrary JavaScript remains blocked while an interrupt is active.
    pub async fn document_snapshot(&self) -> Result<Value> {
        let result = self
            .inner
            .evaluate(DOCUMENT_SNAPSHOT_JS)
            .await
            .map_err(|e| VoidCrawlError::JsEvalError(e.to_string()))?;
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }

    // ── JavaScript ──────────────────────────────────────────────────────

    /// Evaluate a JS expression and return the result as a JSON value.
    pub async fn evaluate_js(&self, expression: &str) -> Result<Value> {
        self.ensure_active().await?;
        let result = self
            .inner
            .evaluate(expression)
            .await
            .map_err(|e| VoidCrawlError::JsEvalError(e.to_string()))?;
        // `into_value()` fails when the JS expression returns null/undefined
        // (the RemoteObject has no `value` field).  Fall back to Value::Null.
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }

    /// Evaluate a JS expression **inside a specific frame's** execution
    /// context and return the result as a JSON value.
    ///
    /// Unlike [`Page::evaluate_js`] — which always runs in the top document —
    /// this targets the frame whose current URL contains `frame_url_pattern`.
    /// It is the only way to read or drive a **cross-origin** iframe: that
    /// frame's `contentDocument` is `null` from the parent under the
    /// same-origin policy, but CDP can evaluate in the frame's own execution
    /// context, where the origin check is satisfied. `expression` runs as if
    /// it were the frame's own page script (`document` is the frame's
    /// document).
    ///
    /// The match must be unique: more than one frame containing
    /// `frame_url_pattern` returns [`VoidCrawlError::AmbiguousFrame`]; no match
    /// (or a matched frame with no scriptable execution context — e.g. a
    /// `sandbox`ed frame without `allow-scripts`, or one not yet loaded)
    /// returns [`VoidCrawlError::FrameNotFound`].
    ///
    /// Normal CDP mode routes the command through the flat session that owns
    /// the matched frame, including site-isolated OOPIF targets. Minimal mode
    /// deliberately disables child-target auto-attach and reports a missing
    /// scriptable context as [`VoidCrawlError::FrameNotFound`].
    pub async fn evaluate_js_in_frame(
        &self,
        frame_url_pattern: &str,
        expression: &str,
    ) -> Result<Value> {
        self.ensure_active().await?;
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let (context_id, session_id) = self
            .frame_execution_context_with_runtime(frame_id.clone(), frame_url_pattern)
            .await?;
        let mut params = EvaluateParams::builder()
            .expression(expression)
            .return_by_value(true)
            .await_promise(true);
        if let Some(context_id) = context_id {
            params = params.context_id(context_id);
        }
        let params = params.build().map_err(VoidCrawlError::JsEvalError)?;
        // `evaluate_expression` (not `evaluate`) so chromiumoxide does not
        // overwrite our explicit `context_id` with the top-document context.
        let result = self
            .inner
            .evaluate_expression_in_frame(frame_id, session_id, params)
            .await
            .map_err(|e| VoidCrawlError::JsEvalError(e.to_string()))?;
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }

    /// Navigate a uniquely matched frame through the flat CDP session that
    /// currently owns it. A concurrent process swap fails closed instead of
    /// sending the navigation through a stale or replacement session.
    pub async fn navigate_frame(&self, frame_url_pattern: &str, url: &str) -> Result<String> {
        self.ensure_active().await?;
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let mut navigated = self
            .inner
            .event_listener::<EventFrameNavigated>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::NavigationFailed(error.to_string()))?;
        let mut same_document = self
            .inner
            .event_listener::<EventNavigatedWithinDocument>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::NavigationFailed(error.to_string()))?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::NavigationFailed(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let mut params = PageNavigateParams::new(url);
        params.frame_id = Some(frame_id.clone());
        match self
            .inner
            .execute_in_frame_session_raw(frame_id.clone(), session_id, params)
            .await
        {
            Ok(_) | Err(ChromiumoxideError::SessionDetached) => {}
            Err(error) => return Err(VoidCrawlError::NavigationFailed(error.to_string())),
        }
        time::timeout(FRAME_NAVIGATION_WAIT, async {
            loop {
                tokio::select! {
                    delivery = navigated.next() => match delivery {
                        Some(EventDelivery::Event(event)) if event.frame.id == frame_id => {
                            return Ok(event.frame.url.clone());
                        }
                        Some(EventDelivery::Event(_)) => {}
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("frame_navigation"));
                        }
                        None => return Err(VoidCrawlError::BrowserClosed),
                    },
                    delivery = same_document.next() => match delivery {
                        Some(EventDelivery::Event(event)) if event.frame_id == frame_id => {
                            return Ok(event.url.clone());
                        }
                        Some(EventDelivery::Event(_)) => {}
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("frame_navigation_same_document"));
                        }
                        None => return Err(VoidCrawlError::BrowserClosed),
                    },
                }
            }
        })
        .await
        .map_err(|_| VoidCrawlError::NavigationTimeout {
            url: url.to_owned(),
            wait_phase: "frame_navigated".to_owned(),
            timeout_secs: FRAME_NAVIGATION_WAIT.as_secs_f64(),
            elapsed_secs: FRAME_NAVIGATION_WAIT.as_secs_f64(),
        })?
    }

    /// Resolve the single frame whose URL contains `pattern`.
    ///
    /// chromiumoxide's handler already tracks the frame tree and each frame's
    /// execution context, so this is a cheap lookup with no extra CDP round
    /// trips beyond reading cached frame URLs.
    ///
    /// **Fails closed on ambiguity.** The match must be *unique*: if more than
    /// one frame's URL contains `pattern`, this returns
    /// [`VoidCrawlError::AmbiguousFrame`] rather than silently picking one.
    /// Frame enumeration order is not stable, and a hostile page can embed a
    /// decoy frame whose URL contains a common substring — so guessing would
    /// risk running the caller's JS in the wrong (possibly attacker-scripted)
    /// frame. Use a specific pattern (e.g. `recaptcha/api2/bframe`, not
    /// `recaptcha`); [`Page::frame_urls`] helps you find one.
    async fn resolve_frame(&self, pattern: &str) -> Result<FrameId> {
        let frames = self
            .inner
            .frames()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let mut matched: Vec<(FrameId, String)> = Vec::new();
        for frame_id in frames {
            let url = self
                .inner
                .frame_url(frame_id.clone())
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            if let Some(url) = url
                && url.contains(pattern)
            {
                matched.push((frame_id, url));
            }
        }
        match matched.len() {
            0 => Err(VoidCrawlError::FrameNotFound(pattern.to_string())),
            1 => Ok(matched.swap_remove(0).0),
            n => {
                let urls = matched
                    .iter()
                    .map(|(_, u)| u.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                Err(VoidCrawlError::AmbiguousFrame(format!(
                    "{pattern:?} matched {n} frames ({urls}); use a more specific substring"
                )))
            }
        }
    }

    /// List the URLs of every frame currently tracked on this page, in no
    /// particular order. Useful for discovering the right `frame_url_pattern`
    /// to pass to [`Page::evaluate_js_in_frame`].
    pub async fn frame_urls(&self) -> Result<Vec<String>> {
        let frames = self
            .inner
            .frames()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let mut urls = Vec::with_capacity(frames.len());
        for frame_id in frames {
            if let Some(url) = self
                .inner
                .frame_url(frame_id)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?
            {
                urls.push(url);
            }
        }
        Ok(urls)
    }

    // ── Viewport / device emulation ──────────────────────────────────────

    /// Persistently override this page's CDP viewport: dimensions, device
    /// pixel ratio, mobile/touch identity, and (if set) UA — the "set the
    /// viewport once, then click/navigate/screenshot as that device" flow.
    /// Stays in effect until [`Page::clear_viewport`] or another call to
    /// this method; does **not** auto-restore.
    ///
    /// `device_scale_factor` drives `window.devicePixelRatio` and CSS
    /// media-query matching (`min-resolution`, etc.) correctly, so layout
    /// and JS see a real Retina/mobile device. It does **not** change the
    /// pixel dimensions of a [`Page::screenshot`] PNG, though — CDP's
    /// `Page.captureScreenshot` renders at CSS-pixel size regardless of
    /// DPR in this configuration (tried both the device-metrics `scale`
    /// field and the per-clip `scale`; neither affected raster output).
    /// For pixel-perfect high-DPI captures, request `width`/`height`
    /// already multiplied by the density you want.
    ///
    /// For a one-off override scoped to a single capture, pass
    /// [`ScreenshotOptions::viewport`] to [`Page::screenshot`] instead —
    /// that snapshots and restores whatever was here before, so it can't
    /// leak a device identity into a later capture.
    pub async fn set_viewport(&self, viewport: Viewport) -> Result<()> {
        let metrics = SetDeviceMetricsOverrideParams::builder()
            .width(i64::from(viewport.width))
            .height(i64::from(viewport.height))
            .device_scale_factor(viewport.device_scale_factor)
            .mobile(viewport.mobile)
            .screen_width(i64::from(viewport.width))
            .screen_height(i64::from(viewport.height))
            .position_x(0_i64)
            .position_y(0_i64)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(metrics)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        self.inner
            .execute(SetTouchEmulationEnabledParams::new(viewport.has_touch))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        if let Some(ua) = viewport.user_agent.clone() {
            let (nav_platform, metadata) = if viewport.mobile {
                mobile_ua_platform_and_metadata(&ua)
            } else {
                client_hints_for_ua(&ua)
            };
            let mut builder = SetUserAgentOverrideParams::builder()
                .user_agent(ua)
                .platform(nav_platform);
            if let Some(metadata) = metadata {
                builder = builder.user_agent_metadata(metadata);
            }
            let params = builder.build().map_err(VoidCrawlError::PageError)?;
            self.inner
                .execute(params)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        }
        *self
            .viewport_override
            .lock()
            .map_err(|_| VoidCrawlError::Other("viewport lock poisoned".into()))? = Some(viewport);
        // The device-metrics change doesn't always reflect in
        // `window.innerWidth`/media queries synchronously once the CDP
        // response returns — settle it before returning.
        self.wait_for_repaint().await
    }

    /// Clear a [`Page::set_viewport`] override, returning to the session's
    /// launch-time default viewport. Does not restore a prior UA override
    /// — call `set_viewport` again with the desired identity if you need
    /// one back.
    pub async fn clear_viewport(&self) -> Result<()> {
        self.inner
            .execute(ClearDeviceMetricsOverrideParams {})
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        self.inner
            .execute(SetTouchEmulationEnabledParams::new(false))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        *self
            .viewport_override
            .lock()
            .map_err(|_| VoidCrawlError::Other("viewport lock poisoned".into()))? = None;
        self.wait_for_repaint().await
    }

    /// The viewport override currently in effect via [`Page::set_viewport`],
    /// or `None` if using the session's launch-time default.
    pub fn current_viewport(&self) -> Option<Viewport> {
        self.viewport_override
            .lock()
            .ok()
            .and_then(|guard| guard.clone())
    }

    // ── Screenshots & PDF ───────────────────────────────────────────────

    /// Capture point-in-time CSS layout metrics for the current document.
    pub async fn layout_snapshot(&self) -> Result<LayoutSnapshot> {
        let metrics = self
            .inner
            .layout_metrics()
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        let dpr = self
            .evaluate_js("window.devicePixelRatio")
            .await
            .ok()
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite() && *value > 0.0);
        let scope = self.top_level_document_scope().await?;
        Ok(LayoutSnapshot {
            scope,
            generated_at_unix_ms: unix_millis_now(),
            layout_viewport: LayoutViewportMetrics {
                page_x: metrics.css_layout_viewport.page_x,
                page_y: metrics.css_layout_viewport.page_y,
                client_width: metrics.css_layout_viewport.client_width,
                client_height: metrics.css_layout_viewport.client_height,
            },
            visual_viewport: VisualViewportMetrics {
                offset_x: metrics.css_visual_viewport.offset_x,
                offset_y: metrics.css_visual_viewport.offset_y,
                page_x: metrics.css_visual_viewport.page_x,
                page_y: metrics.css_visual_viewport.page_y,
                client_width: metrics.css_visual_viewport.client_width,
                client_height: metrics.css_visual_viewport.client_height,
                scale: metrics.css_visual_viewport.scale,
                zoom: metrics.css_visual_viewport.zoom,
            },
            content_size: ContentSizeMetrics {
                x: metrics.css_content_size.x,
                y: metrics.css_content_size.y,
                width: metrics.css_content_size.width,
                height: metrics.css_content_size.height,
            },
            device_scale_factor: dpr,
        })
    }

    /// Capture a screenshot with provider-native visual metadata.
    ///
    /// This method always returns owned bytes. Use [`Page::screenshot`] when a
    /// filesystem output path is desired.
    pub async fn visual_snapshot(&self, mut opts: ScreenshotOptions) -> Result<VisualSnapshot> {
        if opts.path.is_some() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "visual_snapshot",
                reason: "filesystem output paths are not accepted",
            });
        }
        let region = if let Some(bbox) = opts.bbox {
            VisualCaptureRegion::BoundingBox { bbox }
        } else if let Some(target) = &opts.selector {
            VisualCaptureRegion::BrowserTarget {
                target_kind: target.kind,
            }
        } else if opts.full_page {
            VisualCaptureRegion::FullPage
        } else {
            VisualCaptureRegion::Viewport
        };
        let layout = self.layout_snapshot().await?;
        let (capture_viewport, device_scale_factor) = if let Some(viewport) = &opts.viewport {
            (
                yosoi_types::Viewport::try_from_pixels(viewport.width, viewport.height).map_err(
                    |_| VoidCrawlError::InvalidInput {
                        operation: "visual_snapshot",
                        reason: "viewport dimensions must be positive",
                    },
                )?,
                viewport.device_scale_factor,
            )
        } else {
            (
                yosoi_types::Viewport::try_from_pixels(
                    positive_u32(layout.visual_viewport.client_width),
                    positive_u32(layout.visual_viewport.client_height),
                )
                .map_err(|_| VoidCrawlError::InvalidInput {
                    operation: "visual_snapshot",
                    reason: "browser reported an invalid viewport",
                })?,
                layout.device_scale_factor.unwrap_or(1.0),
            )
        };
        opts.path = None;
        let bytes = match self.screenshot(opts).await? {
            ScreenshotOutput::Bytes(bytes) => bytes,
            ScreenshotOutput::Path(_) => {
                return Err(VoidCrawlError::ScreenshotError(
                    "visual snapshot unexpectedly wrote to disk".into(),
                ));
            }
        };
        visual_snapshot(
            bytes,
            layout.scope,
            region,
            capture_viewport,
            device_scale_factor,
        )
        .ok_or_else(|| {
            VoidCrawlError::ScreenshotError("PNG signature/IHDR/dimensions were invalid".into())
        })
    }

    /// Sequentially capture layout and visual evidence in one document epoch.
    /// The two factual observations are not simultaneous or atomically
    /// correlated. Chromium materializes the PNG before callers can enforce
    /// a retention bound; consumers must all-or-discard the returned PNG.
    pub async fn paired_layout_visual_snapshot(
        &self,
        opts: ScreenshotOptions,
    ) -> Result<PairedLayoutVisualSnapshot> {
        let layout = self.layout_snapshot().await?;
        let visual = self.visual_snapshot(opts).await?;
        if layout.scope != visual.scope {
            return Err(VoidCrawlError::PageError(
                "document epoch changed during paired visual capture".into(),
            ));
        }
        Ok(PairedLayoutVisualSnapshot { layout, visual })
    }

    /// Capture a full-page PNG screenshot, returned as raw bytes.
    ///
    /// Backward-compatible shim around [`Page::screenshot`] with no
    /// options (full page, no crop, bytes in memory).
    pub async fn screenshot_png(&self) -> Result<Vec<u8>> {
        match self.screenshot(ScreenshotOptions::default()).await? {
            ScreenshotOutput::Bytes(b) => Ok(b),
            ScreenshotOutput::Path(_) => Err(VoidCrawlError::ScreenshotError(
                "screenshot unexpectedly wrote to disk".into(),
            ))?,
        }
    }

    /// Capture a PNG screenshot with optional cropping, viewport override,
    /// scrolling, and/or writing to disk.
    ///
    /// * No `path` → returns bytes in memory.
    /// * `path` set → writes PNG to disk and returns that path.
    /// * `bbox` crops to a pixel region (CSS pixels, pre-DPR); with `scroll`
    ///   set, `bbox.x`/`bbox.y` are relative to wherever that scroll lands
    ///   rather than the top of the document.
    /// * `viewport` swaps in a device/dimension override (see
    ///   [`Page::set_viewport`]) for just this capture and restores whatever
    ///   was active before, even on error.
    /// * `scroll` moves the page before capturing (see [`ScrollTarget`]) and
    ///   restores the original scroll position after, even on error.
    pub async fn screenshot(&self, opts: ScreenshotOptions) -> Result<ScreenshotOutput> {
        if opts.bbox.is_some() && opts.selector.is_some() {
            return Err(VoidCrawlError::Other(
                "ScreenshotOptions: `bbox` and `selector` are mutually exclusive".into(),
            ));
        }

        // One-shot viewport override for just this capture — snapshot
        // whatever's already in effect so it's restored exactly, even on
        // error, so a temporary device identity never leaks to the next
        // call on this page.
        let restore_viewport = if let Some(ref viewport) = opts.viewport {
            let prev = self.current_viewport();
            self.set_viewport(viewport.clone()).await?;
            Some(prev)
        } else {
            None
        };

        let result = self.screenshot_inner(&opts).await;

        if let Some(prev) = restore_viewport {
            let restored = match prev {
                Some(v) => self.set_viewport(v).await,
                None => self.clear_viewport().await,
            };
            let _ = restored;
        }

        result
    }

    async fn screenshot_inner(&self, opts: &ScreenshotOptions) -> Result<ScreenshotOutput> {
        // Scroll before cropping — lets a fixed viewport (e.g. a 4K
        // desktop) be paged through and a specific on-screen region cropped
        // from wherever it lands, the way a human scrolling and
        // screenshotting would. Restored after capture for the same
        // leak-proofing reason as the viewport override above.
        let restore_scroll = match opts.scroll {
            Some(_) => Some(self.scroll_position().await?),
            None => None,
        };
        let bbox_shift = if let Some(target) = opts.scroll {
            self.scroll_to(target).await?;
            self.scroll_position().await?
        } else {
            (0.0, 0.0)
        };

        // A `selector` resolves to viewport-relative coordinates *as of
        // right now* (after any scroll above), so unlike a caller-supplied
        // numeric `bbox` — specified relative to the page and shifted by
        // `bbox_shift` below — it needs no shift: `getBoundingClientRect`
        // already reflects wherever the page is currently scrolled to.
        let effective_bbox: Option<(Bbox, bool)> = if let Some(bbox) = opts.bbox {
            Some((bbox, true))
        } else if let Some(entry) = &opts.selector {
            if !entry.supports_geometry() {
                return Err(VoidCrawlError::UnsupportedVisualTarget);
            }
            match self.resolve_target(entry).await? {
                TargetResolution::Resolved { bbox } => Some((bbox, false)),
                TargetResolution::Empty { reason } => {
                    return Err(VoidCrawlError::ElementNotVisible(reason));
                }
                TargetResolution::Ambiguous { reason, .. } => {
                    return Err(VoidCrawlError::AmbiguousSelector(reason));
                }
            }
        } else {
            None
        };

        let mut builder = ScreenshotParams::builder().format(CaptureScreenshotFormat::Png);
        if let Some((bbox, apply_shift)) = effective_bbox {
            let (shift_x, shift_y) = if apply_shift { bbox_shift } else { (0.0, 0.0) };
            builder = builder
                .clip(CdpClipViewport {
                    x: f64::from(bbox.x) + shift_x,
                    y: f64::from(bbox.y) + shift_y,
                    width: f64::from(bbox.width),
                    height: f64::from(bbox.height),
                    scale: 1.0,
                })
                // A region can legitimately sit outside the layout viewport
                // (e.g. paging through a fixed viewport via `scroll`), so
                // always allow capture beyond it rather than silently
                // clamping to whatever's currently on screen.
                .capture_beyond_viewport(true);
        } else if opts.full_page {
            builder = builder.full_page(true);
        } else if let Some(vp) = self.current_viewport() {
            // Viewport-only: an explicit clip at the tracked viewport's exact
            // size, rather than relying on Chrome's ambient "currently
            // visible" state. A prior full-page/capture-beyond-viewport
            // capture on this same page can leave that ambient state stale,
            // so an explicit size makes this mode order-independent.
            builder = builder.clip(CdpClipViewport {
                x: 0.0,
                y: 0.0,
                width: f64::from(vp.width),
                height: f64::from(vp.height),
                scale: 1.0,
            });
        }
        // else: no tracked viewport (e.g. a page adopted through an attached session
        // that skipped apply_stealth) — leave unset and take whatever
        // Chrome currently considers the visible viewport.

        // Headless Chrome only reliably composites a frame for the
        // foregrounded tab. With several tabs sharing one browser process,
        // an un-guarded capture on a backgrounded
        // tab can fail with CDP -32000 ("Unable to capture screenshot").
        // Headful Chromium already composites its visible target and can stall
        // indefinitely while acknowledging Target.activateTarget, so do not
        // issue that headless workaround in known headful mode. Attached mode
        // remains conservative because its visibility is unknown.
        let capture_guard = self.capture_lock.lock().await;
        if !matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: yosoi_types::BrowserMode::Headful
            }
        ) {
            self.inner
                .activate()
                .await
                .map_err(|e| VoidCrawlError::ScreenshotError(e.to_string()))?;
        }
        let bytes = self
            .inner
            .screenshot(builder.build())
            .await
            .map_err(|e| VoidCrawlError::ScreenshotError(e.to_string()))?;
        drop(capture_guard);

        if let Some((x, y)) = restore_scroll {
            let _ = self
                .evaluate_js(&format!("window.scrollTo({x}, {y})"))
                .await;
        }

        if let Some(path) = opts.path.clone() {
            fs::write(&path, &bytes).map_err(|e| {
                VoidCrawlError::ScreenshotError(format!("write {}: {e}", path.display()))
            })?;
            Ok(ScreenshotOutput::Path(path))
        } else {
            Ok(ScreenshotOutput::Bytes(bytes))
        }
    }

    /// Current `window.scrollX`/`scrollY`, in CSS pixels.
    pub(crate) async fn scroll_position(&self) -> Result<(f64, f64)> {
        let value = self.evaluate_js("[window.scrollX, window.scrollY]").await?;
        let arr = value.as_array().ok_or_else(|| {
            VoidCrawlError::JsEvalError("scroll position: expected a [x, y] array".into())
        })?;
        let x = arr
            .first()
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0);
        let y = arr
            .get(1)
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0);
        Ok((x, y))
    }

    /// Scroll to `target` (see [`ScrollTarget`]) and wait for the resulting
    /// layout to actually paint — two animation frames — before the caller
    /// captures, rather than a blind sleep.
    pub(crate) async fn scroll_to(&self, target: ScrollTarget) -> Result<()> {
        let y = match target {
            ScrollTarget::Pixels(y) => {
                serde_json::Number::from(y)
                    .as_f64()
                    .ok_or(VoidCrawlError::InvalidInput {
                        operation: "scroll_to",
                        reason: "pixel offset could not be represented as a number",
                    })?
            }
            ScrollTarget::Viewports(n) => {
                let height = self
                    .evaluate_js("window.innerHeight")
                    .await?
                    .as_f64()
                    .unwrap_or(0.0);
                height * n
            }
        };
        self.evaluate_js(&format!("window.scrollTo(0, {y})"))
            .await?;
        self.wait_for_repaint().await
    }

    /// Wait for two animation frames — a layout-affecting CDP command
    /// (device-metrics override, scroll) doesn't always reflect in
    /// `window.innerWidth`/`scrollY`/etc. synchronously once the CDP
    /// response returns; this settles it before the caller reads or
    /// captures, without a blind sleep.
    ///
    /// Bounded: `requestAnimationFrame` never fires on a backgrounded tab in
    /// headless Chrome (the same reason `screenshot()` brings a tab to
    /// front before capturing — see `capture_lock`), and this is called
    /// from `set_viewport`/`clear_viewport`, which can run on tabs that are
    /// *not* guaranteed to be foregrounded. An unbounded wait there
    /// would hang the caller forever instead of just being
    /// occasionally stale. Best-effort: on timeout the caller's JS-visible
    /// state may lag by a frame until the tab is next foregrounded or
    /// navigated, which is an acceptable trade for "never hangs."
    async fn wait_for_repaint(&self) -> Result<()> {
        let _ = time::timeout(
            Duration::from_millis(500),
            self.evaluate_js(
                "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))",
            ),
        )
        .await;
        Ok(())
    }

    /// Generate a PDF of the page, returned as raw bytes.
    pub async fn pdf_bytes(&self) -> Result<Vec<u8>> {
        let params = PrintToPdfParams::default();
        self.inner
            .pdf(params)
            .await
            .map_err(|e| VoidCrawlError::PdfError(e.to_string()))
    }

    /// Download the resource at `url` into `dir`, returning the file that
    /// landed.
    ///
    /// The transfer runs inside this page's browser context — cookies, TLS
    /// fingerprint, and stealth patches are all preserved, unlike a
    /// side-channel HTTP GET. CDP
    /// `Browser.setDownloadBehavior(allowAndName)` routes the bytes to `dir`.
    ///
    /// A plain navigation only triggers a download for `Content-Disposition:
    /// attachment` responses — `inline` resources (e.g. a PDF) get rendered by
    /// Chrome's built-in viewer instead. To download *any* content type, the
    /// save is forced from inside the page: navigate to the URL's origin so an
    /// in-page `fetch` is same-origin (and carries cookies), then stream the
    /// response — **aborting past `max_bytes`** so a hostile server can't OOM
    /// the tab — into a blob and click a `download` anchor.
    ///
    /// Completion is detected by **watching the directory** (the file settling
    /// without a `.crdownload` suffix), not by `Browser.downloadProgress`
    /// events, which are unreliable in headless Chrome. The in-page fetch also
    /// reports its `Content-Type` and any error back through a `window` flag,
    /// so a failed fetch returns promptly instead of waiting out the
    /// timeout.
    ///
    /// The CDP download behavior is **always reset** before returning, so a
    /// reused page never inherits this download's
    /// `allowAndName` mode or output path.
    ///
    /// `dir` should be a fresh, empty directory the caller treats as quarantine
    /// and scans before trusting the file.
    pub async fn download_to_dir(
        &self,
        url: &str,
        dir: &Path,
        timeout: Duration,
        max_bytes: u64,
    ) -> Result<DownloadOutcome> {
        self.ensure_active().await?;
        let outcome = self.run_download(url, dir, timeout, max_bytes).await;
        // ALWAYS reset: setDownloadBehavior is browser-context-scoped and our
        // download_path points at a quarantine dir the caller is about to
        // delete. Leaving it set would mis-route or break the page's next
        // download.
        self.reset_download_behavior().await;
        outcome
    }

    /// Arm a capture for an **action-triggered** download into `dir`, returning
    /// a [`DownloadCapture`]. Set CDP download behavior to route files into
    /// `dir`, then snapshot the directory's current contents so the matching
    /// `wait` only accepts a *new* file.
    ///
    /// Use this for the *arm → act → await* flow when a page action (a button
    /// click, a generated/redirected/cross-origin URL) starts the download —
    /// the Google-Drive case — rather than [`Page::download_to_dir`], which
    /// needs a URL in hand. After arming, perform the triggering action with
    /// the normal methods (e.g. [`Page::click_by_role`]), then call
    /// [`DownloadCapture::wait`].
    ///
    /// `dir` should be a fresh directory the caller treats as quarantine and
    /// scans before trusting the file.
    pub async fn arm_download(&self, dir: &Path, max_bytes: u64) -> Result<DownloadCapture> {
        self.ensure_active().await?;
        let (watcher, events) = watch_download_dir(dir)?;
        let params = SetDownloadBehaviorParams::builder()
            .behavior(SetDownloadBehaviorBehavior::AllowAndName)
            .download_path(dir.to_string_lossy().into_owned())
            .build()
            .map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        self.download_armed.store(true, Ordering::Relaxed);
        Ok(DownloadCapture {
            dir: dir.to_path_buf(),
            before: dir_entries(dir),
            max_bytes,
            _watcher: watcher,
            events,
        })
    }

    /// Reset CDP download behavior to Chrome's default and clear the armed
    /// flag. Best-effort: failures here must not mask the download result,
    /// so errors are swallowed.
    ///
    /// Does **not** navigate the page — a caller's page state (e.g. an open
    /// session sitting on the download's origin) is left intact.
    pub async fn reset_download_behavior(&self) {
        let _ = self.reset_download_behavior_checked().await;
    }

    pub(crate) async fn reset_download_behavior_checked(&self) -> Result<()> {
        let params = SetDownloadBehaviorParams::builder()
            .behavior(SetDownloadBehaviorBehavior::Default)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        let result = self
            .inner
            .execute(params)
            .await
            .map(|_| ())
            .map_err(|error| VoidCrawlError::PageError(error.to_string()));
        self.download_armed.store(false, Ordering::Relaxed);
        result
    }

    async fn run_download(
        &self,
        url: &str,
        dir: &Path,
        timeout: Duration,
        max_bytes: u64,
    ) -> Result<DownloadOutcome> {
        // Snapshot the dir so we only accept a file that appears *after* arming
        // — correctness no longer depends on the caller handing us a fresh dir.
        let before = dir_entries(dir);
        let (_watcher, mut events) = watch_download_dir(dir)?;
        let started = time::Instant::now();

        let params = SetDownloadBehaviorParams::builder()
            .behavior(SetDownloadBehaviorBehavior::AllowAndName)
            .download_path(dir.to_string_lossy().into_owned())
            .build()
            .map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        self.download_armed.store(true, Ordering::Relaxed);

        // Land on the target's origin so the in-page fetch below is same-origin
        // (no CORS wall, cookies included). Best-effort: a 4xx/5xx on the
        // origin root is fine, we only need a document in the right
        // security context.
        if let Some(origin) = origin_of(url) {
            let _ = self.inner.goto(&origin).await;
        }

        // The in-page promise resolves only after the bounded fetch has
        // completed and the download click has fired. The filesystem watcher
        // was armed first, so even an immediate browser save cannot be missed.
        let url_json = serde_json::to_string(url).unwrap_or_else(|_| "''".to_string());
        let js = DOWNLOAD_JS
            .replace("__URL__", &url_json)
            .replace("__MAX__", &max_bytes.to_string());
        let state = time::timeout(timeout, self.evaluate_js(&js))
            .await
            .map_err(|_| download_timeout(timeout))??;
        if let Some(error) = state.get("err").and_then(Value::as_str) {
            return Err(VoidCrawlError::Other(format!("download failed: {error}")));
        }
        let content_type = state
            .get("ct")
            .and_then(Value::as_str)
            .map(strip_mime_params);
        let remaining = timeout.saturating_sub(started.elapsed());
        let outcome =
            wait_for_new_download(dir, &before, max_bytes, &mut events, remaining).await?;
        Ok(DownloadOutcome {
            content_type,
            ..outcome
        })
    }

    /// Fetch the browser-computed accessibility (AX) tree for the root frame.
    ///
    /// Wraps CDP `Accessibility.getFullAXTree`. The result is the raw,
    /// browser-computed semantic view assistive tech sees: a **flat JSON
    /// array of nodes** linked by `childIds`/`parentId`, each carrying
    /// `role`, computed accessible `name`, `properties` (state like
    /// `focusable`/`expanded`), and `backendDOMNodeId` (the bridge back to
    /// the DOM). Implicit roles are resolved and `aria-hidden`/`display:none`
    /// nodes are pruned, so this is far more redesign-durable than markup.
    ///
    /// The tree only reflects real content once JavaScript has rendered the
    /// page — call it after navigation has settled.
    ///
    /// `depth` bounds how far descendants are walked; `None` returns the
    /// whole tree. Nodes are returned verbatim from CDP (no reshaping) so
    /// callers can address into them however they like.
    pub async fn get_full_ax_tree(&self, depth: Option<i64>) -> Result<Value> {
        let nodes = self.full_ax_nodes(depth, None).await?;
        serde_json::to_value(&nodes).map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Capture the top-level raw accessibility tree with explicit bounds.
    pub async fn accessibility_snapshot(
        &self,
        options: AccessibilitySnapshotOptions,
    ) -> Result<AccessibilitySnapshot> {
        validate_accessibility_options(options)?;
        for attempt in 0..2 {
            let before = self.top_level_document_identity().await?;
            let nodes = self.full_ax_nodes(options.depth, None).await?;
            let after = self.top_level_document_identity().await?;
            if before.same_document(&after) {
                let scope = self.scope_for_identity(&after, false)?;
                return accessibility(&nodes, scope, options).map_err(|_| {
                    VoidCrawlError::InvalidInput {
                        operation: "accessibility_snapshot",
                        reason: "max_bytes does not fit browser byte accounting",
                    }
                });
            }
            self.observe_document_identity(&after, false)?;
            if attempt == 1 {
                let scope = self.scope_for_identity(&after, false)?;
                return Ok(unavailable_accessibility(
                    scope,
                    options,
                    SnapshotUnavailableReason::BrowserDidNotReport,
                ));
            }
        }
        Err(VoidCrawlError::PageError(
            "document changed during accessibility capture".into(),
        ))
    }

    /// Capture the top-level accessibility tree using a validated byte limit.
    pub async fn accessibility_snapshot_with_limit(
        &self,
        depth: Option<i64>,
        max_nodes: usize,
        max_bytes: yosoi_types::ByteLimit,
    ) -> Result<AccessibilitySnapshot> {
        let max_bytes = max_bytes
            .as_usize()
            .map_err(|_| VoidCrawlError::InvalidInput {
                operation: "accessibility_snapshot",
                reason: "max_bytes does not fit in usize",
            })?;
        self.accessibility_snapshot(AccessibilitySnapshotOptions {
            depth,
            max_nodes,
            max_bytes,
        })
        .await
    }

    /// Capture one matching frame's raw accessibility tree with explicit
    /// bounds. Missing or ambiguous frame patterns remain typed errors; a
    /// browser that cannot expose the matched frame returns an unavailable
    /// snapshot rather than an observed empty tree.
    pub async fn accessibility_snapshot_in_frame(
        &self,
        frame_url_pattern: &str,
        options: AccessibilitySnapshotOptions,
    ) -> Result<AccessibilitySnapshot> {
        validate_accessibility_options(options)?;
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let before_top = self.top_level_document_identity().await?;
        let before_tree = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetFrameTreeParams::default(),
            )
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .result
            .frame_tree;
        let Some(before_frame) = identity_in_tree(&before_tree, &frame_id) else {
            let top = self.scope_for_identity(&before_top, false)?;
            return Ok(unavailable_accessibility(
                DocumentScope {
                    frame_id: self.browser_frame_id(&frame_id)?,
                    epoch: top.epoch,
                    frame: DocumentFrameScope::Frame { url: None },
                    url: top.url,
                },
                options,
                SnapshotUnavailableReason::FrameUnavailable,
            ));
        };
        let nodes = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetFullAxTreeParams {
                    depth: options.depth,
                    frame_id: Some(frame_id.clone()),
                },
            )
            .await
            .map(|response| response.result.nodes);
        let after_top = self.top_level_document_identity().await?;
        let after_tree = self
            .inner
            .execute_in_frame_session(frame_id.clone(), session_id, GetFrameTreeParams::default())
            .await
            .map(|response| response.result.frame_tree);
        let after_frame = after_tree
            .as_ref()
            .ok()
            .and_then(|tree| identity_in_tree(tree, &frame_id));
        let top = self.scope_for_identity(&after_top, false)?;
        let scope =
            self.scope_for_frame_identity(after_frame.as_ref().unwrap_or(&before_frame), &top)?;
        if !before_top.same_document(&after_top)
            || !after_frame
                .as_ref()
                .is_some_and(|after| before_frame.same_document(after))
        {
            return Ok(unavailable_accessibility(
                scope,
                options,
                SnapshotUnavailableReason::FrameUnavailable,
            ));
        }
        match nodes {
            Ok(nodes) => {
                accessibility(&nodes, scope, options).map_err(|_| VoidCrawlError::InvalidInput {
                    operation: "accessibility_snapshot",
                    reason: "max_bytes does not fit browser byte accounting",
                })
            }
            Err(_) => Ok(unavailable_accessibility(
                scope,
                options,
                SnapshotUnavailableReason::FrameUnavailable,
            )),
        }
    }

    /// Capture one matching frame's accessibility tree using a validated byte
    /// limit.
    pub async fn accessibility_snapshot_in_frame_with_limit(
        &self,
        frame_url_pattern: &str,
        depth: Option<i64>,
        max_nodes: usize,
        max_bytes: yosoi_types::ByteLimit,
    ) -> Result<AccessibilitySnapshot> {
        let max_bytes = max_bytes
            .as_usize()
            .map_err(|_| VoidCrawlError::InvalidInput {
                operation: "accessibility_snapshot",
                reason: "max_bytes does not fit in usize",
            })?;
        self.accessibility_snapshot_in_frame(
            frame_url_pattern,
            AccessibilitySnapshotOptions {
                depth,
                max_nodes,
                max_bytes,
            },
        )
        .await
    }

    async fn full_ax_nodes(
        &self,
        depth: Option<i64>,
        frame_id: Option<FrameId>,
    ) -> Result<Vec<AxNode>> {
        let params = GetFullAxTreeParams { depth, frame_id };
        let response = if let Some(frame_id) = params.frame_id.clone() {
            let session_id = self
                .inner
                .frame_session(frame_id.clone())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| VoidCrawlError::FrameNotFound(format!("{frame_id:?}")))?;
            self.inner
                .execute_in_frame_session(frame_id, session_id, params)
                .await
        } else {
            self.inner.execute(params).await
        }
        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(response.result.nodes)
    }

    /// Fetch the AX tree and render it as a compact, indented `role "name"`
    /// outline — the readable view, with text-noise and hidden nodes pruned.
    /// See [`crate::ax::compact_outline`] for the raw-nodes → string helper.
    pub async fn ax_tree_outline(&self, depth: Option<i64>) -> Result<String> {
        let tree = self.get_full_ax_tree(depth).await?;
        let nodes = tree.as_array().map_or(&[][..], Vec::as_slice);
        Ok(compact_outline(nodes))
    }

    /// Query the accessibility tree for nodes matching `role` and/or the
    /// computed accessible `name`, rooted at the document.
    ///
    /// Wraps CDP `Accessibility.queryAXTree`. Name matching is exact (the
    /// browser's computed accessible name). Returns the matching nodes as
    /// raw CDP JSON — the AX analogue of `query_selector_all`, but addressing
    /// by semantics rather than markup. Passing neither `role` nor `name`
    /// returns every node under the root.
    pub async fn query_ax_tree(&self, role: Option<&str>, name: Option<&str>) -> Result<Value> {
        let nodes = self.query_ax_nodes(role, name).await?;
        serde_json::to_value(&nodes).map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Internal: run `Accessibility.queryAXTree` rooted at the document and
    /// return the typed matches.
    async fn query_ax_nodes(&self, role: Option<&str>, name: Option<&str>) -> Result<Vec<AxNode>> {
        let doc = self
            .inner
            .execute(GetDocumentParams::default())
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let params = QueryAxTreeParams {
            node_id: Some(doc.result.root.node_id),
            accessible_name: name.map(str::to_string),
            role: role.map(str::to_string),
            ..Default::default()
        };
        let resp = self
            .inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(resp.result.nodes)
    }

    /// Click an element addressed by its accessibility `role` and accessible
    /// `name` — the durable, markup-independent analogue of [`click_element`].
    ///
    /// Resolves via `Accessibility.queryAXTree`, picks the `nth` non-ignored
    /// match (0-based), bridges to the DOM through `backendDOMNodeId`, then
    /// scrolls it into view and clicks it. Errors if no such node exists.
    ///
    /// With `humanize = true`, the element is scrolled into view and then
    /// clicked at its box-model centre with a **trusted compositor** event
    /// along a human-like cursor path (see [`click_xy`]) — rather than the
    /// DOM `this.click()` used by default. Untrusted `.click()` is fine for
    /// ordinary forms but rejected by some challenge widgets.
    ///
    /// [`click_element`]: Self::click_element
    /// [`click_xy`]: Self::click_xy
    pub async fn click_by_role(
        &self,
        role: &str,
        name: &str,
        nth: usize,
        humanize: bool,
    ) -> Result<()> {
        self.ensure_active().await?;
        let nodes = self.query_ax_nodes(Some(role), Some(name)).await?;
        let backends: Vec<_> = nodes
            .iter()
            .filter(|n| !n.ignored)
            .filter_map(|n| n.backend_dom_node_id)
            .collect();
        let backend_id = backends.get(nth).copied().ok_or_else(|| {
            VoidCrawlError::ElementNotFound(format!(
                "no AX node with role={role:?} name={name:?} at index {nth} (found {} match(es))",
                backends.len()
            ))
        })?;

        // Bridge AX node → DOM → JS handle. Resolve once; both paths scroll it
        // into view first.
        let resolved = self
            .inner
            .execute(ResolveNodeParams {
                backend_node_id: Some(backend_id),
                ..Default::default()
            })
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let object_id = resolved.result.object.object_id.ok_or_else(|| {
            VoidCrawlError::PageError("AX node could not be resolved to a DOM handle".into())
        })?;

        if humanize {
            // Scroll into view, then a trusted compositor click at the box
            // centre.
            let scroll = CallFunctionOnParams::builder()
                .object_id(object_id)
                .function_declaration(
                    "function(){ this.scrollIntoView({block:'center',inline:'center'}); }",
                )
                .await_promise(false)
                .build()
                .map_err(VoidCrawlError::PageError)?;
            self.inner
                .execute(scroll)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let bm = self
                .inner
                .execute(GetBoxModelParams {
                    backend_node_id: Some(backend_id),
                    ..Default::default()
                })
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let quad = BoxQuad::from_cdp(bm.result.model.content.inner()).ok_or_else(|| {
                VoidCrawlError::PageError("element has no box-model content quad".into())
            })?;
            let (cx, cy) = quad.center();
            return self.click_xy(cx, cy, true).await;
        }

        // Default: the element's own click() — avoids box-model math and
        // survives elements that are off-screen until scrolled into
        // view.
        let call = CallFunctionOnParams::builder()
            .object_id(object_id)
            .function_declaration(
                "function(){ this.scrollIntoView({block:'center',inline:'center'}); this.click(); }",
            )
            .await_promise(false)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(call)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── Selector-backed bbox resolution ──────────────────────────────────

    /// Resolve a VoidCrawl [`BrowserTarget`] to a CSS-pixel rectangle.
    /// See the [`selector`](crate::selector) module docs for the full design:
    /// resolved, empty, and ambiguous are typed `Ok(...)` outcomes; `Err` is
    /// reserved for browser, JavaScript, or CDP failures.
    ///
    /// For a one-off crop, pass [`ScreenshotOptions::selector`] to
    /// [`Page::screenshot`] instead — that converts a non-`Resolved`
    /// outcome into an actionable `Err`, since a screenshot fundamentally
    /// needs a rectangle.
    pub async fn resolve_target(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        entry.validate()?;
        match entry.kind {
            BrowserTargetKind::Jsonld => Ok(TargetResolution::Empty {
                reason: "jsonld selectors address non-visual structured data (a <script> tag \
                         has no render box); not resolved to a rectangle"
                    .into(),
            }),
            BrowserTargetKind::Regex => Ok(TargetResolution::Empty {
                reason: "regex selectors match raw HTML text, which has no canonical DOM \
                         element; not resolved to a rectangle"
                    .into(),
            }),
            BrowserTargetKind::Visual => Ok(self.resolve_visual_selector(entry).await?),
            BrowserTargetKind::Role => self.resolve_role_selector(entry).await,
            BrowserTargetKind::Css
            | BrowserTargetKind::Xpath
            | BrowserTargetKind::Attr
            | BrowserTargetKind::GlobalId => self.resolve_dom_selector(entry).await,
        }
    }

    /// Compatibility wrapper for the pre-CAS-321 method name.
    #[deprecated(note = "use resolve_target")]
    pub async fn resolve_selector(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        self.resolve_target(entry).await
    }

    /// `visual`: an exact 1x1 CSS-pixel box at `(x, y)` — no invented
    /// hit-radius. Coordinates have already passed [`BrowserTarget::validate`];
    /// `Empty` means the point is outside the current viewport.
    async fn resolve_visual_selector(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        let (Some(x), Some(y)) = (entry.x, entry.y) else {
            return Err(VoidCrawlError::InvalidInput {
                operation: "browser_target",
                reason: "visual target requires both x and y coordinates",
            });
        };
        let dims = self
            .evaluate_js("[window.innerWidth, window.innerHeight]")
            .await?
            .as_array()
            .cloned()
            .unwrap_or_default();
        let (vw, vh) = (
            dims.first()
                .and_then(Value::as_f64)
                .unwrap_or(f64::INFINITY),
            dims.get(1).and_then(Value::as_f64).unwrap_or(f64::INFINITY),
        );
        if x >= vw || y >= vh {
            return Ok(TargetResolution::Empty {
                reason: format!(
                    "visual point ({x}, {y}) is outside the current viewport ({vw}x{vh})"
                ),
            });
        }
        Ok(TargetResolution::Resolved {
            bbox: RawRect {
                x,
                y,
                width: 1.0,
                height: 1.0,
            }
            .to_bbox(),
        })
    }

    /// `role`: `Accessibility.queryAXTree` role + exact accessible-name
    /// match — the same resolution [`Page::click_by_role`] uses, so a
    /// selector that could click an element can also crop it.
    async fn resolve_role_selector(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        let name = entry.name.as_deref();
        let nodes = self.query_ax_nodes(Some(&entry.value), name).await?;
        let backends: Vec<_> = nodes
            .iter()
            .filter(|n| !n.ignored)
            .filter_map(|n| n.backend_dom_node_id)
            .collect();
        let describe = || format!("role={:?} name={:?}", entry.value, name.unwrap_or(""));

        if backends.is_empty() {
            return Ok(TargetResolution::Empty {
                reason: format!("{} matched no AX nodes", describe()),
            });
        }
        // AX-tree matches are already "exists in the accessibility tree",
        // which excludes `display:none`/`aria-hidden` — but the box model
        // can still be a zero-area detached node, so resolve+filter each
        // candidate the same way `pick_resolution` treats DOM rects.
        let mut visible = Vec::with_capacity(backends.len());
        for backend_id in &backends {
            let bm = self
                .inner
                .execute(GetBoxModelParams {
                    backend_node_id: Some(*backend_id),
                    ..Default::default()
                })
                .await;
            let Ok(bm) = bm else { continue };
            // The *border* box, not the content box: it's what
            // `getBoundingClientRect()` returns for a typical element, and
            // every other selector kind here resolves via that same JS
            // call — using the content box would exclude an element's own
            // padding/border and disagree with them for no reason.
            let Some(quad) = BoxQuad::from_cdp(bm.result.model.border.inner()) else {
                continue;
            };
            let rect = quad.bounding_rect();
            if rect.width > 0.0 && rect.height > 0.0 {
                visible.push(rect);
            }
        }
        Ok(selector::pick_resolution(
            backends.len(),
            &visible,
            entry.nth,
            describe,
        ))
    }

    /// `css` / `xpath` / `attr` / `global_id`: gather DOM candidates (see
    /// [`selector::candidates_js`]), filter to visible ones, then resolve
    /// via [`selector::pick_resolution`].
    async fn resolve_dom_selector(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        let candidates = selector::candidates_js(entry).ok_or_else(|| {
            VoidCrawlError::PageError(format!("{:?} has no DOM candidate step", entry.kind))
        })?;
        let count_js = format!("({candidates}).length");
        let count = self.evaluate_js(&count_js).await?.as_u64().ok_or_else(|| {
            VoidCrawlError::JsEvalError("candidate count was not a number".into())
        })?;
        let total_matches = usize::try_from(count).map_err(|_| {
            VoidCrawlError::JsEvalError(format!("implausible candidate count: {count}"))
        })?;

        let rects_js = selector::visible_rects_js(&candidates);
        let raw: Value = self.evaluate_js(&rects_js).await?;
        let visible: Vec<RawRect> = serde_json::from_value(raw)
            .map_err(|e| VoidCrawlError::JsEvalError(format!("rect decode failed: {e}")))?;

        let describe = || format!("{:?} {:?}", entry.kind, entry.value);
        Ok(selector::pick_resolution(
            total_matches,
            &visible,
            entry.nth,
            describe,
        ))
    }

    /// Compact accessibility outline of a specific (possibly cross-origin)
    /// **frame** — the cross-frame analogue of [`ax_tree_outline`].
    ///
    /// Roots `Accessibility.getFullAXTree` at the frame matched by
    /// `frame_url_pattern` (resolved like [`evaluate_js_in_frame`]). The AX
    /// tree is browser-computed and ignores shadow-DOM mode, so this
    /// **pierces closed shadow roots** the page's own JavaScript cannot
    /// read — use it to discover the `role` / accessible-name to pass to
    /// [`click_ax_in_frame`].
    ///
    /// [`ax_tree_outline`]: Self::ax_tree_outline
    /// [`evaluate_js_in_frame`]: Self::evaluate_js_in_frame
    /// [`click_ax_in_frame`]: Self::click_ax_in_frame
    pub async fn ax_outline_in_frame(
        &self,
        frame_url_pattern: &str,
        depth: Option<i64>,
    ) -> Result<String> {
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let resp = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id,
                GetFullAxTreeParams {
                    depth,
                    frame_id: Some(frame_id),
                },
            )
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let nodes = serde_json::to_value(&resp.result.nodes)
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(compact_outline(
            nodes.as_array().map_or(&[][..], Vec::as_slice),
        ))
    }

    /// Locate an element by accessibility `role` + accessible `name` **inside a
    /// specific (possibly cross-origin) frame** and click it with a real
    /// **compositor** mouse event. The cross-frame, shadow-piercing analogue of
    /// [`click_by_role`].
    ///
    /// `Accessibility.getFullAXTree` rooted at the resolved frame descends into
    /// that frame's tree **including closed shadow roots** (the AX tree is
    /// browser-computed and ignores shadow mode), so it reaches widgets that
    /// `contentDocument` / page-JS cannot — e.g. Cloudflare Turnstile's
    /// "Verify you are human" checkbox, which lives in a closed shadow root
    /// inside a cross-origin `challenges.cloudflare.com` iframe. The matched
    /// node is clicked at its box-model centre via `Input.dispatchMouseEvent`
    /// (a **trusted** event), *not* a DOM `.click()` — challenge widgets reject
    /// untrusted clicks, and crucially this does **no page-JS shadow
    /// tampering**, so it does not trip Turnstile's closed-shadow check
    /// (ERROR 600010).
    ///
    /// An empty `name` matches any node of that `role`. Picks the `nth`
    /// (0-based) non-ignored match; errors if there is none.
    ///
    /// Normal CDP mode routes AX and DOM geometry commands through the matched
    /// frame's owning session. Minimal mode leaves OOPIF routing disabled.
    ///
    /// [`click_by_role`]: Self::click_by_role
    /// [`evaluate_js_in_frame`]: Self::evaluate_js_in_frame
    pub async fn click_ax_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
        humanize: bool,
    ) -> Result<()> {
        let (frame_id, session_id, quad) = self
            .ax_local_content_quad_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        let (cx, cy) = quad.center();
        self.click_in_frame_session(frame_id, session_id, cx, cy, humanize)
            .await
    }

    /// Locate an element by accessibility `role` + `name` **inside a specific
    /// frame** and return its on-page rectangle `[x, y, width, height]` in CSS
    /// pixels — the geometry needed to drive a **humanized** click yourself
    /// (e.g. move the cursor along a curved path with [`dispatch_mouse_event`]
    /// and press at a jittered point inside the box), rather than the single
    /// centre click of [`click_ax_in_frame`].
    ///
    /// Same cross-frame, closed-shadow-piercing resolution as
    /// [`click_ax_in_frame`]; an empty `name` matches any node of that `role`.
    ///
    /// [`dispatch_mouse_event`]: Self::dispatch_mouse_event
    /// [`click_ax_in_frame`]: Self::click_ax_in_frame
    pub async fn ax_box_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<Vec<f64>> {
        let quad = self
            .ax_content_quad_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        let rect = quad.bounding_rect();
        Ok(vec![rect.x, rect.y, rect.width, rect.height])
    }

    /// Resolve a frame-scoped AX `role`+`name` match to its box-model content
    /// quad `[x1,y1, x2,y2, x3,y3, x4,y4]` in page coordinates.
    async fn ax_content_quad_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<BoxQuad> {
        let (frame_id, _, quad) = self
            .ax_local_content_quad_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        self.map_frame_quad_to_top(frame_id, quad).await
    }

    async fn ax_local_content_quad_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<(FrameId, SessionId, BoxQuad)> {
        let (frame_id, session_id, backend_id) = self
            .ax_backend_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        let bm = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetBoxModelParams {
                    backend_node_id: Some(backend_id),
                    ..Default::default()
                },
            )
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let quad = BoxQuad::from_cdp(bm.result.model.content.inner()).ok_or_else(|| {
            VoidCrawlError::PageError("AX node has no box-model content quad".into())
        })?;
        Ok((frame_id, session_id, quad))
    }

    async fn click_in_frame_session(
        &self,
        frame_id: FrameId,
        session_id: SessionId,
        x: f64,
        y: f64,
        humanize: bool,
    ) -> Result<()> {
        self.ensure_active().await?;
        let input_guard = self.capture_lock.lock().await;
        if !matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: yosoi_types::BrowserMode::Headful
            }
        ) {
            self.inner
                .activate()
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }
        if humanize {
            let mut rng = Rng::seed(runtime_seed());
            for step in humanized_path((0.0, 0.0), (x, y), &HumanizeOptions::default(), &mut rng) {
                time::sleep(Duration::from_millis(step.delay_ms)).await;
                self.dispatch_mouse_event_in_frame(
                    frame_id.clone(),
                    session_id.clone(),
                    DispatchMouseEventType::MouseMoved,
                    step.x,
                    step.y,
                    None,
                    None,
                )
                .await?;
            }
        } else {
            self.dispatch_mouse_event_in_frame(
                frame_id.clone(),
                session_id.clone(),
                DispatchMouseEventType::MouseMoved,
                x,
                y,
                None,
                None,
            )
            .await?;
        }
        for event_type in [
            DispatchMouseEventType::MousePressed,
            DispatchMouseEventType::MouseReleased,
        ] {
            self.dispatch_mouse_event_in_frame(
                frame_id.clone(),
                session_id.clone(),
                event_type,
                x,
                y,
                Some(MouseButton::Left),
                Some(1),
            )
            .await?;
        }
        drop(input_guard);
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    async fn dispatch_mouse_event_in_frame(
        &self,
        frame_id: FrameId,
        session_id: SessionId,
        event_type: DispatchMouseEventType,
        x: f64,
        y: f64,
        button: Option<MouseButton>,
        click_count: Option<i64>,
    ) -> Result<()> {
        let mut builder = DispatchMouseEventParams::builder()
            .r#type(event_type)
            .x(x)
            .y(y);
        if let Some(button) = button {
            builder = builder.button(button);
        }
        if let Some(click_count) = click_count {
            builder = builder.click_count(click_count);
        }
        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute_in_frame_session(frame_id, session_id, params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    async fn map_frame_quad_to_top(
        &self,
        mut frame_id: FrameId,
        mut quad: BoxQuad,
    ) -> Result<BoxQuad> {
        while let Some(parent_frame_id) = self
            .inner
            .frame_parent(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
        {
            let frame_session = self
                .inner
                .frame_session(frame_id.clone())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| VoidCrawlError::FrameNotFound(format!("{frame_id:?}")))?;
            let metrics = self
                .inner
                .execute_in_frame_session(
                    frame_id.clone(),
                    frame_session,
                    GetLayoutMetricsParams::default(),
                )
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let viewport = metrics.result.css_layout_viewport;
            let page_x = f64::from(i32::try_from(viewport.page_x).map_err(|_| {
                VoidCrawlError::PageError("frame page_x exceeds supported geometry range".into())
            })?);
            let page_y = f64::from(i32::try_from(viewport.page_y).map_err(|_| {
                VoidCrawlError::PageError("frame page_y exceeds supported geometry range".into())
            })?);
            let parent_session = self
                .inner
                .frame_session(parent_frame_id.clone())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| VoidCrawlError::FrameNotFound(format!("{parent_frame_id:?}")))?;
            let owner = self
                .inner
                .execute_in_frame_session(
                    parent_frame_id.clone(),
                    parent_session.clone(),
                    GetFrameOwnerParams::new(frame_id.clone()),
                )
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let model = self
                .inner
                .execute_in_frame_session(
                    parent_frame_id.clone(),
                    parent_session,
                    GetBoxModelParams {
                        backend_node_id: Some(owner.result.backend_node_id),
                        ..Default::default()
                    },
                )
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let owner_model = model.result.model;
            let width = f64::from(i32::try_from(owner_model.width).map_err(|_| {
                VoidCrawlError::PageError("frame width exceeds supported geometry range".into())
            })?);
            let height = f64::from(i32::try_from(owner_model.height).map_err(|_| {
                VoidCrawlError::PageError("frame height exceeds supported geometry range".into())
            })?);
            let owner_quad = BoxQuad::from_cdp(owner_model.content.inner()).ok_or_else(|| {
                VoidCrawlError::PageError("frame owner has no box-model content quad".into())
            })?;
            quad = quad
                .map_into_parent(owner_quad, page_x, page_y, width, height)
                .ok_or_else(|| {
                    VoidCrawlError::PageError("frame viewport cannot map geometry".into())
                })?;
            frame_id = parent_frame_id;
        }
        Ok(quad)
    }

    /// Resolve a frame-scoped AX `role`+`name` match to its `backendDOMNodeId`.
    async fn ax_backend_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<(FrameId, SessionId, BackendNodeId)> {
        fn ax_text(v: Option<&AxValue>) -> &str {
            v.and_then(|a| a.value.as_ref())
                .and_then(Value::as_str)
                .unwrap_or("")
        }
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let resp = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetFullAxTreeParams {
                    depth: None,
                    frame_id: Some(frame_id.clone()),
                },
            )
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let matched = resp
            .result
            .nodes
            .iter()
            .filter(|n| {
                !n.ignored
                    && ax_text(n.role.as_ref()) == role
                    && (name.is_empty() || ax_text(n.name.as_ref()) == name)
            })
            .filter_map(|n| n.backend_dom_node_id)
            .nth(nth);
        matched.map(|backend| (frame_id, session_id, backend)).ok_or_else(|| {
            VoidCrawlError::PageError(format!(
                "no AX node with role={role:?} name={name:?} at index {nth} in frame {frame_url_pattern:?}"
            ))
        })
    }

    // ── Humanized pointer input (CAS-147) ───────────────────────────────

    /// Move the virtual cursor to `(x, y)` via CDP `Input.dispatchMouseEvent`.
    ///
    /// With `humanize = true` the cursor travels a realistic path from its last
    /// position — non-linear (arc) curvature, a minimum-jerk velocity profile,
    /// small tremor, and a brief dwell — as multiple `MouseMoved` events
    /// ([`crate::input`]). With `humanize = false` it jumps in a single event.
    /// **No page-world JS** is injected. The path length/duration scale with
    /// distance and stay bounded for agent workflows.
    pub async fn move_mouse(&self, x: f64, y: f64, humanize: bool) -> Result<()> {
        self.ensure_active().await?;
        if humanize {
            let start = *self
                .cursor
                .lock()
                .map_err(|_| VoidCrawlError::Other("cursor lock poisoned".into()))?;
            let mut rng = Rng::seed(runtime_seed());
            let path = humanized_path(start, (x, y), &HumanizeOptions::default(), &mut rng);
            for step in path {
                // EVENT_DRIVEN_SLEEP_APPROVED: Humanized pointer pacing
                // intentionally models elapsed physical movement time between
                // CDP input events.
                time::sleep(Duration::from_millis(step.delay_ms)).await;
                self.dispatch_mouse_event(
                    DispatchMouseEventType::MouseMoved,
                    step.x,
                    step.y,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                .await?;
            }
        } else {
            self.dispatch_mouse_event(
                DispatchMouseEventType::MouseMoved,
                x,
                y,
                None,
                None,
                None,
                None,
                None,
            )
            .await?;
        }
        *self
            .cursor
            .lock()
            .map_err(|_| VoidCrawlError::Other("cursor lock poisoned".into()))? = (x, y);
        Ok(())
    }

    /// Click at `(x, y)` with a **trusted** compositor event (press → release).
    /// With `humanize = true`, the cursor first travels a human-like path to
    /// the point (see [`move_mouse`]). The analogue of
    /// `click_visual_coords`.
    ///
    /// [`move_mouse`]: Self::move_mouse
    pub async fn click_xy(&self, x: f64, y: f64, humanize: bool) -> Result<()> {
        self.ensure_active().await?;
        let input_guard = self.capture_lock.lock().await;
        if !matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: yosoi_types::BrowserMode::Headful
            }
        ) {
            self.inner
                .bring_to_front()
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }
        self.move_mouse(x, y, humanize).await?;
        self.dispatch_mouse_event(
            DispatchMouseEventType::MousePressed,
            x,
            y,
            Some(MouseButton::Left),
            Some(1),
            None,
            None,
            None,
        )
        .await?;
        self.dispatch_mouse_event(
            DispatchMouseEventType::MouseReleased,
            x,
            y,
            Some(MouseButton::Left),
            Some(1),
            None,
            None,
            None,
        )
        .await?;
        drop(input_guard);
        Ok(())
    }

    // ── Emulation ───────────────────────────────────────────────────────

    /// Override the page's geolocation. Geo-aware sites (maps, "near me"
    /// search, store locators) will behave as if the browser is at these
    /// coordinates. `accuracy` defaults to 50 metres.
    ///
    /// Note: sites that read `navigator.geolocation` still gate on the
    /// geolocation *permission* (granted here) and require a secure context
    /// (https / localhost), not `data:` URLs. Header/IP-driven geo (e.g.
    /// Google Maps) keys off [`set_locale`] and the request URL more than this.
    ///
    /// [`set_locale`]: Self::set_locale
    pub async fn set_geolocation(
        &self,
        latitude: f64,
        longitude: f64,
        accuracy: Option<f64>,
    ) -> Result<()> {
        self.ensure_active().await?;
        // Grant the geolocation permission first, otherwise headless Chrome
        // auto-denies `navigator.geolocation` and the override is never read.
        // Origin omitted applies to every origin, while an isolated page's
        // retained provider identity confines the grant to its browser context.
        // Ordinary/shared pages keep the existing default-context behavior.
        let grant = SetPermissionParams {
            permission: PermissionDescriptor::new("geolocation"),
            setting: PermissionSetting::Granted,
            origin: None,
            embedded_origin: None,
            browser_context_id: self
                .provider_context
                .as_ref()
                .map(|context| context.0.clone()),
        };
        self.inner
            .execute(grant)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let params = SetGeolocationOverrideParams {
            latitude: Some(latitude),
            longitude: Some(longitude),
            accuracy: Some(accuracy.unwrap_or(50.0)),
            ..Default::default()
        };
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Apply independently optional rendering preferences in one CDP command.
    pub async fn set_rendering_preferences(&self, preferences: RenderingPreferences) -> Result<()> {
        self.ensure_active().await?;
        if preferences.color_scheme.is_none() && preferences.reduced_motion.is_none() {
            return Ok(());
        }
        let mut tracked = self.rendering_preferences.lock().await;
        let mut candidate = *tracked;
        if preferences.color_scheme.is_some() {
            candidate.color_scheme = preferences.color_scheme;
        }
        if preferences.reduced_motion.is_some() {
            candidate.reduced_motion = preferences.reduced_motion;
        }
        let mut features = Vec::with_capacity(2);
        if let Some(preference) = candidate.color_scheme {
            let value = match preference {
                yosoi_types::ColorScheme::Light => "light",
                yosoi_types::ColorScheme::Dark => "dark",
                yosoi_types::ColorScheme::NoPreference => "no-preference",
            };
            features.push(MediaFeature::new("prefers-color-scheme", value));
        }
        if let Some(preference) = candidate.reduced_motion {
            let value = match preference {
                yosoi_types::ReducedMotion::Reduce => "reduce",
                yosoi_types::ReducedMotion::NoPreference => "no-preference",
            };
            features.push(MediaFeature::new("prefers-reduced-motion", value));
        }
        let params = SetEmulatedMediaParams::builder().features(features).build();
        self.inner
            .execute(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        *tracked = candidate;
        drop(tracked);
        Ok(())
    }

    /// Override the JS locale and `Accept-Language` (e.g. `"en-US"`,
    /// `"fr-FR"`). This is the lever that shifts region-aware content like
    /// Google Maps results or localized pricing.
    pub async fn set_locale(&self, locale: &str) -> Result<()> {
        self.ensure_active().await?;
        let params = SetLocaleOverrideParams {
            locale: Some(locale.to_string()),
        };
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Override the timezone by IANA id (e.g. `"America/New_York"`). Affects
    /// `Date`, `Intl`, and any server probes that read the rendered clock.
    pub async fn set_timezone(&self, timezone_id: &str) -> Result<()> {
        self.ensure_active().await?;
        let params = SetTimezoneOverrideParams::new(timezone_id.to_string());
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── DOM Queries ─────────────────────────────────────────────────────

    /// Run `document.querySelector(selector)` and return the inner HTML.
    /// Returns `None` if no element matches. Void elements (e.g. `<input>`)
    /// return `Some("")`.
    ///
    /// Uses a JS eval rather than `find_element` so that a missing element
    /// returns `Ok(None)` without any CDP error — real errors (closed browser,
    /// network failure, etc.) still propagate as `Err`.
    pub async fn query_selector(&self, selector: &str) -> Result<Option<String>> {
        // `querySelector` returns null for no match — never throws — so the
        // only error path here is a real CDP failure, not a missing element.
        let js = format!(
            "(function(){{ var el = document.querySelector({selector:?}); \
             return el === null ? null : el.innerHTML; }})()"
        );
        let result = self
            .inner
            .evaluate_expression(js)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        // `into_value()` returns Err("No value found") when JS evaluates to
        // null/undefined — that is exactly the "not found" case, not a real
        // error, so map it to Ok(None).
        let val: Value = match result.into_value() {
            Ok(v) => v,
            Err(_) => return Ok(None),
        };

        match val {
            Value::Null => Ok(None),
            Value::String(s) => Ok(Some(s)),
            other => Ok(Some(other.to_string())),
        }
    }

    /// Run `document.querySelectorAll(selector)` and return inner HTML of each.
    /// One entry is returned per matched element; void elements yield `""`.
    pub async fn query_selector_all(&self, selector: &str) -> Result<Vec<String>> {
        // Single JS eval returns all innerHTML at once — avoids N serial CDP
        // round-trips (one per element) that the old find_elements approach
        // needed.
        let js = format!("[...document.querySelectorAll({selector:?})].map(e => e.innerHTML)");
        let val: Value = self
            .inner
            .evaluate_expression(js)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?
            .into_value()
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        match val {
            Value::Array(arr) => Ok(arr
                .into_iter()
                .map(|v| match v {
                    Value::String(s) => s,
                    other => other.to_string(),
                })
                .collect()),
            _ => Ok(Vec::new()),
        }
    }

    // ── Interaction ─────────────────────────────────────────────────────

    /// Click on the first element matching `selector`.
    pub async fn click_element(&self, selector: &str) -> Result<()> {
        self.ensure_active().await?;
        let el = self
            .inner
            .find_element(selector)
            .await
            .map_err(|e| VoidCrawlError::ElementNotFound(e.to_string()))?;
        el.click()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Type text into the first element matching `selector`.
    ///
    /// Focuses the element first so that key events are directed to it.
    pub async fn type_into(&self, selector: &str, text: &str) -> Result<()> {
        self.ensure_active().await?;
        let el = self
            .inner
            .find_element(selector)
            .await
            .map_err(|e| VoidCrawlError::ElementNotFound(e.to_string()))?;
        el.focus()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        el.type_str(text)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── Headers & Network ───────────────────────────────────────────────

    /// Set extra HTTP headers for all subsequent requests from this page.
    pub async fn set_headers(&self, headers: HashMap<String, String>) -> Result<()> {
        self.ensure_active().await?;
        self.ensure_network_enabled().await?;
        let json_val =
            serde_json::to_value(&headers).map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let params = SetExtraHttpHeadersParams::new(Headers::new(json_val));
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── Cookies ─────────────────────────────────────────────────────────

    /// Return all cookies that match the current page URL.
    pub async fn get_cookies(&self) -> Result<Vec<Cookie>> {
        self.inner
            .get_cookies()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Set a single cookie on the current page.
    pub async fn set_cookie(&self, cookie: CookieParam) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .set_cookie(cookie)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Set multiple cookies at once.
    pub async fn set_cookies(&self, cookies: Vec<CookieParam>) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .set_cookies(cookies)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Delete cookies by name, optionally scoped by domain and path.
    pub async fn delete_cookies(&self, cookies: Vec<DeleteCookiesParams>) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .delete_cookies(cookies)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── CDP Input ───────────────────────────────────────────────────────

    /// Dispatch a mouse event via the CDP `Input.dispatchMouseEvent` command.
    ///
    /// This sends a **browser-level** input event — as opposed to a JS
    /// `dispatchEvent(new MouseEvent(...))` — so it is processed by the
    /// compositor and behaves like a real user action (including triggering
    /// hover states, native drag, etc.).
    #[allow(clippy::too_many_arguments)]
    pub async fn dispatch_mouse_event(
        &self,
        event_type: DispatchMouseEventType,
        x: f64,
        y: f64,
        button: Option<MouseButton>,
        click_count: Option<i64>,
        delta_x: Option<f64>,
        delta_y: Option<f64>,
        modifiers: Option<i64>,
    ) -> Result<()> {
        self.ensure_active().await?;
        let mut builder = DispatchMouseEventParams::builder()
            .r#type(event_type)
            .x(x)
            .y(y);

        if let Some(b) = button {
            builder = builder.button(b);
        }
        if let Some(c) = click_count {
            builder = builder.click_count(c);
        }
        if let Some(dx) = delta_x {
            builder = builder.delta_x(dx);
        }
        if let Some(dy) = delta_y {
            builder = builder.delta_y(dy);
        }
        if let Some(m) = modifiers {
            builder = builder.modifiers(m);
        }

        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Dispatch a key event via the CDP `Input.dispatchKeyEvent` command.
    ///
    /// Sends a browser-level keyboard event. Use `KeyDown` + `KeyUp` for
    /// modifier keys or special keys, and `Char` for text input.
    pub async fn dispatch_key_event(
        &self,
        event_type: DispatchKeyEventType,
        key: Option<&str>,
        code: Option<&str>,
        text: Option<&str>,
        modifiers: Option<i64>,
    ) -> Result<()> {
        self.ensure_active().await?;
        let mut builder = DispatchKeyEventParams::builder().r#type(event_type);

        if let Some(k) = key {
            builder = builder.key(k);
        }
        if let Some(c) = code {
            builder = builder.code(c);
        }
        if let Some(t) = text {
            builder = builder.text(t);
        }
        if let Some(m) = modifiers {
            builder = builder.modifiers(m);
        }

        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Close this page / tab.
    pub async fn close(&self) -> Result<()> {
        self.closed.store(true, Ordering::Release);
        self.inner
            .clone()
            .close()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }
}

/// In-page download driver. `__URL__` and `__MAX__` are substituted before
/// evaluation. Streams the response, aborting past `__MAX__` bytes so a hostile
/// server can't OOM the tab, then saves the bytes via a blob `download` anchor
/// (which forces a save even for `Content-Disposition: inline` resources like
/// PDFs that Chrome would otherwise render). Resolves with bounded result data
/// after the save action has fired.
const DOWNLOAD_JS: &str = r"(async () => {
    try {
      const MAX = __MAX__;
      const ctrl = new AbortController();
      const resp = await fetch(__URL__, { credentials: 'include', signal: ctrl.signal });
      const ct = resp.headers.get('content-type');
      const cl = resp.headers.get('content-length');
      if (cl && Number(cl) > MAX) { ctrl.abort(); throw new Error('content-length ' + cl + ' exceeds limit ' + MAX); }
      let blob;
      if (resp.body && resp.body.getReader) {
        const reader = resp.body.getReader();
        const chunks = []; let total = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          total += value.byteLength;
          if (total > MAX) { ctrl.abort(); throw new Error('exceeded size limit ' + MAX + ' bytes'); }
          chunks.push(value);
        }
        blob = new Blob(chunks);
      } else {
        blob = await resp.blob();
        if (blob.size > MAX) throw new Error('exceeded size limit ' + MAX + ' bytes');
      }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (__URL__.split(/[?#]/)[0].split('/').pop()) || 'download';
      (document.body || document.documentElement).appendChild(a);
      a.click();
      return { ct, err: null };
    } catch (e) {
      return { ct: null, err: String((e && e.message) || e) };
    }
})()";

/// Strip parameters from a MIME type: `application/pdf; charset=utf-8` →
/// `application/pdf`.
fn strip_mime_params(mime: &str) -> String {
    mime.split(';')
        .next()
        .unwrap_or(mime)
        .trim()
        .to_ascii_lowercase()
}

/// `scheme://host[:port]` for `url`, or `None` if it isn't an absolute URL.
fn origin_of(url: &str) -> Option<String> {
    let (scheme, rest) = url.split_once("://")?;
    let host = rest.split(['/', '?', '#']).next()?;
    if host.is_empty() {
        return None;
    }
    Some(format!("{scheme}://{host}"))
}

/// Snapshot the set of paths currently in `dir` (empty on a read error).
fn dir_entries(dir: &Path) -> HashSet<PathBuf> {
    fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .collect()
}

/// Finished (non-`.crdownload`, non-empty) files in `dir` that are **not** in
/// `before` — i.e. downloads that appeared after the snapshot.
fn new_complete_files(dir: &Path, before: &HashSet<PathBuf>) -> Vec<(PathBuf, u64)> {
    let Ok(rd) = fs::read_dir(dir) else {
        return Vec::new();
    };
    rd.flatten()
        .filter_map(|entry| {
            let path = entry.path();
            if before.contains(&path) || path.extension().is_some_and(|e| e == "crdownload") {
                return None;
            }
            match entry.metadata() {
                Ok(m) if m.is_file() && m.len() > 0 => Some((path, m.len())),
                _ => None,
            }
        })
        .collect()
}

fn watch_download_dir(
    dir: &Path,
) -> Result<(
    RecommendedWatcher,
    mpsc::UnboundedReceiver<notify::Result<Event>>,
)> {
    let (sender, receiver) = mpsc::unbounded_channel();
    let mut watcher = RecommendedWatcher::new(
        move |event| {
            let _ = sender.send(event);
        },
        Config::default(),
    )
    .map_err(|error| VoidCrawlError::Other(format!("watch {}: {error}", dir.display())))?;
    watcher
        .watch(dir, RecursiveMode::NonRecursive)
        .map_err(|error| VoidCrawlError::Other(format!("watch {}: {error}", dir.display())))?;
    Ok((watcher, receiver))
}

/// Wait for a filesystem event that exposes a **new** completed download, or
/// until `timeout` elapses. The watcher is armed before the browser action;
/// the initial check handles completion that raced ahead of this future.
async fn wait_for_new_download(
    dir: &Path,
    before: &HashSet<PathBuf>,
    max_bytes: u64,
    events: &mut mpsc::UnboundedReceiver<notify::Result<Event>>,
    timeout: Duration,
) -> Result<DownloadOutcome> {
    let wait = async {
        if let Some(outcome) = completed_download(dir, before, max_bytes)? {
            return Ok(outcome);
        }
        loop {
            match events.recv().await {
                Some(Ok(_)) => {
                    if let Some(outcome) = completed_download(dir, before, max_bytes)? {
                        return Ok(outcome);
                    }
                }
                Some(Err(error)) => {
                    return Err(VoidCrawlError::Other(format!(
                        "watch {}: {error}",
                        dir.display()
                    )));
                }
                None => {
                    return Err(VoidCrawlError::Other(format!(
                        "download watcher for {} closed",
                        dir.display()
                    )));
                }
            }
        }
    };
    time::timeout(timeout, wait)
        .await
        .map_err(|_| download_timeout(timeout))?
}

fn completed_download(
    dir: &Path,
    before: &HashSet<PathBuf>,
    max_bytes: u64,
) -> Result<Option<DownloadOutcome>> {
    let files = new_complete_files(dir, before);
    if files.len() > 1 {
        let names = files
            .iter()
            .filter_map(|(path, _)| {
                path.file_name()
                    .map(|name| name.to_string_lossy().into_owned())
            })
            .collect::<Vec<_>>()
            .join(", ");
        return Err(VoidCrawlError::Other(format!(
            "ambiguous download: {} new files appeared ({names}); expected exactly one",
            files.len()
        )));
    }
    let Some((path, size)) = files.into_iter().next() else {
        return Ok(None);
    };
    if size > max_bytes {
        let _ = fs::remove_file(&path);
        return Err(VoidCrawlError::Other(format!(
            "download is {size} bytes, over the {max_bytes}-byte limit"
        )));
    }
    Ok(Some(DownloadOutcome {
        path,
        bytes: size,
        content_type: None,
    }))
}

fn download_timeout(timeout: Duration) -> VoidCrawlError {
    VoidCrawlError::Timeout(format!(
        "download did not complete within {}s",
        timeout.as_secs()
    ))
}

struct BrowserIdentityProbe {
    user_agent: String,
    platform: String,
    metadata: Option<UserAgentMetadata>,
}

/// Read Chrome's exact product and native User-Agent before the headless-token
/// override. `Browser.getVersion` is origin-independent, unlike Client Hints
/// on the initial `about:blank` document.
async fn probe_browser_identity(page: &CdpPage) -> Result<BrowserIdentityProbe> {
    let version = page
        .execute(GetVersionParams::default())
        .await
        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
        .result;
    let full_version = version
        .product
        .split_once('/')
        .map(|(_, value)| value)
        .filter(|value| !value.is_empty());
    let (platform, metadata) =
        client_hints_for_ua_with_full_version(&version.user_agent, full_version);
    Ok(BrowserIdentityProbe {
        user_agent: version.user_agent,
        platform,
        metadata,
    })
}

/// Strip any "Headless" token from a UA. Headless Chrome advertises
/// `HeadlessChrome/<ver>` — an instant bot signal. Rewriting only the
/// `Headless` substring keeps the version accurate (no stale hardcoded UA).
fn dehead(ua: &str) -> String {
    if ua.contains("HeadlessChrome") {
        ua.replace("HeadlessChrome", "Chrome")
    } else if ua.contains("Headless") {
        ua.replace("Headless", "")
    } else {
        ua.to_string()
    }
}

/// Derive a coherent `navigator.platform` value and Client-Hints
/// [`UserAgentMetadata`] from a UA string, so the UA, `navigator.platform`,
/// and `navigator.userAgentData` all agree. A mismatch between them (e.g. a
/// Linux UA with `navigator.platform == "Win32"`, or empty `brands`) is a
/// strong bot signal. Best-effort: an unrecognized UA gets a generic
/// Linux/x86_64 identity, and a missing Chrome version yields empty brands
/// rather than a wrong one.
fn client_hints_for_ua(ua: &str) -> (String, Option<UserAgentMetadata>) {
    client_hints_for_ua_with_full_version(ua, None)
}

fn client_hints_for_ua_with_full_version(
    ua: &str,
    exact_full_version: Option<&str>,
) -> (String, Option<UserAgentMetadata>) {
    // (navigator.platform, Sec-CH-UA-Platform, platformVersion)
    let (nav_platform, ch_platform, platform_version) = if ua.contains("Windows") {
        ("Win32", "Windows", "15.0.0".to_string())
    } else if ua.contains("Mac OS X") || ua.contains("Macintosh") {
        ("MacIntel", "macOS", "14.5.0".to_string())
    } else {
        ("Linux x86_64", "Linux", linux_platform_version())
    };

    // Chrome version from the UA: "…Chrome/148.0.0.0 …" → major "148", full
    // "148.0.0.0". `None` when absent (non-Chrome UA) → no brands.
    let chrome_ver: Option<&str> = ua
        .split("Chrome/")
        .nth(1)
        .and_then(|s| s.split_whitespace().next());
    let major: Option<&str> = chrome_ver.and_then(|v| v.split('.').next());

    let exact_full_version = exact_full_version.or(chrome_ver);
    let mut builder = UserAgentMetadata::builder()
        .platform(ch_platform)
        .platform_version(platform_version)
        .architecture("x86")
        .model("")
        .mobile(false)
        .bitness("64")
        .wow64(false);

    if let (Some(major), Some(full)) = (major, exact_full_version) {
        // Low-entropy `brands` (major only) + `fullVersionList` (full), each
        // with a GREASE entry, mirroring what real Chrome emits.
        builder = builder
            .brands([
                UserAgentBrandVersion::new("Chromium", major),
                UserAgentBrandVersion::new("Google Chrome", major),
                UserAgentBrandVersion::new("Not_A Brand", "24"),
            ])
            .full_version_lists([
                UserAgentBrandVersion::new("Chromium", full),
                UserAgentBrandVersion::new("Google Chrome", full),
                UserAgentBrandVersion::new("Not_A Brand", "24.0.0.0"),
            ]);
    }

    // build() only errors if a mandatory field is unset; platform,
    // platform_version, architecture, model, and mobile are all set above, so
    // this is `Some` in practice. `None` (unreachable) simply skips metadata.
    (nav_platform.to_string(), builder.build().ok())
}

fn linux_platform_version() -> String {
    fs::read_to_string("/proc/sys/kernel/osrelease").map_or_else(
        |_| String::new(),
        |release| {
            release
                .trim()
                .split(['.', '-'])
                .take_while(|component| {
                    !component.is_empty()
                        && component
                            .chars()
                            .all(|character| character.is_ascii_digit())
                })
                .take(3)
                .collect::<Vec<_>>()
                .join(".")
        },
    )
}

/// The mobile counterpart to [`client_hints_for_ua`], used by
/// [`Page::set_viewport`] for device-preset UAs. Real Safari (iPhone/iPad
/// UAs) never sends Client-Hints headers at all, so those get a plain UA
/// override with no fabricated metadata — matching a real device rather
/// than inventing brands Safari itself doesn't have. Chrome-on-Android UAs
/// get `mobile: true` metadata built the same way `client_hints_for_ua`
/// builds it for desktop Chrome.
fn mobile_ua_platform_and_metadata(ua: &str) -> (String, Option<UserAgentMetadata>) {
    if ua.contains("iPad") {
        return ("iPad".to_string(), None);
    }
    if ua.contains("iPhone") {
        return ("iPhone".to_string(), None);
    }

    let chrome_ver: Option<&str> = ua
        .split("Chrome/")
        .nth(1)
        .and_then(|s| s.split_whitespace().next());
    let major: Option<&str> = chrome_ver.and_then(|v| v.split('.').next());

    let mut builder = UserAgentMetadata::builder()
        .platform("Android")
        .platform_version("14.0.0")
        .architecture("")
        .model("")
        .mobile(true)
        .bitness("64")
        .wow64(false);

    if let (Some(major), Some(full)) = (major, chrome_ver) {
        builder = builder
            .brands([
                UserAgentBrandVersion::new("Chromium", major),
                UserAgentBrandVersion::new("Google Chrome", major),
                UserAgentBrandVersion::new("Not_A Brand", "24"),
            ])
            .full_version_lists([
                UserAgentBrandVersion::new("Chromium", full),
                UserAgentBrandVersion::new("Google Chrome", full),
                UserAgentBrandVersion::new("Not_A Brand", "24.0.0.0"),
            ]);
    }

    ("Linux armv8l".to_string(), builder.build().ok())
}

#[cfg(test)]
#[path = "page/page_tests.rs"]
mod page_tests;
