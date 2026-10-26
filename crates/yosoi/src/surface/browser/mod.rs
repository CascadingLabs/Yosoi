//! Live browser observation and authority; platform process details stay local.
mod document;
pub use document::WebSurface;
#[cfg(feature = "browser")]
mod process;
#[cfg(feature = "browser")]
mod session;
#[cfg(feature = "browser")]
pub use session::BrowserSurface;
#[cfg(any(feature = "browser", feature = "surface-video"))]
pub mod archive;
