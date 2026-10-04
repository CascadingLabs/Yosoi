use std::fmt;

use thiserror::Error;
use yosoi_policy::Policy;
use yosoi_types::ActivityId;

/// Maximum UTF-8 bytes accepted in one authored Search query.
pub const MAX_SEARCH_QUERY_BYTES: usize = 512;

/// Error in query intent, detected before provider I/O.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum SearchQueryError {
    #[error("search query must contain non-whitespace text")]
    Empty,
    #[error("search query exceeds {maximum} UTF-8 bytes (observed {observed})")]
    TooLong { maximum: usize, observed: usize },
}

/// Logical identity of one Search query across its provider Requests.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct SearchRequestId(ActivityId);

impl SearchRequestId {
    pub const fn activity_id(self) -> ActivityId {
        self.0
    }
}

impl fmt::Display for SearchRequestId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&self.0, formatter)
    }
}

/// One authored query, independent of provider selection and Policy limits.
#[derive(Clone, Eq, PartialEq)]
pub struct SearchRequest {
    id: SearchRequestId,
    query: String,
}

impl fmt::Debug for SearchRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchRequest")
            .field("id", &self.id)
            .field("query", &"<redacted>")
            .finish()
    }
}

impl SearchRequest {
    pub fn new(query: impl Into<String>) -> Result<Self, SearchQueryError> {
        let query = query.into();
        if query.trim().is_empty() {
            return Err(SearchQueryError::Empty);
        }
        if query.len() > MAX_SEARCH_QUERY_BYTES {
            return Err(SearchQueryError::TooLong {
                maximum: MAX_SEARCH_QUERY_BYTES,
                observed: query.len(),
            });
        }
        Ok(Self {
            id: SearchRequestId(ActivityId::random()),
            query,
        })
    }

    pub const fn id(&self) -> SearchRequestId {
        self.id
    }

    pub fn query(&self) -> &str {
        &self.query
    }

    /// Binds query intent to one complete borrowed Policy declaration.
    pub const fn bind(self, policy: &Policy) -> BoundSearchRequest<'_> {
        BoundSearchRequest {
            request: self,
            policy,
        }
    }
}

/// A Search request borrowing the caller's complete Policy.
pub struct BoundSearchRequest<'policy> {
    request: SearchRequest,
    policy: &'policy Policy,
}

impl fmt::Debug for BoundSearchRequest<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BoundSearchRequest")
            .field("request", &self.request)
            .field("policy", &"<bound>")
            .finish()
    }
}

impl<'policy> BoundSearchRequest<'policy> {
    pub const fn request(&self) -> &SearchRequest {
        &self.request
    }

    pub const fn policy(&self) -> &'policy Policy {
        self.policy
    }
}
