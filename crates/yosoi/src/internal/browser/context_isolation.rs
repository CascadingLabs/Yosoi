//! Explicit browser-state binding and disposable isolated-context primitives.
//!
//! A Chromium browser context is the only reset boundary in this crate that
//! clears cookies, cache, origin storage, service workers, permissions, and
//! context-scoped network state together. Reusable tabs intentionally do not
//! claim that property: they share their browser profile and retain origin
//! state across checkouts.

use crate::internal::types as yosoi_types;

use std::{
    fmt,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

use crate::internal::browser::vendor::chromiumoxide::{
    Browser, CdpMode,
    cdp::browser_protocol::{
        browser::BrowserContextId,
        target::{CreateTargetParams, DisposeBrowserContextParams},
    },
};
use serde::Serialize;
use tokio::{
    runtime::Handle,
    sync::{Mutex, oneshot},
    time,
};

use crate::internal::browser::{
    Page,
    environment::EnvironmentObservation,
    error::{Result, VoidCrawlError},
    interrupt::InterruptRegistry,
    stealth::StealthConfig,
};

/// Where mutable browser state is bound for a page or capture.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserStateBinding {
    /// Reusable tabs in one launched browser share its ephemeral profile.
    SharedBrowserProfile,
    /// State belongs only to one disposable Chromium browser context.
    IsolatedBrowserContext,
    /// State is deliberately retained in a caller-selected managed profile.
    ManagedProfile,
    /// State belongs to an externally owned browser VoidCrawl attached to.
    AttachedBrowser,
}

impl BrowserStateBinding {
    /// Whether disposal provides a browser-enforced state-isolation boundary.
    #[must_use]
    pub const fn is_isolated(self) -> bool {
        matches!(self, Self::IsolatedBrowserContext)
    }
}

/// Stable outcome of disposing an isolated browser context.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextDisposalState {
    Disposed,
    ProviderDisconnected,
    ProviderRejected,
}

/// Secret-safe cleanup report for disposing an isolated context and all its
/// pages.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ContextCleanupReport {
    pub state_binding: BrowserStateBinding,
    pub disposal_state: ContextDisposalState,
    pub cleanup_complete: bool,
}

impl ContextCleanupReport {
    pub(in crate::internal::browser) const fn disposed() -> Self {
        Self {
            state_binding: BrowserStateBinding::IsolatedBrowserContext,
            disposal_state: ContextDisposalState::Disposed,
            cleanup_complete: true,
        }
    }

    pub(in crate::internal::browser) const fn failed(disconnected: bool) -> Self {
        Self {
            state_binding: BrowserStateBinding::IsolatedBrowserContext,
            disposal_state: if disconnected {
                ContextDisposalState::ProviderDisconnected
            } else {
                ContextDisposalState::ProviderRejected
            },
            cleanup_complete: false,
        }
    }
}

/// A page owned by a fresh disposable Chromium browser context.
///
/// Call [`dispose`](Self::dispose) to receive an observable cleanup result.
/// Dropping the handle schedules the same context disposal best-effort when a
/// Tokio runtime is available, but cannot return a report to the caller.
pub struct IsolatedBrowserContext {
    page: Arc<Page>,
    browser: Arc<Mutex<Browser>>,
    context_id: BrowserContextId,
    capture_lock: Arc<Mutex<()>>,
    interrupts: Arc<InterruptRegistry>,
    browser_mode: EnvironmentObservation<yosoi_types::BrowserMode>,
    cdp_mode: CdpMode,
    attached: bool,
    stealth: Option<StealthConfig>,
    disposed: AtomicBool,
    handler_alive: Arc<AtomicBool>,
    browser_closing: Arc<AtomicBool>,
}

impl fmt::Debug for IsolatedBrowserContext {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("IsolatedBrowserContext")
            .field(
                "state_binding",
                &BrowserStateBinding::IsolatedBrowserContext,
            )
            .field("disposed", &self.disposed.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

impl IsolatedBrowserContext {
    #[allow(clippy::too_many_arguments, reason = "retains page construction facts")]
    pub(in crate::internal::browser) fn new(
        page: Page,
        browser: Arc<Mutex<Browser>>,
        context_id: BrowserContextId,
        capture_lock: Arc<Mutex<()>>,
        interrupts: Arc<InterruptRegistry>,
        browser_mode: EnvironmentObservation<yosoi_types::BrowserMode>,
        cdp_mode: CdpMode,
        attached: bool,
        stealth: Option<StealthConfig>,
        handler_alive: Arc<AtomicBool>,
        browser_closing: Arc<AtomicBool>,
    ) -> Self {
        Self {
            page: Arc::new(page),
            browser,
            context_id,
            capture_lock,
            interrupts,
            browser_mode,
            cdp_mode,
            attached,
            stealth,
            disposed: AtomicBool::new(false),
            handler_alive,
            browser_closing,
        }
    }

    /// Page scoped to this isolated context.
    #[must_use]
    pub fn page(&self) -> &Page {
        &self.page
    }

    /// Cloned page handle for language bindings. It becomes unusable after
    /// this context is disposed; cloning it does not extend context lifetime.
    #[must_use]
    pub fn page_handle(&self) -> Arc<Page> {
        Arc::clone(&self.page)
    }

    #[must_use]
    #[allow(
        clippy::unused_self,
        reason = "the receiver requires an existing typed capability value"
    )]
    pub const fn binding(&self) -> BrowserStateBinding {
        BrowserStateBinding::IsolatedBrowserContext
    }

    /// Create another blank page in this context.
    ///
    /// The target is created with this context's exact Chromium
    /// `browser_context_id`, so it shares state only with the other pages in
    /// this disposable context. If applying pre-navigation stealth fails, the
    /// partially created page is closed before the error is returned.
    pub async fn new_blank_page(&self) -> Result<Page> {
        if self.disposed.load(Ordering::Acquire)
            || self.browser_closing.load(Ordering::Acquire)
            || !self.handler_alive.load(Ordering::Acquire)
        {
            return Err(VoidCrawlError::BrowserClosed);
        }
        let browser = Arc::clone(&self.browser);
        let context_id = self.context_id.clone();
        let capture_lock = Arc::clone(&self.capture_lock);
        let interrupts = Arc::clone(&self.interrupts);
        let browser_mode = self.browser_mode.clone();
        let cdp_mode = self.cdp_mode;
        let attached = self.attached;
        let stealth = self.stealth.clone();
        let browser_closing = Arc::clone(&self.browser_closing);

        // Retain creation beyond caller cancellation. A successful page that
        // cannot be delivered is explicitly closed instead of becoming an
        // unowned target that survives until whole-context disposal.
        let (result_tx, result_rx) = oneshot::channel();
        tokio::spawn(async move {
            let result = async {
                let params = CreateTargetParams::builder()
                    .url("about:blank")
                    .browser_context_id(context_id.clone())
                    .build()
                    .map_err(VoidCrawlError::PageError)?;
                let cdp_page = browser
                    .lock()
                    .await
                    .new_page(params)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
                let page = Page::new(
                    cdp_page,
                    capture_lock,
                    interrupts,
                    browser_mode,
                    cdp_mode,
                    attached,
                    browser_closing,
                    BrowserStateBinding::IsolatedBrowserContext,
                    Some(context_id),
                );
                if let Some(stealth) = &stealth
                    && let Err(error) = page.apply_stealth(stealth).await
                {
                    let _ = page.close().await;
                    return Err(error);
                }
                Ok(page)
            }
            .await;
            if let Err(unreceived) = result_tx.send(result)
                && let Ok(page) = unreceived
            {
                let _ = page.close().await;
            }
        });
        result_rx.await.map_err(|_| {
            VoidCrawlError::Other("isolated page construction task ended without a result".into())
        })?
    }

    /// Dispose the entire context, atomically deleting all pages and mutable
    /// context state without running page `beforeunload` handlers.
    pub async fn dispose(self) -> ContextCleanupReport {
        self.dispose_inner(None).await
    }

    /// Dispose the context no later than one absolute monotonic deadline.
    ///
    /// If Chromium does not acknowledge disposal in time, the detached CDP
    /// task is aborted and joined before this method returns. This releases
    /// its browser lock so the owning session can immediately close or be
    /// dropped for process-level termination.
    pub async fn dispose_before(self, deadline: time::Instant) -> ContextCleanupReport {
        self.dispose_inner(Some(deadline)).await
    }

    async fn dispose_inner(self, deadline: Option<time::Instant>) -> ContextCleanupReport {
        let browser = Arc::clone(&self.browser);
        let context_id = self.context_id.clone();
        let handler_alive = Arc::clone(&self.handler_alive);
        // Detach cleanup before the first await so cancellation of the caller
        // cannot race `Drop` into issuing a duplicate disposal request.
        let mut cleanup = tokio::spawn(async move {
            browser
                .lock()
                .await
                .execute(DisposeBrowserContextParams::new(context_id))
                .await
        });
        self.disposed.store(true, Ordering::Release);
        let result = match deadline {
            Some(deadline) => {
                tokio::select! {
                    result = &mut cleanup => Some(result),
                    () = time::sleep_until(deadline) => None,
                }
            }
            None => Some((&mut cleanup).await),
        };
        match result {
            Some(Ok(Ok(_))) => ContextCleanupReport::disposed(),
            Some(Ok(Err(_)) | Err(_)) => {
                ContextCleanupReport::failed(!handler_alive.load(Ordering::Acquire))
            }
            None => {
                cleanup.abort();
                let _ = cleanup.await;
                ContextCleanupReport::failed(!handler_alive.load(Ordering::Acquire))
            }
        }
    }
}

impl Drop for IsolatedBrowserContext {
    fn drop(&mut self) {
        if self.disposed.swap(true, Ordering::AcqRel) {
            return;
        }
        let Ok(runtime) = Handle::try_current() else {
            return;
        };
        let browser = Arc::clone(&self.browser);
        let context_id = self.context_id.clone();
        runtime.spawn(async move {
            let _ = browser
                .lock()
                .await
                .execute(DisposeBrowserContextParams::new(context_id))
                .await;
        });
    }
}
