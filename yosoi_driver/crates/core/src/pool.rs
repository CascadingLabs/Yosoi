//! `BrowserPool` — a pool of reusable browser tabs backed by long-lived Chrome sessions.
//!
//! The pool pre-opens tabs across one or more `BrowserSession` instances and hands them
//! out via `acquire()` / `release()`. Tabs are recycled (navigated to `about:blank`)
//! rather than closed, giving near-instant reuse. Hard recycling (close + reopen)
//! kicks in after `tab_max_uses`, and idle eviction cleans up stale tabs.

use std::collections::VecDeque;
use std::env;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::sync::{Mutex, Semaphore};

use crate::error::{Result, YosoiError};
use crate::page::Page;
use crate::session::BrowserSession;

/// Configuration for a [`BrowserPool`].
#[derive(Debug, Clone)]
pub struct PoolConfig {
    /// Number of Chrome processes (sessions) in the pool.
    pub browsers: usize,
    /// Number of idle tabs pre-opened per browser session.
    pub tabs_per_browser: usize,
    /// Close and reopen a tab after this many uses.
    pub tab_max_uses: u32,
    /// Evict idle tabs after this many seconds.
    pub tab_max_idle_secs: u64,
}

impl Default for PoolConfig {
    fn default() -> Self {
        Self {
            browsers: 1,
            tabs_per_browser: 4,
            tab_max_uses: 50,
            tab_max_idle_secs: 60,
        }
    }
}

/// A tab checked out from the pool.
///
/// Holds the underlying [`Page`] plus bookkeeping metadata.
/// Return it to the pool via [`BrowserPool::release()`].
pub struct PooledTab {
    /// The CDP page / tab.
    pub page: Page,
    /// How many times this tab has been used (incremented on release).
    pub use_count: u32,
    /// When this tab was last returned to the ready queue.
    pub last_used: Instant,
    /// Index into `BrowserPool::sessions` identifying which browser owns this tab.
    pub(crate) browser_idx: usize,
}

/// A pool of reusable browser tabs spread across one or more Chrome sessions.
///
/// # Usage
///
/// ```rust,no_run
/// # async fn example() -> yosoi_driver_core::Result<()> {
/// use yosoi_driver_core::pool::BrowserPool;
///
/// let pool = BrowserPool::from_env().await?;
/// pool.warmup().await?;
///
/// let tab = pool.acquire().await?;
/// tab.page.navigate("https://example.com").await?;
/// let html = tab.page.content().await?;
/// pool.release(tab).await?;
///
/// pool.close().await?;
/// # Ok(())
/// # }
/// ```
pub struct BrowserPool {
    sessions: Vec<BrowserSession>,
    ready: Mutex<VecDeque<PooledTab>>,
    semaphore: Arc<Semaphore>,
    config: PoolConfig,
}

impl BrowserPool {
    /// Create a new pool from pre-built sessions and config.
    ///
    /// Call [`warmup()`](Self::warmup) after construction to pre-open tabs.
    pub fn new(config: PoolConfig, sessions: Vec<BrowserSession>) -> Self {
        let total_tabs = config.browsers * config.tabs_per_browser;
        Self {
            sessions,
            ready: Mutex::new(VecDeque::with_capacity(total_tabs)),
            semaphore: Arc::new(Semaphore::new(0)), // permits added by warmup()
            config,
        }
    }

    /// Build a pool from environment variables.
    ///
    /// | Variable | Description | Default |
    /// |---|---|---|
    /// | `CHROME_WS_URLS` | Comma-separated `ws://` or `http://` URLs (connect mode) | — |
    /// | `BROWSER_COUNT` | Number of Chrome processes to launch | `1` |
    /// | `TABS_PER_BROWSER` | Pre-opened tabs per browser | `4` |
    /// | `TAB_MAX_USES` | Hard recycle threshold | `50` |
    /// | `TAB_MAX_IDLE_SECS` | Idle eviction timeout | `60` |
    /// | `CHROME_NO_SANDBOX` | Set to `"1"` to pass `--no-sandbox` | — |
    pub async fn from_env() -> Result<Self> {
        let tabs_per_browser: usize = env::var("TABS_PER_BROWSER")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(4);
        let tab_max_uses: u32 = env::var("TAB_MAX_USES")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(50);
        let tab_max_idle_secs: u64 = env::var("TAB_MAX_IDLE_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(60);
        let no_sandbox = env::var("CHROME_NO_SANDBOX")
            .ok()
            .is_some_and(|v| v == "1");

        let sessions = if let Ok(urls) = env::var("CHROME_WS_URLS") {
            // Connect mode: attach to pre-existing Chrome instances
            let mut sessions = Vec::new();
            for url in urls.split(',').map(str::trim).filter(|u| !u.is_empty()) {
                let session = BrowserSession::connect(url).await?;
                sessions.push(session);
            }
            if sessions.is_empty() {
                return Err(YosoiError::Other(
                    "CHROME_WS_URLS is set but contains no valid URLs".into(),
                ));
            }
            sessions
        } else {
            // Launch mode: start new Chrome processes
            let browser_count: usize = env::var("BROWSER_COUNT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(1);

            let mut sessions = Vec::with_capacity(browser_count);
            for _ in 0..browser_count {
                let mut builder = BrowserSession::builder().headless();
                if no_sandbox {
                    builder = builder.no_sandbox();
                }
                let session = builder.launch().await?;
                sessions.push(session);
            }
            sessions
        };

        let config = PoolConfig {
            browsers: sessions.len(),
            tabs_per_browser,
            tab_max_uses,
            tab_max_idle_secs,
        };

        Ok(Self::new(config, sessions))
    }

    /// Pre-open tabs across all sessions and fill the ready queue.
    ///
    /// Must be called once after [`new()`](Self::new) or [`from_env()`](Self::from_env).
    pub async fn warmup(&self) -> Result<()> {
        let mut ready = self.ready.lock().await;
        for (idx, session) in self.sessions.iter().enumerate() {
            for _ in 0..self.config.tabs_per_browser {
                let page = session.new_blank_page().await?;
                ready.push_back(PooledTab {
                    page,
                    use_count: 0,
                    last_used: Instant::now(),
                    browser_idx: idx,
                });
            }
        }
        // Grant permits for all the tabs we just created
        self.semaphore.add_permits(ready.len());
        Ok(())
    }

    /// Check out a tab from the pool.
    ///
    /// Blocks if all tabs are currently in use. If the tab has exceeded
    /// `tab_max_uses`, it is silently hard-recycled (closed and reopened).
    pub async fn acquire(&self) -> Result<PooledTab> {
        let permit = self
            .semaphore
            .acquire()
            .await
            .map_err(|_| YosoiError::Other("pool semaphore closed".into()))?;
        // Don't auto-return the permit on drop — release() will add it back.
        permit.forget();

        let tab = {
            let mut ready = self.ready.lock().await;
            ready
                .pop_front()
                .ok_or_else(|| YosoiError::Other("ready queue empty despite semaphore permit".into()))?
        };

        // Hard recycle if this tab is worn out
        if tab.use_count >= self.config.tab_max_uses {
            let browser_idx = tab.browser_idx;
            // Close the old tab (consumes `page`)
            let _ = tab.page.close().await;
            // Open a fresh replacement
            let page = self.sessions[browser_idx].new_blank_page().await?;
            return Ok(PooledTab {
                page,
                use_count: 0,
                last_used: Instant::now(),
                browser_idx,
            });
        }

        Ok(tab)
    }

    /// Return a tab to the pool after use.
    ///
    /// Navigates the tab to `about:blank` to clear state, then pushes it
    /// back into the ready queue.
    pub async fn release(&self, mut tab: PooledTab) -> Result<()> {
        tab.page.navigate("about:blank").await?;
        tab.use_count += 1;
        tab.last_used = Instant::now();

        self.ready.lock().await.push_back(tab);
        self.semaphore.add_permits(1);
        Ok(())
    }

    /// Close idle tabs that have exceeded `tab_max_idle_secs` and open fresh replacements.
    ///
    /// Intended to be called periodically from a background tokio task.
    pub async fn evict_idle(&self) -> Result<()> {
        let max_idle = Duration::from_secs(self.config.tab_max_idle_secs);
        let now = Instant::now();

        // Partition the ready queue into keep vs. evict
        let to_evict: Vec<PooledTab> = {
            let mut ready = self.ready.lock().await;
            let mut keep = VecDeque::with_capacity(ready.len());
            let mut evict = Vec::new();

            while let Some(tab) = ready.pop_front() {
                if now.duration_since(tab.last_used) > max_idle {
                    evict.push(tab);
                } else {
                    keep.push_back(tab);
                }
            }
            *ready = keep;
            evict
        };

        // Close evicted tabs and create replacements
        for tab in to_evict {
            let browser_idx = tab.browser_idx;
            let _ = tab.page.close().await;
            let page = self.sessions[browser_idx].new_blank_page().await?;
            let fresh = PooledTab {
                page,
                use_count: 0,
                last_used: Instant::now(),
                browser_idx,
            };
            self.ready.lock().await.push_back(fresh);
            // No semaphore change — the evicted tab's permit was never taken
        }

        Ok(())
    }

    /// Access the pool configuration.
    pub fn config(&self) -> &PoolConfig {
        &self.config
    }

    /// Drain all tabs and close all browser sessions.
    pub async fn close(&self) -> Result<()> {
        // Drain the ready queue
        let tabs: Vec<PooledTab> = {
            let mut ready = self.ready.lock().await;
            ready.drain(..).collect()
        };

        for tab in tabs {
            let _ = tab.page.close().await;
        }

        // Close all browser sessions
        for session in &self.sessions {
            let _ = session.close().await;
        }

        Ok(())
    }
}
