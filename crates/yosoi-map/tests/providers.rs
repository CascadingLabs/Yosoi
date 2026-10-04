use yosoi_map::providers::{ProviderError, PublicProvider, parse};

const CERTIFICATE_NAMES: &[u8] = include_bytes!("fixtures/sources/certificate-names.json");
const HACKERTARGET: &[u8] = include_bytes!("fixtures/providers/hackertarget.csv");
const SUBDOMAIN_CENTER: &[u8] = include_bytes!("fixtures/providers/subdomain-center.json");
const WAYBACK: &[u8] = include_bytes!("fixtures/providers/wayback.json");
const WAYBACK_RESUME: &[u8] = include_bytes!("fixtures/providers/wayback-resume.json");

#[test]
fn catalog_is_deterministic_and_contains_only_fixed_public_indexes() {
    assert_eq!(
        PublicProvider::all().to_vec(),
        vec![
            PublicProvider::CrtSh,
            PublicProvider::HackerTarget,
            PublicProvider::SubdomainCenter,
            PublicProvider::WaybackArchive,
        ]
    );
    assert_eq!(
        PublicProvider::all()
            .iter()
            .map(|provider| provider.name())
            .collect::<Vec<_>>(),
        ["crtsh", "hackertarget", "subdomaincenter", "waybackarchive"]
    );
}

#[test]
fn endpoints_encode_domain_queries_and_reject_path_injection() {
    let crt = PublicProvider::CrtSh
        .endpoint("example.org")
        .expect("valid CT query");
    let crt_query: Vec<(String, String)> = crt
        .query_pairs()
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect();
    assert_eq!(crt.host_str(), Some("crt.sh"));
    assert_eq!(
        crt_query,
        [
            ("q".to_owned(), "%.example.org".to_owned()),
            ("output".to_owned(), "json".to_owned())
        ]
    );

    let hostsearch = PublicProvider::HackerTarget
        .endpoint("example.org")
        .expect("valid hostsearch query");
    assert_eq!(hostsearch.host_str(), Some("api.hackertarget.com"));
    let hostsearch_query: Vec<(String, String)> = hostsearch
        .query_pairs()
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect();
    assert_eq!(
        hostsearch_query,
        [("q".to_owned(), "example.org".to_owned())]
    );

    let center = PublicProvider::SubdomainCenter
        .endpoint("example.org")
        .expect("valid Subdomain Center query");
    assert_eq!(center.host_str(), Some("api.subdomain.center"));
    let center_query: Vec<(String, String)> = center
        .query_pairs()
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect();
    assert_eq!(
        center_query,
        [("domain".to_owned(), "example.org".to_owned())]
    );

    let wayback = PublicProvider::WaybackArchive
        .endpoint("example.org")
        .expect("valid CDX query");
    let wayback_query: Vec<(String, String)> = wayback
        .query_pairs()
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect();
    assert_eq!(wayback.host_str(), Some("web.archive.org"));
    assert!(wayback_query.contains(&("url".to_owned(), "example.org/*".to_owned())));
    assert!(wayback_query.contains(&("matchType".to_owned(), "domain".to_owned())));
    assert!(wayback_query.contains(&("output".to_owned(), "json".to_owned())));
    assert!(wayback_query.contains(&("limit".to_owned(), "1000".to_owned())));

    for provider in PublicProvider::all() {
        assert!(matches!(
            provider.endpoint("example.org/path"),
            Err(ProviderError::InvalidDomain | ProviderError::Source(_))
        ));
    }
}

#[test]
fn crt_sh_reuses_certificate_parser_and_local_truncation() {
    let parsed =
        parse(PublicProvider::CrtSh, CERTIFICATE_NAMES, 2).expect("valid crt.sh JSON response");
    assert_eq!(parsed.entries.names, ["example.com"]);
    assert_eq!(parsed.entries.wildcard_names, ["*.example.com"]);
    assert!(parsed.entries.truncated);
    assert!(!parsed.sample_limited);
}

#[test]
fn hackertarget_csv_preserves_names_and_rejects_error_text() {
    let parsed = parse(PublicProvider::HackerTarget, HACKERTARGET, 10)
        .expect("valid HackerTarget hostsearch response");
    assert_eq!(parsed.entries.names, ["example.org", "www.example.org"]);
    assert!(!parsed.entries.truncated);
    assert!(!parsed.sample_limited);

    let capped_response = vec!["www.example.org,192.0.2.10"; 50].join("\n");
    let capped = parse(
        PublicProvider::HackerTarget,
        capped_response.as_bytes(),
        100,
    )
    .expect("50 valid results reach the documented provider cap");
    assert!(!capped.entries.truncated);
    assert!(capped.sample_limited);

    assert!(matches!(
        parse(PublicProvider::HackerTarget, b"API count exceeded", 10),
        Err(ProviderError::InvalidRecord {
            provider: PublicProvider::HackerTarget
        })
    ));
}

#[test]
fn subdomain_center_reports_anonymous_sampling_separately_from_retention() {
    let parsed = parse(PublicProvider::SubdomainCenter, SUBDOMAIN_CENTER, 1)
        .expect("valid Subdomain Center JSON response");
    assert_eq!(parsed.entries.names, ["example.org"]);
    assert!(parsed.entries.truncated);
    assert!(parsed.sample_limited);

    let complete = parse(PublicProvider::SubdomainCenter, SUBDOMAIN_CENTER, 10)
        .expect("valid Subdomain Center JSON response");
    assert_eq!(complete.entries.names, ["example.org", "www.example.org"]);
    assert_eq!(complete.entries.wildcard_names, ["*.example.org"]);
    assert!(!complete.entries.truncated);
    assert!(complete.sample_limited);

    assert!(matches!(
        parse(
            PublicProvider::SubdomainCenter,
            br#"{"error":"rate limited"}"#,
            10
        ),
        Err(ProviderError::UnsupportedResponse {
            provider: PublicProvider::SubdomainCenter
        })
    ));
}

#[test]
fn wayback_cdx_parses_original_hosts_and_resume_metadata() {
    let parsed =
        parse(PublicProvider::WaybackArchive, WAYBACK, 1).expect("valid Wayback CDX response");
    assert_eq!(parsed.entries.names, ["example.org"]);
    assert!(parsed.entries.truncated);
    assert!(!parsed.sample_limited);

    let resumed = parse(PublicProvider::WaybackArchive, WAYBACK_RESUME, 10)
        .expect("valid Wayback CDX response with resume key");
    assert_eq!(resumed.entries.names, ["example.org"]);
    assert!(!resumed.entries.truncated);
    assert!(resumed.sample_limited);
}

#[test]
fn html_challenges_and_malformed_indexes_are_typed_errors() {
    for provider in PublicProvider::all() {
        assert!(matches!(
            parse(*provider, b"<!doctype html><html>challenge</html>", 10),
            Err(ProviderError::UnsupportedResponse { .. })
        ));
    }

    assert!(matches!(
        parse(
            PublicProvider::WaybackArchive,
            br#"[["not-original"],["x"]]"#,
            10
        ),
        Err(ProviderError::UnsupportedResponse {
            provider: PublicProvider::WaybackArchive
        })
    ));
    assert!(matches!(
        parse(
            PublicProvider::WaybackArchive,
            br#"[["original"],["not-a-url"]]"#,
            10
        ),
        Err(ProviderError::InvalidRecord {
            provider: PublicProvider::WaybackArchive
        })
    ));
}
