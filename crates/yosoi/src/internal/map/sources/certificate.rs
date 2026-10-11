use std::net::Ipv4Addr;

use url::Url;

use super::ParseError;

const MAX_CERTIFICATE_RESPONSE_BYTES: usize = 16 * 1024 * 1024;

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
pub fn validated_domain(domain: &str) -> Result<String, ParseError> {
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
