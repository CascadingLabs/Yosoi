//! `BrowserSession` — the main entry point for controlling a browser.

use std::sync::Arc;

use chromiumoxide::browser::{Browser, BrowserConfig};
use chromiumoxide::handler::Handler;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

use crate::error::{Result, YosoiError};
use crate::page::Page;
use crate::stealth::StealthConfig;

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

/// Builder for `BrowserSession`.
#[derive(Debug, Clone)]
pub struct BrowserSessionBuilder {
    mode: BrowserMode,
    stealth: StealthConfig,
    extra_args: Vec<String>,
    chrome_executable: Option<String>,
    proxy: Option<String>,
    no_sandbox: bool,
    window_size: Option<(u32, u32)>,
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

    pub fn no_stealth(mut self) -> Self {
        self.stealth = StealthConfig::none();
        self
    }

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

    pub fn no_sandbox(mut self) -> Self {
        self.no_sandbox = true;
        self
    }

    pub fn window_size(mut self, width: u32, height: u32) -> Self {
        self.window_size = Some((width, height));
        self
    }

    /// Override the stealth viewport dimensions.
    ///
    /// This sets the CDP device metrics override that the page reports to
    /// JavaScript (e.g. `window.innerWidth`). It does NOT resize the Chrome
    /// window — use [`window_size`](Self::window_size) for that.
    pub fn viewport(mut self, width: u32, height: u32) -> Self {
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
        )
        .await
    }
}

/// A live browser session wrapping `chromiumoxide::Browser`.
///
/// Use [`BrowserSessionBuilder`] or the convenience constructors to create one.
pub struct BrowserSession {
    browser: Arc<Mutex<Browser>>,
    _handler_task: JoinHandle<()>,
    stealth: StealthConfig,
}

impl BrowserSession {
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
    async fn connect_or_launch(
        mode: BrowserMode,
        stealth: StealthConfig,
        extra_args: Vec<String>,
        chrome_executable: Option<String>,
        proxy: Option<String>,
        no_sandbox: bool,
        window_size: Option<(u32, u32)>,
    ) -> Result<Self> {
        let (browser, handler) = match &mode {
            BrowserMode::RemoteDebug { ws_url } => {
                let ws = resolve_ws_url(ws_url).await?;
                Browser::connect(&ws)
                    .await
                    .map_err(|e| YosoiError::ConnectionFailed(e.to_string()))?
            }
            _ => {
                // Disable chromiumoxide's DEFAULT_ARGS which include
                // `--enable-automation` and `--disable-extensions` —
                // both are instant giveaways to WAFs like Akamai.
                let mut builder = BrowserConfig::builder().disable_default_args();

                // Each browser instance needs its own user data dir to avoid
                // SingletonLock conflicts when launching multiple browsers.
                let user_data_dir = tempfile::tempdir()
                    .map_err(|e| YosoiError::LaunchFailed(format!("tmpdir: {e}")))?;
                builder = builder.user_data_dir(user_data_dir.keep());

                if matches!(mode, BrowserMode::Headful) {
                    builder = builder.with_head();
                }

                if let Some(ref exe) = chrome_executable {
                    builder = builder.chrome_executable(exe);
                }

                if no_sandbox {
                    builder = builder.no_sandbox();
                }

                if let Some((w, h)) = window_size {
                    builder = builder.window_size(w, h);
                }

                if let Some(ref p) = proxy {
                    builder = builder.arg(format!("--proxy-server={p}"));
                }

                for a in extra_args {
                    builder = builder.arg(a);
                }

                // Stealth-first Chrome flags.
                //
                // We disabled chromiumoxide's DEFAULT_ARGS above because
                // they include `--enable-automation` and `--disable-extensions`,
                // both of which are instant giveaways to Akamai / Cloudflare.
                //
                // Below we re-add the safe defaults we still want, plus the
                // zendriver / nodriver flags that are known to pass real WAFs.
                builder = builder
                    // ── Anti-automation core ────────────────────────────
                    .arg("--disable-blink-features=AutomationControlled")
                    .arg("--disable-infobars")
                    .arg("--disable-features=IsolateOrigins,site-per-process,TranslateUI")
                    // ── Safe defaults from chromiumoxide we keep ────────
                    .arg("--disable-background-networking")
                    .arg("--disable-background-timer-throttling")
                    .arg("--disable-backgrounding-occluded-windows")
                    .arg("--disable-breakpad")
                    .arg("--disable-client-side-phishing-detection")
                    .arg("--disable-component-extensions-with-background-pages")
                    .arg("--disable-default-apps")
                    .arg("--disable-dev-shm-usage")
                    .arg("--disable-hang-monitor")
                    .arg("--disable-ipc-flooding-protection")
                    .arg("--disable-popup-blocking")
                    .arg("--disable-prompt-on-repost")
                    .arg("--disable-renderer-backgrounding")
                    .arg("--disable-sync")
                    .arg("--force-color-profile=srgb")
                    .arg("--metrics-recording-only")
                    .arg("--no-first-run")
                    .arg("--password-store=basic")
                    .arg("--use-mock-keychain")
                    // ── Extra zendriver flags ───────────────────────────
                    .arg("--no-service-autorun")
                    .arg("--no-default-browser-check")
                    .arg("--no-pings")
                    .arg("--disable-component-update")
                    .arg("--disable-session-crashed-bubble")
                    .arg("--disable-search-engine-choice-screen")
                    .arg("--homepage=about:blank");

                let config = builder
                    .build()
                    .map_err(|e| YosoiError::LaunchFailed(e.to_string()))?;

                Browser::launch(config)
                    .await
                    .map_err(|e| YosoiError::LaunchFailed(e.to_string()))?
            }
        };

        let handler_task = spawn_handler(handler);

        Ok(Self {
            browser: Arc::new(Mutex::new(browser)),
            _handler_task: handler_task,
            stealth,
        })
    }

    /// Open a new tab, apply stealth settings, and navigate to `url`.
    ///
    /// Stealth is applied on a blank page *before* navigation so that
    /// `addScriptToEvaluateOnNewDocument` scripts fire during the real
    /// page load — not after it.
    pub async fn new_page(&self, url: &str) -> Result<Page> {
        let page = {
            let browser = self.browser.lock().await;
            let cdp_page = browser
                .new_page("about:blank")
                .await
                .map_err(|e| YosoiError::PageError(e.to_string()))?;
            Page::new(cdp_page)
        }; // browser lock released before navigation

        page.apply_stealth(&self.stealth).await?;
        page.navigate(url).await?;
        Ok(page)
    }

    /// Open a blank tab with stealth applied (no navigation).
    pub async fn new_blank_page(&self) -> Result<Page> {
        let page = {
            let browser = self.browser.lock().await;
            let cdp_page = browser
                .new_page("about:blank")
                .await
                .map_err(|e| YosoiError::PageError(e.to_string()))?;
            Page::new(cdp_page)
        };
        page.apply_stealth(&self.stealth).await?;
        Ok(page)
    }

    /// List all open pages.
    pub async fn pages(&self) -> Result<Vec<Page>> {
        let browser = self.browser.lock().await;
        let cdp_pages = browser
            .pages()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        Ok(cdp_pages.into_iter().map(Page::new).collect())
    }

    /// Get browser version string.
    pub async fn version(&self) -> Result<String> {
        let browser = self.browser.lock().await;
        let info = browser
            .version()
            .await
            .map_err(|e| YosoiError::Other(e.to_string()))?;
        Ok(info.product)
    }

    /// Gracefully close the browser.
    pub async fn close(&self) -> Result<()> {
        let mut browser = self.browser.lock().await;
        browser
            .close()
            .await
            .map_err(|e| YosoiError::Other(e.to_string()))?;
        Ok(())
    }

    /// Access stealth config.
    pub fn stealth_config(&self) -> &StealthConfig {
        &self.stealth
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────

/// Spawn the CDP handler loop on a background tokio task.
fn spawn_handler(mut handler: Handler) -> JoinHandle<()> {
    tokio::spawn(async move {
        use futures::StreamExt;
        while handler.next().await.is_some() {}
    })
}

/// If the user gives us `http://host:port` (Chrome's debug HTTP endpoint),
/// resolve it to the actual `ws://` URL by hitting `/json/version`.
async fn resolve_ws_url(url: &str) -> Result<String> {
    // Already a ws:// URL — use directly
    if url.starts_with("ws://") || url.starts_with("wss://") {
        return Ok(url.to_string());
    }

    // Treat as an HTTP endpoint, fetch /json/version
    let version_url = format!("{}/json/version", url.trim_end_matches('/'));
    let resp: serde_json::Value = reqwest::get(&version_url)
        .await
        .map_err(|e| YosoiError::ConnectionFailed(format!("GET {version_url}: {e}")))?
        .json()
        .await
        .map_err(|e| YosoiError::ConnectionFailed(format!("parse {version_url}: {e}")))?;

    resp.get("webSocketDebuggerUrl")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| {
            YosoiError::ConnectionFailed(
                "webSocketDebuggerUrl not found in /json/version response".into(),
            )
        })
}
