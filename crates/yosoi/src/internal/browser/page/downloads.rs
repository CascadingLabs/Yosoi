use self::download_fs::strip_mime_params;
use super::DownloadCapture;
use super::DownloadOutcome;
use super::Page;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::browser::SetDownloadBehaviorBehavior;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::browser::SetDownloadBehaviorParams;
use serde_json::Value;
use std::path::Path;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::time;

#[path = "download_fs.rs"]
pub(super) mod download_fs;

impl Page {
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
        let (watcher, events) = download_fs::watch_download_dir(dir)?;
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
        Ok(DownloadCapture::new(
            dir.to_path_buf(),
            download_fs::dir_entries(dir),
            max_bytes,
            watcher,
            events,
        ))
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

    pub(in crate::internal::browser) async fn reset_download_behavior_checked(&self) -> Result<()> {
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
        let before = download_fs::dir_entries(dir);
        let (_watcher, mut events) = download_fs::watch_download_dir(dir)?;
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
        if let Some(origin) = download_fs::origin_of(url) {
            let _ = self.inner.goto(&origin).await;
        }

        // The in-page promise resolves only after the bounded fetch has
        // completed and the download click has fired. The filesystem watcher
        // was armed first, so even an immediate browser save cannot be missed.
        let url_json = serde_json::to_string(url).unwrap_or_else(|_| "''".to_string());
        let js = download_fs::DOWNLOAD_JS
            .replace("__URL__", &url_json)
            .replace("__MAX__", &max_bytes.to_string());
        let state = time::timeout(timeout, self.evaluate_js(&js))
            .await
            .map_err(|_| download_fs::download_timeout(timeout))??;
        if let Some(error) = state.get("err").and_then(Value::as_str) {
            return Err(VoidCrawlError::Other(format!("download failed: {error}")));
        }
        let content_type = state
            .get("ct")
            .and_then(Value::as_str)
            .map(strip_mime_params);
        let remaining = timeout.saturating_sub(started.elapsed());
        let outcome =
            download_fs::wait_for_new_download(dir, &before, max_bytes, &mut events, remaining)
                .await?;
        Ok(DownloadOutcome {
            content_type,
            ..outcome
        })
    }
}
