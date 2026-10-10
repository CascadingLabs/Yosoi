//! Emit Rust-owned `Ord` and `PartialOrd` pairs for the Python Map SDK.

use std::{
    cmp::Ordering,
    error::Error,
    io::{self, Write},
};

use serde::Serialize;
use serde_json::{Value, json};
use yosoi::map::{
    DiscoverySource, Observation, OmissionReason, PublicProvider, Rejection, Relationship,
    RelationshipKind,
};

const fn cmp_number(value: Ordering) -> i8 {
    match value {
        Ordering::Less => -1,
        Ordering::Equal => 0,
        Ordering::Greater => 1,
    }
}

fn record_pair<T: Ord + PartialOrd + Serialize>(
    output: &mut Vec<Value>,
    name: &str,
    kind: &str,
    left: &T,
    right: &T,
    expected_cmp: i8,
) -> Result<(), serde_json::Error> {
    let rust_cmp = cmp_number(left.cmp(right));
    let rust_partial_cmp = left.partial_cmp(right).map_or(2_i8, cmp_number);
    let left_json = serde_json::to_value(left)?;
    let right_json = serde_json::to_value(right)?;
    output.push(json!({
        "name": name,
        "kind": kind,
        "left": left_json,
        "right": right_json,
        "expected_cmp": expected_cmp,
        "rust_cmp": rust_cmp,
        "rust_partial_cmp": rust_partial_cmp,
        "fixture_passed": rust_cmp == expected_cmp && rust_partial_cmp == expected_cmp,
    }));
    Ok(())
}

fn record_ordered_sequence<T: Ord + PartialOrd + Serialize>(
    output: &mut Vec<Value>,
    kind: &str,
    values: &[(&str, T)],
) -> Result<(), serde_json::Error> {
    for (name, value) in values {
        record_pair(
            output,
            &format!("{kind}-{name}-equal"),
            kind,
            value,
            value,
            0,
        )?;
    }
    for pair in values.windows(2) {
        let [(left_name, left), (right_name, right)] = pair else {
            continue;
        };
        record_pair(
            output,
            &format!("{kind}-{left_name}-before-{right_name}"),
            kind,
            left,
            right,
            -1,
        )?;
    }
    Ok(())
}

fn all_providers() -> Vec<(&'static str, PublicProvider)> {
    vec![
        ("crt_sh", PublicProvider::CrtSh),
        ("hacker_target", PublicProvider::HackerTarget),
        ("subdomain_center", PublicProvider::SubdomainCenter),
        ("wayback_archive", PublicProvider::WaybackArchive),
    ]
}

fn all_rejections() -> Vec<(&'static str, Rejection)> {
    vec![
        ("invalid_url", Rejection::InvalidUrl),
        ("unsupported_scheme", Rejection::UnsupportedScheme),
        ("credentials", Rejection::Credentials),
        ("host_scope", Rejection::HostScope),
        ("origin_scope", Rejection::OriginScope),
        ("path_scope", Rejection::PathScope),
        ("filtered", Rejection::Filtered),
        ("url_length", Rejection::UrlLength),
        ("invalid_host", Rejection::InvalidHost),
        (
            "unsupported_domain_scope",
            Rejection::UnsupportedDomainScope,
        ),
        ("hostname_length", Rejection::HostnameLength),
    ]
}

fn record_observation_cases(output: &mut Vec<Value>) -> Result<(), Box<dyn Error>> {
    let seed_z = Observation {
        source: DiscoverySource::Seed,
        source_url: Some("https://z.example/source".parse()?),
    };
    let seed_a = Observation {
        source: DiscoverySource::Seed,
        source_url: Some("https://a.example/source".parse()?),
    };
    let seed_none = Observation {
        source: DiscoverySource::Seed,
        source_url: None,
    };
    let html_none = Observation {
        source: DiscoverySource::HtmlLink,
        source_url: None,
    };
    record_pair(
        output,
        "observation-none-before-source-url",
        "observation",
        &seed_none,
        &seed_a,
        -1,
    )?;
    record_pair(
        output,
        "observation-url-order",
        "observation",
        &seed_z,
        &seed_a,
        1,
    )?;
    record_pair(
        output,
        "observation-source-before-source-url",
        "observation",
        &seed_z,
        &html_none,
        -1,
    )?;
    Ok(())
}

fn record_relationship_cases(output: &mut Vec<Value>) -> Result<(), Box<dyn Error>> {
    let link = Relationship {
        from: "https://a.example/from".parse()?,
        to: "https://a.example/to-a".parse()?,
        kind: RelationshipKind::Link,
    };
    let canonical = Relationship {
        kind: RelationshipKind::Canonical,
        ..link.clone()
    };
    let to_z = Relationship {
        to: "https://z.example/to".parse()?,
        ..link.clone()
    };
    let from_z = Relationship {
        from: "https://z.example/from".parse()?,
        kind: RelationshipKind::Canonical,
        ..link.clone()
    };
    let from_a = Relationship {
        from: "https://a.example/from".parse()?,
        kind: RelationshipKind::Link,
        ..link.clone()
    };
    record_pair(
        output,
        "relationship-kind-ord-differs-from-lexical",
        "relationship",
        &link,
        &canonical,
        -1,
    )?;
    record_pair(
        output,
        "relationship-to-field-order",
        "relationship",
        &to_z,
        &link,
        1,
    )?;
    record_pair(
        output,
        "relationship-from-field-order",
        "relationship",
        &from_z,
        &from_a,
        1,
    )?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut output = Vec::new();
    let providers = all_providers();
    record_ordered_sequence(&mut output, "public_provider", &providers)?;

    let mut sources = vec![
        ("seed", DiscoverySource::Seed),
        ("html_link", DiscoverySource::HtmlLink),
        ("xml_link", DiscoverySource::XmlLink),
    ];
    sources.extend(
        providers
            .iter()
            .map(|(name, provider)| (*name, DiscoverySource::PassiveProvider(*provider))),
    );
    sources.extend([
        ("sitemap", DiscoverySource::Sitemap),
        ("robots", DiscoverySource::Robots),
        ("redirect", DiscoverySource::Redirect),
        ("passive_certificate", DiscoverySource::PassiveCertificate),
    ]);
    record_ordered_sequence(&mut output, "discovery_source", &sources)?;

    record_observation_cases(&mut output)?;

    let rejections = all_rejections();
    record_ordered_sequence(&mut output, "rejection", &rejections)?;

    let mut omissions = rejections
        .iter()
        .map(|(name, rejection)| (*name, OmissionReason::Admission(*rejection)))
        .collect::<Vec<_>>();
    omissions.extend([
        ("robots", OmissionReason::Robots),
        ("depth", OmissionReason::Depth),
        ("sitemap_depth", OmissionReason::SitemapDepth),
        ("pending", OmissionReason::Pending),
        ("inventory", OmissionReason::Inventory),
        ("retention", OmissionReason::Retention),
        ("wildcard", OmissionReason::Wildcard),
        ("other", OmissionReason::Other),
    ]);
    record_ordered_sequence(&mut output, "omission_reason", &omissions)?;

    record_ordered_sequence(
        &mut output,
        "relationship_kind",
        &[
            ("link", RelationshipKind::Link),
            ("redirect", RelationshipKind::Redirect),
            ("canonical", RelationshipKind::Canonical),
        ],
    )?;
    record_relationship_cases(&mut output)?;

    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());
    serde_json::to_writer(&mut writer, &output)?;
    writeln!(writer)?;
    Ok(())
}
