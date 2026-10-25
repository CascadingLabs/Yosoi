//! Document reading and live browser interaction; process details stay local.
mod document;
pub use document::WebSurface;
#[cfg(feature = "surface-connections")]
pub mod archive;
#[cfg(feature = "surface-connections")]
mod process;
#[cfg(feature = "surface-connections")]
mod session;
#[cfg(feature = "surface-connections")]
pub use session::BrowserSurface;
