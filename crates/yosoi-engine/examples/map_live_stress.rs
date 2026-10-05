//! Run bounded, serial Map checks against fixed public sites.
//!
//! Running without arguments executes the full matrix and emits JSONL.
//! Pass one case name to run just that case, or --list to print case names.

use std::{
    collections::BTreeMap,
    env,
    error::Error,
    io::{self, Write},
    time::{Duration, Instant},
};

use serde_json::{Value, json};
use url::Url;
use yosoi_engine::prelude as ys;

type HarnessResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

struct LiveCase {
    name: &'static str,
    seed: &'static str,
    registrable_domain: Option<&'static str>,
    policy: ys::Policy,
}

#[derive(Clone, Copy)]
struct LiveCaseConfig {
    name: &'static str,
    seed: &'static str,
    hosts: ys::policy::HostScope,
    registrable_domain: Option<&'static str>,
    pages: ys::policy::PageDiscovery,
    subdomains: ys::policy::Subdomains,
    max_link_depth: u16,
    max_requests: u32,
    operation_seconds: u64,
    request_seconds: u64,
}

const fn budget(value: u32) -> Result<ys::policy::Budget, ys::PolicyError> {
    ys::policy::Budget::new(value)
}

fn live_case(config: LiveCaseConfig) -> Result<LiveCase, ys::PolicyError> {
    Ok(LiveCase {
        name: config.name,
        seed: config.seed,
        registrable_domain: config.registrable_domain,
        policy: ys::Policy {
            request: ys::policy::Request {
                maximum_elapsed: ys::MaximumElapsed::try_from(
                    config.request_seconds.saturating_mul(1_000_000),
                )?,
                ..Default::default()
            },
            map: ys::policy::Map {
                scope: ys::policy::Scope {
                    hosts: config.hosts,
                    paths: ys::policy::PathScope::SeedSubtree,
                },
                robots: ys::policy::Robots::Ignore,
                pages: config.pages,
                subdomains: config.subdomains,
                limits: ys::policy::Limits {
                    max_link_depth: config.max_link_depth,
                    max_requests: budget(config.max_requests)?,
                    max_concurrency: budget(1)?,
                    maximum_elapsed: Duration::from_secs(config.operation_seconds),
                    ..Default::default()
                },
                documents: ys::policy::DiscoveryDocuments::RetainWithinBudget,
                ..Default::default()
            },
            ..Default::default()
        },
    })
}

fn live_cases() -> Result<Vec<LiveCase>, ys::PolicyError> {
    let seed_host = ys::policy::HostScope::SeedHost;
    let registrable = ys::policy::HostScope::RegistrableDomain;
    let explore = ys::policy::PageDiscovery::Explore;
    let disabled = ys::policy::PageDiscovery::Disabled;
    let no_subdomains = ys::policy::Subdomains::Disabled;
    let passive = ys::policy::Subdomains::Passive;

    let mut cases = vec![
        live_case(LiveCaseConfig {
            name: "rust-root",
            seed: "https://www.rust-lang.org/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 2,
            max_requests: 30,
            operation_seconds: 60,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "rust-book",
            seed: "https://doc.rust-lang.org/book/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 2,
            max_requests: 40,
            operation_seconds: 60,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "python-library",
            seed: "https://docs.python.org/3/library/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 2,
            max_requests: 40,
            operation_seconds: 60,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "mdn-http",
            seed: "https://developer.mozilla.org/en-US/docs/Web/HTTP/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 2,
            max_requests: 30,
            operation_seconds: 60,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "example-org-passive",
            seed: "https://example.org/",
            hosts: registrable,
            registrable_domain: Some("example.org"),
            pages: disabled,
            subdomains: passive,
            max_link_depth: 0,
            max_requests: 100,
            operation_seconds: 60,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "example-org-combined",
            seed: "https://example.org/",
            hosts: registrable,
            registrable_domain: Some("example.org"),
            pages: explore,
            subdomains: passive,
            max_link_depth: 0,
            max_requests: 20,
            operation_seconds: 90,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "qscrape-root",
            seed: "https://qscrape.dev/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 2,
            max_requests: 100,
            operation_seconds: 90,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "qscrape-news",
            seed: "https://qscrape.dev/l1/news/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 3,
            max_requests: 100,
            operation_seconds: 90,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "qscrape-news-respect-robots",
            seed: "https://qscrape.dev/l1/news/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 3,
            max_requests: 100,
            operation_seconds: 90,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "qscrape-eshop",
            seed: "https://qscrape.dev/l1/eshop/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 3,
            max_requests: 150,
            operation_seconds: 120,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "qscrape-stress",
            seed: "https://qscrape.dev/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 4,
            max_requests: 500,
            operation_seconds: 180,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "qscrape-filter-utm-source",
            seed: "https://qscrape.dev/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 2,
            max_requests: 100,
            operation_seconds: 90,
            request_seconds: 30,
        })?,
        live_case(LiveCaseConfig {
            name: "yahoo-root",
            seed: "https://www.yahoo.com/",
            hosts: seed_host,
            registrable_domain: None,
            pages: explore,
            subdomains: no_subdomains,
            max_link_depth: 1,
            max_requests: 20,
            operation_seconds: 60,
            request_seconds: 30,
        })?,
    ];

    if let Some(case) = cases
        .iter_mut()
        .find(|case| case.name == "example-org-passive")
    {
        case.policy.map.limits.max_hosts = budget(100)?;
        case.policy.map.limits.max_response_bytes = budget(4 * 1024 * 1024)?;
        case.policy.map.limits.max_total_response_bytes = budget(4 * 1024 * 1024)?;
    }

    if let Some(case) = cases.iter_mut().find(|case| case.name == "qscrape-root") {
        case.policy.map.limits.max_urls = budget(1_000)?;
    }

    if let Some(case) = cases.iter_mut().find(|case| case.name == "qscrape-stress") {
        case.policy.map.limits.max_urls = budget(5_000)?;
        case.policy.map.limits.max_relationships = budget(20_000)?;
        case.policy.map.limits.max_observations = budget(30_000)?;
        case.policy.map.limits.max_pending = budget(5_000)?;
        case.policy.map.limits.max_hosts = budget(1_000)?;
        case.policy.map.limits.max_inventory_bytes = budget(16 * 1024 * 1024)?;
        case.policy.map.limits.max_total_response_bytes = budget(64 * 1024 * 1024)?;
    }

    if let Some(case) = cases
        .iter_mut()
        .find(|case| case.name == "qscrape-filter-utm-source")
    {
        case.policy.map.limits.max_urls = budget(1_000)?;
        case.policy.map.filters.excluded_query_keys = vec!["utm_source".to_owned()];
    }

    if let Some(case) = cases
        .iter_mut()
        .find(|case| case.name == "qscrape-news-respect-robots")
    {
        case.policy.map.robots = ys::policy::Robots::Respect;
    }

    if let Some(case) = cases.iter_mut().find(|case| case.name == "yahoo-root") {
        case.policy.map.limits.max_urls = budget(5_000)?;
        case.policy.map.limits.max_inventory_bytes = budget(16 * 1024 * 1024)?;
    }

    Ok(cases)
}

fn write_json_line(writer: &mut impl Write, value: &Value) -> HarnessResult {
    writer.write_all(&serde_json::to_vec(value)?)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn write_stdout_json_line(value: &Value) -> HarnessResult {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    write_json_line(&mut output, value)?;
    output.flush()?;
    Ok(())
}

fn elapsed_milliseconds(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX)
}

fn policy_caps(case: &LiveCase) -> Value {
    let limits = &case.policy.map.limits;
    json!({
        "host_scope": format!("{:?}", case.policy.map.scope.hosts),
        "path_scope": format!("{:?}", case.policy.map.scope.paths),
        "registrable_domain": case.registrable_domain,
        "pages": format!("{:?}", case.policy.map.pages),
        "subdomains": format!("{:?}", case.policy.map.subdomains),
        "robots": format!("{:?}", case.policy.map.robots),
        "documents": format!("{:?}", case.policy.map.documents),
        "excluded_query_keys": case.policy.map.filters.excluded_query_keys,
        "max_link_depth": limits.max_link_depth,
        "max_hosts": limits.max_hosts.get(),
        "max_urls": limits.max_urls.get(),
        "max_relationships": limits.max_relationships.get(),
        "max_observations": limits.max_observations.get(),
        "max_pending": limits.max_pending.get(),
        "max_requests": limits.max_requests.get(),
        "max_sitemaps": limits.max_sitemaps.get(),
        "max_sitemap_depth": limits.max_sitemap_depth,
        "max_response_bytes": limits.max_response_bytes.get(),
        "max_total_response_bytes": limits.max_total_response_bytes.get(),
        "max_retained_document_bytes": limits.max_retained_document_bytes.get(),
        "max_concurrency": limits.max_concurrency.get(),
        "operation_deadline_ms": limits.maximum_elapsed.as_millis(),
        "request_deadline_us": case.policy.request.maximum_elapsed.as_microseconds(),
        "max_url_bytes": limits.max_url_bytes.get(),
        "max_inventory_bytes": limits.max_inventory_bytes.get(),
        "max_parser_entries": limits.max_parser_entries.get(),
        "max_hostname_bytes": limits.max_hostname_bytes.get(),
    })
}

fn increment(counts: &mut BTreeMap<String, u64>, key: impl Into<String>) {
    let count = counts.entry(key.into()).or_default();
    *count = count.saturating_add(1);
}

const fn source_status_bucket(status: &ys::map::SourceStatus) -> &'static str {
    match status {
        ys::map::SourceStatus::Completed => "completed",
        ys::map::SourceStatus::Sampled => "sampled",
        ys::map::SourceStatus::Skipped(_) => "skipped",
        ys::map::SourceStatus::Disabled => "disabled",
        ys::map::SourceStatus::Failed(_) => "failed",
        ys::map::SourceStatus::Truncated => "truncated",
        ys::map::SourceStatus::NotStarted => "not_started",
    }
}

fn source_counts(outcome: &ys::MapOutcome) -> Value {
    let mut by_source: BTreeMap<String, BTreeMap<String, u64>> = BTreeMap::new();
    let mut http_statuses = BTreeMap::new();
    let mut failure_kinds = BTreeMap::new();
    for source in outcome.sources() {
        let source_name = format!("{:?}", source.source);
        let statuses = by_source.entry(source_name).or_default();
        increment(statuses, source_status_bucket(&source.status));
        if let ys::map::SourceStatus::Failed(failure) = &source.status {
            increment(&mut failure_kinds, format!("{failure:?}"));
            if let ys::map::SourceFailure::HttpStatus(status) = failure {
                increment(&mut http_statuses, status.to_string());
            }
        }
    }
    json!({
        "by_source": by_source,
        "http_status_failures": http_statuses,
        "failure_kinds": failure_kinds,
    })
}

fn support_status_counts(outcome: &ys::MapOutcome) -> Value {
    let mut by_kind: BTreeMap<String, BTreeMap<String, u64>> = BTreeMap::new();
    for support in outcome.support_documents() {
        let statuses = by_kind.entry(format!("{:?}", support.kind)).or_default();
        increment(statuses, source_status_bucket(&support.status));
    }
    json!(by_kind)
}

fn page_exploration_counts(outcome: &ys::MapOutcome) -> Value {
    let mut counts = BTreeMap::new();
    for page in outcome.pages() {
        let label = match &page.exploration {
            ys::map::Exploration::Inventoried => "inventoried".to_owned(),
            ys::map::Exploration::Pending => "pending".to_owned(),
            ys::map::Exploration::Inspected => "inspected".to_owned(),
            ys::map::Exploration::Skipped(reason) => format!("skipped_{reason:?}"),
            ys::map::Exploration::Failed(reason) => format!("failed_{reason:?}"),
        };
        increment(&mut counts, label);
    }
    json!(counts)
}

fn frontier_reason_counts(outcome: &ys::MapOutcome) -> Value {
    let mut counts = BTreeMap::new();
    for entry in outcome.frontier() {
        increment(&mut counts, format!("{:?}", entry.reason));
    }
    json!(counts)
}

fn retained_original_documents(outcome: &ys::MapOutcome) -> u64 {
    let mut total = 0_u64;
    for capture in outcome.captures() {
        for attempt in capture.response().attempts() {
            let Some(result) = attempt.result() else {
                continue;
            };
            for document in result.documents() {
                if document.outcome().document().is_some() {
                    total = total.saturating_add(1);
                }
            }
        }
    }
    total
}

fn host_is_in_scope(case: &LiveCase, seed: &Url, host: &str) -> bool {
    match case.policy.map.scope.hosts {
        ys::policy::HostScope::SeedHost => seed.host_str() == Some(host),
        ys::policy::HostScope::RegistrableDomain => case.registrable_domain.is_some_and(|domain| {
            host == domain
                || host
                    .strip_suffix(domain)
                    .is_some_and(|prefix| prefix.ends_with('.'))
        }),
    }
}

fn path_is_within_subtree(path: &str, root: &str) -> bool {
    if path == root || root == "/" {
        return true;
    }
    if root.ends_with('/') {
        return path.starts_with(root);
    }
    path.strip_prefix(root)
        .is_some_and(|remainder| remainder.starts_with('/'))
}

fn check_case_expectations(
    case: &LiveCase,
    seed: &Url,
    outcome: &ys::MapOutcome,
    violations: &mut Vec<&'static str>,
) {
    if case.policy.map.pages == ys::policy::PageDiscovery::Explore
        && !outcome.pages().iter().any(|page| &page.url == seed)
    {
        violations.push("explore_seed_missing");
    }
    if case.policy.map.pages == ys::policy::PageDiscovery::Disabled && !outcome.pages().is_empty() {
        violations.push("disabled_pages_present");
    }
    if case.name == "yahoo-root"
        && !outcome
            .pages()
            .iter()
            .any(|page| page.exploration == ys::map::Exploration::Inspected)
    {
        violations.push("yahoo_no_inspected_pages");
    }
    if case.name == "qscrape-news-respect-robots" {
        let seed_is_robots_skipped = outcome.pages().iter().any(|page| {
            &page.url == seed
                && page.exploration == ys::map::Exploration::Skipped(ys::map::SkipReason::Robots)
        });
        if !seed_is_robots_skipped {
            violations.push("qscrape_respect_seed_not_robots_skipped");
        }
        if outcome
            .request_trace()
            .iter()
            .any(|trace| &trace.target == seed)
        {
            violations.push("qscrape_respect_seed_was_requested");
        }
    } else if case.name.starts_with("qscrape-") {
        let seed_is_inspected = outcome
            .pages()
            .iter()
            .any(|page| &page.url == seed && page.exploration == ys::map::Exploration::Inspected);
        if !seed_is_inspected {
            violations.push("qscrape_seed_not_inspected");
        }
        if !outcome
            .relationships()
            .iter()
            .any(|edge| edge.kind == ys::map::RelationshipKind::Link)
        {
            violations.push("qscrape_no_html_link_discovery");
        }
    }
}

fn check_page_scope(
    case: &LiveCase,
    seed: &Url,
    outcome: &ys::MapOutcome,
    violations: &mut Vec<&'static str>,
) {
    for page in outcome.pages() {
        let origin_matches = page.url.scheme() == seed.scheme()
            && page.url.port_or_known_default() == seed.port_or_known_default();
        let host_matches = page
            .url
            .host_str()
            .is_some_and(|host| host_is_in_scope(case, seed, host));
        let path_matches = case.policy.map.scope.paths == ys::policy::PathScope::EntireOrigin
            || path_is_within_subtree(page.url.path(), seed.path());
        if !origin_matches || !host_matches || !path_matches {
            violations.push("page_out_of_scope");
        }
        if page.url.as_str().len()
            > usize::try_from(case.policy.map.limits.max_url_bytes.get()).unwrap_or(usize::MAX)
        {
            violations.push("page_url_budget_exceeded");
        }
        if page
            .minimum_link_depth
            .is_some_and(|depth| depth > case.policy.map.limits.max_link_depth)
            && page.exploration == ys::map::Exploration::Inspected
        {
            violations.push("inspected_beyond_link_depth");
        }
    }
}

fn check_host_scope(
    case: &LiveCase,
    seed: &Url,
    outcome: &ys::MapOutcome,
    violations: &mut Vec<&'static str>,
) {
    for host in outcome.hosts() {
        if !host_is_in_scope(case, seed, &host.host) {
            violations.push("host_out_of_scope");
        }
        if host.host.len()
            > usize::try_from(case.policy.map.limits.max_hostname_bytes.get()).unwrap_or(usize::MAX)
        {
            violations.push("host_name_budget_exceeded");
        }
    }
}

fn check_capture_scope(
    case: &LiveCase,
    seed: &Url,
    outcome: &ys::MapOutcome,
    violations: &mut Vec<&'static str>,
) {
    for capture in outcome.captures() {
        if !capture
            .url()
            .host_str()
            .is_some_and(|host| host_is_in_scope(case, seed, host))
            || capture.url().scheme() != seed.scheme()
            || capture.url().port_or_known_default() != seed.port_or_known_default()
            || (case.policy.map.scope.paths == ys::policy::PathScope::SeedSubtree
                && !path_is_within_subtree(capture.url().path(), seed.path()))
        {
            violations.push("capture_out_of_scope");
        }
    }
}

fn check_request_trace(
    case: &LiveCase,
    seed: &Url,
    outcome: &ys::MapOutcome,
    violations: &mut Vec<&'static str>,
) {
    let limits = &case.policy.map.limits;
    let trace_count = u64::try_from(outcome.request_trace().len()).unwrap_or(u64::MAX);
    if u64::from(outcome.summary().requests) > u64::from(limits.max_requests.get()) {
        violations.push("request_budget_exceeded");
    }
    if trace_count > u64::from(limits.max_requests.get()) {
        violations.push("request_trace_budget_exceeded");
    }
    if trace_count != u64::from(outcome.summary().requests) {
        violations.push("request_trace_count_mismatch");
    }
    let charged_trace_bytes = outcome.request_trace().iter().fold(0_u64, |total, trace| {
        total.saturating_add(trace.charged_response_bytes)
    });
    if charged_trace_bytes != outcome.summary().response_bytes {
        violations.push("request_trace_response_bytes_mismatch");
    }
    for trace in outcome.request_trace() {
        if trace.charged_response_bytes > u64::from(limits.max_response_bytes.get()) {
            violations.push("per_response_byte_budget_exceeded");
        }

        let target_is_in_scope = trace.target.scheme() == seed.scheme()
            && trace.target.port_or_known_default() == seed.port_or_known_default()
            && trace
                .target
                .host_str()
                .is_some_and(|host| host_is_in_scope(case, seed, host));
        let target_is_certificate_service = case.policy.map.subdomains
            == ys::policy::Subdomains::Passive
            && trace.target.scheme() == "https"
            && trace.target.host_str() == Some("crt.sh")
            && trace.target.port_or_known_default() == Some(443);
        if !target_is_in_scope && !target_is_certificate_service {
            violations.push("request_target_out_of_scope");
        }
    }
}

fn check_output_budgets(
    case: &LiveCase,
    outcome: &ys::MapOutcome,
    violations: &mut Vec<&'static str>,
) {
    let limits = &case.policy.map.limits;
    if u64::try_from(outcome.hosts().len()).unwrap_or(u64::MAX) > u64::from(limits.max_hosts.get())
    {
        violations.push("host_budget_exceeded");
    }
    if u64::try_from(outcome.pages().len()).unwrap_or(u64::MAX) > u64::from(limits.max_urls.get()) {
        violations.push("url_budget_exceeded");
    }
    if u64::try_from(outcome.relationships().len()).unwrap_or(u64::MAX)
        > u64::from(limits.max_relationships.get())
    {
        violations.push("relationship_budget_exceeded");
    }
    if u64::from(outcome.summary().observations) > u64::from(limits.max_observations.get()) {
        violations.push("observation_budget_exceeded");
    }
    if u64::try_from(outcome.frontier().len()).unwrap_or(u64::MAX)
        > u64::from(limits.max_pending.get())
    {
        violations.push("frontier_budget_exceeded");
    }
    if outcome.summary().response_bytes > u64::from(limits.max_total_response_bytes.get()) {
        violations.push("total_response_byte_budget_exceeded");
    }
    if outcome.summary().inventory_bytes > u64::from(limits.max_inventory_bytes.get()) {
        violations.push("inventory_byte_budget_exceeded");
    }
    if outcome.summary().retained_document_bytes
        > u64::from(limits.max_retained_document_bytes.get())
    {
        violations.push("retained_document_budget_exceeded");
    }
}

fn scope_violations(case: &LiveCase, outcome: &ys::MapOutcome) -> HarnessResult<Vec<&'static str>> {
    let seed = Url::parse(case.seed)?;
    let mut violations = Vec::new();

    check_case_expectations(case, &seed, outcome, &mut violations);
    check_page_scope(case, &seed, outcome, &mut violations);
    check_host_scope(case, &seed, outcome, &mut violations);
    check_capture_scope(case, &seed, outcome, &mut violations);
    check_request_trace(case, &seed, outcome, &mut violations);
    check_output_budgets(case, outcome, &mut violations);

    violations.sort_unstable();
    violations.dedup();
    Ok(violations)
}

fn outcome_report(
    case: &LiveCase,
    outcome: &ys::MapOutcome,
    elapsed_ms: u64,
    violations: &[&str],
    source_revision: Option<&str>,
) -> Value {
    let verified_hosts = outcome
        .hosts()
        .iter()
        .filter(|host| host.verification == ys::map::HostVerification::HttpObserved)
        .count();
    json!({
        "case": case.name,
        "selected_case": case.name,
        "phase": if violations.is_empty() { "outcome" } else { "invariant_failure" },
        "seed": case.seed,
        "actual_caps": policy_caps(case),
        "source_revision": source_revision,
        "effective_policy_identity_version": outcome.policy_snapshot().identity().version(),
        "effective_policy_digest": outcome.policy_snapshot().identity().digest().to_string(),
        "response_byte_accounting": "charged extent/reservation; not exact wire traffic",
        "elapsed_ms": elapsed_ms,
        "termination": format!("{:?}", outcome.termination()),
        "counts": {
            "requests": outcome.summary().requests,
            "charged_response_bytes": outcome.summary().response_bytes,
            "inventory_bytes": outcome.summary().inventory_bytes,
            "observations": outcome.summary().observations,
            "omitted": outcome.summary().omitted,
            "omissions": outcome.omissions().iter().map(|omission| json!({
                "reason": format!("{:?}", omission.reason),
                "count": omission.count,
            })).collect::<Vec<_>>(),
            "hosts": outcome.hosts().len(),
            "http_observed_hosts": verified_hosts,
            "unverified_hosts": outcome.hosts().len().saturating_sub(verified_hosts),
            "pages": outcome.pages().len(),
            "page_exploration": page_exploration_counts(outcome),
            "relationships": outcome.relationships().len(),
            "html_link_relationships": outcome.relationships().iter().filter(|edge| {
                edge.kind == ys::map::RelationshipKind::Link
            }).count(),
            "frontier": outcome.frontier().len(),
            "frontier_reasons": frontier_reason_counts(outcome),
            "support_documents": outcome.support_documents().len(),
            "support_statuses": support_status_counts(outcome),
            "retained_responses": outcome.captures().len(),
            "original_documents": retained_original_documents(outcome),
            "retained_document_bytes": outcome.summary().retained_document_bytes,
            "wildcard_patterns": outcome.wildcard_names().len(),
        },
        "request_trace": outcome.request_trace().iter().map(|trace| json!({
            "target": trace.target.as_str(),
            "status": trace.status,
            "charged_response_bytes": trace.charged_response_bytes,
        })).collect::<Vec<_>>(),
        "source_statuses": source_counts(outcome),
        "invariants": {
            "passed": violations.is_empty(),
            "violations": violations,
        },
    })
}

async fn run() -> HarnessResult {
    let source_revision = env::var("MAP_LIVE_SOURCE_REVISION").ok();
    let arguments = env::args().skip(1).collect::<Vec<_>>();
    if arguments.len() > 1 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "usage: cargo run -p yosoi --example map_live_stress -- [--list|case-name]",
        )
        .into());
    }
    if arguments
        .first()
        .is_some_and(|argument| argument == "--help")
    {
        println!("Usage: cargo run -p yosoi --example map_live_stress -- [--list|case-name]");
        return Ok(());
    }

    let cases = live_cases()?;
    if arguments
        .first()
        .is_some_and(|argument| argument == "--list")
    {
        for case in &cases {
            println!("{}", case.name);
        }
        return Ok(());
    }
    let selected_name = arguments.first().map(String::as_str);
    if selected_name.is_some_and(|name| !cases.iter().any(|case| case.name == name)) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "unknown Map live case").into());
    }

    let mut had_failure = false;
    let mut ran_case = false;
    for case in cases
        .into_iter()
        .filter(|case| selected_name.is_none_or(|name| case.name == name))
    {
        ran_case = true;
        write_stdout_json_line(&json!({
            "case": case.name,
            "phase": "started",
            "seed": case.seed,
            "selected_case": case.name,
            "actual_caps": policy_caps(&case),
            "source_revision": source_revision,
        }))?;

        let started = Instant::now();
        match ys::map::new(case.seed).bind(&case.policy).send().await {
            Ok(outcome) => {
                let violations = scope_violations(&case, &outcome)?;
                let elapsed_ms = elapsed_milliseconds(started);
                let report = outcome_report(
                    &case,
                    &outcome,
                    elapsed_ms,
                    &violations,
                    source_revision.as_deref(),
                );
                write_stdout_json_line(&report)?;
                had_failure |= !violations.is_empty();
            }
            Err(error) => {
                let report = json!({
                    "case": case.name,
                    "phase": "map_error",
                    "seed": case.seed,
                    "selected_case": case.name,
                    "actual_caps": policy_caps(&case),
                    "source_revision": source_revision,
                    "elapsed_ms": elapsed_milliseconds(started),
                    "error": error.to_string(),
                });
                write_stdout_json_line(&report)?;
                had_failure = true;
            }
        }
    }

    if !ran_case {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "no Map cases selected").into());
    }
    if had_failure {
        return Err(io::Error::other(
            "one or more live Map cases failed setup or invariant checks; see JSONL output",
        )
        .into());
    }
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> HarnessResult {
    run().await
}
