use url::Url;
use yosoi_map::admission::{Rejection, Scope, normalize};
use yosoi_policy::policy::{Budget, HostScope, Map, PathScope};

fn policy(hosts: HostScope, paths: PathScope) -> Map {
    let mut policy = Map::default();
    policy.scope.hosts = hosts;
    policy.scope.paths = paths;
    policy
}

#[expect(
    clippy::expect_used,
    reason = "The test helper accepts only fixed valid URL fixtures."
)]
fn url(value: &str) -> Url {
    Url::parse(value).expect("test URL is valid")
}

#[test]
fn normalize_resolves_reference_and_removes_only_fragment() {
    let base = url("https://example.com/Docs/Start?first=1&second=2");
    let normalized =
        normalize("../Guide/?b=2&a=1#section", Some(&base), 256).expect("reference resolves");

    assert_eq!(normalized.as_str(), "https://example.com/Guide/?b=2&a=1");
}

#[test]
fn normalize_preserves_scheme_path_case_query_order_and_trailing_slash() {
    let first = normalize("https://example.com/Docs?a=1&b=2", None, 128).expect("first URL parses");
    let second =
        normalize("https://example.com/docs/?b=2&a=1", None, 128).expect("second URL parses");

    assert_eq!(first.as_str(), "https://example.com/Docs?a=1&b=2");
    assert_eq!(second.as_str(), "https://example.com/docs/?b=2&a=1");
    assert_ne!(first, second);
}

#[test]
fn normalize_rejects_non_http_credentials_and_overlong_values() {
    assert_eq!(
        normalize("file:///tmp/page", None, 128),
        Err(Rejection::UnsupportedScheme)
    );
    assert_eq!(
        normalize("https://user:pass@example.com/", None, 128),
        Err(Rejection::Credentials)
    );
    assert_eq!(
        normalize("https://@example.com/", None, 128),
        Err(Rejection::Credentials)
    );
    assert_eq!(
        normalize("https:/@example.com/", None, 128),
        Err(Rejection::Credentials)
    );
    assert_eq!(
        normalize("https://example.com/long", None, 8),
        Err(Rejection::UrlLength)
    );
    let long_fragment = format!("https://example.com/#{}", "x".repeat(1_000));
    assert_eq!(
        normalize(&long_fragment, None, 64)
            .expect("fragment is removed before the normalized URL limit is applied")
            .as_str(),
        "https://example.com/"
    );
}

#[test]
fn seed_subtree_uses_encoded_path_segment_boundaries() {
    let scope = Scope::new(
        &url("https://example.com/about-us"),
        &policy(HostScope::SeedHost, PathScope::SeedSubtree),
    )
    .expect("scope is valid");

    for accepted in [
        "https://example.com/about-us",
        "https://example.com/about-us/",
        "https://example.com/about-us/team",
        "https://example.com/about-us/%2Fteam",
    ] {
        assert_eq!(scope.admit(&url(accepted)), Ok(()), "{accepted}");
    }

    for rejected in [
        "https://example.com/about",
        "https://example.com/about-us-old",
        "https://example.com/about-us%2Fteam",
        "https://example.com/products",
        "https://example.com/About-us",
    ] {
        assert_eq!(
            scope.admit(&url(rejected)),
            Err(Rejection::PathScope),
            "{rejected}"
        );
    }
}

#[test]
fn entire_origin_allows_other_paths_but_keeps_scheme_and_port() {
    let scope = Scope::new(
        &url("https://example.com/docs/start"),
        &policy(HostScope::SeedHost, PathScope::EntireOrigin),
    )
    .expect("scope is valid");

    assert_eq!(scope.admit(&url("https://example.com/")), Ok(()));
    assert_eq!(
        scope.admit(&url("http://example.com/docs/start")),
        Err(Rejection::OriginScope)
    );
    assert_eq!(
        scope.admit(&url("https://example.com:8443/docs/start")),
        Err(Rejection::OriginScope)
    );
}

#[test]
fn registrable_domain_scope_uses_public_and_private_suffix_rules() {
    let uk_scope = Scope::new(
        &url("https://www.example.co.uk/"),
        &policy(HostScope::RegistrableDomain, PathScope::EntireOrigin),
    )
    .expect("registrable scope is valid");
    assert_eq!(uk_scope.domain(), Some("example.co.uk"));
    assert_eq!(
        uk_scope.admit_host("shop.example.co.uk"),
        Ok("shop.example.co.uk".to_owned())
    );
    assert_eq!(
        uk_scope.admit_host("example.co.uk.attacker.test"),
        Err(Rejection::HostScope)
    );

    let tenant_scope = Scope::new(
        &url("https://alice.github.io/"),
        &policy(HostScope::RegistrableDomain, PathScope::EntireOrigin),
    )
    .expect("private suffix scope is valid");
    assert_eq!(tenant_scope.domain(), Some("alice.github.io"));
    assert_eq!(
        tenant_scope.admit_host("docs.alice.github.io"),
        Ok("docs.alice.github.io".to_owned())
    );
    assert_eq!(
        tenant_scope.admit_host("mallory.github.io"),
        Err(Rejection::HostScope)
    );
}

#[test]
fn registrable_domain_scope_canonicalizes_idn_and_rejects_unsupported_seeds() {
    let idn_scope = Scope::new(
        &url("https://shop.bücher.de/"),
        &policy(HostScope::RegistrableDomain, PathScope::EntireOrigin),
    )
    .expect("IDN registrable scope is valid");
    assert_eq!(idn_scope.domain(), Some("xn--bcher-kva.de"));
    assert_eq!(
        idn_scope.admit_host("cdn.xn--bcher-kva.de"),
        Ok("cdn.xn--bcher-kva.de".to_owned())
    );

    for unsupported in ["http://localhost/", "http://127.0.0.1/", "https://co.uk/"] {
        assert_eq!(
            Scope::new(
                &url(unsupported),
                &policy(HostScope::RegistrableDomain, PathScope::SeedSubtree),
            )
            .err(),
            Some(Rejection::UnsupportedDomainScope),
            "{unsupported}"
        );
    }
}

#[test]
fn scope_filters_query_keys_and_excluded_path_prefixes() {
    let mut declared = policy(HostScope::SeedHost, PathScope::EntireOrigin);
    declared
        .filters
        .excluded_query_keys
        .push("tracking".to_owned());
    declared
        .filters
        .excluded_path_prefixes
        .push("/private".to_owned());
    let scope = Scope::new(&url("https://example.com/"), &declared).expect("scope is valid");

    assert_eq!(
        scope.admit(&url("https://example.com/page?tracking=1")),
        Err(Rejection::Filtered)
    );
    assert_eq!(
        scope.admit(&url("https://example.com/private/account")),
        Err(Rejection::Filtered)
    );
    assert_eq!(
        scope.admit(&url("https://example.com/privateer")),
        Err(Rejection::Filtered)
    );
}

#[test]
fn admission_enforces_url_and_hostname_budgets() {
    let mut declared = policy(HostScope::SeedHost, PathScope::EntireOrigin);
    declared.limits.max_hostname_bytes = Budget::new(11).expect("positive test budget");
    let scope = Scope::new(&url("https://example.com/"), &declared).expect("scope is valid");

    assert_eq!(
        scope.admit(&url(&format!("https://example.com/{}", "x".repeat(9_000)))),
        Err(Rejection::UrlLength)
    );
    assert_eq!(
        scope.admit_host("sub.example.com"),
        Err(Rejection::HostnameLength)
    );
}
