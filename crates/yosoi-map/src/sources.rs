//! Bounded parsers for the public discovery sources used by Map.

mod certificate;
mod robots;
mod sitemap;

pub(crate) use certificate::validated_domain;
pub use certificate::{CertificateNames, certificate_names, certificate_url};
pub use robots::Robots;
pub use sitemap::{Sitemap, SitemapKind, parse_sitemap};

use std::io;

use thiserror::Error;

/// Errors returned while parsing bounded discovery source documents.
#[derive(Debug, Error)]
pub enum ParseError {
    #[error("source document exceeds the configured byte limit of {limit} bytes")]
    ByteLimitExceeded { limit: usize },
    #[error("source document contains more than the configured {limit} entries")]
    EntryLimitExceeded { limit: usize },
    #[error("robots user-agent must not be empty")]
    EmptyUserAgent,
    #[error("invalid sitemap XML: {0}")]
    SitemapXml(#[from] roxmltree::Error),
    #[error("sitemap root element is unsupported: {root}")]
    UnsupportedSitemapRoot { root: String },
    #[error("sitemap contains an invalid {entry} entry: {reason}")]
    InvalidSitemapEntry {
        entry: &'static str,
        reason: &'static str,
    },
    #[error("sitemap gzip stream is invalid: {0}")]
    InvalidGzip(#[source] io::Error),
    #[error("certificate response JSON is invalid: {0}")]
    CertificateJson(#[from] serde_json::Error),
    #[error("certificate response must be a JSON array")]
    InvalidCertificateResponse,
    #[error("certificate response item must contain a string name_value")]
    InvalidCertificateRecord,
    #[error("certificate query domain is invalid")]
    InvalidDomain,
    #[error("certificate query URL is invalid: {0}")]
    CertificateUrl(#[from] url::ParseError),
}
