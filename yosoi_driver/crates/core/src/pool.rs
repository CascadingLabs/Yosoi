//! `BrowserPool` — a pool of reusable browser tabs backed by long-lived Chrome sessions.
//!
//! The pool creates tabs **lazily** on first `acquire()` and recycles them on
//! `release()`. Tabs are navigated to `about:blank` for reuse rather than closed,
//! giving near-instant subsequent acquires. Hard recycling (close + reopen)
//! kicks in after `tab_max_uses`, and idle eviction cleans up stale tabs.
//!
//! `warmup()` is **optional** — calling it pre-creates tabs for faster first acquires,
//! but the pool works correctly without it.

use std::collections::VecDeque;
use std::env;
use std::sync::atomic::{AtomicUsize, Ordering};
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
    /// Maximum concurrent tabs per browser session.
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
/// Tabs are created lazily on first `acquire()`. Call [`warmup()`](Self::warmup)
/// to optionally pre-create tabs for faster first acquires.
///
/// # Usage
///
/// ```rust,no_run
/// # async fn example() -> yosoi_driver_core::Result<()> {
/// use yosoi_driver_core::pool::BrowserPool;
///
/// let pool = BrowserPool::from_env().await?;
/// // warmup() is optional — tabs are created on demand
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
    /// Round-robin counter for distributing new tabs across sessions.
    next_session: AtomicUsize,
}

impl BrowserPool {
    /// Create a new pool from pre-built sessions and config.
    ///
    /// The pool starts with **no tabs** — they are created lazily on
    /// [`acquire()`](Self::acquire) or optionally pre-created via
    /// [`warmup()`](Self::warmup).
    pub fn new(config: PoolConfig, sessions: Vec<BrowserSession>) -> Self {
        let total_tabs = config.browsers * config.tabs_per_browser;
        Self {
            sessions,
            ready: Mutex::new(VecDeque::with_capacity(total_tabs)),
            // Permits = max concurrency. Tabs created lazily within this limit.
            semaphore: Arc::new(Semaphore::new(total_tabs)),
            config,
            next_session: AtomicUsize::new(0),
        }
    }

    /// Build a pool from environment variables.
    ///
    /// | Variable | Description | Default |
    /// |---|---|---|
    /// | `CHROME_WS_URLS` | Comma-separated `ws://` or `http://` URLs (connect mode) | — |
    /// | `BROWSER_COUNT` | Number of Chrome processes to launch | `1` |
    /// | `TABS_PER_BROWSER` | Max concurrent tabs per browser | `4` |
    /// | `TAB_MAX_USES` | Hard recycle threshold | `50` |
    /// | `TAB_MAX_IDLE_SECS` | Idle eviction timeout | `60` |
    /// | `CHROME_NO_SANDBOX` | Set to `"1"` to pass `--no-sandbox` | — |
    /// | `CHROME_HEADLESS` | Set to `"0"` for headful mode | `1` |
    /// | `VIEWPORT_WIDTH` | Stealth viewport width | `1920` |
    /// | `VIEWPORT_HEIGHT` | Stealth viewport height | `1080` |
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
        let headless = env::var("CHROME_HEADLESS")
            .ok()
            .map_or(true, |v| v != "0");
        let viewport_width: Option<u32> = env::var("VIEWPORT_WIDTH")
            .ok()
            .and_then(|v| v.parse().ok());
        let viewport_height: Option<u32> = env::var("VIEWPORT_HEIGHT")
            .ok()
            .and_then(|v| v.parse().ok());

        let sessions = if let Ok(urls) = env::var("CHROME_WS_URLS") {
            // Connect mode: attach to pre-existing Chrome instances **in parallel**
            let futs: Vec<_> = urls
                .split(',')
                .map(str::trim)
                .filter(|u| !u.is_empty())
                .map(|url| BrowserSession::connect(url.to_string()))
                .collect();

            if futs.is_empty() {
                return Err(YosoiError::Other(
                    "CHROME_WS_URLS is set but contains no valid URLs".into(),
                ));
            }

            let results = futures::future::join_all(futs).await;
            results.into_iter().collect::<Result<Vec<_>>>()?
        } else {
            // Launch mode: start Chrome processes **in parallel**
            let browser_count: usize = env::var("BROWSER_COUNT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(1);

            let futs: Vec<_> = (0..browser_count)
                .map(|_| {
                    let mut builder = if headless {
                        BrowserSession::builder().headless()
                    } else {
                        BrowserSession::builder().headful()
                    };
                    if no_sandbox {
                        builder = builder.no_sandbox();
                    }
                    if let (Some(w), Some(h)) = (viewport_width, viewport_height) {
                        builder = builder.viewport(w, h);
                    } else if let Some(w) = viewport_width {
                        builder = builder.viewport(w, 1080);
                    } else if let Some(h) = viewport_height {
                        builder = builder.viewport(1920, h);
                    }
                    builder.launch()
                })
                .collect();

            let results = futures::future::join_all(futs).await;
            results.into_iter().collect::<Result<Vec<_>>>()?
        };

        let config = PoolConfig {
            browsers: sessions.len(),
            tabs_per_browser,
            tab_max_uses,
            tab_max_idle_secs,
        };

        Ok(Self::new(config, sessions))
    }

    /// Pick the next session index (round-robin).
    fn next_browser_idx(&self) -> usize {
        if self.sessions.len() == 1 {
            return 0;
        }
        self.next_session.fetch_add(1, Ordering::Relaxed) % self.sessions.len()
    }

    /// Create a fresh tab on a round-robin browser session.
    async fn create_tab(&self) -> Result<PooledTab> {
        let idx = self.next_browser_idx();
        let page = self.sessions[idx].new_blank_page().await?;
        Ok(PooledTab {
            page,
            use_count: 0,
            last_used: Instant::now(),
            browser_idx: idx,
        })
    }

    /// Optionally pre-open tabs across all sessions and fill the ready queue.
    ///
    /// Tabs are created **in parallel** across sessions, then inserted
    /// into the ready queue in one batch under a single lock acquisition.
    ///
    /// This is **optional** — if not called, tabs are created lazily on
    /// first [`acquire()`](Self::acquire).
    pub async fn warmup(&self) -> Result<()> {
        // Build futures for all tabs across all sessions
        let mut futs = Vec::with_capacity(self.config.browsers * self.config.tabs_per_browser);
        for (idx, session) in self.sessions.iter().enumerate() {
            for _ in 0..self.config.tabs_per_browser {
                futs.push(async move {
                    let page = session.new_blank_page().await?;
                    Ok::<_, YosoiError>(PooledTab {
                        page,
                        use_count: 0,
                        last_used: Instant::now(),
                        browser_idx: idx,
                    })
                });
            }
        }

        // Create all tabs in parallel
        let results = futures::future::join_all(futs).await;

        // Lock once, insert all. Consume one semaphore permit per tab (they
        // were already counted at construction time for lazy growth).
        let mut ready = self.ready.lock().await;
        for result in results {
            let tab = result?;
            // Consume a permit so the accounting stays consistent:
            // the semaphore starts at max_tabs, and each queued tab
            // represents one of those permits being "occupied".
            let permit = self
                .semaphore
                .acquire()
                .await
                .map_err(|_| YosoiError::Other("pool semaphore closed".into()))?;
            permit.forget();
            ready.push_back(tab);
        }
        // Now add back one permit per queued tab — they're "available".
        self.semaphore.add_permits(ready.len());
        Ok(())
    }

    /// Check out a tab from the pool.
    ///
    /// If an idle tab is available, it is returned immediately. Otherwise,
    /// a new tab is created on demand (up to `tabs_per_browser * browsers`
    /// total). Blocks only when all tabs are currently in use.
    ///
    /// Tabs that have exceeded `tab_max_uses` are silently hard-recycled.
    pub async fn acquire(&self) -> Result<PooledTab> {
        let permit = self
            .semaphore
            .acquire()
            .await
            .map_err(|_| YosoiError::Other("pool semaphore closed".into()))?;
        // Don't auto-return the permit on drop — release() will add it back.
        permit.forget();

        // Try the ready queue first (fast path: reuse an existing tab)
        let maybe_tab = {
            let mut ready = self.ready.lock().await;
            ready.pop_front()
        };

        let tab = match maybe_tab {
            Some(tab) => tab,
            // No idle tab — create one on demand (lazy growth)
            None => self.create_tab().await?,
        };

        // Hard recycle if this tab is worn out
        if tab.use_count >= self.config.tab_max_uses {
            let browser_idx = tab.browser_idx;
            let _ = tab.page.close().await;
            let page = self.sessions[browser_idx].new_blank_page().await?;
            return Ok(PooledTab {
                page,
                use_count: 0,
                last_used: Instant::now(),
                browser_idx,
            });
        }

        // Lazy cleanup: navigate reused tabs to about:blank to clear prior state.
        // This was previously done in release() but is deferred here so that
        // release() returns instantly without blocking on a CDP round-trip.
        if tab.use_count > 0 {
            tab.page.navigate("about:blank").await?;
        }

        Ok(tab)
    }

    /// Return a tab to the pool after use.
    ///
    /// Instant return — no CDP round-trip. State cleanup (navigate to
    /// `about:blank`) is deferred to the next [`acquire()`](Self::acquire).
    pub async fn release(&self, mut tab: PooledTab) -> Result<()> {
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

        // Close evicted tabs and create replacements in parallel
        let futs: Vec<_> = to_evict
            .into_iter()
            .map(|tab| {
                let browser_idx = tab.browser_idx;
                let session = &self.sessions[browser_idx];
                async move {
                    let _ = tab.page.close().await;
                    let page = session.new_blank_page().await?;
                    Ok::<_, YosoiError>(PooledTab {
                        page,
                        use_count: 0,
                        last_used: Instant::now(),
                        browser_idx,
                    })
                }
            })
            .collect();

        let results = futures::future::join_all(futs).await;
        let mut ready = self.ready.lock().await;
        for result in results {
            ready.push_back(result?);
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

        // Close all tabs in parallel
        let tab_futs: Vec<_> = tabs.into_iter().map(|tab| tab.page.close()).collect();
        futures::future::join_all(tab_futs).await;

        // Close all browser sessions in parallel
        let session_futs: Vec<_> = self.sessions.iter().map(|s| s.close()).collect();
        futures::future::join_all(session_futs).await;

        Ok(())
    }
}
