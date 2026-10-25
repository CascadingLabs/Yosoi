//! Private provider boundary. Chrome keeps its existing implementation.

use crate::browser as browser_config;
use crate::browser::{BrowserConfig, BrowserEngine};
use std::sync::atomic;
use std::{path::PathBuf, sync::Arc, time::Duration};
use tokio::runtime::Handle as RuntimeHandle;
use tokio::time::{Instant, timeout_at};
#[cfg(feature = "browser-bidi")]
use tokio_util::sync::CancellationToken;

// Domain observations stay shared; the concrete process/page handles below do
// not escape this internal boundary or masquerade as CDP handles.
pub use super::*;

#[derive(Debug)]
pub enum BrowserSession {
    Chrome(Arc<super::BrowserSession>),
    #[cfg(feature = "browser-bidi")]
    Bidi(Arc<super::bidi::session::Session>),
}

#[derive(Debug)]
pub struct BrowserSessionBuilder {
    chrome: super::session::BrowserSessionBuilder,
    browser: BrowserConfig,
    headful: bool,
    managed_profile: bool,
    proxy_configured: bool,
}

impl BrowserSessionBuilder {
    pub fn browser(mut self, config: BrowserConfig) -> Self {
        self.browser = config;
        self
    }
    pub fn cdp_mode(mut self, mode: CdpMode) -> Self {
        self.chrome = self.chrome.cdp_mode(mode);
        self
    }
    pub fn headful(mut self) -> Self {
        self.headful = true;
        self.chrome = self.chrome.headful();
        self
    }
    pub fn headless(mut self) -> Self {
        self.headful = false;
        self.chrome = self.chrome.headless();
        self
    }
    pub fn user_data_dir(mut self, path: PathBuf) -> Self {
        self.managed_profile = true;
        self.chrome = self.chrome.user_data_dir(path);
        self
    }

    pub fn proxy(mut self, url: impl Into<String>) -> Self {
        self.proxy_configured = true;
        self.chrome = self.chrome.proxy(url);
        self
    }

    pub fn arg(mut self, argument: impl Into<String>) -> Self {
        self.chrome = self.chrome.arg(argument);
        self
    }

    pub async fn launch(mut self) -> Result<BrowserSession> {
        self.browser
            .validate_headful(self.headful)
            .map_err(|_| VoidCrawlError::InvalidInput {
                operation: "browser configuration",
                reason: "invalid engine configuration",
            })?;
        if self.browser.engine == BrowserEngine::Chrome {
            if let Some(path) = &self.browser.executable {
                let path = path.to_str().ok_or(VoidCrawlError::InvalidInput {
                    operation: "browser executable",
                    reason: "non-UTF8 path",
                })?;
                self.chrome = self.chrome.chrome_executable(path);
            }
            return Ok(BrowserSession::Chrome(Arc::new(
                self.chrome.launch().await?,
            )));
        }
        if self.managed_profile {
            return Err(unsupported("optional-engine managed profiles"));
        }
        if self.proxy_configured {
            return Err(unsupported("optional-engine network routing"));
        }
        #[cfg(feature = "browser-bidi")]
        {
            let session = super::bidi::session::Session::launch(
                self.browser,
                self.headful,
                &CancellationToken::new(),
                operation_deadline()?,
            )
            .await
            .map_err(map_bidi)?;
            Ok(BrowserSession::Bidi(session))
        }
        #[cfg(not(feature = "browser-bidi"))]
        Err(unsupported("browser-bidi feature is disabled"))
    }
}

impl BrowserSession {
    pub fn builder() -> BrowserSessionBuilder {
        BrowserSessionBuilder {
            chrome: super::BrowserSession::builder(),
            browser: BrowserConfig::default(),
            headful: false,
            managed_profile: false,
            proxy_configured: false,
        }
    }

    pub fn is_alive(&self) -> bool {
        match self {
            Self::Chrome(session) => session.is_alive(),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(session) => !session.connection.is_closed(),
        }
    }

    pub async fn close(&self) -> Result<()> {
        match self {
            Self::Chrome(session) => session.close().await,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(session) => session.close().await.map_err(map_bidi),
        }
    }

    pub async fn close_before(&self, deadline: Instant) -> Result<()> {
        timeout_at(deadline, self.close())
            .await
            .map_err(|_| VoidCrawlError::Timeout("browser close deadline".into()))?
    }

    pub fn managed_profile_context(&self) -> Result<ManagedProfileContext> {
        match self {
            Self::Chrome(session) => Ok(ManagedProfileContext(session.managed_profile_context()?)),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(_) => Err(unsupported("optional-engine managed profiles")),
        }
    }

    pub async fn new_isolated_context(&self) -> Result<IsolatedBrowserContext> {
        match self {
            Self::Chrome(session) => {
                let context = session.new_isolated_context().await?;
                let page = Arc::new(Page::Chrome(context.page_handle()));
                Ok(IsolatedBrowserContext::Chrome { context, page })
            }
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(session) => {
                let token = CancellationToken::new();
                let deadline = operation_deadline()?;
                let user = session
                    .new_user_context(&token, deadline)
                    .await
                    .map_err(map_bidi)?;
                let page = match session.new_page(&user, &token, deadline).await {
                    Ok(page) => page,
                    Err(error) => {
                        if session
                            .remove_user_context(&user, &token, deadline)
                            .await
                            .is_err()
                        {
                            session.connection.fence();
                        }
                        return Err(map_bidi(error));
                    }
                };
                Ok(IsolatedBrowserContext::Bidi(BidiContext {
                    session: Arc::clone(session),
                    user,
                    page: Arc::new(Page::Bidi(page)),
                    disposed: atomic::AtomicBool::new(false),
                }))
            }
        }
    }
}

#[derive(Debug)]
pub struct ManagedProfileContext(super::ManagedProfileContext);
impl ManagedProfileContext {
    pub async fn new_page(&self) -> Result<Page> {
        Ok(Page::Chrome(Arc::new(self.0.new_page().await?)))
    }
}

#[derive(Debug)]
pub enum IsolatedBrowserContext {
    Chrome {
        context: super::IsolatedBrowserContext,
        page: Arc<Page>,
    },
    #[cfg(feature = "browser-bidi")]
    Bidi(BidiContext),
}

impl IsolatedBrowserContext {
    pub fn page(&self) -> &Page {
        match self {
            Self::Chrome { page, .. } => page,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(context) => &context.page,
        }
    }
    pub fn page_handle(&self) -> Arc<Page> {
        match self {
            Self::Chrome { page, .. } => Arc::clone(page),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(context) => Arc::clone(&context.page),
        }
    }
    pub async fn new_blank_page(&self) -> Result<Page> {
        match self {
            Self::Chrome { context, .. } => {
                Ok(Page::Chrome(Arc::new(context.new_blank_page().await?)))
            }
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(context) => {
                if context.disposed.load(atomic::Ordering::Acquire) {
                    return Err(VoidCrawlError::BrowserClosed);
                }
                Ok(Page::Bidi(
                    context
                        .session
                        .new_page(
                            &context.user,
                            &CancellationToken::new(),
                            operation_deadline()?,
                        )
                        .await
                        .map_err(map_bidi)?,
                ))
            }
        }
    }
    pub async fn dispose_before(self, deadline: Instant) -> ContextCleanupReport {
        match self {
            Self::Chrome { context, .. } => context.dispose_before(deadline).await,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(context) => {
                if context
                    .session
                    .remove_user_context(&context.user, &CancellationToken::new(), deadline)
                    .await
                    .is_ok()
                {
                    context.disposed.store(true, atomic::Ordering::Release);
                    ContextCleanupReport::disposed()
                } else {
                    ContextCleanupReport::failed(context.session.connection.is_closed())
                }
            }
        }
    }
}

#[cfg(feature = "browser-bidi")]
#[derive(Debug)]
pub struct BidiContext {
    session: Arc<super::bidi::session::Session>,
    user: String,
    page: Arc<Page>,
    disposed: atomic::AtomicBool,
}
#[cfg(feature = "browser-bidi")]
impl Drop for BidiContext {
    fn drop(&mut self) {
        if self.disposed.load(atomic::Ordering::Acquire) {
            return;
        }
        let Ok(runtime) = RuntimeHandle::try_current() else {
            self.session.connection.fence();
            return;
        };
        let session = Arc::clone(&self.session);
        let user = self.user.clone();
        runtime.spawn(async move {
            let Ok(deadline) = operation_deadline() else {
                session.connection.fence();
                return;
            };
            if session
                .remove_user_context(&user, &CancellationToken::new(), deadline)
                .await
                .is_err()
            {
                session.connection.fence();
            }
        });
    }
}

#[derive(Debug)]
pub enum Page {
    Chrome(Arc<super::Page>),
    #[cfg(feature = "browser-bidi")]
    Bidi(super::bidi::session::Page),
}

macro_rules! native_method {
    (fn $method:ident($($arg:ident: $ty:ty),*) -> $output:ty, |$page:ident, $token:ident, $deadline:ident| $native:expr) => {
        pub async fn $method(&self, $($arg:$ty),*) -> Result<$output> {
            match self {
                Self::Chrome(page) => page.$method($($arg),*).await,
                #[cfg(feature = "browser-bidi")]
                Self::Bidi($page) => {
                    let $token = CancellationToken::new();
                    let $deadline = operation_deadline()?;
                    $native.map_err(map_bidi)
                }
            }
        }
    }
}

macro_rules! chrome_method {
    (fn $method:ident($($arg:ident: $ty:ty),*) -> $output:ty) => {
        pub async fn $method(&self, $($arg:$ty),*) -> Result<$output> {
            match self {
                Self::Chrome(page) => page.$method($($arg),*).await,
                #[cfg(feature = "browser-bidi")]
                Self::Bidi(_) => Err(unsupported(stringify!($method))),
            }
        }
    }
}

impl Page {
    pub fn execution_identity(&self) -> Option<browser_config::BrowserExecutionIdentity> {
        match self {
            Self::Chrome(_) => None,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(page) => Some(page.session.execution_identity()),
        }
    }
    pub fn instrumentation_state(&self) -> super::page::TabInstrumentationState {
        match self {
            Self::Chrome(page) => page.instrumentation_state(),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(_) => super::page::TabInstrumentationState {
                low_cdp: false,
                network_enabled: false,
                runtime_enabled: false,
                utility_world_enabled: false,
                pre_navigation_stealth: false,
            },
        }
    }
    native_method!(fn close() -> (), |page, token, deadline| page.close(&token, deadline).await);
    native_method!(fn navigate(url: &str) -> (), |page, token, deadline| page.navigate(url, "complete", &token, deadline).await);
    native_method!(fn evaluate_js(source: &str) -> serde_json::Value, |page, token, deadline| page.evaluate(source, &token, deadline).await.map(|result| result.0));
    native_method!(fn evaluate_js_in_frame(pattern: &str, source: &str) -> serde_json::Value, |page, token, deadline| page.evaluate_in_frame(pattern, source, &token, deadline).await);
    native_method!(fn document_scope() -> DocumentScope, |page, token, deadline| page.document_scope(&token, deadline).await);
    native_method!(fn rendered_dom_snapshot(max_bytes: usize) -> RenderedDomSnapshot, |page, token, deadline| page.rendered_dom_snapshot(max_bytes, &token, deadline).await);
    native_method!(fn screenshot_png() -> Vec<u8>, |page, token, deadline| page.screenshot_png(&token, deadline).await);
    native_method!(fn click_unique_element(selector: &str) -> (), |page, token, deadline| page.click_unique_element(selector, &token, deadline).await);
    native_method!(fn type_into_unique_element(selector: &str, text: &str) -> (), |page, token, deadline| page.type_into_unique_element(selector, text, &token, deadline).await);
    native_method!(fn frame_urls() -> Vec<String>, |page, token, deadline| page.frames(&token, deadline).await.map(|frames| frames.into_iter().map(|frame| frame.url).collect()));
    native_method!(fn navigate_until_dom_content_loaded(url: &str, options: ActiveNavigationOptions) -> (), |page, token, deadline| {
        let maximum = Instant::now().checked_add(options.max_duration()).ok_or(super::bidi::session::SessionError::Capacity);
        match maximum {
            Ok(maximum) => page.navigate(url, "interactive", &token, deadline.min(maximum)).await,
            Err(error) => Err(error),
        }
    });

    native_method!(fn environment_snapshot() -> BrowserEnvironmentSnapshot, |page, token, deadline| page.environment_snapshot(&token, deadline).await);
    chrome_method!(fn accessibility_snapshot(options: AccessibilitySnapshotOptions) -> AccessibilitySnapshot);
    chrome_method!(fn get_full_ax_tree(depth: Option<i64>) -> serde_json::Value);
    chrome_method!(fn layout_snapshot() -> LayoutSnapshot);
    chrome_method!(fn visual_snapshot(options: ScreenshotOptions) -> VisualSnapshot);
    chrome_method!(fn arm_navigation_capture(options: NavigationCaptureOptions) -> NavigationCapture);
    chrome_method!(fn start_navigation(url: &str, options: ActiveNavigationOptions) -> ActiveNavigation);
    chrome_method!(fn stop_loading() -> ());
    chrome_method!(fn set_viewport(viewport: Viewport) -> ());
    chrome_method!(fn set_locale(locale: &str) -> ());
    chrome_method!(fn set_timezone(timezone: &str) -> ());
    chrome_method!(fn set_rendering_preferences(preferences: RenderingPreferences) -> ());
    chrome_method!(fn start_observation_watch(options: ObservationWatchOptions) -> ObservationWatch);
    chrome_method!(fn capture_observation_response_body(candidate: &CompletedResponseCandidate, max_bytes: usize) -> ObservationResponseBody);
    chrome_method!(fn evaluate_js_in_observation_scope(source: &str, watch: &ObservationWatch) -> serde_json::Value);
    chrome_method!(fn click_element_in_scope(selector: &str, watch: &ObservationWatch) -> ());
    chrome_method!(fn type_into_in_scope(selector: &str, text: &str, watch: &ObservationWatch) -> ());

    pub async fn url(&self) -> Result<Option<String>> {
        match self {
            Self::Chrome(page) => page.url().await,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(_) => Ok(self
                .document_scope()
                .await?
                .url
                .map(|url| url.as_str().to_owned())),
        }
    }

    pub async fn arm_observation(&self, options: ObservationOptions) -> Result<ObservationScope> {
        match self {
            Self::Chrome(page) => page.arm_observation(options).await,
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(page) => ObservationScope::arm_bidi(page.clone(), options).await,
        }
    }

    pub async fn start_condition_wait(
        &self,
        expression: &str,
        maximum: Duration,
    ) -> Result<page::ConditionWait> {
        match self {
            Self::Chrome(page) => Ok(page::ConditionWait::Chrome(
                page.start_condition_wait(expression, maximum).await?,
            )),
            #[cfg(feature = "browser-bidi")]
            Self::Bidi(page) => Ok(page::ConditionWait::Bidi(
                page.start_condition_wait(
                    expression,
                    maximum,
                    &CancellationToken::new(),
                    operation_deadline()?,
                )
                .await
                .map_err(map_bidi)?,
            )),
        }
    }

    pub async fn wait_for_expression(&self, expression: &str, maximum: Duration) -> Result<bool> {
        self.start_condition_wait(expression, maximum)
            .await?
            .finish()
            .await
    }
}

pub mod page {
    #[cfg(feature = "browser-bidi")]
    use crate::internal::browser::bidi::condition::ConditionWait as BidiConditionWait;
    use crate::internal::browser::page::ConditionWait as ChromeConditionWait;
    #[derive(Debug)]
    pub enum ConditionWait {
        Chrome(ChromeConditionWait),
        #[cfg(feature = "browser-bidi")]
        Bidi(BidiConditionWait),
    }
    impl ConditionWait {
        pub async fn finish(&mut self) -> super::Result<bool> {
            match self {
                Self::Chrome(wait) => wait.finish().await,
                #[cfg(feature = "browser-bidi")]
                Self::Bidi(wait) => wait.finish().await.map_err(super::map_bidi),
            }
        }
    }
}

const fn unsupported(operation: &'static str) -> VoidCrawlError {
    VoidCrawlError::UnsupportedCapability { operation }
}

fn operation_deadline() -> Result<Instant> {
    Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or(VoidCrawlError::InvalidInput {
            operation: "browser operation",
            reason: "deadline overflow",
        })
}

#[cfg(feature = "browser-bidi")]
#[expect(
    clippy::needless_pass_by_value,
    reason = "The owned error adapter is passed directly to Result::map_err."
)]
fn map_bidi(error: super::bidi::session::SessionError) -> VoidCrawlError {
    use super::bidi::{session::SessionError, transport::BidiError};
    match error {
        SessionError::InvalidInput => VoidCrawlError::InvalidInput {
            operation: "resolve_input",
            reason: "invalid native target or input",
        },
        SessionError::InputTargetLost => VoidCrawlError::InvalidInput {
            operation: "type_into",
            reason: "target_lost_before_typing",
        },
        SessionError::Unsupported(operation) => unsupported(operation),
        SessionError::Script => VoidCrawlError::JsEvalError("BiDi script failed".into()),
        SessionError::Transport(BidiError::Deadline | BidiError::Cancelled)
        | SessionError::Context
        | SessionError::DocumentChanged => VoidCrawlError::NavigationStateUncertain,
        SessionError::Launch(_) => VoidCrawlError::LaunchFailed("BiDi launch failed".into()),
        SessionError::Transport(_) => VoidCrawlError::BrowserClosed,
        SessionError::Capacity => VoidCrawlError::InvalidInput {
            operation: "BiDi bounds",
            reason: "capacity exceeded",
        },
        SessionError::Identity | SessionError::Serialization => {
            VoidCrawlError::PageError("invalid BiDi response".into())
        }
    }
}
