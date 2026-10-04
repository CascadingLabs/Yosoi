#![expect(clippy::panic_in_result_fn, reason = "Assertions report test failures")]

use std::{error::Error, io, time::Duration};

use tokio::time::Instant;
use url::Url;
use yosoi_map::admission::{Rejection, Scope};
use yosoi_policy::policy::{Budget, HostScope, PathScope, Subdomains};

use crate::{CancellationToken, Policy, PolicySnapshot, request::execution};
use yosoi_web_capture::UserAgent;

use super::{DiscoverySource, LimitReached, MapTermination, OmissionReason, Runner, SourceStatus};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn map_policy(hosts: HostScope, subdomains: Subdomains, max_hosts: u32) -> TestResult<Policy> {
    let mut policy = Policy::default();
    policy.map.scope.hosts = hosts;
    policy.map.scope.paths = PathScope::EntireOrigin;
    policy.map.subdomains = subdomains;
    policy.map.limits.max_hosts = Budget::new(max_hosts)?;
    Ok(policy)
}

fn runner<'a>(policy: &Policy, cancellation: &'a CancellationToken) -> TestResult<Runner<'a>> {
    let snapshot = PolicySnapshot::from_policy(policy)?;
    let seed = Url::parse("https://example.com/")?;
    let scope = Scope::new(&seed, &policy.map)?;
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or_else(|| io::Error::other("Map test deadline overflow"))?;
    let user_agent = UserAgent::new("YosoiMap/test")?;
    let executor = execution::direct_http_executor_with_user_agent(user_agent)?;
    Ok(Runner::new(
        seed,
        snapshot,
        scope,
        deadline,
        cancellation,
        executor,
    ))
}

fn provider_url() -> TestResult<Url> {
    Ok(Url::parse("https://crt.sh/?q=%25.example.com&output=json")?)
}

#[test]
fn host_budget_keeps_the_first_passive_host_and_returns_typed_limit() -> TestResult {
    let policy = map_policy(HostScope::RegistrableDomain, Subdomains::Passive, 1)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;
    let provider = provider_url()?;

    assert!(runner.host_name(
        "a.example.com",
        DiscoverySource::PassiveCertificate,
        Some(&provider),
    ));
    assert!(!runner.host_name(
        "b.example.com",
        DiscoverySource::PassiveCertificate,
        Some(&provider),
    ));

    assert_eq!(
        runner.termination,
        Some(MapTermination::Limit(LimitReached::Hosts))
    );
    assert_eq!(runner.hosts.len(), 1);
    let first = runner
        .hosts
        .get("a.example.com")
        .ok_or_else(|| io::Error::other("first admitted host was not retained"))?;
    assert_eq!(first.host, "a.example.com");
    assert_eq!(first.observations.len(), 1);
    let observation = first
        .observations
        .first()
        .ok_or_else(|| io::Error::other("first host observation was not retained"))?;
    assert_eq!(observation.source, DiscoverySource::PassiveCertificate);
    assert_eq!(observation.source_url.as_ref(), Some(&provider));
    assert_eq!(runner.summary.observations, 1);
    assert_eq!(runner.summary.requests, 0);
    assert_eq!(runner.summary.response_bytes, 0);
    Ok(())
}

#[test]
fn shared_host_admission_deduplicates_only_equal_source_provenance() -> TestResult {
    let policy = map_policy(HostScope::RegistrableDomain, Subdomains::Passive, 2)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;
    let provider = provider_url()?;
    let seed = Url::parse("https://example.com/")?;

    assert!(runner.host_name(
        "A.Example.com",
        DiscoverySource::PassiveCertificate,
        Some(&provider),
    ));
    assert!(runner.host_name(
        "a.example.com",
        DiscoverySource::PassiveCertificate,
        Some(&provider),
    ));
    assert_eq!(runner.summary.observations, 1);

    assert!(runner.host_name("a.example.com", DiscoverySource::HtmlLink, Some(&seed),));
    assert_eq!(runner.summary.observations, 2);
    assert_eq!(runner.hosts.len(), 1);
    let host = runner
        .hosts
        .get("a.example.com")
        .ok_or_else(|| io::Error::other("canonical host was not retained"))?;
    assert_eq!(host.observations.len(), 2);
    let mut observations = host.observations.iter();
    let first = observations
        .next()
        .ok_or_else(|| io::Error::other("passive provenance was not retained"))?;
    let second = observations
        .next()
        .ok_or_else(|| io::Error::other("link provenance was not retained"))?;
    assert_eq!(first.source_url.as_ref(), Some(&provider));
    assert_eq!(second.source_url.as_ref(), Some(&seed));

    assert!(!runner.host_name(
        "example.com.attacker.test",
        DiscoverySource::PassiveCertificate,
        Some(&provider),
    ));
    assert_eq!(runner.hosts.len(), 1);
    assert_eq!(runner.summary.observations, 2);
    assert_eq!(
        runner
            .omissions
            .get(&OmissionReason::Admission(Rejection::HostScope)),
        Some(&1)
    );
    assert_eq!(runner.termination, None);
    assert_eq!(runner.summary.requests, 0);
    Ok(())
}

#[tokio::test]
async fn cancelled_passive_discovery_is_not_started_and_schedules_no_probes() -> TestResult {
    let policy = map_policy(HostScope::RegistrableDomain, Subdomains::Passive, 50)?;
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let mut runner = runner(&policy, &cancellation)?;

    runner.passive().await;

    assert_eq!(runner.termination, Some(MapTermination::Cancelled));
    assert_eq!(runner.summary.requests, 0);
    assert_eq!(runner.summary.response_bytes, 0);
    assert_eq!(runner.hosts.len(), 0);
    assert_eq!(runner.probes.len(), 0);
    assert_eq!(runner.queue.len(), 0);
    assert_eq!(
        runner.source_outcomes.first().map(|source| &source.status),
        Some(&SourceStatus::NotStarted)
    );
    Ok(())
}

#[tokio::test]
async fn disabled_passive_discovery_does_not_schedule_provider_work() -> TestResult {
    let policy = map_policy(HostScope::SeedHost, Subdomains::Disabled, 50)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;

    runner.passive().await;

    assert_eq!(runner.termination, None);
    assert_eq!(runner.summary.requests, 0);
    assert_eq!(runner.hosts.len(), 0);
    assert_eq!(runner.probes.len(), 0);
    assert_eq!(runner.queue.len(), 0);
    assert_eq!(
        runner.source_outcomes.first().map(|source| &source.status),
        Some(&SourceStatus::Disabled)
    );
    Ok(())
}

#[test]
fn wildcard_patterns_are_scoped_deduplicated_and_never_become_concrete_hosts() -> TestResult {
    let policy = map_policy(HostScope::RegistrableDomain, Subdomains::Passive, 50)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;
    let provider = provider_url()?;
    runner.wildcard(
        "*.A.Example.com",
        &provider,
        DiscoverySource::PassiveCertificate,
    );
    runner.wildcard(
        "*.a.example.com",
        &provider,
        DiscoverySource::PassiveCertificate,
    );
    runner.wildcard(
        "*.attacker.test",
        &provider,
        DiscoverySource::PassiveCertificate,
    );
    runner.wildcard(
        "*.*.example.com",
        &provider,
        DiscoverySource::PassiveCertificate,
    );
    assert_eq!(runner.wildcard_names, ["*.a.example.com"]);
    assert_eq!(runner.hosts.len(), 0);
    assert_eq!(runner.queue.len(), 0);
    assert_eq!(runner.summary.observations, 1);
    assert_eq!(runner.summary.omitted, 2);
    Ok(())
}

#[test]
fn map_preflight_is_synchronous_and_uses_the_same_seed_and_acquisition_rules() -> TestResult {
    use super::{MapError, new};
    use yosoi_policy::policy::Acquisition;
    use yosoi_types::BrowserMode;

    new("https://example.com/docs/").validate()?;
    assert!(matches!(
        new("https://user:secret@example.com/").validate(),
        Err(MapError::Admission(_))
    ));
    let mut policy = Policy::default();
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
    assert!(matches!(
        new("https://example.com/").bind(&policy).validate(),
        Err(MapError::UnsupportedAcquisition)
    ));
    Ok(())
}
