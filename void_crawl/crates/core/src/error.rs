//! Error types for void_crawl_core.

use thiserror::Error;

/// All errors produced by this crate.
#[derive(Debug, Error)]
pub enum YosoiError {
    #[error("browser launch failed: {0}")]
    LaunchFailed(String),

    #[error("browser connection failed: {0}")]
    ConnectionFailed(String),

    #[error("navigation failed: {0}")]
    NavigationFailed(String),

    #[error("page error: {0}")]
    PageError(String),

    #[error("javascript evaluation failed: {0}")]
    JsEvalError(String),

    #[error("screenshot failed: {0}")]
    ScreenshotError(String),

    #[error("pdf generation failed: {0}")]
    PdfError(String),

    #[error("element not found: {0}")]
    ElementNotFound(String),

    #[error("timeout: {0}")]
    Timeout(String),

    #[error("browser closed")]
    BrowserClosed,

    #[error("chromium fetch failed: {0}")]
    FetchChromiumError(String),

    #[error("{0}")]
    Other(String),
}

/// Convenience alias.
pub type Result<T> = std::result::Result<T, YosoiError>;

impl From<chromiumoxide::error::CdpError> for YosoiError {
    fn from(e: chromiumoxide::error::CdpError) -> Self {
        YosoiError::Other(e.to_string())
    }
}
