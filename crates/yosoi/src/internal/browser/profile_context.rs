//! Pages bound to one caller-owned persistent Chrome profile.

use std::{fmt, sync::Arc};

use crate::internal::browser::{
    context_isolation::BrowserStateBinding, error::Result, page::Page, session::BrowserSession,
};

/// Default browser-profile pages owned by one managed-profile browser session.
///
/// Closing pages created by this handle leaves the profile's cookies and other
/// persisted browser state intact. The browser session and its managed-profile
/// lock remain owned by the caller.
pub struct ManagedProfileContext {
    session: Arc<BrowserSession>,
}

impl fmt::Debug for ManagedProfileContext {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedProfileContext")
            .field("state_binding", &BrowserStateBinding::ManagedProfile)
            .finish_non_exhaustive()
    }
}

impl ManagedProfileContext {
    pub(in crate::internal::browser) const fn new(session: Arc<BrowserSession>) -> Self {
        Self { session }
    }

    /// Opens a blank page in the session's default managed-profile context.
    pub async fn new_page(&self) -> Result<Page> {
        self.session.new_blank_page().await
    }

    /// Reports the mutable-state boundary used by pages from this context.
    #[allow(
        clippy::unused_self,
        reason = "the receiver requires an existing typed capability value"
    )]
    pub const fn state_binding(&self) -> BrowserStateBinding {
        BrowserStateBinding::ManagedProfile
    }
}
