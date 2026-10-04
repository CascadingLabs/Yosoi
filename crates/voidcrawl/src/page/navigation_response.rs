use std::collections::HashSet;

/// The result of a [`crate::page::Page::goto_and_wait_for_idle`] call.
///
/// Bundles the final HTML, URL, and HTTP response metadata captured during
/// navigation.  `status_code` is `None` when the page was served from a
/// service worker, disk cache, or the browser failed to capture a network
/// response (e.g. `file://` URLs).
#[derive(Debug, Clone)]
pub struct PageResponse {
    /// Outer HTML of `<html>` after the page reached network idle.
    pub html: String,
    /// Final URL after any redirects.
    pub url: String,
    /// HTTP status code of the last response in the navigation chain.
    pub status_code: Option<u16>,
    /// `true` when at least one HTTP redirect occurred before the final URL.
    pub redirected: bool,
    /// Response headers of the final Document response (`name`, `value`),
    /// lowercased names, in arrival order. Empty when no network response was
    /// captured (cache/service-worker/`file://`). Feeds downstream response
    /// classification and replay-grade provenance (`cf-ray`, `x-cache`, …).
    pub headers: Vec<(String, String)>,
    /// Data-plane network endpoints (XHR + Fetch request URLs) observed during
    /// navigation — a sorted, deduplicated set of `scheme://host[:port]/path`
    /// strings with query/fragment/userinfo stripped and secret-like path
    /// segments redacted at the source (a replay-grade archive must never
    /// persist a token; see [`safe_endpoint`] and
    /// `ENDPOINT_SANITIZER_VERSION`). `None` when capture was not requested
    /// (opt-in); `Some(empty)` when requested but the page made no
    /// XHR/fetch calls. The *consumer* templatizes id-bearing path segments
    /// — this stays a generic, faithful observation.
    pub endpoints: Option<Vec<String>>,
    /// `true` when the captured endpoint set hit its cap and further endpoints
    /// were dropped — so a consumer can tell "made few calls" from "we stopped
    /// counting". Always `false` when `endpoints` is `None`.
    pub endpoints_truncated: bool,
    /// The [`ENDPOINT_SANITIZER_VERSION`] the `endpoints` were redacted under,
    /// so a long-term archive can reproduce/audit exactly which rules produced
    /// the set. `None` iff
    /// `endpoints` is `None` (capture was not requested).
    pub endpoint_sanitizer_version: Option<&'static str>,
}

/// Version of the endpoint-sanitization rules ([`safe_endpoint`]).
///
/// Bump on any change to the redaction patterns so a captured set is
/// reproducible/auditable at replay time.
pub const ENDPOINT_SANITIZER_VERSION: &str = "ep-2026.06.06";

/// Largest distinct-endpoint set kept per navigation; past this, capture stops
/// and `PageResponse::endpoints_truncated` is set. Bounds memory on chatty
/// SPAs.
pub(super) const MAX_ENDPOINTS: usize = 256;

/// Reduce a raw request URL to a `scheme://host[:port]/path` key with secrets
/// removed, or `None` if it must not be archived at all.
///
/// A replay-grade archive cannot retroactively un-persist a secret, so this
/// strips at the source — BEFORE the string is ever stored — and is
/// **redact-by-default** on the path (deny-unknown, not allow-unknown):
///   * query string + fragment removed (where tokens/PII/cache-busters live),
///   * userinfo (`user:pass@`) removed,
///   * non-`http(s)` schemes and loopback/private/CGNAT/`.local` hosts dropped
///     entirely (an operator-environment leak, not page signal),
///   * a path segment is KEPT only when it is clearly a short, low-entropy
///     template token ([`is_safe_segment`]); ANYTHING else — long blobs
///     (JWT/signed-URL/hash), kv/matrix markers (`;`/`=`/`%`), emails, long
///     digit runs — becomes `:redacted`.
///
/// This is a best-effort *security* filter, not a proof: a short high-entropy
/// secret can still resemble a word. It deliberately does NOT templatize
/// ordinary id segments (`/users/123/` keeps `123`) — that semantic
/// normalization is the *consumer's* fingerprint concern; this function's job
/// is only to keep secrets out while staying a faithful, generic observation.
pub fn safe_endpoint(raw_url: &str) -> Option<String> {
    // Cut everything from the first `?` or `#` — query and fragment never
    // enter.
    let head = raw_url.split(['?', '#']).next().unwrap_or("");

    let (scheme, rest) = head.split_once("://")?;
    let scheme = scheme.to_ascii_lowercase();
    if scheme != "http" && scheme != "https" {
        return None;
    }

    // Authority is everything up to the first `/`; the rest is the path.
    let (authority, path) = match rest.split_once('/') {
        Some((a, p)) => (a, format!("/{p}")),
        None => (rest, String::new()),
    };
    // Drop userinfo (`user:pass@host`) — embedded credentials — then lowercase
    // the host:port ONCE (the single source of truth for both the local-host
    // guard and the emitted key).
    let host_port = authority
        .rsplit_once('@')
        .map_or(authority, |(_, hp)| hp)
        .to_ascii_lowercase();
    let host = bare_host(&host_port);
    if host.is_empty() || is_local_host(host) {
        return None;
    }

    let safe_path: String = path
        .split('/')
        .map(|seg| {
            if is_safe_segment(seg) {
                seg
            } else {
                ":redacted"
            }
        })
        .collect::<Vec<_>>()
        .join("/");

    Some(format!("{scheme}://{host_port}{safe_path}"))
}

/// The bare host from a (already-lowercased) `host[:port]` authority, handling
/// the bracketed IPv6 form `[::1]:9000` → `::1` (a plain `split(':')` would
/// return `"["` and let loopback IPv6 slip past [`is_local_host`]).
fn bare_host(host_port: &str) -> &str {
    if let Some(after) = host_port.strip_prefix('[') {
        return after.split(']').next().unwrap_or("");
    }
    host_port.split(':').next().unwrap_or("")
}

/// Loopback / private / CGNAT / link-local / mDNS hosts — never archive these
/// (they describe the crawl operator's machine/network, not the page). `host`
/// is the bare, lowercased host (no brackets, no port).
fn is_local_host(host: &str) -> bool {
    // IPv6 loopback / unspecified / link-local / unique-local (fc00::/7).
    if host == "::1"
        || host == "::"
        || host.starts_with("fe80:")
        || host.starts_with("fc")
        || host.starts_with("fd")
    {
        return true;
    }
    // mDNS `*.local` (compare the final label, not via ends_with — that trips
    // clippy's file-extension lint and would also match a bare "local").
    let mdns_local = host.rsplit_once('.').is_some_and(|(_, tld)| tld == "local");
    if host == "localhost" || host == "0.0.0.0" || mdns_local {
        return true;
    }
    if host.starts_with("127.")
        || host.starts_with("10.")
        || host.starts_with("192.168.")
        || host.starts_with("169.254.")
    {
        return true;
    }
    // RFC-1918 172.16.0.0/12 and RFC-6598 CGNAT 100.64.0.0/10.
    let second_octet = |s: &str| s.split('.').nth(1).and_then(|o| o.parse::<u8>().ok());
    if host.starts_with("172.") {
        return second_octet(host).is_some_and(|o| (16..=31).contains(&o));
    }
    if host.starts_with("100.") {
        return second_octet(host).is_some_and(|o| (64..=127).contains(&o));
    }
    false
}

/// True when a path segment is clearly a SAFE template token worth keeping —
/// the allow-list half of the redact-by-default policy. Conservative: anything
/// that isn't obviously a short, low-entropy lexical/id token is redacted.
///
/// Keeps: `finance`, `quoteSummary`, `v10`, `users`, `123`, `AAPL` (the
/// consumer templatizes ordinary ids). Redacts: JWTs/signed-URLs/hashes (long
/// or high-entropy), emails / kv / matrix params (`@`/`=`/`;`/`%`), and long
/// digit runs (card/SSN/phone).
fn is_safe_segment(seg: &str) -> bool {
    // Empty (a `//` or trailing `/`) is structure, not content — keep it.
    if seg.is_empty() {
        return true;
    }
    // Any kv / matrix / userinfo / percent-encoding marker → not a plain token.
    if seg.contains(['@', '=', ';', '%', ':']) {
        return false;
    }
    // Only ordinary url-path token characters.
    if !seg
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '~'))
    {
        return false;
    }
    // Long segments are tokens/blobs, not template words (`recommendations` is
    // 15).
    if seg.len() > 15 {
        return false;
    }
    let digits = seg.chars().filter(char::is_ascii_digit).count();
    // 9+ digits → SSN / card / phone range (ordinary numeric ids are shorter).
    if digits >= 9 {
        return false;
    }
    // A 12+ char all-hex blob is a hash/token, never a word.
    if seg.len() >= 12 && seg.chars().all(|c| c.is_ascii_hexdigit()) {
        return false;
    }
    // A 12+ char segment spanning 3 character classes (lower AND upper AND
    // digit) is an opaque mixed-case token, not a template word — `oAuth2…`-
    // style names are rare in paths and over-redacting them is the safe trade.
    if seg.len() >= 12 {
        let has_lower = seg.chars().any(|c| c.is_ascii_lowercase());
        let has_upper = seg.chars().any(|c| c.is_ascii_uppercase());
        let has_digit = seg.chars().any(|c| c.is_ascii_digit());
        if has_lower && has_upper && has_digit {
            return false;
        }
    }
    true
}

/// Turn the in-loop deduped endpoint set into the final field value: `None`
/// when capture was off, else a SORTED `Vec` (a stable set — arrival order is a
/// session/timing tell, and the consumer set-ifies anyway).
pub(super) fn finalize_endpoints(seen: &HashSet<String>, capture: bool) -> Option<Vec<String>> {
    if !capture {
        return None;
    }
    let mut v: Vec<String> = seen.iter().cloned().collect();
    v.sort();
    Some(v)
}

/// Flatten CDP's `Network.Response.headers` (a JSON object of name → string
/// value) into ordered `(lowercased-name, value)` pairs. Non-string values are
/// skipped; an unexpected non-object yields an empty list.
pub(super) fn flatten_headers(value: &serde_json::Value) -> Vec<(String, String)> {
    value
        .as_object()
        .map(|map| {
            map.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.to_lowercase(), s.to_string())))
                .collect()
        })
        .unwrap_or_default()
}
