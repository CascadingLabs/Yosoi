//! `BrowserSession` — the main entry point for controlling a browser.

use std::{
    env, fmt,
    net::Ipv4Addr,
    num::NonZeroU16,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use chromiumoxide::{
    Page as CdpPage,
    browser::{Browser, BrowserConfig, BrowserConfigBuilder, CdpMode},
    cdp::browser_protocol::{
        browser::BrowserContextId,
        target::{
            CreateBrowserContextParams, CreateTargetParams, DisposeBrowserContextParams, TargetInfo,
        },
    },
    error::{BrowserStderr, CdpError},
    handler::{Handler, HandlerConfig},
};
use tokio::{
    net::TcpListener,
    runtime::Handle,
    sync::{Mutex, oneshot},
    task::JoinHandle,
    time,
};

const SESSION_CLOSE_TIMEOUT: Duration = Duration::from_secs(10);
const ATTACHED_TARGET_WAIT_TIMEOUT: Duration = Duration::from_secs(5);
const AUTO_DEBUG_PORT_ATTEMPTS: u8 = 3;

mod browser_distribution;
mod browser_mode;
mod security;
use browser_distribution::supported_chrome_executable;
use browser_mode::browser_mode_observation;

use crate::{
    context_isolation::{BrowserStateBinding, IsolatedBrowserContext},
    environment::EnvironmentObservation,
    error::{Result, VoidCrawlError},
    interrupt::{InterruptInfo, InterruptRegistry, InterruptRequest},
    page::Page,
    profile_context::ManagedProfileContext,
    stealth::StealthConfig,
};

async fn fetch_attached_pages(browser: &mut Browser) -> Result<Vec<(TargetInfo, CdpPage)>> {
    let targets = browser
        .fetch_targets()
        .await
        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
    let mut pages = Vec::new();
    for target in targets.into_iter().filter(|target| target.r#type == "page") {
        let page = time::timeout(
            ATTACHED_TARGET_WAIT_TIMEOUT,
            browser.wait_for_page(target.target_id.clone()),
        )
        .await
        .map_err(|_| {
            VoidCrawlError::Timeout(format!(
                "browser target {:?} did not initialize within 5s",
                target.target_id.inner()
            ))
        })?
        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        pages.push((target, page));
    }
    Ok(pages)
}

/// VoidCrawl's default Chrome command-line flags, applied to every launched
/// (non-remote) session.
///
/// Two groups:
/// 1. **Low-noise launch hygiene** — re-adds only the operational flags we
///    want after `disable_default_args()`. Avoid unsupported anti-automation
///    switches and broad background/network/render throttling suppression.
/// 2. **Hardware GPU / WebGL** — new headless disables the GPU and falls back
///    to SwiftShader software WebGL, which `WEBGL_debug_renderer_info` reports
///    as "SwiftShader" — a strong bot signal Cloudflare Turnstile weighs. These
///    request hardware acceleration through ANGLE while preserving Chromium's
///    GPU-process sandbox. Sandbox-disabling caller switches are rejected before launch.
///
/// Flags are stored **without** the leading `--`: chromiumoxide's
/// `BrowserConfig::arg` prepends `--` itself (it treats the whole string as a
/// switch key and emits `--{key}`), so passing `"--foo"` would yield the
/// inert `----foo`. Caller `extra_args` are normalized the same way (a leading
/// `--` is stripped) — see [`assemble_chrome_args`].
///
/// These are merged *before* caller `extra_args`; a caller value for the same
/// switch replaces the default (see [`assemble_chrome_args`]).
pub(crate) const DEFAULT_CHROME_ARGS: &[&str] = &[
    // ── Browser interoperability ────────────────────────────────────
    "remote-allow-origins=*",
    // Preserve Chrome's site and process isolation defaults. Cross-origin
    // out-of-process frame support belongs in the controller/session model;
    // making those frames easier to reach is not a reason to weaken the
    // production browser's security boundary.
    // ── Low-noise nodriver profile hygiene ──────────────────────────
    "disable-breakpad",
    "disable-dev-shm-usage",
    "no-first-run",
    "no-service-autorun",
    "no-default-browser-check",
    "no-pings",
    "password-store=basic",
    "disable-session-crashed-bubble",
    "disable-search-engine-choice-screen",
    "homepage=about:blank",
    // ── Hardware GPU / WebGL ────────────────────────────────────────
    "enable-gpu",
    "ignore-gpu-blocklist",
    // ANGLE backend selector — the single GPU-backend knob a caller overrides
    // (e.g. `use-angle=swiftshader` / `=gl`). Note: do NOT also pass
    // `enable-features=Vulkan` here; that force-enables Vulkan independently
    // and would silently defeat a caller's `use-angle` override.
    "use-angle=vulkan",
];

/// Default `Browser::launch` timeout. chromiumoxide ships a 20s default, which
/// is too tight for a cold start on a headless CI runner: the stealth-critical
/// `enable-gpu` / `use-angle=vulkan` flags ([`DEFAULT_CHROME_ARGS`]) hit a box
/// with no working Vulkan ICD (every GitHub-hosted runner is one), so the GPU
/// process crash-loops before Chrome prints its `DevTools listening on ws://…`
/// line — occasionally pushing the first launch past 20s and aborting it with a
/// `LaunchTimeout`. 45s gives that cold start headroom without touching the GPU
/// flags. Override with `CHROME_LAUNCH_TIMEOUT_SECS`.
const DEFAULT_LAUNCH_TIMEOUT_SECS: u64 = 45;

/// Resolve the Chrome launch timeout from `CHROME_LAUNCH_TIMEOUT_SECS`, falling
/// back to [`DEFAULT_LAUNCH_TIMEOUT_SECS`]. An unset, unparseable, or `0` value
/// uses the default.
fn launch_timeout() -> Duration {
    let secs = env::var("CHROME_LAUNCH_TIMEOUT_SECS")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .filter(|&n| n > 0)
        .unwrap_or(DEFAULT_LAUNCH_TIMEOUT_SECS);
    Duration::from_secs(secs)
}

async fn reserve_debug_port() -> Result<u16> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .map_err(|error| VoidCrawlError::LaunchFailed(error.to_string()))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| VoidCrawlError::LaunchFailed(error.to_string()))
}

fn stderr_mentions_debug_port_collision(stderr: &BrowserStderr) -> bool {
    [
        b"Address already in use".as_slice(),
        b"bind() failed".as_slice(),
        b"Cannot start http server for devtools".as_slice(),
    ]
    .iter()
    .any(|needle| {
        stderr
            .as_slice()
            .windows(needle.len())
            .any(|window| window == *needle)
    })
}

fn launch_failed_on_debug_port(error: &CdpError) -> bool {
    match error {
        CdpError::LaunchExit(_, stderr)
        | CdpError::LaunchTimeout(stderr)
        | CdpError::LaunchIo(_, stderr) => stderr_mentions_debug_port_collision(stderr),
        _ => false,
    }
}

async fn launch_with_debug_port(
    builder: BrowserConfigBuilder,
    policy: BrowserDebugPortPolicy,
) -> Result<(Browser, Handler)> {
    let mut attempt = 0_u8;
    loop {
        attempt = attempt.saturating_add(1);
        let port = match policy {
            BrowserDebugPortPolicy::SupportedEphemeral => reserve_debug_port().await?,
            BrowserDebugPortPolicy::ChromeAssigned => 0,
            BrowserDebugPortPolicy::Fixed(port) => port.get(),
        };
        let config = builder
            .clone()
            .port(port)
            .build()
            .map_err(VoidCrawlError::LaunchFailed)?;
        match Browser::launch(config).await {
            Ok(launched) => return Ok(launched),
            Err(error)
                if matches!(policy, BrowserDebugPortPolicy::SupportedEphemeral)
                    && attempt < AUTO_DEBUG_PORT_ATTEMPTS
                    && launch_failed_on_debug_port(&error) => {}
            Err(error) => return Err(VoidCrawlError::LaunchFailed(error.to_string())),
        }
    }
}

/// Normalize a Chrome flag to the form chromiumoxide wants: strip a single
/// leading `--` if present, so both `"--use-angle=gl"` (how a human/Python
/// caller writes it) and `"use-angle=gl"` end up as `use-angle=gl`.
fn normalize_flag(arg: &str) -> &str {
    arg.strip_prefix("--").unwrap_or(arg)
}

/// The switch key of a (normalized) Chrome flag: the part before `=`, or the
/// whole flag if it takes no value. `use-angle=vulkan` → `use-angle`.
fn switch_key(arg: &str) -> &str {
    arg.split_once('=').map_or(arg, |(k, _)| k)
}

/// Assemble the final Chrome flag list from VoidCrawl's [`DEFAULT_CHROME_ARGS`]
/// merged with the caller's `extra_args`. Output is in chromiumoxide form (no
/// leading `--`).
///
/// **Override contract (directional control):** caller args are normalized
/// (leading `--` stripped) and merged by switch key — for each caller arg that
/// shares a key with a default (e.g. `--use-angle=gl` vs the default
/// `use-angle=vulkan`), the caller's value *replaces* the default in place,
/// leaving a single occurrence; novel caller args are appended. We deliberately
/// do **not** emit duplicate switches and hope Chrome picks the right one — its
/// precedence is per-switch and inconsistent (`use-angle` takes the *first*
/// value). Dedup-by-key makes Yosoi's explicit browser configuration
/// deterministic.
pub(crate) fn assemble_chrome_args(extra_args: &[String]) -> Vec<String> {
    let mut out: Vec<String> = DEFAULT_CHROME_ARGS
        .iter()
        .map(|s| (*s).to_string())
        .collect();
    for arg in extra_args {
        let flag = normalize_flag(arg);
        let key = switch_key(flag);
        if let Some(slot) = out.iter_mut().find(|d| switch_key(d) == key) {
            *slot = flag.to_string(); // caller overrides the default for this switch
        } else {
            out.push(flag.to_string());
        }
    }
    out
}

/// How the browser should be acquired.
#[derive(Debug, Clone, Default)]
pub enum BrowserMode {
    /// Launch a new headless browser.
    #[default]
    Headless,
    /// Launch a new browser with a visible window.
    Headful,
    /// Connect to an already-running Chrome via its WebSocket debugger URL.
    RemoteDebug { ws_url: String },
}

/// How launched Chrome binds its loopback DevTools endpoint.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum BrowserDebugPortPolicy {
    /// Reserve a non-zero ephemeral port and retry only a proven bind race.
    /// Chrome natively reports `navigator.webdriver == false`.
    #[default]
    SupportedEphemeral,
    /// Pass port zero and let Chrome choose the final port. Chrome natively
    /// reports `navigator.webdriver == true` in this mode.
    ChromeAssigned,
    /// Bind one operator-selected non-zero port.
    Fixed(NonZeroU16),
}

/// Builder for `BrowserSession`.
#[derive(Debug, Clone)]
#[must_use]
pub struct BrowserSessionBuilder {
    mode: BrowserMode,
    stealth: StealthConfig,
    extra_args: Vec<String>,
    chrome_executable: Option<String>,
    proxy: Option<String>,
    no_sandbox: bool,
    window_size: Option<(u32, u32)>,
    debug_port: BrowserDebugPortPolicy,
    /// Persistent Chrome profile directory. `None` (default) = ephemeral
    /// `TempDir` that is deleted on session drop. `Some(path)` = mount an
    /// existing profile (e.g. one you've logged into `LinkedIn` in) and
    /// leave the directory on disk after the session ends.
    user_data_dir: Option<PathBuf>,
    /// How many CDP domains to eagerly enable. Defaults to
    /// [`CdpMode::Normal`], which every capture-dependent feature needs.
    /// See [`BrowserSessionBuilder::cdp_mode`].
    cdp_mode: CdpMode,
}

impl Default for BrowserSessionBuilder {
    fn default() -> Self {
        Self {
            mode: BrowserMode::Headless,
            stealth: StealthConfig::chrome_like(),
            extra_args: Vec::new(),
            chrome_executable: None,
            proxy: None,
            no_sandbox: false,
            window_size: None,
            debug_port: BrowserDebugPortPolicy::default(),
            user_data_dir: None,
            cdp_mode: CdpMode::from_env_default(),
        }
    }
}

impl BrowserSessionBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn mode(mut self, mode: BrowserMode) -> Self {
        self.mode = mode;
        self
    }

    pub fn headless(self) -> Self {
        self.mode(BrowserMode::Headless)
    }

    pub fn headful(self) -> Self {
        self.mode(BrowserMode::Headful)
    }

    pub fn remote_debug(self, ws_url: impl Into<String>) -> Self {
        self.mode(BrowserMode::RemoteDebug {
            ws_url: ws_url.into(),
        })
    }

    pub fn stealth(mut self, config: StealthConfig) -> Self {
        self.stealth = config;
        self
    }

    /// Add one explicit Chrome command-line switch.
    ///
    /// VoidCrawl preserves Chromium's GPU-process sandbox by default. Use
    /// `disable-gpu-sandbox` only as a host-specific, documented workaround
    /// after confirming a graphics-driver incompatibility; Chrome warns that
    /// it reduces security and stability.
    pub fn arg(mut self, arg: impl Into<String>) -> Self {
        self.extra_args.push(arg.into());
        self
    }

    pub fn chrome_executable(mut self, path: impl Into<String>) -> Self {
        self.chrome_executable = Some(path.into());
        self
    }

    pub fn proxy(mut self, proxy_url: impl Into<String>) -> Self {
        self.proxy = Some(proxy_url.into());
        self
    }

    /// Legacy setting retained for callers; launch rejects it because no
    /// sandbox-disabling security exception is currently approved.
    pub const fn no_sandbox(mut self) -> Self {
        self.no_sandbox = true;
        self
    }

    pub const fn window_size(mut self, width: u32, height: u32) -> Self {
        self.window_size = Some((width, height));
        self
    }

    /// Select Chrome's loopback DevTools port policy.
    pub const fn debug_port_policy(mut self, policy: BrowserDebugPortPolicy) -> Self {
        self.debug_port = policy;
        self
    }

    /// Mount a persistent Chrome profile directory. Use this to reuse
    /// an existing login (cookies, local storage, extensions) across
    /// sessions. The directory is NOT deleted when the session closes.
    ///
    /// Pick a directory dedicated to `void_crawl` — Chrome locks a
    /// profile while it's running, so pointing at your daily-driver
    /// profile while your real Chrome is open will fail to launch.
    pub fn user_data_dir(mut self, path: impl Into<PathBuf>) -> Self {
        self.user_data_dir = Some(path.into());
        self
    }

    /// Choose how many CDP domains to eagerly enable for this session.
    ///
    /// [`CdpMode::Normal`] (the default) enables `Runtime`, `Network`,
    /// `Performance`, `Log`, and target auto-attach up front — the behavior
    /// every capture-dependent feature is built on.
    ///
    /// [`CdpMode::Minimal`] skips all of them, which is what lets a session
    /// clear a Cloudflare Managed Challenge that a normal CDP client
    /// cannot. It is a real trade, not a free win — in Minimal mode these
    /// stop working:
    ///
    /// - [`Page::arm_response_capture`](crate::Page::arm_response_capture) and
    ///   everything over it (`network_capture_arm` / `network_capture_wait`,
    ///   CDP request-header capture) — no `Network.enable`, so no events arrive
    /// - [`Page::wait_for_network_idle`](crate::Page::wait_for_network_idle)
    /// - cross-origin `evaluate_js_in_frame` and `evaluate_function` — both
    ///   need `Runtime` / the isolated utility world
    /// - OOPIF and child-target auto-attach
    ///
    /// Navigation, screenshots, accessibility, input, and main-world
    /// `eval_js` are unaffected.
    pub const fn cdp_mode(mut self, mode: CdpMode) -> Self {
        self.cdp_mode = mode;
        self
    }

    /// Shorthand for [`cdp_mode(CdpMode::Minimal)`](Self::cdp_mode). Read that
    /// method's list of what Minimal gives up before reaching for this.
    pub const fn minimal_cdp(self) -> Self {
        self.cdp_mode(CdpMode::Minimal)
    }

    /// Override the stealth viewport dimensions.
    ///
    /// This sets the CDP device metrics override that the page reports to
    /// JavaScript (e.g. `window.innerWidth`). It does NOT resize the Chrome
    /// window — use [`window_size`](Self::window_size) for that.
    pub const fn viewport(mut self, width: u32, height: u32) -> Self {
        self.stealth.viewport_width = width;
        self.stealth.viewport_height = height;
        self
    }

    /// Build and launch (or connect to) the browser.
    pub async fn launch(self) -> Result<BrowserSession> {
        BrowserSession::connect_or_launch(
            self.mode,
            self.stealth,
            self.extra_args,
            self.chrome_executable,
            self.proxy,
            self.no_sandbox,
            self.window_size,
            self.debug_port,
            self.user_data_dir,
            self.cdp_mode,
        )
        .await
    }
}

struct PendingBrowserContext {
    browser: Arc<Mutex<Browser>>,
    context_id: Option<BrowserContextId>,
}

impl PendingBrowserContext {
    const fn new(browser: Arc<Mutex<Browser>>, context_id: BrowserContextId) -> Self {
        Self {
            browser,
            context_id: Some(context_id),
        }
    }

    fn disarm(&mut self) {
        self.context_id = None;
    }

    async fn dispose(mut self) {
        let Some(context_id) = self.context_id.take() else {
            return;
        };
        let browser = Arc::clone(&self.browser);
        let cleanup = tokio::spawn(async move {
            let _ = browser
                .lock()
                .await
                .execute(DisposeBrowserContextParams::new(context_id))
                .await;
        });
        let _ = cleanup.await;
    }
}

impl Drop for PendingBrowserContext {
    fn drop(&mut self) {
        let Some(context_id) = self.context_id.take() else {
            return;
        };
        let Ok(runtime) = Handle::try_current() else {
            return;
        };
        let browser = Arc::clone(&self.browser);
        runtime.spawn(async move {
            let _ = browser
                .lock()
                .await
                .execute(DisposeBrowserContextParams::new(context_id))
                .await;
        });
    }
}

/// A live browser session wrapping `chromiumoxide::Browser`.
///
/// Use [`BrowserSessionBuilder`] or the convenience constructors to create one.
pub struct BrowserSession {
    browser: Arc<Mutex<Browser>>,
    browser_mode: EnvironmentObservation<yosoi_types::BrowserMode>,
    cdp_mode: CdpMode,
    interrupts: Arc<InterruptRegistry>,
    /// Retained until shutdown completes so cancellation of `close()` cannot
    /// detach the handler task.
    handler_task: Mutex<Option<JoinHandle<()>>>,
    /// Launched-browser shutdown is a one-way background operation. Retaining
    /// its handle lets a later `close()` await the same work after
    /// cancellation.
    browser_shutdown_task: Mutex<Option<JoinHandle<Result<()>>>>,
    handler_alive: Arc<AtomicBool>,
    /// Serializes close attempts. A cancelled close leaves this unlocked so a
    /// later call can finish shutdown without issuing duplicate successful
    /// work.
    close_lock: Mutex<()>,
    close_started: Arc<AtomicBool>,
    close_complete: AtomicBool,
    stealth: StealthConfig,
    /// True when this session attached to an already-running Chrome via
    /// `BrowserMode::RemoteDebug`. In that case `close()` must NOT send
    /// `Browser.close` over CDP — doing so terminates the user's Chromium
    /// process, which we didn't spawn and have no business shutting down.
    attached: bool,
    state_binding: BrowserStateBinding,
    /// Owns the temporary user data directory for launched browsers.
    /// `None` for remote-debug sessions (no local user data dir).
    /// Dropped after `browser` and `_handler_task`, so Chrome has already
    /// been signalled to close before the directory is deleted.
    _user_data_dir: Option<tempfile::TempDir>,
    /// Shared with every `Page` this session creates, so screenshot capture
    /// is serialized per-browser rather than per-tab. See [`Page::screenshot`].
    capture_lock: Arc<Mutex<()>>,
}

impl fmt::Debug for BrowserSession {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BrowserSession")
            .field("stealth", &self.stealth)
            .finish_non_exhaustive()
    }
}

impl BrowserSession {
    /// Returns `true` while the CDP handler loop is still running.
    ///
    /// When this returns `false`, the browser process has likely crashed or
    /// the WebSocket connection has been lost — all subsequent CDP calls
    /// will fail. VoidCrawl intentionally does not expose a termination
    /// subscription: the handler owns the CDP stream, while this synchronous
    /// liveness fact and typed `BrowserClosed`/provider errors let callers
    /// distinguish a dead provider without creating another public task or
    /// event-lifetime contract.
    pub fn is_alive(&self) -> bool {
        !self.close_started.load(Ordering::Acquire) && self.handler_alive.load(Ordering::Acquire)
    }

    /// Check that the handler is still running; return `BrowserClosed` if not.
    fn check_alive(&self) -> Result<()> {
        if self.is_alive() {
            Ok(())
        } else {
            Err(VoidCrawlError::BrowserClosed)
        }
    }

    /// Create a builder.
    pub fn builder() -> BrowserSessionBuilder {
        BrowserSessionBuilder::new()
    }

    /// Quick headless launch with default stealth.
    pub async fn launch_headless() -> Result<Self> {
        Self::builder().headless().launch().await
    }

    /// Quick headed launch with default stealth.
    pub async fn launch_headful() -> Result<Self> {
        Self::builder().headful().launch().await
    }

    /// Connect to an existing browser.
    pub async fn connect(ws_url: impl Into<String>) -> Result<Self> {
        Self::builder().remote_debug(ws_url).launch().await
    }

    /// Internal factory that handles all three modes.
    #[allow(
        clippy::too_many_arguments,
        reason = "builder forwards all options at once"
    )]
    async fn connect_or_launch(
        mode: BrowserMode,
        stealth: StealthConfig,
        extra_args: Vec<String>,
        chrome_executable: Option<String>,
        proxy: Option<String>,
        no_sandbox: bool,
        window_size: Option<(u32, u32)>,
        debug_port: BrowserDebugPortPolicy,
        persistent_user_data_dir: Option<PathBuf>,
        cdp_mode: CdpMode,
    ) -> Result<Self> {
        security::validate_launch_security(&extra_args, no_sandbox)?;
        let browser_mode = browser_mode_observation(&mode);
        let state_binding = if matches!(mode, BrowserMode::RemoteDebug { .. }) {
            BrowserStateBinding::AttachedBrowser
        } else if persistent_user_data_dir.is_some() {
            BrowserStateBinding::ManagedProfile
        } else {
            BrowserStateBinding::SharedBrowserProfile
        };
        let mut owned_user_data_dir: Option<tempfile::TempDir> = None;

        let (browser, handler) = match &mode {
            BrowserMode::RemoteDebug { ws_url } => {
                security::require_local_attachment(ws_url)?;
                let ws = security::resolve_ws_url(ws_url).await?;
                security::require_local_attachment(&ws)?;
                // `Browser::connect` hardcodes `HandlerConfig::default()`,
                // which would re-read the environment and
                // discard an explicit `cdp_mode`.
                let handler_config = HandlerConfig {
                    cdp_mode,
                    ignore_invalid_messages: false,
                    ..HandlerConfig::default()
                };
                Browser::connect_with_config(&ws, handler_config)
                    .await
                    .map_err(|e| VoidCrawlError::ConnectionFailed(e.to_string()))?
            }
            BrowserMode::Headless | BrowserMode::Headful => {
                let chrome_executable =
                    supported_chrome_executable(chrome_executable.as_deref()).await?;
                // Disable chromiumoxide's DEFAULT_ARGS which include
                // `--enable-automation` and `--disable-extensions` —
                // both are instant giveaways to WAFs like Akamai.
                let mut builder = BrowserConfig::builder()
                    .disable_default_args()
                    .cdp_mode(cdp_mode)
                    .surface_invalid_messages();

                // Caller-supplied persistent profile vs. ephemeral
                // `TempDir`. The ephemeral path handles SingletonLock
                // conflicts across concurrent browsers automatically;
                // the persistent path is the caller's problem (they
                // chose it, so don't pick their live daily-driver).
                if let Some(ref path) = persistent_user_data_dir {
                    builder = builder.user_data_dir(path);
                } else {
                    let tmp = tempfile::tempdir()
                        .map_err(|e| VoidCrawlError::LaunchFailed(format!("tmpdir: {e}")))?;
                    builder = builder.user_data_dir(tmp.path());
                    owned_user_data_dir = Some(tmp);
                }

                if matches!(mode, BrowserMode::Headful) {
                    builder = builder.with_head();
                } else {
                    // Use the *new* headless mode. chromiumoxide defaults to
                    // `HeadlessMode::True`, which emits the legacy `--headless`
                    // flag — and legacy headless forces SwiftShader software
                    // rendering, so `WEBGL_debug_renderer_info` reports
                    // "SwiftShader", a glaring bot signal that WAFs like
                    // Cloudflare Turnstile weigh heavily. `--headless=new` runs
                    // the full browser stack and can drive a real GPU.
                    builder = builder.new_headless_mode();
                }

                builder = builder.chrome_executable(&chrome_executable);

                if no_sandbox {
                    builder = builder.no_sandbox();
                }

                // Keep the native window/screen geometry aligned with the
                // launch-time viewport override. Without an explicit window
                // size, new headless Chrome exposes its 800x600 default screen
                // alongside VoidCrawl's 1920x1080 inner viewport.
                let (window_width, window_height) =
                    window_size.unwrap_or((stealth.viewport_width, stealth.viewport_height));
                builder = builder.window_size(window_width, window_height);

                if let Some(ref p) = proxy {
                    builder = builder.arg(format!("--proxy-server={p}"));
                }

                // VoidCrawl's default Chrome flags merged with the caller's
                // `extra_args` (dedup-by-switch-key; caller value replaces the
                // default). Lets the Yosoi caller override any default
                // deterministically via `BrowserConfig(extra_args=...)`. See
                // `assemble_chrome_args` and its unit tests.
                let final_args = assemble_chrome_args(&extra_args);
                for a in final_args {
                    builder = builder.arg(a);
                }

                // Give Chrome longer than chromiumoxide's 20s default to print
                // its WebSocket URL — a cold start with the GPU stack thrashing
                // (no Vulkan on CI) can run past 20s. See `launch_timeout`.
                builder = builder.launch_timeout(launch_timeout());

                launch_with_debug_port(builder, debug_port).await?
            }
        };

        let alive = Arc::new(AtomicBool::new(true));
        let handler_task = spawn_handler(handler, Arc::clone(&alive));
        if matches!(mode, BrowserMode::RemoteDebug { .. })
            && let Err(error) = security::verify_attached_browser(&browser).await
        {
            handler_task.abort();
            let _ = handler_task.await;
            return Err(error);
        }

        Ok(Self {
            browser: Arc::new(Mutex::new(browser)),
            browser_mode,
            cdp_mode,
            interrupts: InterruptRegistry::new(),
            handler_task: Mutex::new(Some(handler_task)),
            browser_shutdown_task: Mutex::new(None),
            handler_alive: alive,
            close_lock: Mutex::new(()),
            close_started: Arc::new(AtomicBool::new(false)),
            close_complete: AtomicBool::new(false),
            stealth,
            attached: matches!(mode, BrowserMode::RemoteDebug { .. }),
            state_binding,
            _user_data_dir: owned_user_data_dir,
            capture_lock: Arc::new(Mutex::new(())),
        })
    }

    /// Open a new tab, apply stealth settings, and navigate to `url`.
    ///
    /// Stealth is applied on a blank page *before* navigation so that
    /// `addScriptToEvaluateOnNewDocument` scripts fire during the real
    /// page load — not after it.
    pub async fn new_page(&self, url: &str) -> Result<Page> {
        self.check_alive()?;
        let page = {
            let browser = self.browser.lock().await;
            let cdp_page = browser
                .new_page("about:blank")
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let page = self.wrap_page(cdp_page);
            drop(browser);
            page
        }; // browser lock released before navigation

        if let Some(stealth) = self.stealth_for_session() {
            page.apply_stealth(&stealth).await?;
        }
        page.navigate(url).await?;
        Ok(page)
    }

    /// Open a blank tab with stealth applied (no navigation).
    pub async fn new_blank_page(&self) -> Result<Page> {
        self.check_alive()?;
        let page = {
            let browser = self.browser.lock().await;
            let cdp_page = browser
                .new_page("about:blank")
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let page = self.wrap_page(cdp_page);
            drop(browser);
            page
        };
        if let Some(stealth) = self.stealth_for_session() {
            page.apply_stealth(&stealth).await?;
        }
        Ok(page)
    }

    /// Create a fresh disposable Chromium browser context and one blank page.
    ///
    /// Unlike ordinary pages in the session's default profile, this context does not share
    /// cookies, cache, origin storage, service workers, permissions, or
    /// context-scoped network state with the session's default profile or
    /// another isolated context. Dispose the returned handle rather than
    /// attempting to reset those state families individually.
    pub async fn new_isolated_context(&self) -> Result<IsolatedBrowserContext> {
        self.check_alive()?;
        let browser = Arc::clone(&self.browser);
        let capture_lock = Arc::clone(&self.capture_lock);
        let interrupts = Arc::clone(&self.interrupts);
        let browser_mode = self.browser_mode.clone();
        let handler_alive = Arc::clone(&self.handler_alive);
        let browser_closing = Arc::clone(&self.close_started);
        let stealth = self.stealth_for_session();
        let cdp_mode = self.cdp_mode;
        let attached = self.attached;

        // Retain the entire construction beyond caller cancellation. The
        // worker sends its result through a channel rather than returning an
        // owned context as detached task output. If the caller disappears,
        // the failed send gives the worker the context back for explicit
        // awaited disposal.
        let (result_tx, result_rx) = oneshot::channel();
        tokio::spawn(async move {
            let result = async move {
                let (context_id, cdp_page, mut pending_context) = {
                    let browser_guard = browser.lock().await;
                    let context_id = browser_guard
                        .execute(
                            CreateBrowserContextParams::builder()
                                .dispose_on_detach(true)
                                .build(),
                        )
                        .await
                        .map_err(|e| VoidCrawlError::PageError(e.to_string()))?
                        .result
                        .browser_context_id;
                    let mut pending_context =
                        PendingBrowserContext::new(Arc::clone(&browser), context_id.clone());
                    let params = CreateTargetParams::builder()
                        .url("about:blank")
                        .browser_context_id(context_id.clone())
                        .build()
                        .map_err(VoidCrawlError::PageError)?;
                    let result = match browser_guard.new_page(params).await {
                        Ok(page) => (context_id, page, pending_context),
                        Err(error) => {
                            let _ = browser_guard
                                .execute(DisposeBrowserContextParams::new(context_id))
                                .await;
                            pending_context.disarm();
                            return Err(VoidCrawlError::PageError(error.to_string()));
                        }
                    };
                    drop(browser_guard);
                    result
                };
                let page = Page::new(
                    cdp_page,
                    Arc::clone(&capture_lock),
                    Arc::clone(&interrupts),
                    browser_mode.clone(),
                    cdp_mode,
                    attached,
                    Arc::clone(&browser_closing),
                    BrowserStateBinding::IsolatedBrowserContext,
                    Some(context_id.clone()),
                );
                if let Some(stealth) = &stealth
                    && let Err(error) = page.apply_stealth(stealth).await
                {
                    pending_context.dispose().await;
                    return Err(error);
                }
                pending_context.disarm();
                Ok(IsolatedBrowserContext::new(
                    page,
                    browser,
                    context_id,
                    capture_lock,
                    interrupts,
                    browser_mode,
                    cdp_mode,
                    attached,
                    stealth,
                    handler_alive,
                    browser_closing,
                ))
            }
            .await;

            if let Err(unreceived) = result_tx.send(result)
                && let Ok(context) = unreceived
            {
                let _ = context.dispose().await;
            }
        });
        result_rx.await.map_err(|_| {
            VoidCrawlError::Other("context construction task ended without a result".into())
        })?
    }

    fn wrap_page(&self, page: chromiumoxide::Page) -> Page {
        self.wrap_page_with_binding(page, self.state_binding)
    }

    fn wrap_page_with_binding(
        &self,
        page: chromiumoxide::Page,
        state_binding: BrowserStateBinding,
    ) -> Page {
        Page::new(
            page,
            Arc::clone(&self.capture_lock),
            Arc::clone(&self.interrupts),
            self.browser_mode.clone(),
            self.cdp_mode,
            self.attached,
            Arc::clone(&self.close_started),
            state_binding,
            None,
        )
    }

    fn stealth_for_session(&self) -> Option<StealthConfig> {
        if self.attached {
            // Remote/headful Chrome already has native UA, window, and language
            // state. Avoid pre-navigation mutations and keep the CDP footprint
            // close to nodriver/a human operator.
            return None;
        }

        Some(self.stealth.clone())
    }

    /// Open a new tab **in its own browser window**, apply stealth settings,
    /// and navigate to `url`.
    ///
    /// Headless Chrome composites the frontmost tab of a window. Tabs opened
    /// by [`BrowserSession::new_page`] share one window, so bringing any of
    /// them to the front stops the others painting — which is why
    /// [`Page::screenshot`](crate::Page::screenshot) serializes on a
    /// browser-wide capture lock, and why a
    /// [`recording`](crate::recording) on a shared-window tab goes silent as
    /// soon as a sibling captures.
    ///
    /// A tab in its own window is not occluded by activity in another
    /// window, so it keeps painting and keeps delivering screencast frames
    /// while other tabs capture. That makes this the tab to record on when
    /// recording has to run concurrently with other work — see
    /// [`RecordingOptions::foreground`](crate::RecordingOptions::foreground).
    ///
    /// Costs a real browser window's worth of resources, so this is opt-in
    /// rather than what `new_page` does by default.
    pub async fn new_page_in_window(&self, url: &str) -> Result<Page> {
        self.check_alive()?;
        let params = CreateTargetParams::builder()
            .url("about:blank")
            .new_window(true)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        let page = {
            let browser = self.browser.lock().await;
            let cdp_page = browser
                .new_page(params)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let page = self.wrap_page(cdp_page);
            drop(browser);
            page
        }; // browser lock released before navigation

        page.apply_stealth(&self.stealth).await?;
        page.navigate(url).await?;
        Ok(page)
    }
    /// List all open pages.
    pub async fn pages(&self) -> Result<Vec<Page>> {
        self.check_alive()?;
        let mut browser = self.browser.lock().await;
        if self.attached {
            // A remote-debug session may attach after its tabs already exist.
            let pages = fetch_attached_pages(&mut browser).await?;
            let pages = pages
                .into_iter()
                .map(|(_, page)| self.wrap_page(page))
                .collect();
            drop(browser);
            return Ok(pages);
        }
        let cdp_pages = browser
            .pages()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let pages = cdp_pages
            .into_iter()
            .map(|page| self.wrap_page(page))
            .collect();
        drop(browser);
        Ok(pages)
    }

    /// The browser's CDP WebSocket endpoint (`ws://…`).
    ///
    /// Hand this to another process so a typed [`BrowserSession`] can attach to
    /// the same Chrome via `BrowserConfig { ws_url, .. }` and enumerate its
    /// pages. VoidCrawl does not expose raw target identities for exact-tab
    /// adoption.
    pub async fn websocket_url(&self) -> String {
        self.browser.lock().await.websocket_address().clone()
    }

    /// Mark one page as requiring explicit external review. No page action is
    /// replayed by [`resume_interrupt`](Self::resume_interrupt).
    pub async fn interrupt_page(
        &self,
        page: &Page,
        request: InterruptRequest,
    ) -> Result<InterruptInfo> {
        self.check_alive()?;
        if !page.belongs_to_interrupt_registry(&self.interrupts) {
            return Err(VoidCrawlError::InterruptPageNotOwned);
        }
        self.interrupts.interrupt(page.target_id(), request).await
    }

    /// Return redacted status for an interrupt owned by this browser session.
    pub async fn interrupt_status(&self, interrupt_id: &str) -> Result<InterruptInfo> {
        self.interrupts.status(interrupt_id).await
    }

    /// Reactivate a previously interrupted page in this browser session.
    pub async fn resume_interrupt(&self, interrupt_id: &str) -> Result<InterruptInfo> {
        self.check_alive()?;
        self.interrupts.resume(interrupt_id).await
    }

    /// Release a previously interrupted page without replaying any browser
    /// action.
    pub async fn release_interrupt(&self, interrupt_id: &str) -> Result<InterruptInfo> {
        self.interrupts.release(interrupt_id).await
    }

    /// Get browser version string.
    pub async fn version(&self) -> Result<String> {
        self.check_alive()?;
        let browser = self.browser.lock().await;
        let info = browser
            .version()
            .await
            .map_err(|e| VoidCrawlError::Other(e.to_string()))?;
        drop(browser);
        Ok(info.product)
    }

    /// Gracefully close the session. This operation is idempotent and may be
    /// retried if its caller is cancelled. Launched sessions send
    /// `Browser.close` once and wait at most [`SESSION_CLOSE_TIMEOUT`] for
    /// the handler/process; attached sessions only disconnect their handler
    /// and never close Chrome.
    pub async fn close(&self) -> Result<()> {
        if self.close_complete.load(Ordering::Acquire) {
            return Ok(());
        }
        self.close_started.store(true, Ordering::Release);
        let _close = self.close_lock.lock().await;
        if self.close_complete.load(Ordering::Acquire) {
            return Ok(());
        }

        if self.attached {
            self.stop_handler().await?;
            self.close_complete.store(true, Ordering::Release);
            return Ok(());
        }

        // Do not await Browser.close directly: cancelling this caller after
        // Chrome accepted the request would otherwise make a retry send a
        // duplicate close. The retained task also performs the mandatory child
        // reap before this session may report successful shutdown.
        {
            let mut shutdown_task = self.browser_shutdown_task.lock().await;
            if shutdown_task.is_none() {
                *shutdown_task = Some(tokio::spawn(shutdown_launched_browser(Arc::clone(
                    &self.browser,
                ))));
            }
            let Some(task) = shutdown_task.as_mut() else {
                return Err(VoidCrawlError::Other(
                    "browser shutdown task was not installed".into(),
                ));
            };
            let outcome = task.await;
            // The completed handle must be consumed before either returning or
            // retrying; polling a completed JoinHandle panics. A failed task is
            // deliberately forgotten so the next close launches fresh work.
            shutdown_task.take();
            let result = match outcome {
                Ok(result) => result,
                Err(error) => {
                    return Err(VoidCrawlError::Other(format!(
                        "browser shutdown task failed: {error}"
                    )));
                }
            };
            drop(shutdown_task);
            result?;
        }

        self.stop_handler().await?;
        self.close_complete.store(true, Ordering::Release);
        Ok(())
    }

    /// Stop and retain the handler task. Retention is intentional: cancellation
    /// while awaiting it must leave the handle available to the next close.
    async fn stop_handler(&self) -> Result<()> {
        let mut handler_task = self.handler_task.lock().await;
        if let Some(task) = handler_task.as_mut() {
            task.abort();
            if time::timeout(SESSION_CLOSE_TIMEOUT, task).await.is_err() {
                return Err(VoidCrawlError::Timeout(
                    "browser session close timed out stopping the CDP handler".into(),
                ));
            }
            handler_task.take();
        }
        drop(handler_task);
        self.handler_alive.store(false, Ordering::Release);
        Ok(())
    }

    /// Close and reap this session no later than `deadline`.
    ///
    /// Timing out cancels only this waiter. The retained shutdown task remains
    /// owned by the session, so a later `close` or `close_before` can safely
    /// resume the same idempotent shutdown.
    pub async fn close_before(&self, deadline: time::Instant) -> Result<()> {
        time::timeout_at(deadline, self.close())
            .await
            .map_err(|_| VoidCrawlError::Timeout("browser session close deadline reached".into()))?
    }

    /// True when this session was attached to an already-running browser
    /// (the `ws_url` / `RemoteDebug` code path).
    #[must_use]
    pub const fn is_attached(&self) -> bool {
        self.attached
    }

    /// Mutable-state boundary used by ordinary pages from this session.
    #[must_use]
    pub const fn state_binding(&self) -> BrowserStateBinding {
        self.state_binding
    }

    /// Creates a handle for pages that intentionally share this managed profile.
    ///
    /// Returns an error when this session uses an ephemeral, attached, or
    /// shared browser profile. The returned handle does not expose the session
    /// or its filesystem path.
    pub fn managed_profile_context(self: &Arc<Self>) -> Result<ManagedProfileContext> {
        if self.state_binding != BrowserStateBinding::ManagedProfile {
            return Err(VoidCrawlError::InvalidInput {
                operation: "managed profile context",
                reason: "browser session does not own a managed profile",
            });
        }
        Ok(ManagedProfileContext::new(Arc::clone(self)))
    }

    /// Access stealth config.
    pub const fn stealth_config(&self) -> &StealthConfig {
        &self.stealth
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────

/// Spawn the CDP handler loop on a background tokio task.
///
/// Sets `alive` to `false` when the handler stream ends (browser crash,
/// WebSocket disconnect, or graceful close).
fn spawn_handler(mut handler: Handler, alive: Arc<AtomicBool>) -> JoinHandle<()> {
    tokio::spawn(async move {
        use futures::StreamExt;
        while handler.next().await.is_some() {}
        alive.store(false, Ordering::Release);
    })
}

/// Close and reap a Chromium process. Every process operation is bounded; if
/// graceful close or its reap stalls, `kill` is bounded too and reaps the child
/// itself per chromiumoxide's contract.
async fn shutdown_launched_browser(browser: Arc<Mutex<Browser>>) -> Result<()> {
    let _close = time::timeout(SESSION_CLOSE_TIMEOUT, async {
        browser
            .lock()
            .await
            .close()
            .await
            .map_err(|error| error.to_string())
    })
    .await;

    let exited = time::timeout(SESSION_CLOSE_TIMEOUT, async {
        browser
            .lock()
            .await
            .wait()
            .await
            .map_err(|error| error.to_string())
    })
    .await;
    if matches!(exited, Ok(Ok(_))) {
        return Ok(());
    }

    match time::timeout(SESSION_CLOSE_TIMEOUT, async {
        match browser.lock().await.kill().await {
            Some(Ok(())) | None => Ok(()),
            Some(Err(error)) => Err(error.to_string()),
        }
    })
    .await
    {
        Ok(Ok(())) => Ok(()),
        Ok(Err(error)) => Err(VoidCrawlError::Other(format!(
            "browser session close could not reap Chromium: {error}"
        ))),
        Err(_) => Err(VoidCrawlError::Timeout(
            "browser session close timed out killing Chromium".into(),
        )),
    }
}

#[cfg(test)]
#[path = "session/browser_distribution_tests.rs"]
mod browser_distribution_tests;

#[cfg(test)]
#[path = "session/session_tests.rs"]
mod session_tests;
