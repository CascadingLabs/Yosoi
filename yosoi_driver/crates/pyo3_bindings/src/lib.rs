//! PyO3 bindings for `yosoi_driver_core`.
//!
//! Exposes `PyBrowserSession` and `PyPage` as Python classes with async methods
//! that bridge to Python's asyncio via `pyo3-async-runtimes`.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use tokio::sync::Mutex;
use yosoi_driver_core::{BrowserMode, BrowserPool, BrowserSession, Page, PooledTab, StealthConfig};

// ── Error conversion ────────────────────────────────────────────────────

fn to_py_err(e: yosoi_driver_core::YosoiError) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

/// Wrapper so `Vec<u8>` converts to Python `bytes` instead of `list[int]`.
struct PyBytesResult(Vec<u8>);

impl<'py> IntoPyObject<'py> for PyBytesResult {
    type Target = PyBytes;
    type Output = Bound<'py, PyBytes>;
    type Error = std::convert::Infallible;

    fn into_pyobject(self, py: Python<'py>) -> std::result::Result<Self::Output, Self::Error> {
        Ok(PyBytes::new(py, &self.0))
    }
}

// ── Shared launch logic ─────────────────────────────────────────────────

async fn do_launch(
    inner: Arc<Mutex<Option<BrowserSession>>>,
    mode: BrowserMode,
    stealth_enabled: bool,
    no_sandbox: bool,
    proxy: Option<String>,
    chrome_executable: Option<String>,
    extra_args: Vec<String>,
) -> PyResult<()> {
    let stealth = if stealth_enabled {
        StealthConfig::chrome_like()
    } else {
        StealthConfig::none()
    };

    let mut builder = BrowserSession::builder().mode(mode).stealth(stealth);

    if no_sandbox {
        builder = builder.no_sandbox();
    }
    if let Some(p) = proxy {
        builder = builder.proxy(p);
    }
    if let Some(exe) = chrome_executable {
        builder = builder.chrome_executable(exe);
    }
    for arg in extra_args {
        builder = builder.arg(arg);
    }

    let session = builder.launch().await.map_err(to_py_err)?;
    let mut guard = inner.lock().await;
    *guard = Some(session);
    Ok(())
}

// ── PyPage ──────────────────────────────────────────────────────────────

/// A browser page / tab.
///
/// All navigation and DOM methods are async — await them from Python.
#[pyclass(name = "Page")]
pub struct PyPage {
    inner: Arc<Mutex<Option<Page>>>,
}

impl PyPage {
    fn new(page: Page) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Some(page))),
        }
    }
}

/// Run an async op on the inner page. Returns PyRuntimeError if page was closed.
macro_rules! with_page {
    ($self:expr, $py:expr, |$page:ident| $body:expr) => {{
        let inner = Arc::clone(&$self.inner);
        pyo3_async_runtimes::tokio::future_into_py($py, async move {
            let guard = inner.lock().await;
            let $page = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("page is closed"))?;
            $body.await.map_err(to_py_err)
        })
    }};
}

#[pymethods]
impl PyPage {
    /// Navigate to a URL.
    fn navigate<'py>(&self, py: Python<'py>, url: String) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.navigate(&url))
    }

    /// Wait for the current navigation to complete.
    fn wait_for_navigation<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.wait_for_navigation())
    }

    /// Get the full HTML content of the page.
    fn content<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.content())
    }

    /// Get the page title.
    fn title<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.title())
    }

    /// Get the current URL.
    fn url<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.url())
    }

    /// Evaluate a JavaScript expression and return the result as a string (JSON).
    fn evaluate_js<'py>(&self, py: Python<'py>, expression: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let page = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("page is closed"))?;
            let val = page.evaluate_js(&expression).await.map_err(to_py_err)?;
            Ok(val.to_string())
        })
    }

    /// Take a PNG screenshot, returned as Python bytes.
    fn screenshot_png<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let page = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("page is closed"))?;
            let bytes = page.screenshot_png().await.map_err(to_py_err)?;
            Ok(PyBytesResult(bytes))
        })
    }

    /// Generate a PDF, returned as Python bytes.
    fn pdf_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let page = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("page is closed"))?;
            let bytes = page.pdf_bytes().await.map_err(to_py_err)?;
            Ok(PyBytesResult(bytes))
        })
    }

    /// Query for an element by CSS selector, return its inner HTML or None.
    fn query_selector<'py>(&self, py: Python<'py>, selector: String) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.query_selector(&selector))
    }

    /// Query for all matching elements, return list of inner HTML strings.
    fn query_selector_all<'py>(&self, py: Python<'py>, selector: String) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.query_selector_all(&selector))
    }

    /// Click on the first element matching a CSS selector.
    fn click_element<'py>(&self, py: Python<'py>, selector: String) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.click_element(&selector))
    }

    /// Type text into the first element matching a CSS selector.
    fn type_into<'py>(&self, py: Python<'py>, selector: String, text: String) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.type_into(&selector, &text))
    }

    /// Set extra HTTP headers for all subsequent requests.
    fn set_headers<'py>(&self, py: Python<'py>, headers: HashMap<String, String>) -> PyResult<Bound<'py, PyAny>> {
        with_page!(self, py, |page| page.set_headers(headers))
    }

    /// Wait until the DOM stabilises and exceeds `min_length` characters.
    ///
    /// Returns True if stabilised within timeout, False otherwise.
    /// Prevents redirect gates / loading stubs from being treated as content.
    #[pyo3(signature = (timeout=10.0, min_length=5000, stable_checks=5))]
    fn wait_for_stable_dom<'py>(
        &self,
        py: Python<'py>,
        timeout: f64,
        min_length: usize,
        stable_checks: u32,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let page = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("page is closed"))?;
            page.wait_for_stable_dom(
                Duration::from_secs_f64(timeout),
                min_length,
                stable_checks,
            )
            .await
            .map_err(to_py_err)
        })
    }

    /// Event-driven wait for network idle. No polling.
    ///
    /// Returns the lifecycle event name ("networkIdle" or "networkAlmostIdle")
    /// or None if the timeout was reached.
    #[pyo3(signature = (timeout=30.0))]
    fn wait_for_network_idle<'py>(
        &self,
        py: Python<'py>,
        timeout: f64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let page = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("page is closed"))?;
            page.wait_for_network_idle(Duration::from_secs_f64(timeout))
                .await
                .map_err(to_py_err)
        })
    }

    /// Close this page / tab.
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = inner.lock().await;
            if let Some(page) = guard.take() {
                page.close().await.map_err(to_py_err)?;
            }
            Ok(())
        })
    }
}

// ── PyBrowserSession ────────────────────────────────────────────────────

/// Browser session that wraps a Chromium instance via CDP.
///
/// Supports async context manager protocol (`async with`).
///
/// Example::
///
///     async with BrowserSession() as browser:
///         page = await browser.new_page("https://example.com")
///         html = await page.content()
#[pyclass(name = "BrowserSession")]
pub struct PyBrowserSession {
    inner: Arc<Mutex<Option<BrowserSession>>>,
    mode: BrowserMode,
    stealth_enabled: bool,
    no_sandbox: bool,
    proxy: Option<String>,
    chrome_executable: Option<String>,
    extra_args: Vec<String>,
}

#[pymethods]
impl PyBrowserSession {
    /// Create a new browser session.
    ///
    /// Args:
    ///     headless: Run in headless mode (default True).
    ///     ws_url: Connect to existing browser via WebSocket URL.
    ///     stealth: Enable anti-detection (default True).
    ///     no_sandbox: Disable Chrome sandbox (default False).
    ///     proxy: Proxy server URL.
    ///     chrome_executable: Path to Chrome/Chromium binary.
    ///     extra_args: Additional Chrome command-line arguments.
    #[new]
    #[pyo3(signature = (*, headless=true, ws_url=None, stealth=true, no_sandbox=false, proxy=None, chrome_executable=None, extra_args=None))]
    fn new(
        headless: bool,
        ws_url: Option<String>,
        stealth: bool,
        no_sandbox: bool,
        proxy: Option<String>,
        chrome_executable: Option<String>,
        extra_args: Option<Vec<String>>,
    ) -> Self {
        let mode = if let Some(url) = ws_url {
            BrowserMode::RemoteDebug { ws_url: url }
        } else if headless {
            BrowserMode::Headless
        } else {
            BrowserMode::Headful
        };

        Self {
            inner: Arc::new(Mutex::new(None)),
            mode,
            stealth_enabled: stealth,
            no_sandbox,
            proxy,
            chrome_executable,
            extra_args: extra_args.unwrap_or_default(),
        }
    }

    /// Launch (or connect to) the browser. Called automatically by `__aenter__`.
    fn launch<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        let mode = self.mode.clone();
        let stealth_enabled = self.stealth_enabled;
        let no_sandbox = self.no_sandbox;
        let proxy = self.proxy.clone();
        let chrome_executable = self.chrome_executable.clone();
        let extra_args = self.extra_args.clone();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            do_launch(inner, mode, stealth_enabled, no_sandbox, proxy, chrome_executable, extra_args).await
        })
    }

    /// Open a new page and navigate to the URL.
    fn new_page<'py>(&self, py: Python<'py>, url: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let session = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("browser not launched — use `async with` or call launch() first"))?;
            let page = session.new_page(&url).await.map_err(to_py_err)?;
            Ok(PyPage::new(page))
        })
    }

    /// Get browser version string.
    fn version<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let session = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("browser not launched"))?;
            session.version().await.map_err(to_py_err)
        })
    }

    /// Close the browser.
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = inner.lock().await;
            if let Some(session) = guard.take() {
                session.close().await.map_err(to_py_err)?;
            }
            Ok(())
        })
    }

    // ── async context manager ───────────────────────────────────────────

    fn __aenter__<'py>(slf: Bound<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let (inner, mode, stealth_enabled, no_sandbox, proxy, chrome_executable, extra_args) = {
            let this = slf.borrow();
            (
                Arc::clone(&this.inner),
                this.mode.clone(),
                this.stealth_enabled,
                this.no_sandbox,
                this.proxy.clone(),
                this.chrome_executable.clone(),
                this.extra_args.clone(),
            )
        };
        let slf_ref = slf.into_any().unbind();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            do_launch(inner, mode, stealth_enabled, no_sandbox, proxy, chrome_executable, extra_args).await?;
            Ok(slf_ref)
        })
    }

    #[pyo3(signature = (_exc_type=None, _exc_val=None, _exc_tb=None))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_val: Option<Bound<'py, PyAny>>,
        _exc_tb: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = inner.lock().await;
            if let Some(session) = guard.take() {
                let _ = session.close().await;
            }
            Ok(false) // don't suppress exceptions
        })
    }

    fn __repr__(&self) -> String {
        let mode = match &self.mode {
            BrowserMode::Headless => "headless",
            BrowserMode::Headful => "headful",
            BrowserMode::RemoteDebug { ws_url } => ws_url,
        };
        format!("BrowserSession(mode={mode})")
    }
}

// ── PyPooledTab ────────────────────────────────────────────────────────

/// A tab checked out from a [`BrowserPool`].
///
/// Exposes the same navigation / DOM methods as [`Page`]. When used as an
/// async context manager the tab is automatically returned to the pool on exit.
///
/// Example::
///
///     async with pool.acquire() as tab:
///         await tab.navigate("https://example.com")
///         html = await tab.content()
#[pyclass(name = "PooledTab")]
pub struct PyPooledTab {
    inner: Arc<Mutex<Option<PooledTab>>>,
    pool: Arc<BrowserPool>,
    /// Snapshot of use_count at the moment the tab was acquired.
    #[pyo3(get)]
    use_count: u32,
}

/// Helper macro: run an async op on the page inside the pooled tab.
macro_rules! with_pooled_page {
    ($self:expr, $py:expr, |$page:ident| $body:expr) => {{
        let inner = Arc::clone(&$self.inner);
        pyo3_async_runtimes::tokio::future_into_py($py, async move {
            let guard = inner.lock().await;
            let tab = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("tab has been released"))?;
            let $page = &tab.page;
            $body.await.map_err(to_py_err)
        })
    }};
}

#[pymethods]
impl PyPooledTab {
    fn navigate<'py>(&self, py: Python<'py>, url: String) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.navigate(&url))
    }

    fn wait_for_navigation<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.wait_for_navigation())
    }

    fn content<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.content())
    }

    fn title<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.title())
    }

    fn url<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.url())
    }

    fn evaluate_js<'py>(&self, py: Python<'py>, expression: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let tab = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("tab has been released"))?;
            let val = tab.page.evaluate_js(&expression).await.map_err(to_py_err)?;
            Ok(val.to_string())
        })
    }

    fn screenshot_png<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let tab = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("tab has been released"))?;
            let bytes = tab.page.screenshot_png().await.map_err(to_py_err)?;
            Ok(PyBytesResult(bytes))
        })
    }

    fn query_selector<'py>(&self, py: Python<'py>, selector: String) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.query_selector(&selector))
    }

    fn query_selector_all<'py>(&self, py: Python<'py>, selector: String) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.query_selector_all(&selector))
    }

    fn click_element<'py>(&self, py: Python<'py>, selector: String) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.click_element(&selector))
    }

    fn type_into<'py>(&self, py: Python<'py>, selector: String, text: String) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.type_into(&selector, &text))
    }

    fn set_headers<'py>(&self, py: Python<'py>, headers: HashMap<String, String>) -> PyResult<Bound<'py, PyAny>> {
        with_pooled_page!(self, py, |page| page.set_headers(headers))
    }

    /// Wait until the DOM stabilises and exceeds `min_length` characters.
    ///
    /// Returns True if stabilised within timeout, False otherwise.
    #[pyo3(signature = (timeout=10.0, min_length=5000, stable_checks=5))]
    fn wait_for_stable_dom<'py>(
        &self,
        py: Python<'py>,
        timeout: f64,
        min_length: usize,
        stable_checks: u32,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let tab = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("tab has been released"))?;
            tab.page
                .wait_for_stable_dom(
                    Duration::from_secs_f64(timeout),
                    min_length,
                    stable_checks,
                )
                .await
                .map_err(to_py_err)
        })
    }

    /// Event-driven wait for network idle. No polling.
    ///
    /// Returns the lifecycle event name ("networkIdle" or "networkAlmostIdle")
    /// or None if the timeout was reached.
    #[pyo3(signature = (timeout=30.0))]
    fn wait_for_network_idle<'py>(
        &self,
        py: Python<'py>,
        timeout: f64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let guard = inner.lock().await;
            let tab = guard
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("tab has been released"))?;
            tab.page
                .wait_for_network_idle(Duration::from_secs_f64(timeout))
                .await
                .map_err(to_py_err)
        })
    }

    // ── async context manager ───────────────────────────────────────────

    fn __aenter__<'py>(slf: Bound<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let slf_ref = slf.into_any().unbind();
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf_ref) })
    }

    #[pyo3(signature = (_exc_type=None, _exc_val=None, _exc_tb=None))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_val: Option<Bound<'py, PyAny>>,
        _exc_tb: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        let pool = Arc::clone(&self.pool);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = inner.lock().await;
            if let Some(tab) = guard.take() {
                let _ = pool.release(tab).await;
            }
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        format!("PooledTab(use_count={})", self.use_count)
    }
}

// ── PyBrowserPool ──────────────────────────────────────────────────────

/// Pool of reusable browser tabs across one or more Chrome sessions.
///
/// Supports async context manager protocol (`async with`).
///
/// Example::
///
///     async with await BrowserPool.from_env() as pool:
///         async with await pool.acquire() as tab:
///             await tab.navigate("https://example.com")
///             html = await tab.content()
#[pyclass(name = "BrowserPool")]
pub struct PyBrowserPool {
    inner: Arc<BrowserPool>,
}

#[pymethods]
impl PyBrowserPool {
    /// Create a pool from environment variables.
    #[classmethod]
    fn from_env<'py>(_cls: &Bound<'py, pyo3::types::PyType>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let pool = BrowserPool::from_env().await.map_err(to_py_err)?;
            Ok(PyBrowserPool {
                inner: Arc::new(pool),
            })
        })
    }

    /// Pre-open tabs across all sessions.
    fn warmup<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pool = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pool.warmup().await.map_err(to_py_err)
        })
    }

    /// Check out a tab from the pool.
    fn acquire<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pool = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let tab = pool.acquire().await.map_err(to_py_err)?;
            let use_count = tab.use_count;
            Ok(PyPooledTab {
                inner: Arc::new(Mutex::new(Some(tab))),
                pool,
                use_count,
            })
        })
    }

    /// Return a tab to the pool.
    fn release<'py>(&self, py: Python<'py>, tab: Bound<'py, PyPooledTab>) -> PyResult<Bound<'py, PyAny>> {
        let pool = Arc::clone(&self.inner);
        let tab_inner = Arc::clone(&tab.borrow().inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = tab_inner.lock().await;
            if let Some(pooled_tab) = guard.take() {
                pool.release(pooled_tab).await.map_err(to_py_err)?;
            }
            Ok(())
        })
    }

    // ── async context manager ───────────────────────────────────────────

    fn __aenter__<'py>(slf: Bound<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let slf_ref = slf.into_any().unbind();
        // No warmup — tabs are created lazily on first acquire().
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf_ref) })
    }

    #[pyo3(signature = (_exc_type=None, _exc_val=None, _exc_tb=None))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_val: Option<Bound<'py, PyAny>>,
        _exc_tb: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let pool = Arc::clone(&self.inner);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let _ = pool.close().await;
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        let cfg = self.inner.config();
        format!(
            "BrowserPool(browsers={}, tabs_per_browser={})",
            cfg.browsers, cfg.tabs_per_browser
        )
    }
}

// ── Module ──────────────────────────────────────────────────────────────

#[pymodule]
fn yosoi_driver(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyBrowserSession>()?;
    m.add_class::<PyPage>()?;
    m.add_class::<PyBrowserPool>()?;
    m.add_class::<PyPooledTab>()?;
    Ok(())
}
