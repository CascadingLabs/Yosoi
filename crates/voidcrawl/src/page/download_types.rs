use notify::{Event, RecommendedWatcher};
use std::{collections::HashSet, path::PathBuf, time::Duration};
use tokio::sync::mpsc;

use super::Page;
use crate::error::Result;

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
    pub(super) const fn new(
        dir: PathBuf,
        before: HashSet<PathBuf>,
        max_bytes: u64,
        watcher: RecommendedWatcher,
        events: mpsc::UnboundedReceiver<notify::Result<Event>>,
    ) -> Self {
        Self {
            dir,
            before,
            max_bytes,
            _watcher: watcher,
            events,
        }
    }

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
        super::downloads::download_fs::wait_for_new_download(
            &self.dir,
            &self.before,
            self.max_bytes,
            &mut self.events,
            timeout,
        )
        .await
    }
}
