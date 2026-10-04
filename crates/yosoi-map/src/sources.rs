//! Bounded parsers for the public discovery sources used by Map.

use std::{
    io::{self, Read},
    net::Ipv4Addr,
    str,
};

use flate2::read::GzDecoder;
use roxmltree::Node;
use thiserror::Error;
use url::Url;

const MAX_ROBOTS_BYTES: usize = 1024 * 1024;
const MAX_ROBOTS_ENTRIES: usize = 10_000;
const MAX_ROBOTS_MATCH_BYTES: usize = 64 * 1024;
const MAX_ROBOTS_MATCH_WORK: usize = 8 * 1024 * 1024;
const MAX_CERTIFICATE_RESPONSE_BYTES: usize = 16 * 1024 * 1024;

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

/// A parsed robots policy after selecting the most specific matching group.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Robots {
    rules: Vec<RobotsRule>,
    sitemaps: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RobotsRule {
    pattern: Vec<PatternToken>,
    anchored: bool,
    specificity: usize,
    allow: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PatternToken {
    Literal(u8),
    Escaped(u8),
    Wildcard,
}

#[derive(Default)]
struct RobotsGroup {
    agents: Vec<String>,
    rules: Vec<RobotsRule>,
    has_directive: bool,
}

impl Robots {
    /// Parses robots.txt with a fixed limit of 10,000 recognized directives.
    pub fn parse(text: &str, agent: &str) -> Result<Self, ParseError> {
        Self::parse_bounded(text, agent, MAX_ROBOTS_ENTRIES)
    }

    /// Parses robots.txt and fails if it has more than max_entries recognized
    /// user-agent, rule, or sitemap directives.
    pub fn parse_bounded(text: &str, agent: &str, max_entries: usize) -> Result<Self, ParseError> {
        if text.len() > MAX_ROBOTS_BYTES {
            return Err(ParseError::ByteLimitExceeded {
                limit: MAX_ROBOTS_BYTES,
            });
        }

        let agent = agent.trim().to_ascii_lowercase();
        if agent.is_empty() {
            return Err(ParseError::EmptyUserAgent);
        }

        let mut groups = Vec::new();
        let mut current = RobotsGroup::default();
        let mut sitemaps = Vec::new();
        let mut entry_count = 0usize;

        for raw_line in text.lines() {
            let uncommented = raw_line.split_once('#').map_or(raw_line, |(line, _)| line);
            let line = uncommented.trim();
            if line.is_empty() {
                continue;
            }

            let Some((name, value)) = line.split_once(':') else {
                continue;
            };
            let name = name.trim();
            let value = value.trim();

            if name.eq_ignore_ascii_case("user-agent") {
                bump_entry_count(&mut entry_count, max_entries)?;
                if current.has_directive {
                    groups.push(current);
                    current = RobotsGroup::default();
                }
                if !value.is_empty() {
                    current.agents.push(value.to_ascii_lowercase());
                }
                continue;
            }

            if name.eq_ignore_ascii_case("sitemap") {
                bump_entry_count(&mut entry_count, max_entries)?;
                if !value.is_empty() {
                    sitemaps.push(value.to_owned());
                }
                continue;
            }

            if name.eq_ignore_ascii_case("allow") || name.eq_ignore_ascii_case("disallow") {
                bump_entry_count(&mut entry_count, max_entries)?;
                if !current.agents.is_empty() {
                    current.has_directive = true;
                    if !value.is_empty() {
                        current
                            .rules
                            .push(parse_robots_rule(value, name.eq_ignore_ascii_case("allow")));
                    }
                }
                continue;
            }

            // Unsupported directives still end a user-agent section, as they
            // separate its agent declarations from any following group.
            current.has_directive = true;
        }

        if !current.agents.is_empty() {
            groups.push(current);
        }

        let selected_rules = select_robot_rules(groups, &agent);
        Ok(Self {
            rules: selected_rules,
            sitemaps,
        })
    }

    /// Returns whether a path and query string are allowed by the selected
    /// robots group. The input should be the serialized URI path and query.
    /// Paths beyond the matcher bounds are conservatively disallowed.
    pub fn allowed(&self, path_and_query: &str) -> bool {
        if path_and_query.len() > MAX_ROBOTS_MATCH_BYTES {
            return false;
        }
        let path = normalize_uri(path_and_query.as_bytes());
        let mut best: Option<(usize, bool)> = None;
        let mut remaining_work = MAX_ROBOTS_MATCH_WORK;

        for rule in &self.rules {
            let Some(matches) =
                glob_matches(&rule.pattern, &path, rule.anchored, &mut remaining_work)
            else {
                return false;
            };
            if matches {
                match best {
                    None => best = Some((rule.specificity, rule.allow)),
                    Some((best_specificity, best_allow))
                        if rule.specificity > best_specificity
                            || (rule.specificity == best_specificity
                                && rule.allow
                                && !best_allow) =>
                    {
                        best = Some((rule.specificity, rule.allow));
                    }
                    Some(_) => {}
                }
            }
        }

        best.is_none_or(|(_, allow)| allow)
    }

    /// Returns the sitemap URLs declared in the document.
    pub fn sitemaps(&self) -> &[String] {
        &self.sitemaps
    }
}

const fn bump_entry_count(count: &mut usize, limit: usize) -> Result<(), ParseError> {
    if *count >= limit {
        return Err(ParseError::EntryLimitExceeded { limit });
    }
    *count = (*count).saturating_add(1);
    Ok(())
}

fn parse_robots_rule(value: &str, allow: bool) -> RobotsRule {
    let bytes = value.as_bytes();
    let anchored = bytes.last() == Some(&b'$');
    let pattern_end = if anchored {
        bytes.len().saturating_sub(1)
    } else {
        bytes.len()
    };
    let pattern = parse_pattern(bytes.get(..pattern_end).unwrap_or_default());
    let specificity = pattern
        .iter()
        .filter(|token| !matches!(token, PatternToken::Wildcard))
        .count();
    RobotsRule {
        pattern,
        anchored,
        specificity,
        allow,
    }
}

fn parse_pattern(bytes: &[u8]) -> Vec<PatternToken> {
    let mut pattern = Vec::with_capacity(bytes.len());
    let mut index = 0usize;
    while index < bytes.len() {
        let byte = bytes.get(index).copied().unwrap_or_default();
        if byte == b'*' {
            pattern.push(PatternToken::Wildcard);
            index = index.saturating_add(1);
            continue;
        }

        if byte == b'%' {
            let escaped = bytes
                .get(index.saturating_add(1)..index.saturating_add(3))
                .and_then(decode_hex_pair);
            if let Some(octet) = escaped {
                if is_unreserved(octet) {
                    pattern.push(PatternToken::Literal(octet));
                } else {
                    pattern.push(PatternToken::Escaped(octet));
                }
                index = index.saturating_add(3);
                continue;
            }
        }

        pattern.push(normalize_raw_octet(byte));
        index = index.saturating_add(1);
    }
    pattern
}

fn normalize_uri(bytes: &[u8]) -> Vec<PatternToken> {
    let mut normalized = Vec::with_capacity(bytes.len());
    let mut index = 0usize;
    while index < bytes.len() {
        let byte = bytes.get(index).copied().unwrap_or_default();
        if byte == b'%' {
            let escaped = bytes
                .get(index.saturating_add(1)..index.saturating_add(3))
                .and_then(decode_hex_pair);
            if let Some(octet) = escaped {
                if is_unreserved(octet) {
                    normalized.push(PatternToken::Literal(octet));
                } else {
                    normalized.push(PatternToken::Escaped(octet));
                }
                index = index.saturating_add(3);
                continue;
            }
        }
        normalized.push(normalize_raw_octet(byte));
        index = index.saturating_add(1);
    }
    normalized
}

const fn normalize_raw_octet(byte: u8) -> PatternToken {
    if byte >= 0x80 || is_reserved(byte) {
        PatternToken::Escaped(byte)
    } else {
        PatternToken::Literal(byte)
    }
}

fn decode_hex_pair(digits: &[u8]) -> Option<u8> {
    let mut values = digits.iter().copied();
    let high = hex_value(values.next()?)?;
    let low = hex_value(values.next()?)?;
    if values.next().is_some() {
        return None;
    }
    Some((high << 4) | low)
}

const fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => byte.checked_sub(b'0'),
        b'a'..=b'f' => match byte.checked_sub(b'a') {
            Some(value) => value.checked_add(10),
            None => None,
        },
        b'A'..=b'F' => match byte.checked_sub(b'A') {
            Some(value) => value.checked_add(10),
            None => None,
        },
        _ => None,
    }
}

const fn is_unreserved(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~')
}

const fn is_reserved(byte: u8) -> bool {
    matches!(
        byte,
        b':' | b'/'
            | b'?'
            | b'#'
            | b'['
            | b']'
            | b'@'
            | b'!'
            | b'$'
            | b'&'
            | b'\''
            | b'('
            | b')'
            | b'*'
            | b'+'
            | b','
            | b';'
            | b'='
    )
}

fn glob_matches(
    pattern: &[PatternToken],
    path: &[PatternToken],
    anchored: bool,
    remaining_work: &mut usize,
) -> Option<bool> {
    let mut pattern_index = 0usize;
    let mut path_index = 0usize;
    let mut last_wildcard: Option<(usize, usize)> = None;

    while path_index < path.len() {
        if *remaining_work == 0 {
            return None;
        }
        *remaining_work = (*remaining_work).saturating_sub(1);
        if pattern_index == pattern.len() {
            if !anchored {
                return Some(true);
            }
            if let Some((wildcard_index, matched_path_index)) = last_wildcard {
                let next_path_index = matched_path_index.saturating_add(1);
                last_wildcard = Some((wildcard_index, next_path_index));
                pattern_index = wildcard_index.saturating_add(1);
                path_index = next_path_index;
                continue;
            }
            return Some(false);
        }

        let expected = pattern.get(pattern_index).copied();
        let actual = path.get(path_index).copied();
        match (expected, actual) {
            (Some(PatternToken::Wildcard), _) => {
                last_wildcard = Some((pattern_index, path_index));
                pattern_index = pattern_index.saturating_add(1);
            }
            (Some(expected), Some(actual)) if expected == actual => {
                pattern_index = pattern_index.saturating_add(1);
                path_index = path_index.saturating_add(1);
            }
            _ => {
                if let Some((wildcard_index, matched_path_index)) = last_wildcard {
                    let next_path_index = matched_path_index.saturating_add(1);
                    last_wildcard = Some((wildcard_index, next_path_index));
                    pattern_index = wildcard_index.saturating_add(1);
                    path_index = next_path_index;
                } else {
                    return Some(false);
                }
            }
        }
    }

    while matches!(pattern.get(pattern_index), Some(PatternToken::Wildcard)) {
        if *remaining_work == 0 {
            return None;
        }
        *remaining_work = (*remaining_work).saturating_sub(1);
        pattern_index = pattern_index.saturating_add(1);
    }

    Some(pattern_index == pattern.len())
}

fn select_robot_rules(groups: Vec<RobotsGroup>, agent: &str) -> Vec<RobotsRule> {
    let mut specific_groups: Vec<(usize, RobotsGroup)> = Vec::new();
    let mut wildcard_groups = Vec::new();
    let mut best_specificity = 0usize;

    for group in groups {
        let mut group_specificity = 0usize;
        let mut wildcard_match = false;
        for group_agent in &group.agents {
            if group_agent == "*" {
                wildcard_match = true;
            } else if agent.contains(group_agent) {
                group_specificity = group_specificity.max(group_agent.len());
            }
        }

        if group_specificity > 0 {
            best_specificity = best_specificity.max(group_specificity);
            specific_groups.push((group_specificity, group));
        } else if wildcard_match {
            wildcard_groups.push(group);
        }
    }

    let matching_groups = if best_specificity > 0 {
        specific_groups
            .into_iter()
            .filter_map(|(specificity, group)| (specificity == best_specificity).then_some(group))
            .collect()
    } else {
        wildcard_groups
    };

    matching_groups
        .into_iter()
        .flat_map(|group| group.rules)
        .collect()
}

/// The parsed contents of either a sitemap URL set or a sitemap index.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Sitemap {
    pub kind: SitemapKind,
    pub locations: Vec<String>,
    pub truncated: bool,
    /// Number of decoded XML bytes supplied to the XML parser.
    pub decoded_bytes: usize,
}

/// Identifies whether sitemap locations point to pages or nested sitemap files.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SitemapKind {
    Urls,
    Index,
}

/// Parses XML sitemap data, transparently decompressing gzip input.
///
/// max_bytes limits the uncompressed XML size and max_entries limits the
/// retained locations. Entries beyond the retention limit are still validated.
pub fn parse_sitemap(
    bytes: &[u8],
    max_entries: usize,
    max_bytes: usize,
) -> Result<Sitemap, ParseError> {
    let xml_bytes = if bytes.starts_with(&[0x1f, 0x8b]) {
        read_bounded_gzip(bytes, max_bytes)?
    } else {
        if bytes.len() > max_bytes {
            return Err(ParseError::ByteLimitExceeded { limit: max_bytes });
        }
        bytes.to_vec()
    };
    let xml = str::from_utf8(&xml_bytes).map_err(|_| ParseError::InvalidSitemapEntry {
        entry: "XML document",
        reason: "document is not UTF-8",
    })?;

    let document = roxmltree::Document::parse(xml)?;
    let root = document.root_element();
    let (kind, entry_name) = match root.tag_name().name() {
        "urlset" => (SitemapKind::Urls, "url"),
        "sitemapindex" => (SitemapKind::Index, "sitemap"),
        root_name => {
            return Err(ParseError::UnsupportedSitemapRoot {
                root: root_name.to_owned(),
            });
        }
    };

    let mut locations = Vec::with_capacity(max_entries.min(256));
    let mut truncated = false;
    for entry in root
        .children()
        .filter(|node| node.is_element() && node.tag_name().name() == entry_name)
    {
        // Validate every supported entry, including ones omitted after the cap.
        let location = sitemap_location(entry, entry_name)?;
        if locations.len() < max_entries {
            locations.push(location);
        } else {
            truncated = true;
        }
    }

    Ok(Sitemap {
        kind,
        locations,
        truncated,
        decoded_bytes: xml_bytes.len(),
    })
}

fn sitemap_location(
    entry: roxmltree::Node<'_, '_>,
    entry_name: &'static str,
) -> Result<String, ParseError> {
    let mut locations = entry
        .children()
        .filter(|node| node.is_element() && node.tag_name().name() == "loc");
    let Some(location_node) = locations.next() else {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "entry has no direct loc child",
        });
    };
    if locations.next().is_some() {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "entry has multiple direct loc children",
        });
    }

    if location_node.children().any(|node| node.is_element()) {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "loc contains nested elements",
        });
    }
    let mut value = String::new();
    for child in location_node.children().filter(Node::is_text) {
        if let Some(text) = child.text() {
            value.push_str(text);
        }
    }
    let value = value.trim();
    if value.is_empty() {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "loc is empty",
        });
    }
    Ok(value.to_owned())
}

fn read_bounded_gzip(bytes: &[u8], max_bytes: usize) -> Result<Vec<u8>, ParseError> {
    let limit = u64::try_from(max_bytes)
        .unwrap_or(u64::MAX)
        .saturating_add(1);
    let decoder = GzDecoder::new(bytes);
    let mut bounded = decoder.take(limit);
    let mut decoded = Vec::new();
    bounded
        .read_to_end(&mut decoded)
        .map_err(ParseError::InvalidGzip)?;
    if decoded.len() > max_bytes {
        return Err(ParseError::ByteLimitExceeded { limit: max_bytes });
    }
    Ok(decoded)
}

/// Names extracted from Certificate Transparency JSON returned by crt.sh.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct CertificateNames {
    pub names: Vec<String>,
    pub wildcard_names: Vec<String>,
    pub truncated: bool,
}

/// Parses crt.sh output=json responses, retaining at most max_entries
/// newline-separated certificate names.
///
/// The input is capped at 16 MiB. Every JSON record is validated even after
/// retained names reach the cap. Wildcard names remain intact and are kept in
/// their own list; this parser never invents a concrete host from a wildcard.
pub fn certificate_names(bytes: &[u8], max_entries: usize) -> Result<CertificateNames, ParseError> {
    if bytes.len() > MAX_CERTIFICATE_RESPONSE_BYTES {
        return Err(ParseError::ByteLimitExceeded {
            limit: MAX_CERTIFICATE_RESPONSE_BYTES,
        });
    }
    let response: serde_json::Value = serde_json::from_slice(bytes)?;
    let records = response
        .as_array()
        .ok_or(ParseError::InvalidCertificateResponse)?;

    let mut result = CertificateNames::default();
    let mut retained = 0usize;
    for record in records {
        let name_value = record
            .as_object()
            .and_then(|object| object.get("name_value"))
            .and_then(serde_json::Value::as_str)
            .ok_or(ParseError::InvalidCertificateRecord)?;
        for line in name_value.lines() {
            let name = line.trim();
            if name.is_empty() {
                continue;
            }
            if retained >= max_entries {
                result.truncated = true;
                continue;
            }
            if name.starts_with("*.") {
                result.wildcard_names.push(name.to_owned());
            } else {
                result.names.push(name.to_owned());
            }
            retained = retained.saturating_add(1);
        }
    }
    Ok(result)
}

/// Builds the crt.sh JSON endpoint for a DNS domain.
pub(crate) fn validated_domain(domain: &str) -> Result<String, ParseError> {
    if domain.is_empty()
        || domain.len() > 1024
        || domain
            .chars()
            .any(|character| character.is_whitespace() || "/?#@:\\".contains(character))
    {
        return Err(ParseError::InvalidDomain);
    }

    let domain = domain.strip_suffix('.').unwrap_or(domain);
    let parsed_domain =
        Url::parse(&format!("https://{domain}/")).map_err(|_| ParseError::InvalidDomain)?;
    if !parsed_domain.username().is_empty()
        || parsed_domain.password().is_some()
        || parsed_domain.port().is_some()
        || parsed_domain.path() != "/"
        || parsed_domain.query().is_some()
        || parsed_domain.fragment().is_some()
    {
        return Err(ParseError::InvalidDomain);
    }
    let host = parsed_domain.host_str().ok_or(ParseError::InvalidDomain)?;
    let host = host.strip_suffix('.').unwrap_or(host);
    if host.is_empty()
        || host.len() > 253
        || host.parse::<Ipv4Addr>().is_ok()
        || host.split('.').count() < 2
    {
        return Err(ParseError::InvalidDomain);
    }
    let labels: Vec<&str> = host.split('.').collect();
    if labels.iter().any(|label| {
        label.is_empty()
            || label.len() > 63
            || label.starts_with('-')
            || label.ends_with('-')
            || !label
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    }) {
        return Err(ParseError::InvalidDomain);
    }

    Ok(host.to_owned())
}

pub fn certificate_url(domain: &str) -> Result<Url, ParseError> {
    let host = validated_domain(domain)?;
    let mut url = Url::parse("https://crt.sh/")?;
    url.query_pairs_mut()
        .append_pair("q", &format!("%.{host}"))
        .append_pair("output", "json");
    Ok(url)
}
