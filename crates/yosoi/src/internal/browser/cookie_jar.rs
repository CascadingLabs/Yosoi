//! Scoped, revocable cookie handoff out of a live browser context (CAS-251,
//! VoidCrawl side).
//!
//! # What this is and is not
//!
//! VoidCrawl's job here is to produce **facts**: a forked snapshot of the
//! cookies that a given replay origin could possibly involve, plus a
//! value-free provenance record for each. It deliberately does NOT decide
//! whether replay is *safe* — no eligible/expired/HTTPS-only/partition
//! verdicts live here. That classification is policy and belongs to the
//! caller, so the two can never drift out of sync with each other.
//!
//! The one thing that *is* enforced here is **scope**: a lease is bound to one
//! replay origin at creation and only ever holds cookies whose domain could
//! be sent to it. A caller cannot ask for "all cookies".
//!
//! # Why the value/provenance split is a type, not a convention
//!
//! [`CookieProvenance`] has no value field at all and is the only part that
//! derives `Serialize`. Values live in [`CookieLease`], which derives neither
//! `Serialize` nor a value-revealing `Debug`. So "a cookie value must never
//! reach a log, trace, recipe, or artifact" is not a rule someone has to
//! remember — there is no code path that serializes one.
//!
//! # Fork, never a live handle
//!
//! [`CookieLease`] is a copy taken at one instant. It is intentionally not a
//! view onto Chrome's cookie store: if a caller replayed a request and fed the
//! resulting `Set-Cookie` back into a shared store, it would silently mutate
//! the live authenticated session. A snapshot cannot do that.

use std::{
    collections::HashMap,
    fmt,
    time::{SystemTime, UNIX_EPOCH},
};

use super::vendor::chromiumoxide::cdp::browser_protocol::network::{Cookie, CookieSourceScheme};
use serde::Serialize;
use uuid::Uuid;

use crate::internal::browser::error::{Result, VoidCrawlError};

/// The replay target a lease is bound to. Only cookies whose domain could be
/// sent to this origin enter the lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeaseScope {
    /// Scheme, lowercased (`"https"`).
    pub scheme: String,
    /// Host, lowercased, no port (`"api.example.com"`).
    pub host: String,
    /// Port, when the caller gave a non-default one. Kept only so
    /// [`LeaseScope::origin`] can round-trip what was asked for — cookie
    /// matching ignores it, because cookies are not port-scoped (RFC 6265).
    pub port: Option<u16>,
}

impl LeaseScope {
    /// Parse a scope from an absolute URL. Rejects anything without a scheme
    /// and host, so a lease can never be created with an empty scope that
    /// would then match every cookie.
    pub fn from_url(url: &str) -> Result<Self> {
        let (scheme, rest) = url
            .split_once("://")
            .ok_or_else(|| VoidCrawlError::Other(format!("replay origin needs a scheme: {url}")))?;
        let host = rest.split(['/', '?', '#']).next().unwrap_or_default();
        // Strip userinfo and port; keep bracketed IPv6 literals intact.
        let host = host.rsplit_once('@').map_or(host, |(_, h)| h);
        let (host, port_str) = if host.starts_with(']') {
            (host, None)
        } else if host.starts_with('[') {
            match host.split_once(']') {
                Some((h, rest)) => {
                    let Some(end) = h.len().checked_add(1) else {
                        return Err(VoidCrawlError::Other(
                            "replay origin host is too long".into(),
                        ));
                    };
                    (
                        host.get(..end).unwrap_or(host),
                        rest.strip_prefix(':').filter(|p| !p.is_empty()),
                    )
                }
                None => (host, None),
            }
        } else {
            match host.split_once(':') {
                Some((h, p)) => (h, Some(p).filter(|p| !p.is_empty())),
                None => (host, None),
            }
        };
        if scheme.is_empty() || host.is_empty() {
            return Err(VoidCrawlError::Other(format!(
                "replay origin is not absolute: {url}"
            )));
        }
        let port = match port_str {
            Some(p) => Some(p.parse::<u16>().map_err(|_| {
                VoidCrawlError::Other(format!("replay origin has an invalid port: {url}"))
            })?),
            None => None,
        };
        Ok(Self {
            scheme: scheme.to_ascii_lowercase(),
            host: host.to_ascii_lowercase(),
            port,
        })
    }

    /// `scheme://host[:port]` — round-trips the port the caller supplied, so a
    /// stored provenance record still names a replayable origin.
    #[must_use]
    pub fn origin(&self) -> String {
        self.port.map_or_else(
            || format!("{}://{}", self.scheme, self.host),
            |port| format!("{}://{}:{port}", self.scheme, self.host),
        )
    }

    /// RFC 6265 §5.1.3 domain matching: exact host, or a suffix match on a
    /// domain-scoped cookie at a label boundary. Deliberately mechanical —
    /// this decides membership in the jar, not replay safety.
    #[must_use]
    pub fn domain_matches(&self, cookie_domain: &str) -> bool {
        let domain = cookie_domain.trim_start_matches('.').to_ascii_lowercase();
        if domain.is_empty() {
            return false;
        }
        if self.host == domain {
            return true;
        }
        // A host-only cookie (no leading dot) must match exactly.
        if !cookie_domain.starts_with('.') {
            return false;
        }
        let Some(separator_width) = domain.len().checked_add(1) else {
            return false;
        };
        let Some(separator) = self.host.len().checked_sub(separator_width) else {
            return false;
        };
        self.host.ends_with(&domain) && self.host.as_bytes().get(separator).copied() == Some(b'.')
    }
}

/// Everything known about one candidate cookie **except its value**.
///
/// Safe to serialize into a trace, log, or evidence artifact: there is no
/// value field to leak. The caller classifies replay eligibility from these
/// facts.
#[allow(
    clippy::struct_excessive_bools,
    reason = "mirrors CDP's cookie attribute set; each flag is a distinct fact a \
              downstream classifier needs, not a state machine to collapse"
)]
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CookieProvenance {
    pub name: String,
    pub domain: String,
    pub path: String,
    /// Origin that set the cookie: CDP's `sourceScheme` + domain, with no
    /// port, because cookies are not port-scoped (RFC 6265). The port CDP
    /// reported is exposed separately as `source_port`.
    pub issuing_origin: String,
    /// Replay origin this lease is bound to — recorded so a stored provenance
    /// record still says what it was gathered *for*.
    pub intended_replay_origin: String,
    /// The site in the address bar when the cookie was set (CHIPS partition
    /// key). `None` for unpartitioned cookies.
    ///
    /// Unreconstructable after the fact — it is ambient state at capture time
    /// — which is why it is recorded eagerly rather than derived later.
    pub top_level_site: Option<String>,
    /// True when the partition key exists but Chrome will not name it.
    pub partition_key_opaque: bool,
    /// Whether the cookie has ancestors cross-site to `top_level_site`.
    pub has_cross_site_ancestor: Option<bool>,
    /// Top-level URL of the page at export time: the browsing context the
    /// snapshot was taken in, which is also ambient and unrecoverable later.
    pub observed_in_top_level_url: Option<String>,
    /// Expiry as seconds since the UNIX epoch. `None` for a session cookie.
    pub expires_unix: Option<i64>,
    pub is_session_cookie: bool,
    pub http_only: bool,
    pub secure: bool,
    /// `"strict"`, `"lax"`, `"none"`, or `None` when unset.
    pub same_site: Option<String>,
    pub source_scheme: String,
    pub source_port: i64,
    /// Whether the cookie carries a non-empty value. Deliberately a boolean
    /// and not a length: a secret's length is itself information.
    pub has_value: bool,
    /// Opaque identity of the browser session this came from.
    pub session_id: String,
    /// When CDP was asked, as seconds since the UNIX epoch.
    pub acquired_at_unix: u64,
}

/// CDP reports expiry as `f64` seconds since the epoch, using `-1` when unset.
/// A session cookie has no expiry at all, so both collapse to `None` rather
/// than a bogus date. Clamped before narrowing so an absurd or non-finite value
/// cannot wrap into a date in the past.
#[allow(
    clippy::cast_possible_truncation,
    reason = "clamped to i64 range first; sub-second cookie expiry is not meaningful"
)]
fn expiry_seconds(cookie: &Cookie) -> Option<i64> {
    if cookie.session || !cookie.expires.is_finite() || cookie.expires < 0.0 {
        return None;
    }
    /// 9999-12-31T23:59:59Z — well beyond any plausible cookie expiry, and
    /// exactly representable in `f64`.
    const MAX_EPOCH_SECS: f64 = 253_402_300_799.0;
    let clamped = cookie.expires.trunc().clamp(0.0, MAX_EPOCH_SECS);
    format!("{clamped:.0}").parse().ok()
}

fn same_site_str(cookie: &Cookie) -> Option<String> {
    cookie
        .same_site
        .as_ref()
        .map(|s| format!("{s:?}").to_ascii_lowercase())
}

fn source_scheme_str(scheme: &CookieSourceScheme) -> String {
    format!("{scheme:?}").to_ascii_lowercase()
}

/// A forked, revocable snapshot of cookie values plus their provenance.
///
/// Neither `Serialize` nor a value-revealing `Debug` is implemented, so a
/// value cannot reach an artifact through this type. Values are reachable only
/// via [`CookieLease::header_for`], and only while the lease is live.
pub struct CookieLease {
    id: String,
    session_id: String,
    scope: LeaseScope,
    created_at: SystemTime,
    /// Provenance paired with its value, in CDP order.
    entries: Vec<(CookieProvenance, String)>,
    revoked: bool,
    /// Why the lease was revoked, for a machine-readable failure story.
    revoked_for: Option<String>,
}

impl fmt::Debug for CookieLease {
    /// Never prints values — this is what makes an accidental `{:?}` safe.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CookieLease")
            .field("id", &self.id)
            .field("session_id", &self.session_id)
            .field("scope", &self.scope.origin())
            .field("cookies", &self.entries.len())
            .field("revoked", &self.revoked)
            .field("revoked_for", &self.revoked_for)
            .finish_non_exhaustive()
    }
}

impl CookieLease {
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    #[must_use]
    pub fn session_id(&self) -> &str {
        &self.session_id
    }

    #[must_use]
    pub const fn scope(&self) -> &LeaseScope {
        &self.scope
    }

    #[must_use]
    pub const fn created_at(&self) -> SystemTime {
        self.created_at
    }

    #[must_use]
    pub const fn is_revoked(&self) -> bool {
        self.revoked
    }

    #[must_use]
    pub fn revoked_for(&self) -> Option<&str> {
        self.revoked_for.as_deref()
    }

    #[must_use]
    pub const fn len(&self) -> usize {
        self.entries.len()
    }

    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// The value-free provenance for every cookie in the lease. This is the
    /// only thing a caller should ever persist or transmit.
    #[must_use]
    pub fn provenance(&self) -> Vec<CookieProvenance> {
        self.entries.iter().map(|(p, _)| p.clone()).collect()
    }

    /// Build a `Cookie:` request-header value from the named cookies.
    ///
    /// The caller names exactly which cookies it decided are eligible — this
    /// type does not choose. Fails closed if the lease is revoked, and errors
    /// on an unknown name rather than silently omitting it (a request quietly
    /// missing its session cookie is a confusing auth failure).
    pub fn header_for(&self, names: &[&str]) -> Result<String> {
        if self.revoked {
            return Err(VoidCrawlError::Other(format!(
                "cookie lease {} is revoked ({})",
                self.id,
                self.revoked_for.as_deref().unwrap_or("no reason recorded")
            )));
        }
        let by_name: HashMap<&str, &str> = self
            .entries
            .iter()
            .map(|(p, v)| (p.name.as_str(), v.as_str()))
            .collect();
        let mut pairs = Vec::with_capacity(names.len());
        for name in names {
            let value = by_name.get(*name).ok_or_else(|| {
                VoidCrawlError::Other(format!(
                    "cookie {name:?} is not in lease {} (scope {})",
                    self.id,
                    self.scope.origin()
                ))
            })?;
            pairs.push(format!("{name}={value}"));
        }
        Ok(pairs.join("; "))
    }

    /// Drop every value and mark the lease dead. Idempotent; the first reason
    /// recorded wins so the original cause survives a later blanket revoke.
    pub fn revoke(&mut self, reason: impl Into<String>) {
        // Best-effort scrub before the allocation is released. Rust cannot
        // promise the compiler keeps this, but it removes the plaintext from
        // any buffer that outlives the free.
        for (_, value) in &mut self.entries {
            let len = value.len();
            value.clear();
            value.push_str(&"\0".repeat(len));
            value.clear();
            value.shrink_to_fit();
        }
        self.entries.clear();
        self.entries.shrink_to_fit();
        if !self.revoked {
            self.revoked_for = Some(reason.into());
        }
        self.revoked = true;
    }
}

impl Drop for CookieLease {
    /// A lease going out of scope — including the session that owns it being
    /// closed — must not leave values in freed memory.
    fn drop(&mut self) {
        if !self.revoked {
            self.revoke("lease dropped");
        }
    }
}

/// Fork the cookies reachable by `scope` out of a live browser context.
///
/// `cookies` is what CDP reported, `observed_in_top_level_url` the page's
/// current top-level URL (recorded because it cannot be recovered later), and
/// `session_id` the opaque browser-session identity.
///
/// Returns a lease holding a copy, never a handle onto Chrome's store.
#[must_use]
pub fn fork_scoped(
    cookies: &[Cookie],
    scope: LeaseScope,
    session_id: &str,
    observed_in_top_level_url: Option<&str>,
) -> CookieLease {
    let acquired_at_unix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or_default();
    let intended_replay_origin = scope.origin();

    let entries = cookies
        .iter()
        .filter(|c| scope.domain_matches(&c.domain))
        .map(|c| {
            let source_scheme = source_scheme_str(&c.source_scheme);
            let expires_unix = expiry_seconds(c);
            let provenance = CookieProvenance {
                name: c.name.clone(),
                domain: c.domain.clone(),
                path: c.path.clone(),
                issuing_origin: format!(
                    "{}://{}",
                    if source_scheme == "secure" {
                        "https"
                    } else {
                        "http"
                    },
                    c.domain.trim_start_matches('.')
                ),
                intended_replay_origin: intended_replay_origin.clone(),
                top_level_site: c.partition_key.as_ref().map(|k| k.top_level_site.clone()),
                partition_key_opaque: c.partition_key_opaque.unwrap_or(false),
                has_cross_site_ancestor: c
                    .partition_key
                    .as_ref()
                    .map(|k| k.has_cross_site_ancestor),
                observed_in_top_level_url: observed_in_top_level_url.map(str::to_string),
                expires_unix,
                is_session_cookie: c.session,
                http_only: c.http_only,
                secure: c.secure,
                same_site: same_site_str(c),
                source_scheme,
                source_port: c.source_port,
                has_value: !c.value.is_empty(),
                session_id: session_id.to_string(),
                acquired_at_unix,
            };
            (provenance, c.value.clone())
        })
        .collect::<Vec<_>>();

    CookieLease {
        id: Uuid::new_v4().to_string(),
        session_id: session_id.to_string(),
        scope,
        created_at: SystemTime::now(),
        entries,
        revoked: false,
        revoked_for: None,
    }
}

#[cfg(test)]
#[allow(
    clippy::expect_used,
    clippy::unwrap_used,
    clippy::panic,
    reason = "test harness"
)]
mod tests {
    use super::super::vendor::chromiumoxide::cdp::browser_protocol::network::{
        CookiePartitionKey, CookiePriority, CookieSameSite,
    };

    use super::*;

    fn cookie(name: &str, domain: &str, value: &str) -> Cookie {
        Cookie {
            name: name.into(),
            value: value.into(),
            domain: domain.into(),
            path: "/".into(),
            expires: -1.0,
            size: 0,
            http_only: true,
            secure: true,
            session: true,
            same_site: Some(CookieSameSite::Lax),
            priority: CookiePriority::Medium,
            source_scheme: CookieSourceScheme::Secure,
            source_port: 443,
            partition_key: None,
            partition_key_opaque: None,
        }
    }

    fn scope(url: &str) -> LeaseScope {
        LeaseScope::from_url(url).expect("valid scope")
    }

    // ── Scope parsing ────────────────────────────────────────────────────

    #[test]
    fn scope_parsing_strips_port_path_and_userinfo() {
        assert_eq!(
            scope("https://api.example.com:8443/v1?x=1").host,
            "api.example.com"
        );
        assert_eq!(
            scope("https://user:pw@api.example.com/v1").host,
            "api.example.com"
        );
        assert_eq!(
            scope("HTTPS://API.Example.COM").origin(),
            "https://api.example.com"
        );
    }

    #[test]
    fn a_non_default_port_round_trips_into_the_echoed_origin() {
        // The caller must get back something they can actually replay against.
        assert_eq!(
            scope("http://127.0.0.1:8901/").origin(),
            "http://127.0.0.1:8901"
        );
        assert_eq!(
            scope("https://api.example.com/v1").origin(),
            "https://api.example.com"
        );
    }

    #[test]
    fn a_port_is_ignored_for_cookie_matching() {
        // Cookies are not port-scoped, so the port must not narrow the jar.
        let s = scope("http://127.0.0.1:8901/");
        assert!(s.domain_matches("127.0.0.1"));
    }

    #[test]
    fn an_invalid_port_is_rejected_rather_than_silently_dropped() {
        assert!(LeaseScope::from_url("http://example.com:notaport/").is_err());
    }

    #[test]
    fn scope_parsing_keeps_ipv6_literals_intact() {
        assert_eq!(scope("http://[::1]:8080/x").host, "[::1]");
        assert_eq!(scope("http://[::1]:8080/x").port, Some(8080));
        assert_eq!(scope("http://[::1]/x").port, None);
        assert_eq!(scope("http://[::1]:8080/x").origin(), "http://[::1]:8080");
    }

    #[test]
    fn a_scope_cannot_be_created_without_scheme_and_host() {
        // Guards the "callers cannot request arbitrary cookie export" rule: an
        // empty scope would domain-match nothing, but a *missing* one must not
        // be silently accepted either.
        for bad in ["example.com/v1", "https://", "://example.com", ""] {
            assert!(
                LeaseScope::from_url(bad).is_err(),
                "{bad:?} should be rejected"
            );
        }
    }

    // ── Domain matching ──────────────────────────────────────────────────

    #[test]
    fn host_only_cookies_require_an_exact_host() {
        let s = scope("https://api.example.com");
        assert!(s.domain_matches("api.example.com"));
        assert!(!s.domain_matches("example.com"));
        assert!(!s.domain_matches("other.example.com"));
    }

    #[test]
    fn domain_cookies_match_subdomains_only_at_a_label_boundary() {
        let s = scope("https://api.example.com");
        assert!(s.domain_matches(".example.com"));
        assert!(s.domain_matches(".api.example.com"));
        // The classic suffix-confusion bug: notexample.com must NOT match
        // .example.com just because the string ends with it.
        assert!(!scope("https://notexample.com").domain_matches(".example.com"));
        assert!(!scope("https://evil-example.com").domain_matches(".example.com"));
    }

    #[test]
    fn an_empty_cookie_domain_matches_nothing() {
        assert!(!scope("https://example.com").domain_matches(""));
        assert!(!scope("https://example.com").domain_matches("."));
    }

    // ── Forking and scoping ──────────────────────────────────────────────

    #[test]
    fn forking_keeps_only_cookies_in_scope() {
        let cookies = vec![
            cookie("session", "api.example.com", "wanted"),
            cookie("other", "unrelated.test", "not-wanted"),
        ];
        let lease = fork_scoped(&cookies, scope("https://api.example.com"), "sess-1", None);
        assert_eq!(lease.len(), 1);
        assert_eq!(lease.provenance()[0].name, "session");
    }

    #[test]
    fn provenance_records_both_origin_and_top_level_site() {
        // The pair is the point: issuing origin says whose cookie it is,
        // top_level_site says which first-party partition it belongs to.
        let mut c = cookie("session", "api.stripe.test", "v");
        c.partition_key = Some(CookiePartitionKey {
            top_level_site: "https://shop-a.test".into(),
            has_cross_site_ancestor: true,
        });
        let lease = fork_scoped(
            &[c],
            scope("https://api.stripe.test"),
            "sess-1",
            Some("https://shop-a.test/checkout"),
        );
        let p = &lease.provenance()[0];
        assert_eq!(p.issuing_origin, "https://api.stripe.test");
        assert_eq!(p.top_level_site.as_deref(), Some("https://shop-a.test"));
        assert_eq!(p.has_cross_site_ancestor, Some(true));
        assert_eq!(
            p.observed_in_top_level_url.as_deref(),
            Some("https://shop-a.test/checkout")
        );
        assert_eq!(p.intended_replay_origin, "https://api.stripe.test");
    }

    #[test]
    fn unpartitioned_cookies_report_no_top_level_site() {
        let lease = fork_scoped(
            &[cookie("a", "example.com", "v")],
            scope("https://example.com"),
            "s",
            None,
        );
        let p = &lease.provenance()[0];
        assert_eq!(p.top_level_site, None);
        assert_eq!(p.has_cross_site_ancestor, None);
        assert!(!p.partition_key_opaque);
    }

    #[test]
    fn session_and_unset_expiry_both_collapse_to_none() {
        let mut expiring = cookie("a", "example.com", "v");
        expiring.session = false;
        expiring.expires = 1_800_000_000.0;
        let mut unset = cookie("b", "example.com", "v");
        unset.session = false;
        unset.expires = -1.0;

        let lease = fork_scoped(&[expiring, unset], scope("https://example.com"), "s", None);
        let p = lease.provenance();
        assert_eq!(p[0].expires_unix, Some(1_800_000_000));
        assert_eq!(
            p[1].expires_unix, None,
            "CDP's -1 sentinel must not become a real date"
        );
    }

    #[test]
    fn attributes_needed_for_downstream_classification_survive_the_fork() {
        let lease = fork_scoped(
            &[cookie("a", "example.com", "v")],
            scope("https://example.com"),
            "s",
            None,
        );
        let p = &lease.provenance()[0];
        assert!(p.http_only, "HttpOnly must be exported, not dropped");
        assert!(p.secure);
        assert_eq!(p.same_site.as_deref(), Some("lax"));
        assert_eq!(p.source_scheme, "secure");
        assert_eq!(p.source_port, 443);
    }

    // ── The value/provenance boundary ────────────────────────────────────

    #[test]
    fn serialized_provenance_contains_no_cookie_value() {
        // The invariant, asserted end-to-end rather than trusted: serialize
        // the public record and prove the secret is absent.
        let lease = fork_scoped(
            &[cookie("session", "example.com", "SUPER-SECRET-VALUE")],
            scope("https://example.com"),
            "sess-1",
            None,
        );
        let secret = "SUPER-SECRET-VALUE";
        let json = serde_json::to_string(&lease.provenance()).expect("serializes");
        assert!(
            !json.contains(secret),
            "value leaked into provenance JSON: {json}"
        );
        assert!(json.contains("\"has_value\":true"));

        // The length must not be encoded either — check by field, not by
        // substring: a bare `contains("18")` would also match a timestamp.
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("valid json");
        let record = parsed[0].as_object().expect("object");
        for (key, value) in record {
            let lower = key.to_ascii_lowercase();
            assert!(
                !(lower.contains("len") || lower.contains("size")),
                "provenance exposes a length-ish field {key:?}"
            );
            if let Some(n) = value.as_u64() {
                assert_ne!(
                    usize::try_from(n).unwrap_or(usize::MAX),
                    secret.len(),
                    "field {key:?} equals the secret's length"
                );
            }
        }
    }

    #[test]
    fn debug_formatting_a_lease_never_prints_values() {
        let lease = fork_scoped(
            &[cookie("session", "example.com", "SUPER-SECRET-VALUE")],
            scope("https://example.com"),
            "sess-1",
            None,
        );
        let rendered = format!("{lease:?}");
        assert!(
            !rendered.contains("SUPER-SECRET-VALUE"),
            "value leaked via Debug: {rendered}"
        );
    }

    // ── Header assembly ──────────────────────────────────────────────────

    #[test]
    fn header_includes_exactly_the_named_cookies() {
        let cookies = vec![
            cookie("session", "example.com", "abc"),
            cookie("tracking", "example.com", "xyz"),
        ];
        let lease = fork_scoped(&cookies, scope("https://example.com"), "s", None);
        assert_eq!(
            lease.header_for(&["session"]).expect("header"),
            "session=abc"
        );
        assert_eq!(
            lease.header_for(&["session", "tracking"]).expect("header"),
            "session=abc; tracking=xyz"
        );
    }

    #[test]
    fn an_unknown_cookie_name_errors_rather_than_being_dropped() {
        // Silently omitting it would surface later as a baffling auth failure.
        let lease = fork_scoped(
            &[cookie("session", "example.com", "abc")],
            scope("https://example.com"),
            "s",
            None,
        );
        let err = lease
            .header_for(&["session", "nope"])
            .expect_err("must error");
        assert!(format!("{err}").contains("nope"));
    }

    // ── Revocation ───────────────────────────────────────────────────────

    #[test]
    fn revoking_clears_values_and_fails_closed_with_a_reason() {
        let mut lease = fork_scoped(
            &[cookie("session", "example.com", "abc")],
            scope("https://example.com"),
            "s",
            None,
        );
        assert!(lease.header_for(&["session"]).is_ok());

        lease.revoke("session closed");
        assert!(lease.is_revoked());
        assert_eq!(lease.revoked_for(), Some("session closed"));
        assert_eq!(lease.len(), 0, "values must be dropped, not just flagged");

        let err = lease
            .header_for(&["session"])
            .expect_err("revoked lease must fail closed");
        let message = format!("{err}");
        assert!(
            message.contains("revoked"),
            "reason should be machine-readable: {message}"
        );
        assert!(message.contains("session closed"));
    }

    #[test]
    fn revocation_is_idempotent_and_keeps_the_first_reason() {
        // A later blanket revoke must not erase why it originally died.
        let mut lease = fork_scoped(
            &[cookie("a", "example.com", "v")],
            scope("https://example.com"),
            "s",
            None,
        );
        lease.revoke("auth failed");
        lease.revoke("session closed");
        assert_eq!(lease.revoked_for(), Some("auth failed"));
    }

    #[test]
    fn provenance_survives_revocation_for_post_mortem_explanation() {
        // Values die; the value-free story of what was held must remain so a
        // failure can still be explained.
        let mut lease = fork_scoped(
            &[cookie("a", "example.com", "v")],
            scope("https://example.com"),
            "s",
            None,
        );
        let before = lease.provenance();
        lease.revoke("auth failed");
        assert_eq!(before.len(), 1);
        assert_eq!(lease.provenance().len(), 0);
    }
}
