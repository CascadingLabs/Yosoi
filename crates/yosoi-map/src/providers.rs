//! Fixed catalog and pure parsers for anonymous public discovery indexes.
//!
//! This module contains no acquisition client, credential path, resolver, or
//! endpoint override. The caller owns request, byte, concurrency, and deadline
//! budgets and records the returned endpoint as source provenance.

use std::{net::IpAddr, str};

use thiserror::Error;
use url::Url;

use crate::sources::{self, CertificateNames, ParseError};

const WAYBACK_QUERY_LIMIT: usize = 1_000;
const HACKERTARGET_RESULT_LIMIT: usize = 50;

/// Anonymous, public indexes with a bounded and documented query shape.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PublicProvider {
    CrtSh,
    HackerTarget,
    SubdomainCenter,
    WaybackArchive,
}

const PUBLIC_PROVIDERS: &[PublicProvider] = &[
    PublicProvider::CrtSh,
    PublicProvider::HackerTarget,
    PublicProvider::SubdomainCenter,
    PublicProvider::WaybackArchive,
];

impl PublicProvider {
    /// Returns the deterministic catalog of anonymous providers.
    pub const fn all() -> &'static [Self] {
        PUBLIC_PROVIDERS
    }

    /// Returns the stable catalog key used for outcomes and provenance.
    pub const fn name(self) -> &'static str {
        match self {
            Self::CrtSh => "crtsh",
            Self::HackerTarget => "hackertarget",
            Self::SubdomainCenter => "subdomaincenter",
            Self::WaybackArchive => "waybackarchive",
        }
    }

    /// Builds a fixed HTTPS query to the provider's public historical index.
    ///
    /// The domain is validated with the same DNS-host constraints as the
    /// existing crt.sh query. All provider-specific values use URL query
    /// encoding; callers cannot supply a host, path, or endpoint override.
    pub fn endpoint(self, domain: &str) -> Result<Url, ProviderError> {
        if self == Self::CrtSh {
            return sources::certificate_url(domain).map_err(ProviderError::Source);
        }

        let domain = validated_domain(domain)?;
        let base = match self {
            Self::CrtSh => return sources::certificate_url(&domain).map_err(ProviderError::Source),
            Self::HackerTarget => "https://api.hackertarget.com/hostsearch/",
            Self::SubdomainCenter => "https://api.subdomain.center/",
            Self::WaybackArchive => "https://web.archive.org/cdx/search/cdx",
        };
        let mut url = Url::parse(base).map_err(ProviderError::EndpointUrl)?;
        match self {
            Self::CrtSh => return sources::certificate_url(&domain).map_err(ProviderError::Source),
            Self::HackerTarget => {
                url.query_pairs_mut().append_pair("q", &domain);
            }
            Self::SubdomainCenter => {
                url.query_pairs_mut().append_pair("domain", &domain);
            }
            Self::WaybackArchive => {
                url.query_pairs_mut()
                    .append_pair("url", &format!("{domain}/*"))
                    .append_pair("matchType", "domain")
                    .append_pair("output", "json")
                    .append_pair("fl", "original")
                    .append_pair("limit", "1000")
                    .append_pair("showResumeKey", "true")
                    .append_pair("gzip", "false");
            }
        }
        Ok(url)
    }
}

/// Parsed provider names and provider-side coverage information.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderNames {
    /// Names retained by the caller's `max_entries` limit.
    /// `entries.truncated` reports only that local retention limit.
    pub entries: CertificateNames,
    /// The anonymous provider response is known or likely to be incomplete.
    /// This is independent from `entries.truncated`.
    pub sample_limited: bool,
}

/// Typed failures for invalid domains and unsupported or malformed responses.
#[derive(Debug, Error)]
pub enum ProviderError {
    #[error("provider query domain is invalid")]
    InvalidDomain,
    #[error("provider endpoint URL is invalid: {0}")]
    EndpointUrl(#[source] url::ParseError),
    #[error(transparent)]
    Source(#[from] ParseError),
    #[error("provider returned invalid JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("{provider:?} returned an unsupported response shape")]
    UnsupportedResponse { provider: PublicProvider },
    #[error("{provider:?} returned an invalid record")]
    InvalidRecord { provider: PublicProvider },
    #[error("provider response is not valid UTF-8")]
    InvalidText,
}

/// Parses one bounded provider response without performing network access.
///
/// The acquisition caller must cap response bytes before calling this
/// function. `entries.truncated` describes only `max_entries`; `sample_limited`
/// describes a provider's own public sample or fixed result ceiling.
pub fn parse(
    provider: PublicProvider,
    bytes: &[u8],
    max_entries: usize,
) -> Result<ProviderNames, ProviderError> {
    if looks_like_html(bytes) {
        return Err(ProviderError::UnsupportedResponse { provider });
    }

    match provider {
        PublicProvider::CrtSh => Ok(ProviderNames {
            entries: sources::certificate_names(bytes, max_entries)?,
            sample_limited: false,
        }),
        PublicProvider::HackerTarget => parse_hackertarget(bytes, max_entries),
        PublicProvider::SubdomainCenter => parse_subdomain_center(bytes, max_entries),
        PublicProvider::WaybackArchive => parse_wayback(bytes, max_entries),
    }
}

fn validated_domain(domain: &str) -> Result<String, ProviderError> {
    sources::validated_domain(domain).map_err(ProviderError::Source)
}

fn parse_hackertarget(bytes: &[u8], max_entries: usize) -> Result<ProviderNames, ProviderError> {
    let text = str::from_utf8(bytes).map_err(|_| ProviderError::InvalidText)?;
    let mut entries = CertificateNames::default();
    let mut retained = 0usize;
    let mut record_count = 0usize;

    if text.trim().is_empty() {
        return Err(ProviderError::UnsupportedResponse {
            provider: PublicProvider::HackerTarget,
        });
    }

    for line in text.lines() {
        if line.is_empty() {
            continue;
        }
        let mut fields = line.split(',');
        let Some(host) = fields.next() else {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::HackerTarget,
            });
        };
        let Some(address) = fields.next() else {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::HackerTarget,
            });
        };
        let host = host.trim();
        if host.is_empty() || address.trim().parse::<IpAddr>().is_err() || fields.next().is_some() {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::HackerTarget,
            });
        }
        retain_name(&mut entries, host, max_entries, &mut retained);
        record_count = record_count.saturating_add(1);
    }

    Ok(ProviderNames {
        entries,
        sample_limited: record_count >= HACKERTARGET_RESULT_LIMIT,
    })
}

fn parse_subdomain_center(
    bytes: &[u8],
    max_entries: usize,
) -> Result<ProviderNames, ProviderError> {
    let records: serde_json::Value = serde_json::from_slice(bytes)?;
    let records = records
        .as_array()
        .ok_or(ProviderError::UnsupportedResponse {
            provider: PublicProvider::SubdomainCenter,
        })?;
    let mut entries = CertificateNames::default();
    let mut retained = 0usize;

    for record in records {
        let Some(name) = record.as_str() else {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::SubdomainCenter,
            });
        };
        let name = name.trim();
        if name.is_empty() {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::SubdomainCenter,
            });
        }
        retain_name(&mut entries, name, max_entries, &mut retained);
    }

    // The anonymous API always returns a shuffled sample of at most 500 names.
    // Its X-Truncated header is outside this pure body parser's input.
    Ok(ProviderNames {
        entries,
        sample_limited: true,
    })
}

fn parse_wayback(bytes: &[u8], max_entries: usize) -> Result<ProviderNames, ProviderError> {
    let rows: serde_json::Value = serde_json::from_slice(bytes)?;
    let rows = rows.as_array().ok_or(ProviderError::UnsupportedResponse {
        provider: PublicProvider::WaybackArchive,
    })?;
    if rows.is_empty() {
        return Ok(ProviderNames {
            entries: CertificateNames::default(),
            sample_limited: false,
        });
    }

    let header = rows.first().and_then(serde_json::Value::as_array).ok_or(
        ProviderError::UnsupportedResponse {
            provider: PublicProvider::WaybackArchive,
        },
    )?;
    let mut original_fields = header
        .iter()
        .enumerate()
        .filter_map(|(index, value)| (value.as_str() == Some("original")).then_some(index));
    let original_index = original_fields
        .next()
        .ok_or(ProviderError::UnsupportedResponse {
            provider: PublicProvider::WaybackArchive,
        })?;
    if original_fields.next().is_some() {
        return Err(ProviderError::UnsupportedResponse {
            provider: PublicProvider::WaybackArchive,
        });
    }

    let mut entries = CertificateNames::default();
    let mut retained = 0usize;
    let mut record_count = 0usize;
    let mut saw_resume_separator = false;
    let mut saw_resume_key = false;

    for row in rows.iter().skip(1) {
        let fields = row.as_array().ok_or(ProviderError::InvalidRecord {
            provider: PublicProvider::WaybackArchive,
        })?;
        if fields.is_empty() {
            if saw_resume_separator || saw_resume_key {
                return Err(ProviderError::InvalidRecord {
                    provider: PublicProvider::WaybackArchive,
                });
            }
            saw_resume_separator = true;
            continue;
        }
        if saw_resume_separator {
            if fields.len() != 1
                || fields
                    .first()
                    .and_then(serde_json::Value::as_str)
                    .is_none_or(str::is_empty)
            {
                return Err(ProviderError::InvalidRecord {
                    provider: PublicProvider::WaybackArchive,
                });
            }
            saw_resume_key = true;
            continue;
        }
        if fields.len() != header.len() {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::WaybackArchive,
            });
        }
        let original = fields
            .get(original_index)
            .and_then(serde_json::Value::as_str)
            .ok_or(ProviderError::InvalidRecord {
                provider: PublicProvider::WaybackArchive,
            })?;
        let parsed_url = Url::parse(original).map_err(|_| ProviderError::InvalidRecord {
            provider: PublicProvider::WaybackArchive,
        })?;
        if !matches!(parsed_url.scheme(), "http" | "https") {
            return Err(ProviderError::InvalidRecord {
                provider: PublicProvider::WaybackArchive,
            });
        }
        let host = parsed_url.host_str().ok_or(ProviderError::InvalidRecord {
            provider: PublicProvider::WaybackArchive,
        })?;
        retain_name(&mut entries, host, max_entries, &mut retained);
        record_count = record_count.saturating_add(1);
    }

    if saw_resume_separator && !saw_resume_key {
        return Err(ProviderError::InvalidRecord {
            provider: PublicProvider::WaybackArchive,
        });
    }

    Ok(ProviderNames {
        entries,
        sample_limited: saw_resume_key || record_count >= WAYBACK_QUERY_LIMIT,
    })
}

fn retain_name(
    entries: &mut CertificateNames,
    name: &str,
    max_entries: usize,
    retained: &mut usize,
) {
    if *retained >= max_entries {
        entries.truncated = true;
        return;
    }
    if name.starts_with("*.") {
        entries.wildcard_names.push(name.to_owned());
    } else {
        entries.names.push(name.to_owned());
    }
    *retained = retained.saturating_add(1);
}

fn looks_like_html(bytes: &[u8]) -> bool {
    let prefix = bytes
        .get(..bytes.len().min(128))
        .map_or(&[][..], |value| value);
    let Ok(prefix) = str::from_utf8(prefix) else {
        return false;
    };
    let prefix = prefix.trim_start().to_ascii_lowercase();
    prefix.starts_with("<!doctype html") || prefix.starts_with("<html")
}
