use std::io::Write;

use crate::internal::map::sources::{
    ParseError, Robots, SitemapKind, certificate_names, certificate_url, parse_sitemap,
};
use flate2::{Compression, write::GzEncoder};

const ROBOTS_GROUPS: &str = include_str!("fixtures/sources/robots-groups.txt");
const ROBOTS_PERCENT: &str = include_str!("fixtures/sources/robots-percent.txt");
const SITEMAP_URLS: &[u8] = include_bytes!("fixtures/sources/sitemap-namespaced.xml");
const SITEMAP_INDEX: &[u8] = include_bytes!("fixtures/sources/sitemap-index.xml");
const CERTIFICATE_NAMES: &[u8] = include_bytes!("fixtures/sources/certificate-names.json");

#[test]
fn robots_selects_and_combines_most_specific_groups() {
    let robots = Robots::parse(ROBOTS_GROUPS, "yosoimap/1.0").expect("valid robots fixture");

    assert!(!robots.allowed("/private"));
    assert!(robots.allowed("/private/public/page"));
    assert!(robots.allowed("/tie/anything"));
    assert!(!robots.allowed("/assets/app.js"));
    assert!(robots.allowed("/assets/app.js.map"));
    assert!(robots.allowed("/all-bots"));
    assert_eq!(
        robots.sitemaps(),
        [
            "https://example.com/sitemap-index.xml",
            "https://example.com/inside-group.xml"
        ]
    );
}

#[test]
fn robots_falls_back_to_wildcard_group_when_no_agent_group_matches() {
    let robots = Robots::parse(ROBOTS_GROUPS, "OtherBot").expect("valid robots fixture");
    assert!(!robots.allowed("/all-bots"));
    assert!(robots.allowed("/private"));
}

#[test]
fn robots_normalizes_percent_encoded_unreserved_and_preserves_reserved_octets() {
    let robots = Robots::parse(ROBOTS_PERCENT, "YosoiMap").expect("valid robots fixture");

    assert!(!robots.allowed("/%7Emember"));
    assert!(!robots.allowed("/encoded%2fslash"));
    assert!(!robots.allowed("/encoded/slash"));
    assert!(!robots.allowed("/file-with-a-*.html"));
    assert!(!robots.allowed("/search?q=%62lue"));
    assert!(!robots.allowed("/café"));
    assert!(!robots.allowed("/caf%C3%A9"));
    assert!(robots.allowed("/caf%C3%89"));
}

#[test]
fn robots_entry_limit_is_an_error_instead_of_a_partial_allow_policy() {
    let error = Robots::parse_bounded("User-agent: *\nDisallow: /private\n", "YosoiMap", 1)
        .expect_err("two directives exceed the configured limit");
    assert!(matches!(error, ParseError::EntryLimitExceeded { limit: 1 }));
}

#[test]
fn sitemap_parses_namespaced_url_sets_entities_and_truncation() {
    let sitemap = parse_sitemap(SITEMAP_URLS, 1, 4096).expect("valid sitemap fixture");

    assert_eq!(sitemap.kind, SitemapKind::Urls);
    assert_eq!(sitemap.locations, ["https://example.com/a?x=1&y=2"]);
    assert!(sitemap.truncated);
}

#[test]
fn sitemap_index_is_reported_without_expanding_child_sitemaps() {
    let sitemap = parse_sitemap(SITEMAP_INDEX, 10, 4096).expect("valid sitemap index");

    assert_eq!(sitemap.kind, SitemapKind::Index);
    assert_eq!(sitemap.locations, ["https://example.com/child.xml"]);
    assert!(!sitemap.truncated);
}

#[test]
fn sitemap_rejects_unsupported_roots_malformed_xml_and_entity_declarations() {
    let unsupported = parse_sitemap(b"<feed><entry/></feed>", 10, 4096)
        .expect_err("unsupported XML roots are not sitemaps");
    assert!(matches!(
        unsupported,
        ParseError::UnsupportedSitemapRoot { .. }
    ));

    assert!(matches!(
        parse_sitemap(b"<urlset><url></urlset>", 10, 4096),
        Err(ParseError::SitemapXml(_))
    ));

    let entity_attack = br#"<!DOCTYPE urlset [<!ENTITY x "https://attacker.example/">]>
        <urlset><url><loc>&x;</loc></url></urlset>"#;
    assert!(parse_sitemap(entity_attack, 10, 4096).is_err());
}

#[test]
fn sitemap_validates_entries_after_the_retention_limit() {
    let malformed_tail = br#"<urlset>
        <url><loc>https://example.com/kept</loc></url>
        <url><changefreq>daily</changefreq></url>
    </urlset>"#;

    assert!(matches!(
        parse_sitemap(malformed_tail, 1, 4096),
        Err(ParseError::InvalidSitemapEntry { .. })
    ));

    let nested_location =
        br#"<urlset><wrapper><url><loc>https://example.com/hidden</loc></url></wrapper></urlset>"#;
    let sitemap =
        parse_sitemap(nested_location, 10, 4096).expect("well-formed XML without direct entries");
    assert_eq!(sitemap.locations, Vec::<String>::new());
}

#[test]
fn sitemap_enforces_the_decoded_gzip_byte_limit() {
    let xml = b"<urlset><url><loc>https://example.com/expanded</loc></url></urlset>";
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml).expect("write gzip fixture");
    let compressed = encoder.finish().expect("finish gzip fixture");

    let error = parse_sitemap(&compressed, 10, xml.len() - 1)
        .expect_err("decoded content exceeds the configured limit");
    assert!(matches!(
        error,
        ParseError::ByteLimitExceeded { limit } if limit == xml.len() - 1
    ));
    let sitemap = parse_sitemap(&compressed, 10, xml.len()).expect("valid compressed sitemap");
    assert_eq!(sitemap.locations, ["https://example.com/expanded"]);
    assert_eq!(sitemap.decoded_bytes, xml.len());
    assert_ne!(sitemap.decoded_bytes, compressed.len());
    assert!(matches!(
        parse_sitemap(&[0x1f, 0x8b, 0x00], 10, 4096),
        Err(ParseError::InvalidGzip(_))
    ));
}

#[test]
fn certificate_parser_splits_names_and_preserves_wildcards_and_duplicates() {
    let result = certificate_names(CERTIFICATE_NAMES, 2).expect("valid crt.sh fixture");

    assert_eq!(result.names, ["example.com"]);
    assert_eq!(result.wildcard_names, ["*.example.com"]);
    assert!(result.truncated);

    let complete = certificate_names(CERTIFICATE_NAMES, 10).expect("valid crt.sh fixture");
    assert_eq!(
        complete.names,
        ["example.com", "example.com", "api.example.com"]
    );
    assert_eq!(complete.wildcard_names, ["*.example.com", "*.example.com"]);
    assert!(!complete.truncated);
}

#[test]
fn certificate_parser_rejects_wrong_shapes_and_truncates_zero_entries() {
    assert!(matches!(
        certificate_names(br#"{"name_value":"example.com"}"#, 10),
        Err(ParseError::InvalidCertificateResponse)
    ));
    assert!(matches!(
        certificate_names(br#"[{"name_value":null}]"#, 10),
        Err(ParseError::InvalidCertificateRecord)
    ));
    assert!(matches!(
        certificate_names(
            br#"[{"name_value":"kept.example"},{"other":"missing name_value"}]"#,
            1
        ),
        Err(ParseError::InvalidCertificateRecord)
    ));

    let empty = certificate_names(br#"[{"name_value":"\n\r\n"}]"#, 0)
        .expect("empty name records are valid");
    assert!(!empty.truncated);
    let nonempty =
        certificate_names(br#"[{"name_value":"example.com"}]"#, 0).expect("valid crt.sh response");
    assert!(nonempty.truncated);
    assert_eq!(nonempty.names, Vec::<String>::new());
}

#[test]
fn certificate_url_encodes_crt_sh_wildcard_query_and_rejects_url_injection() {
    let url = certificate_url("example.com").expect("valid DNS domain");
    let query: Vec<(String, String)> = url
        .query_pairs()
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect();
    assert_eq!(
        query,
        [
            ("q".to_owned(), "%.example.com".to_owned()),
            ("output".to_owned(), "json".to_owned())
        ]
    );

    assert!(matches!(
        certificate_url("example.com/path"),
        Err(ParseError::InvalidDomain)
    ));
    assert!(matches!(
        certificate_url("127.0.0.1"),
        Err(ParseError::InvalidDomain)
    ));
}
