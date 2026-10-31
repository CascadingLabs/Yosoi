//! Live browser observation and authority; platform process details stay local.
mod document;
mod evidence;
pub use document::WebSurface;
pub use evidence::{BrowserObservation, BrowserRepresentation};
#[cfg(feature = "browser")]
mod backend;
#[cfg(feature = "browser")]
mod native;
#[cfg(feature = "browser")]
mod process;
#[cfg(feature = "browser")]
mod session;
#[cfg(feature = "browser")]
pub use session::BrowserSurface;

/// Binds the existing native Session's initial tab without launching another browser.
///
/// The returned Surface retains exclusive Work control until close; close releases
/// that control without explicitly closing the shared Session or sibling tabs.
#[cfg(feature = "browser")]
pub async fn consume_session(
    session: NativeSession,
    policy: SurfacePolicy,
) -> Result<BrowserSurface, ExecutionError> {
    BrowserSurface::consume_session(session, policy).await
}
#[cfg(feature = "browser")]
use crate::{
    session::Session as NativeSession,
    surface::{ExecutionError, SurfacePolicy},
};
#[cfg(any(feature = "browser", feature = "surface-video"))]
pub mod archive;
