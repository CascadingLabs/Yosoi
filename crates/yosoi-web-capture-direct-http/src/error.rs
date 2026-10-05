use std::{error::Error, fmt};

use crate::{
    CaptureResolutionError, LifecycleError, LifecycleEventError, StructuredWebCaptureError,
    WebCaptureErrorCategory, WebCaptureErrorCode,
};

use super::DirectHttpRedirectErrorKind;

/// Stable transport failure class, independent of provider error wording.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum DirectHttpTransportErrorKind {
    Dns,
    Connect,
    Tls,
    Timeout,
    Protocol,
    Client,
    Cancelled,
    UnsupportedProfile,
    UnsupportedSession,
    UnsupportedRedirects,
    Redirect(DirectHttpRedirectErrorKind),
}

/// A secret-safe transport failure which retains an opaque provider source.
pub struct DirectHttpTransportError {
    kind: DirectHttpTransportErrorKind,
    source: Option<Box<dyn Error + Send + Sync>>,
}

impl DirectHttpTransportError {
    pub(crate) fn from_wreq(error: wreq::Error) -> Self {
        let kind = if error.is_timeout() {
            DirectHttpTransportErrorKind::Timeout
        } else if error.is_dns() {
            DirectHttpTransportErrorKind::Dns
        } else if error.is_tls() {
            DirectHttpTransportErrorKind::Tls
        } else if error.is_connect() {
            DirectHttpTransportErrorKind::Connect
        } else if error.is_builder() {
            DirectHttpTransportErrorKind::Client
        } else {
            DirectHttpTransportErrorKind::Protocol
        };
        Self {
            kind,
            source: Some(Box::new(error.without_uri())),
        }
    }

    pub(crate) const fn timeout() -> Self {
        Self::without_source(DirectHttpTransportErrorKind::Timeout)
    }
    pub(crate) const fn cancelled() -> Self {
        Self::without_source(DirectHttpTransportErrorKind::Cancelled)
    }
    pub(crate) const fn unsupported_profile() -> Self {
        Self::without_source(DirectHttpTransportErrorKind::UnsupportedProfile)
    }
    pub(crate) const fn unsupported_session() -> Self {
        Self::without_source(DirectHttpTransportErrorKind::UnsupportedSession)
    }
    pub(crate) const fn producer_mismatch() -> Self {
        Self::without_source(DirectHttpTransportErrorKind::Client)
    }
    pub(crate) const fn redirect(kind: DirectHttpRedirectErrorKind) -> Self {
        Self::without_source(DirectHttpTransportErrorKind::Redirect(kind))
    }
    pub(crate) fn response_url(error: crate::WebUrlParseError) -> Self {
        Self {
            kind: DirectHttpTransportErrorKind::Protocol,
            source: Some(Box::new(error)),
        }
    }
    pub(crate) fn resolution(error: CaptureResolutionError) -> Self {
        Self {
            kind: DirectHttpTransportErrorKind::Protocol,
            source: Some(Box::new(error)),
        }
    }
    pub(crate) fn lifecycle(error: LifecycleError) -> Self {
        Self {
            kind: DirectHttpTransportErrorKind::Protocol,
            source: Some(Box::new(error)),
        }
    }
    pub(crate) fn lifecycle_event(error: LifecycleEventError) -> Self {
        Self {
            kind: DirectHttpTransportErrorKind::Client,
            source: Some(Box::new(error)),
        }
    }
    pub(crate) fn identity(error: impl Error + Send + Sync + 'static) -> Self {
        Self {
            kind: DirectHttpTransportErrorKind::Client,
            source: Some(Box::new(error)),
        }
    }

    const fn without_source(kind: DirectHttpTransportErrorKind) -> Self {
        Self { kind, source: None }
    }

    pub const fn kind(&self) -> DirectHttpTransportErrorKind {
        self.kind
    }

    const fn message(&self) -> &'static str {
        match self.kind {
            DirectHttpTransportErrorKind::Dns => "direct HTTP DNS resolution failed",
            DirectHttpTransportErrorKind::Connect => "direct HTTP connection failed",
            DirectHttpTransportErrorKind::Tls => "direct HTTP TLS negotiation failed",
            DirectHttpTransportErrorKind::Timeout => "direct HTTP attempt timed out",
            DirectHttpTransportErrorKind::Protocol => "direct HTTP protocol exchange failed",
            DirectHttpTransportErrorKind::Client => "direct HTTP client configuration failed",
            DirectHttpTransportErrorKind::Cancelled => "direct HTTP attempt was cancelled",
            DirectHttpTransportErrorKind::UnsupportedProfile => {
                "direct HTTP transport profile is unsupported"
            }
            DirectHttpTransportErrorKind::UnsupportedSession => {
                "direct HTTP session mode is unsupported"
            }
            DirectHttpTransportErrorKind::UnsupportedRedirects => {
                "direct HTTP redirect traversal is unsupported"
            }
            DirectHttpTransportErrorKind::Redirect(kind) => kind.message(),
        }
    }
}

impl fmt::Display for DirectHttpTransportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message())
    }
}

impl fmt::Debug for DirectHttpTransportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DirectHttpTransportError")
            .field("kind", &self.kind)
            .field("message", &self.message())
            .finish_non_exhaustive()
    }
}

impl Error for DirectHttpTransportError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        self.source.as_deref().map(|source| {
            let source: &(dyn Error + 'static) = source;
            source
        })
    }
}

impl StructuredWebCaptureError for DirectHttpTransportError {
    fn code(&self) -> WebCaptureErrorCode {
        let code = match self.kind {
            DirectHttpTransportErrorKind::Dns => "web_capture.direct_http.dns",
            DirectHttpTransportErrorKind::Connect => "web_capture.direct_http.connect",
            DirectHttpTransportErrorKind::Tls => "web_capture.direct_http.tls",
            DirectHttpTransportErrorKind::Timeout => "web_capture.direct_http.timeout",
            DirectHttpTransportErrorKind::Protocol => "web_capture.direct_http.protocol",
            DirectHttpTransportErrorKind::Client => "web_capture.direct_http.client",
            DirectHttpTransportErrorKind::Cancelled => "web_capture.direct_http.cancelled",
            DirectHttpTransportErrorKind::UnsupportedProfile => {
                "web_capture.direct_http.profile_unsupported"
            }
            DirectHttpTransportErrorKind::UnsupportedSession => {
                "web_capture.direct_http.session_unsupported"
            }
            DirectHttpTransportErrorKind::UnsupportedRedirects => {
                "web_capture.direct_http.redirects_unsupported"
            }
            DirectHttpTransportErrorKind::Redirect(kind) => match kind {
                DirectHttpRedirectErrorKind::MissingLocation => {
                    "web_capture.direct_http.redirect_location_missing"
                }
                DirectHttpRedirectErrorKind::MalformedLocation => {
                    "web_capture.direct_http.redirect_location_malformed"
                }
                DirectHttpRedirectErrorKind::CredentialsNotAllowed => {
                    "web_capture.direct_http.redirect_credentials"
                }
                DirectHttpRedirectErrorKind::UnsupportedScheme => {
                    "web_capture.direct_http.redirect_scheme"
                }
                DirectHttpRedirectErrorKind::TargetRefused => {
                    "web_capture.direct_http.redirect_refused"
                }
                DirectHttpRedirectErrorKind::Loop => "web_capture.direct_http.redirect_loop",
                DirectHttpRedirectErrorKind::HopLimit => {
                    "web_capture.direct_http.redirect_hop_limit"
                }
            },
        };
        WebCaptureErrorCode::from_static(code)
    }

    fn category(&self) -> WebCaptureErrorCategory {
        match self.kind {
            DirectHttpTransportErrorKind::Timeout => WebCaptureErrorCategory::LimitExhaustion,
            DirectHttpTransportErrorKind::UnsupportedProfile
            | DirectHttpTransportErrorKind::UnsupportedSession
            | DirectHttpTransportErrorKind::UnsupportedRedirects => {
                WebCaptureErrorCategory::UnsupportedCapability
            }
            DirectHttpTransportErrorKind::Redirect(DirectHttpRedirectErrorKind::TargetRefused) => {
                WebCaptureErrorCategory::PolicyRefusal
            }
            DirectHttpTransportErrorKind::Redirect(_) => WebCaptureErrorCategory::InvalidInput,
            _ => WebCaptureErrorCategory::InternalFailure,
        }
    }
}
