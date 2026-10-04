//! URL normalization and pure map scope admission.

use std::{str, sync::OnceLock};

use publicsuffix::{List as PublicSuffixList, Psl};
use thiserror::Error;
use url::{Host, Url};
use yosoi_policy::policy::{HostScope, Map, PathScope};

/// Why a URL or hostname did not pass map admission.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq, Ord, PartialOrd)]
pub enum Rejection {
    /// The input could not be parsed as a URL.
    #[error("invalid URL")]
    InvalidUrl,
    /// Only HTTP and HTTPS URLs are supported.
    #[error("unsupported URL scheme")]
    UnsupportedScheme,
    /// URLs containing user information are not admitted.
    #[error("URL credentials are not admitted")]
    Credentials,
    /// The hostname is outside the declared host scope.
    #[error("hostname is outside the declared scope")]
    HostScope,
    /// The URL's scheme or port differs from the seed origin.
    #[error("URL is outside the seed origin")]
    OriginScope,
    /// The path is outside the declared path scope.
    #[error("path is outside the declared scope")]
    PathScope,
    /// A URL matched a declared exclusion filter.
    #[error("URL matched an exclusion filter")]
    Filtered,
    /// A URL exceeds the configured URL byte limit.
    #[error("URL exceeds the configured byte limit")]
    UrlLength,
    /// The hostname could not be parsed or canonicalized.
    #[error("invalid hostname")]
    InvalidHost,
    /// Registrable-domain scope is unavailable for the seed hostname.
    #[error("registrable-domain scope is unsupported for this hostname")]
    UnsupportedDomainScope,
    /// A hostname exceeds the configured hostname byte limit.
    #[error("hostname exceeds the configured byte limit")]
    HostnameLength,
}

/// Normalizes an absolute URL or resolves a reference against `base`.
///
/// The returned URL has no fragment. Its scheme, path case, query order, and
/// query contents are otherwise preserved by the URL parser's canonical form.
pub fn normalize(value: &str, base: Option<&Url>, max_url_bytes: u32) -> Result<Url, Rejection> {
    let mut url = base
        .map_or_else(|| Url::parse(value), |base| base.join(value))
        .map_err(|_| Rejection::InvalidUrl)?;

    match url.scheme() {
        "http" | "https" => {}
        _ => return Err(Rejection::UnsupportedScheme),
    }

    if has_user_information(&url) || has_raw_user_information(value) {
        return Err(Rejection::Credentials);
    }

    if url.host().is_none() {
        return Err(Rejection::InvalidHost);
    }

    url.set_fragment(None);
    if exceeds_limit(url.as_str().len(), max_url_bytes) {
        return Err(Rejection::UrlLength);
    }

    Ok(url)
}

/// Immutable URL and host admission state derived from a map policy and seed.
#[derive(Clone, Debug)]
pub struct Scope {
    seed_host: String,
    seed_scheme: String,
    seed_port: Option<u16>,
    seed_path: String,
    policy: Map,
    domain: Option<String>,
    maximum_hostname_bytes: u32,
}

impl Scope {
    /// Creates admission state for `seed` and the declared map policy.
    pub fn new(seed: &Url, policy: &Map) -> Result<Self, Rejection> {
        let maximum_url_bytes = policy.limits.max_url_bytes.get();
        let seed = normalize(seed.as_str(), None, maximum_url_bytes)?;
        let seed_host = canonical_host(&seed)?;
        let maximum_hostname_bytes = policy.limits.max_hostname_bytes.get();
        if exceeds_limit(seed_host.len(), maximum_hostname_bytes) {
            return Err(Rejection::HostnameLength);
        }

        let domain = registrable_domain(&seed_host)?;
        if policy.scope.hosts == HostScope::RegistrableDomain && domain.is_none() {
            return Err(Rejection::UnsupportedDomainScope);
        }

        Ok(Self {
            seed_host,
            seed_scheme: seed.scheme().to_owned(),
            seed_port: seed.port_or_known_default(),
            seed_path: seed.path().to_owned(),
            policy: policy.clone(),
            domain,
            maximum_hostname_bytes,
        })
    }

    /// Admits a normalized URL when its origin, host, path, and filters allow it.
    pub fn admit(&self, url: &Url) -> Result<(), Rejection> {
        let url = normalize(url.as_str(), None, self.policy.limits.max_url_bytes.get())?;
        let host = canonical_host(&url)?;
        self.admit_host(&host)?;

        if url.scheme() != self.seed_scheme || url.port_or_known_default() != self.seed_port {
            return Err(Rejection::OriginScope);
        }

        if self.policy.scope.paths == PathScope::SeedSubtree
            && !path_is_within_subtree(url.path(), &self.seed_path)
        {
            return Err(Rejection::PathScope);
        }

        if self
            .policy
            .filters
            .excluded_path_prefixes
            .iter()
            .any(|prefix| url.path().starts_with(prefix))
            || query_has_excluded_key(&url, &self.policy.filters.excluded_query_keys)
        {
            return Err(Rejection::Filtered);
        }

        Ok(())
    }

    /// Canonicalizes and admits one host under the declared host scope.
    ///
    /// The returned host uses URL canonical form, including IDNA ASCII form
    /// and canonical IP notation.
    pub fn admit_host(&self, host: &str) -> Result<String, Rejection> {
        let canonical = canonical_host_string(host)?;
        if exceeds_limit(canonical.len(), self.maximum_hostname_bytes) {
            return Err(Rejection::HostnameLength);
        }

        match self.policy.scope.hosts {
            HostScope::SeedHost if canonical == self.seed_host => Ok(canonical),
            HostScope::SeedHost => Err(Rejection::HostScope),
            HostScope::RegistrableDomain => {
                let candidate_domain =
                    registrable_domain(&canonical)?.ok_or(Rejection::UnsupportedDomainScope)?;
                if self.domain.as_deref() == Some(candidate_domain.as_str()) {
                    Ok(canonical)
                } else {
                    Err(Rejection::HostScope)
                }
            }
        }
    }

    /// Returns the seed's registrable domain when it has one.
    #[must_use]
    pub fn domain(&self) -> Option<&str> {
        self.domain.as_deref()
    }
}

fn has_user_information(url: &Url) -> bool {
    if !url.username().is_empty() || url.password().is_some() {
        return true;
    }

    url.as_str()
        .split_once("://")
        .and_then(|(_, remainder)| remainder.split(['/', '?', '#']).next())
        .is_some_and(|authority| authority.contains('@'))
}

fn has_raw_user_information(value: &str) -> bool {
    let after_http_scheme = value.split_once(':').and_then(|(scheme, remainder)| {
        matches!(scheme.to_ascii_lowercase().as_str(), "http" | "https").then_some(remainder)
    });
    let Some(authority) = after_http_scheme
        .or_else(|| value.strip_prefix("//"))
        .or_else(|| value.strip_prefix("\\\\"))
        .or_else(|| value.strip_prefix("/\\"))
        .or_else(|| value.strip_prefix("\\/"))
    else {
        return false;
    };
    let authority = authority.trim_start_matches(['/', '\\']);
    authority
        .split(['/', '\\', '?', '#'])
        .next()
        .is_some_and(|authority| authority.contains('@'))
}

fn canonical_host(url: &Url) -> Result<String, Rejection> {
    url.host()
        .map(|host| host.to_string())
        .ok_or(Rejection::InvalidHost)
}

fn canonical_host_string(host: &str) -> Result<String, Rejection> {
    Host::<String>::parse(host)
        .map(|host| host.to_string())
        .map_err(|_| Rejection::InvalidHost)
}

fn registrable_domain(host: &str) -> Result<Option<String>, Rejection> {
    let canonical = Host::<String>::parse(host).map_err(|_| Rejection::InvalidHost)?;
    let Host::Domain(domain) = canonical else {
        return Ok(None);
    };
    let list = public_suffix_list()?;
    let Some(domain) = list.domain(domain.as_bytes()) else {
        return Ok(None);
    };
    let domain = domain.trim();
    let domain = str::from_utf8(domain.as_bytes()).map_err(|_| Rejection::InvalidHost)?;
    Ok(Some(domain.to_owned()))
}

fn public_suffix_list() -> Result<&'static PublicSuffixList, Rejection> {
    static LIST: OnceLock<Result<PublicSuffixList, ()>> = OnceLock::new();
    LIST.get_or_init(|| {
        PublicSuffixList::from_bytes(include_bytes!("../data/public_suffix_list.dat"))
            .map_err(|_| ())
    })
    .as_ref()
    .map_err(|()| Rejection::UnsupportedDomainScope)
}

fn path_is_within_subtree(path: &str, root: &str) -> bool {
    if path == root {
        return true;
    }
    if root == "/" {
        return path.starts_with('/');
    }
    if root.ends_with('/') {
        return path.starts_with(root);
    }
    path.strip_prefix(root)
        .is_some_and(|remainder| remainder.starts_with('/'))
}

fn query_has_excluded_key(url: &Url, excluded_keys: &[String]) -> bool {
    url.query_pairs().any(|(key, _)| {
        excluded_keys
            .iter()
            .any(|excluded| excluded == key.as_ref())
    })
}

fn exceeds_limit(byte_len: usize, maximum: u32) -> bool {
    u64::try_from(byte_len).map_or(true, |byte_len| byte_len > u64::from(maximum))
}
