use crate::internal::types as yosoi_types;

use super::DocumentIdentityState;
use super::Page;
use super::ProviderBrowserContextIdentity;
use crate::internal::browser::active_navigation::NavigationState;
use crate::internal::browser::context_isolation::BrowserStateBinding;
use crate::internal::browser::environment::EnvironmentObservation;
use crate::internal::browser::environment::RenderingPreferences;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::interrupt::InterruptRegistry;
use chromiumoxide::CdpMode;
use chromiumoxide::Page as CdpPage;
use chromiumoxide::cdp::browser_protocol::browser::BrowserContextId;
use chromiumoxide::cdp::browser_protocol::browser::GetWindowForTargetParams;
use chromiumoxide::cdp::browser_protocol::target::GetTargetsParams;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::sync::Mutex as AsyncMutex;

impl Page {
    /// Wrap an existing CDP page. `capture_lock` and `interrupts` are shared
    /// by every page created from the same `BrowserSession`.
    #[allow(clippy::too_many_arguments, reason = "retains page construction facts")]
    pub(in crate::internal::browser) fn new(
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
    /// protocol commands (see [`crate::internal::browser::recording`], which drives the
    /// `Page.startScreencast` domain directly).
    pub(in crate::internal::browser) const fn cdp(&self) -> &CdpPage {
        &self.inner
    }

    /// A second handle on the same tab, sharing the browser's capture lock and
    /// interrupt registry.
    ///
    /// For background tasks that need to *query* a page the caller still owns —
    /// [`crate::internal::browser::recording`]'s mask tracker re-resolves selectors on a timer
    /// while the original `Page` stays behind its own lock. Deliberately not
    /// `Clone`: the per-page state that isn't shared (virtual cursor position,
    /// one-shot viewport override) resets on the new handle, so this is only
    /// safe for read-only work like [`Page::resolve_target`].
    pub(in crate::internal::browser) fn clone_handle(&self) -> Self {
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
    pub(in crate::internal::browser) fn capture_lock(&self) -> Arc<AsyncMutex<()>> {
        Arc::clone(&self.capture_lock)
    }

    /// The id of the browser window this tab lives in.
    ///
    /// Chrome composites only the frontmost tab *of a window*, so two pages
    /// sharing a window id cannot both paint — the constraint behind
    /// [`Page::screenshot`]'s capture lock and
    /// [`RecordingOptions::foreground`](crate::internal::browser::RecordingOptions::foreground).
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
    /// [`recording`](crate::internal::browser::recording) possible.
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

    pub(in crate::internal::browser) fn belongs_to_interrupt_registry(
        &self,
        registry: &Arc<InterruptRegistry>,
    ) -> bool {
        Arc::ptr_eq(&self.interrupts, registry)
    }

    /// Whether a download is currently armed on this page (set by
    /// `arm_download` / `download_to_dir`, cleared by
    /// `reset_download_behavior`).
    pub fn is_download_armed(&self) -> bool {
        self.download_armed.load(Ordering::Relaxed)
    }

    /// The CDP target id used for internal browser bookkeeping.
    pub(in crate::internal::browser) fn target_id(&self) -> String {
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
