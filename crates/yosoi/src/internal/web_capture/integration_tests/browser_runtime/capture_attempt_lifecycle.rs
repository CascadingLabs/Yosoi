#![cfg(feature = "browser")]
#![allow(
    clippy::expect_used,
    clippy::panic,
    clippy::unwrap_used,
    reason = "independent deterministic CAS-327 browser contract tests"
)]

use super::fixture;

use crate::internal::browser::ProfileRegistry;
use crate::internal::types::{
    CaptureId, OperationId, Producer, ReasonCode, Schema, SchemaId, SchemaVersion,
};
use crate::internal::web_capture::*;
use crate::internal::web_capture::{
    BrowserExecutionManager, BrowserExecutionManagerConfig, VoidCrawlAdapterError, capture_attempt,
    capture_attempt_managed,
};
use std::{
    env, fs, io,
    net::{Ipv4Addr, SocketAddr},
    num::{NonZeroU32, NonZeroU64},
    path::PathBuf,
    process,
    sync::{
        Arc, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, SystemTime},
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
    select,
    sync::Mutex,
    task::JoinHandle,
    time::timeout,
};
use tokio_util::sync::CancellationToken;

fn browser_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

fn execution_limits() -> BrowserExecutionLimits {
    BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::MIN),
        BrowserContextTotalLimit::new(NonZeroU32::MIN),
        BrowserContextsPerProcessLimit::new(NonZeroU32::MIN),
        BrowserTabTotalLimit::new(NonZeroU32::MIN),
        BrowserTabsPerSessionLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(NonZeroU32::new(4).unwrap()),
        BrowserQueueWaitLimit::new(NonZeroU64::new(10_000).unwrap()),
        BrowserCleanupDeadline::new(NonZeroU64::new(10_000).unwrap()),
        BrowserRecycleThreshold::new(NonZeroU32::new(100).unwrap()),
    )
    .unwrap()
}

fn execution_limits_with_contexts(
    contexts_total: u32,
    contexts_per_process: u32,
) -> BrowserExecutionLimits {
    let processes = if contexts_per_process >= contexts_total {
        1
    } else {
        contexts_total
    };
    BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::new(processes).unwrap()),
        BrowserContextTotalLimit::new(NonZeroU32::new(contexts_total).unwrap()),
        BrowserContextsPerProcessLimit::new(NonZeroU32::new(contexts_per_process).unwrap()),
        BrowserTabTotalLimit::new(NonZeroU32::new(contexts_total).unwrap()),
        BrowserTabsPerSessionLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(NonZeroU32::new(4).unwrap()),
        BrowserQueueWaitLimit::new(NonZeroU64::new(10_000).unwrap()),
        BrowserCleanupDeadline::new(NonZeroU64::new(10_000).unwrap()),
        BrowserRecycleThreshold::new(NonZeroU32::new(100).unwrap()),
    )
    .unwrap()
}

fn producer() -> Producer {
    void_crawl_adapter_producer().expect("linked VoidCrawl producer identity must be valid")
}

fn capabilities(mode: BrowserMode) -> CertifiedBrowserCapabilities {
    let supported = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let unavailable = ArtifactCapability::Unsupported {
        reason: ReasonCode::new("test.unavailable").unwrap(),
    };
    let profile = WebProviderCapabilityProfile::new(
        producer(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            mode,
        )),
        WebArtifactCapabilitySet::new(
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            unavailable,
            supported.clone(),
            supported.clone(),
            supported,
        ),
    )
    .unwrap();
    CertifiedBrowserCapabilities::new(
        profile,
        &producer(),
        mode,
        BrowserInstrumentationMode::Normal,
        BrowserFamilyCapabilities::new(
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Unsupported {
                reason: ReasonCode::new("test.unavailable").unwrap(),
            },
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
        ),
    )
    .unwrap()
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "fixture URLs are owned temporaries at each test call site"
)]
fn spec(
    target: String,
    maximum_micros: u64,
    max_events: u32,
    max_resources: u32,
    rendered_dom_limit: Option<u64>,
) -> ResolvedBrowserCaptureSpec {
    spec_with_settlement(
        &target,
        maximum_micros,
        max_events,
        max_resources,
        rendered_dom_limit,
        true,
        SettlementPolicy::Disabled,
    )
}

fn spec_with_settlement(
    target: &str,
    maximum_micros: u64,
    max_events: u32,
    max_resources: u32,
    rendered_dom_limit: Option<u64>,
    network_requested: bool,
    settlement: SettlementPolicy,
) -> ResolvedBrowserCaptureSpec {
    spec_with_mode(
        target,
        maximum_micros,
        max_events,
        max_resources,
        rendered_dom_limit,
        network_requested,
        settlement,
        BrowserMode::Headless,
    )
}

fn source_only_event_limit_spec(target: &str) -> ResolvedBrowserCaptureSpec {
    spec_with_source_mode_and_overrides(
        target,
        10_000_000,
        1,
        64,
        None,
        true,
        false,
        SettlementPolicy::Disabled,
        BrowserMode::Headless,
        BrowserEnvironmentOverrides::default(),
    )
}

#[allow(
    clippy::too_many_arguments,
    reason = "fixture construction keeps each resolved capture decision explicit"
)]
fn spec_with_mode(
    target: &str,
    maximum_micros: u64,
    max_events: u32,
    max_resources: u32,
    rendered_dom_limit: Option<u64>,
    network_requested: bool,
    settlement: SettlementPolicy,
    mode: BrowserMode,
) -> ResolvedBrowserCaptureSpec {
    spec_with_mode_and_overrides(
        target,
        maximum_micros,
        max_events,
        max_resources,
        rendered_dom_limit,
        network_requested,
        settlement,
        mode,
        BrowserEnvironmentOverrides::default(),
    )
}

#[allow(
    clippy::too_many_arguments,
    reason = "fixture construction keeps each resolved capture decision explicit"
)]
fn spec_with_mode_and_overrides(
    target: &str,
    maximum_micros: u64,
    max_events: u32,
    max_resources: u32,
    rendered_dom_limit: Option<u64>,
    network_requested: bool,
    settlement: SettlementPolicy,
    mode: BrowserMode,
    overrides: BrowserEnvironmentOverrides,
) -> ResolvedBrowserCaptureSpec {
    spec_with_source_mode_and_overrides(
        target,
        maximum_micros,
        max_events,
        max_resources,
        rendered_dom_limit,
        false,
        network_requested,
        settlement,
        mode,
        overrides,
    )
}

#[allow(
    clippy::too_many_arguments,
    reason = "fixture construction keeps each resolved capture decision explicit"
)]
fn spec_with_source_mode_and_overrides(
    target: &str,
    maximum_micros: u64,
    max_events: u32,
    max_resources: u32,
    rendered_dom_limit: Option<u64>,
    source_requested: bool,
    network_requested: bool,
    settlement: SettlementPolicy,
    mode: BrowserMode,
    overrides: BrowserEnvironmentOverrides,
) -> ResolvedBrowserCaptureSpec {
    let capture_id = CaptureId::random();
    let source = if source_requested {
        ArtifactRequest::Required
    } else {
        ArtifactRequest::NotRequested
    };
    let rendered_dom = if rendered_dom_limit.is_some() {
        ArtifactRequest::Required
    } else {
        ArtifactRequest::NotRequested
    };
    let network = if network_requested {
        ArtifactRequest::Required
    } else {
        ArtifactRequest::NotRequested
    };
    let mut byte_bounds = Vec::new();
    if source_requested {
        byte_bounds.push(BrowserByteBound::new(
            BrowserByteDomain::CdpDecodedBody,
            NonZeroU64::new(1_000_000).unwrap(),
            BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ));
        byte_bounds.push(BrowserByteBound::new(
            BrowserByteDomain::DecodedSourceUtf8,
            NonZeroU64::new(1_000_000).unwrap(),
            BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ));
    }
    if let Some(limit) = rendered_dom_limit.and_then(NonZeroU64::new) {
        byte_bounds.push(BrowserByteBound::new(
            BrowserByteDomain::RenderedDomUtf8,
            limit,
            BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ));
    }
    ResolvedBrowserCaptureSpec::new(
        WebCaptureRequest::new(
            capture_id,
            RequestedWebTarget::parse(target).unwrap(),
            WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
                NavigationContext::FreshTopLevel,
            )),
        ),
        WebArtifactRequestSet::new(
            source,
            rendered_dom,
            ArtifactRequest::NotRequested,
            network,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
        ),
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(maximum_micros).unwrap(),
                None,
                None,
            ),
            settlement,
        ),
        BrowserNavigationPolicy::new(NavigationCompletionPolicy::ControllerCompleted),
        BrowserAttemptEnvironment::with_overrides(mode, overrides),
        BrowserProviderBounds::new(
            byte_bounds,
            NonZeroU64::new(u64::from(max_events)).unwrap(),
            NonZeroU32::new(max_resources).unwrap(),
            NonZeroU32::new(10_000).unwrap(),
        )
        .unwrap(),
        capabilities(mode),
        producer(),
        OperationId::new("test.capture-attempt").unwrap(),
        BrowserOutputSchemas::new(
            source_requested.then(|| {
                Schema::new(
                    SchemaId::new("test.source").unwrap(),
                    SchemaVersion::new(NonZeroU32::MIN),
                )
            }),
            source_requested.then(|| {
                Schema::new(
                    SchemaId::new("test.source-representation").unwrap(),
                    SchemaVersion::new(NonZeroU32::MIN),
                )
            }),
            source_requested.then(|| {
                Schema::new(
                    SchemaId::new("test.decoded-source").unwrap(),
                    SchemaVersion::new(NonZeroU32::MIN),
                )
            }),
            rendered_dom_limit.map(|_| {
                Schema::new(
                    SchemaId::new("test.rendered-dom").unwrap(),
                    SchemaVersion::new(NonZeroU32::MIN),
                )
            }),
            None,
            network_requested.then(|| {
                Schema::new(
                    SchemaId::new("test.network").unwrap(),
                    SchemaVersion::new(NonZeroU32::MIN),
                )
            }),
            None,
            None,
            None,
            None,
            None,
        ),
        BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::AdmitNetworkUrls,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::Omit,
        ),
    )
    .unwrap()
}

async fn clean_shutdown(fixture: fixture::BrowserFixture) {
    timeout(Duration::from_secs(5), fixture.shutdown())
        .await
        .expect("fixture shutdown timeout")
        .expect("fixture shutdown");
}

#[tokio::test]
async fn pre_cancel_is_typed_and_does_not_touch_the_fixture() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let result = timeout(
        Duration::from_secs(10),
        capture_attempt(
            &spec(fixture.url("/shell").unwrap(), 10_000_000, 64, 64, None),
            &cancellation,
        ),
    )
    .await;
    assert!(matches!(
        result,
        Ok(Err(VoidCrawlAdapterError::CancelledBeforeOwnership))
    ));
    assert_eq!(fixture.requests().await, Vec::<String>::new());
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn delayed_and_endless_attempts_stop_with_preserved_terminal_and_cleanup() {
    let _browser = browser_lock().lock().await;
    for route in ["/delayed", "/endless"] {
        let fixture = fixture::BrowserFixture::start().await.unwrap();
        let cancellation = CancellationToken::new();
        let task = tokio::spawn({
            let cancellation = cancellation.clone();
            let capture_spec = spec(fixture.url(route).unwrap(), 10_000_000, 64, 64, None);
            async move { capture_attempt(&capture_spec, &cancellation).await }
        });
        if route == "/delayed" {
            timeout(
                Duration::from_secs(10),
                fixture.barriers.delayed_requested.wait(),
            )
            .await
            .expect("delayed request timeout")
            .unwrap();
        } else {
            timeout(
                Duration::from_secs(10),
                fixture.barriers.endless_requested.wait(),
            )
            .await
            .expect("endless request timeout")
            .unwrap();
        }
        cancellation.cancel();
        let result = timeout(Duration::from_secs(15), task)
            .await
            .expect("attempt cancellation timeout")
            .unwrap()
            .unwrap();
        assert!(!result.is_ready());
        assert!(matches!(
            result.terminal().kind(),
            BrowserTerminalKind::CallerCancelled { .. }
        ));
        assert_eq!(result.facts().cleanup(), CleanupState::Complete);
        clean_shutdown(fixture).await;
    }
}

fn assert_main_resource_failed(result: &BrowserAdapterResult) {
    let network = result
        .facts()
        .staging()
        .slots()
        .iter()
        .find(|slot| slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::Network))
        .expect("network slot");
    let BrowserStagingParts::Structured {
        evidence:
            BrowserStructuredEvidence::Network {
                main_document: Some(main_document),
                resources,
                ..
            },
        ..
    } = network.outcome().parts()
    else {
        panic!("network evidence includes the main document")
    };
    assert!(resources.iter().any(|resource| {
        resource.id == main_document.resource
            && matches!(resource.outcome, BrowserResourceOutcome::Failed { .. })
    }));
}

#[tokio::test]
async fn deadline_event_resource_and_partial_navigation_are_bounded() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let deadline_cancellation = CancellationToken::new();
    // The end-to-end deadline includes Chromium launch and context creation. Allow
    // ordinary concurrent-startup variance while the endless response deterministically
    // drives a post-navigation deadline.
    let deadline_spec = spec(fixture.url("/endless").unwrap(), 10_000_000, 64, 64, None);
    let mut deadline_task = tokio::spawn({
        let cancellation = deadline_cancellation.clone();
        async move { capture_attempt(&deadline_spec, &cancellation).await }
    });
    select! {
        requested = timeout(
            Duration::from_secs(15),
            fixture.barriers.endless_requested.wait(),
        ) => requested.expect("endless request timeout").unwrap(),
        result = &mut deadline_task => {
            panic!("attempt completed before endless request: {result:?}");
        }
    }
    let deadline = timeout(Duration::from_secs(20), deadline_task)
        .await
        .expect("deadline attempt timeout")
        .unwrap()
        .unwrap();
    assert!(matches!(
        deadline.terminal().kind(),
        BrowserTerminalKind::DeadlineReached { .. }
    ));
    assert_eq!(deadline.facts().cleanup(), CleanupState::Complete);
    clean_shutdown(fixture).await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let flood_cancellation = CancellationToken::new();
    let flood_spec = spec_with_settlement(
        &fixture.url("/event-flood").unwrap(),
        10_000_000,
        1,
        1,
        None,
        true,
        SettlementPolicy::QuietPeriod(QuietPeriodPolicy::new(
            SettlementPolicyId::new("test.browser.event-limit").unwrap(),
            QuietPeriod::try_from(100_000).unwrap(),
            ActivityCount::new(0),
        )),
    );
    let flooded = tokio::spawn({
        let cancellation = flood_cancellation.clone();
        async move { capture_attempt(&flood_spec, &cancellation).await }
    });
    timeout(
        Duration::from_secs(10),
        fixture.barriers.event_flood_requested.wait(),
    )
    .await
    .expect("event request timeout")
    .unwrap();
    let flooded = timeout(Duration::from_secs(15), flooded)
        .await
        .expect("flood attempt timeout")
        .unwrap()
        .unwrap();
    assert!(
        matches!(
            flooded.terminal().kind(),
            BrowserTerminalKind::EventLimitReached
        ),
        "unexpected flood terminal: {:?}, events: {:?}",
        flooded.terminal(),
        flooded.facts().events()
    );
    let network = flooded
        .facts()
        .staging()
        .slots()
        .iter()
        .find(|slot| slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::Network))
        .expect("network slot");
    let BrowserStagingParts::Structured {
        evidence:
            BrowserStructuredEvidence::Network {
                events,
                resource_accounting,
                event_accounting,
                ..
            },
        ..
    } = network.outcome().parts()
    else {
        panic!("network is structured")
    };
    assert!(resource_accounting.retained() <= 1);
    assert_eq!(event_accounting.admitted().get(), 1);
    assert!(
        events
            .iter()
            .all(|event| event.at <= flooded.terminal().at())
    );
    let lifecycle = flooded.lifecycle().expect("event-limit lifecycle");
    assert_eq!(lifecycle.admitted_events(), 1);
    assert_eq!(
        lifecycle.retained_events(),
        flooded.facts().events().retained().get()
    );
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::EventLimitReached { event_limit }) if event_limit.get() == 1
    ));
    assert_eq!(flooded.facts().cleanup(), CleanupState::Complete);
    clean_shutdown(fixture).await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let partial_cancellation = CancellationToken::new();
    let partial_spec = spec(fixture.url("/partial").unwrap(), 2_000_000, 64, 64, None);
    let partial = tokio::spawn({
        let cancellation = partial_cancellation.clone();
        async move { capture_attempt(&partial_spec, &cancellation).await }
    });
    timeout(
        Duration::from_secs(10),
        fixture.barriers.partial_requested.wait(),
    )
    .await
    .expect("partial request timeout")
    .unwrap();
    let partial = timeout(Duration::from_secs(15), partial)
        .await
        .expect("partial attempt timeout")
        .unwrap()
        .unwrap();
    assert_main_resource_failed(&partial);
    match partial.terminal().kind() {
        // Controller completion reports the page lifecycle checkpoint, while
        // the independently retained network facts still record the failed
        // short body. Both facts are truthful and must remain distinct.
        BrowserTerminalKind::ControllerCompleted => assert!(partial.is_ready()),
        BrowserTerminalKind::ProviderStopped {
            reason:
                BrowserProviderStop::NavigationFailure | BrowserProviderStop::BrowserDisconnected,
        }
        | BrowserTerminalKind::DeadlineReached { .. } => assert!(!partial.is_ready()),
        terminal => panic!("unexpected partial response terminal: {terminal:?}"),
    }
    assert_eq!(partial.facts().cleanup(), CleanupState::Complete);
    clean_shutdown(fixture).await;
}

fn assert_source_only_event_limit(result: &BrowserAdapterResult) {
    assert!(matches!(
        result.terminal().kind(),
        BrowserTerminalKind::EventLimitReached
    ));
    assert_eq!(result.terminal().at(), result.facts().observed_through());
    assert_eq!(result.facts().events().admitted().get(), 1);
    let lifecycle = result
        .lifecycle()
        .expect("source-only event-limit lifecycle");
    assert_eq!(lifecycle.admitted_events(), 1);
    assert_eq!(
        lifecycle.retained_events(),
        result.facts().events().retained().get()
    );
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::EventLimitReached { event_limit }) if event_limit.get() == 1
    ));
    assert!(
        result
            .facts()
            .staging()
            .slots()
            .iter()
            .filter_map(BrowserStagingSlot::envelope)
            .all(|envelope| envelope.generated_at() <= result.terminal().at())
    );
    let network = result
        .facts()
        .staging()
        .slots()
        .iter()
        .find(|slot| slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::Network))
        .expect("network slot");
    assert_eq!(network.outcome().state(), StagingState::Unrequested);
}

#[tokio::test]
async fn source_only_event_limit_preserves_navigation_accounting_direct_and_managed() {
    let _browser = browser_lock().lock().await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let target = fixture.url("/event-flood").unwrap();
    let direct = timeout(
        Duration::from_secs(15),
        capture_attempt(
            &source_only_event_limit_spec(&target),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("source-only direct timeout")
    .unwrap();
    assert_source_only_event_limit(&direct);
    clean_shutdown(fixture).await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let target = fixture.url("/event-flood").unwrap();
    let managed = timeout(
        Duration::from_secs(15),
        capture_attempt_managed(
            &manager,
            &source_only_event_limit_spec(&target),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("source-only managed timeout")
    .unwrap();
    assert_source_only_event_limit(&managed);
    assert_eq!(
        managed.execution().unwrap().terminal().reason(),
        BrowserExecutionTerminalReason::ObservationLimitExceeded
    );
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn repeated_successful_attempts_remain_ready_after_prior_cancellation() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    for _ in 0..2 {
        let result = timeout(
            Duration::from_secs(30),
            capture_attempt(
                &spec(fixture.url("/shell").unwrap(), 10_000_000, 64, 64, None),
                &CancellationToken::new(),
            ),
        )
        .await
        .expect("successful attempt timeout")
        .unwrap();
        assert!(result.is_ready());
        assert!(matches!(
            result.terminal().kind(),
            BrowserTerminalKind::ControllerCompleted
        ));
        assert_eq!(result.facts().cleanup(), CleanupState::Complete);
    }
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn rendered_dom_truncation_preserves_ready_sibling_evidence() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let result = timeout(
        Duration::from_secs(30),
        capture_attempt(
            &spec(fixture.url("/shell").unwrap(), 10_000_000, 64, 64, Some(1)),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("byte-limited attempt timeout")
    .unwrap();
    assert!(result.is_ready());
    assert!(matches!(
        result.terminal().kind(),
        BrowserTerminalKind::ControllerCompleted
    ));
    let dom = result
        .facts()
        .staging()
        .slots()
        .iter()
        .find(|slot| {
            slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom)
        })
        .expect("rendered DOM slot");
    assert_eq!(dom.outcome().state(), StagingState::Truncated);
    assert_eq!(result.facts().cleanup(), CleanupState::Complete);
    clean_shutdown(fixture).await;
}

fn assert_fresh_isolation(result: &BrowserAdapterResult, expected: &[u8]) {
    let lifecycle = result.lifecycle().expect("live acquisition lifecycle");
    assert!(lifecycle.termination().is_some());
    assert_eq!(lifecycle.observed_through(), result.terminal().at());
    assert_eq!(
        lifecycle.admitted_events(),
        result.facts().events().admitted().get()
    );
    assert_eq!(
        lifecycle.retained_bytes(),
        result.facts().bytes().retained()
    );
    let dom = result
        .facts()
        .staging()
        .slots()
        .iter()
        .find(|slot| {
            slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom)
        })
        .and_then(|slot| slot.outcome().bytes())
        .expect("rendered DOM");
    assert!(
        dom.windows(expected.len()).any(|part| part == expected),
        "fresh context must not observe prior cookie or local/session storage state: {}",
        String::from_utf8_lossy(dom)
    );
    assert_eq!(result.facts().cleanup(), CleanupState::Complete);
}

#[tokio::test]
async fn sequential_fresh_contexts_do_not_leak_browser_state() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    for _ in 0..2 {
        let result = timeout(
            Duration::from_secs(30),
            capture_attempt(
                &spec(
                    fixture.url("/isolated-state").unwrap(),
                    10_000_000,
                    64,
                    64,
                    Some(100_000),
                ),
                &CancellationToken::new(),
            ),
        )
        .await
        .expect("isolated attempt timeout")
        .unwrap();
        assert_fresh_isolation(
            &result,
            b"<output id=\"isolation-result\">cookie-fresh|local-fresh|session-fresh</output>",
        );
    }
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn managed_captures_reuse_one_process_with_fresh_state_and_full_receipts() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let mut generation = None;
    for _ in 0..2 {
        let result = timeout(
            Duration::from_secs(30),
            capture_attempt_managed(
                &manager,
                &spec(
                    fixture.url("/isolated-state").unwrap(),
                    10_000_000,
                    64,
                    64,
                    Some(100_000),
                ),
                &CancellationToken::new(),
            ),
        )
        .await
        .expect("managed isolated attempt timeout")
        .unwrap();
        assert_fresh_isolation(
            &result,
            b"<output id=\"isolation-result\">cookie-fresh|local-fresh|session-fresh</output>",
        );
        let receipt = result.execution().expect("managed execution receipt");
        assert_eq!(
            receipt.terminal().reason(),
            BrowserExecutionTerminalReason::Completed
        );
        assert_eq!(
            receipt.terminal().cleanup().context(),
            BrowserContextCleanupDisposition::Completed
        );
        assert_eq!(
            receipt.terminal().cleanup().process(),
            BrowserProcessCleanupDisposition::WarmRetained
        );
        assert_eq!(
            receipt.accounting().phase(),
            BrowserExecutionAccountingPhase::Terminal
        );
        let current = receipt
            .terminal()
            .admission()
            .execution()
            .process()
            .generation();
        if let Some(previous) = generation {
            assert_eq!(current, previous, "warm process generation must be reused");
        }
        generation = Some(current);
        let encoded = serde_json::to_string(receipt).unwrap();
        for forbidden in ["authorization", "cookie", "localStorage", "http://"] {
            assert!(!encoded.contains(forbidden), "receipt leaked {forbidden}");
        }
    }
    let warm = manager.snapshot().await.unwrap();
    assert_eq!(warm.active_processes, 1);
    assert_eq!(warm.active_contexts, 0);
    assert_eq!(warm.active_tabs, 0);
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn managed_cancellation_and_deadline_release_capacity_with_terminal_receipts() {
    let _browser = browser_lock().lock().await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let cancellation = CancellationToken::new();
    let task = tokio::spawn({
        let manager = manager.clone();
        let cancellation = cancellation.clone();
        let capture_spec = spec(fixture.url("/endless").unwrap(), 10_000_000, 64, 64, None);
        async move { capture_attempt_managed(&manager, &capture_spec, &cancellation).await }
    });
    timeout(
        Duration::from_secs(10),
        fixture.barriers.endless_requested.wait(),
    )
    .await
    .expect("managed cancellation request timeout")
    .unwrap();
    cancellation.cancel();
    let cancelled = timeout(Duration::from_secs(15), task)
        .await
        .expect("managed cancellation timeout")
        .unwrap()
        .unwrap();
    assert!(matches!(
        cancelled.terminal().kind(),
        BrowserTerminalKind::CallerCancelled { .. }
    ));
    assert_eq!(
        cancelled.execution().unwrap().terminal().reason(),
        BrowserExecutionTerminalReason::CallerCancelled
    );
    assert_eq!(manager.snapshot().await.unwrap().active_contexts, 0);
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let deadline = timeout(
        Duration::from_secs(15),
        capture_attempt_managed(
            &manager,
            &spec(fixture.url("/endless").unwrap(), 2_000_000, 64, 64, None),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("managed deadline timeout")
    .unwrap();
    assert!(matches!(
        deadline.terminal().kind(),
        BrowserTerminalKind::DeadlineReached { .. }
    ));
    assert_eq!(
        deadline.execution().unwrap().terminal().reason(),
        BrowserExecutionTerminalReason::DeadlineExceeded
    );
    let released = manager.snapshot().await.unwrap();
    assert_eq!(released.active_contexts, 0);
    assert_eq!(released.active_tabs, 0);
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn managed_setup_collector_and_disconnect_terminals_keep_execution_receipts() {
    let _browser = browser_lock().lock().await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let invalid_overrides = BrowserEnvironmentOverrides {
        time_zone: Some(TimeZone::new("Invalid/Browser-Time-Zone").unwrap()),
        ..BrowserEnvironmentOverrides::default()
    };
    let setup_spec = spec_with_mode_and_overrides(
        &fixture.url("/shell").unwrap(),
        10_000_000,
        64,
        64,
        None,
        true,
        SettlementPolicy::Disabled,
        BrowserMode::Headless,
        invalid_overrides,
    );
    let setup_error = timeout(
        Duration::from_secs(20),
        capture_attempt_managed(&manager, &setup_spec, &CancellationToken::new()),
    )
    .await
    .expect("managed setup failure timeout")
    .expect_err("invalid provider setup unexpectedly succeeded");
    let setup_receipt = setup_error
        .execution_receipt()
        .expect("post-admission setup failure receipt");
    assert_eq!(
        setup_receipt.terminal().reason(),
        BrowserExecutionTerminalReason::ProviderFailure
    );
    assert_eq!(
        setup_receipt.accounting().phase(),
        BrowserExecutionAccountingPhase::Terminal
    );
    assert_eq!(
        setup_receipt.capture_id(),
        setup_spec.request().capture_id()
    );
    let setup_wire = serde_json::to_vec(setup_receipt).unwrap();
    assert_eq!(
        serde_json::from_slice::<BrowserExecutionReceipt>(&setup_wire).unwrap(),
        *setup_receipt
    );
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let collector_spec = spec_with_settlement(
        &fixture.url("/event-flood").unwrap(),
        10_000_000,
        1,
        1,
        None,
        true,
        SettlementPolicy::QuietPeriod(QuietPeriodPolicy::new(
            SettlementPolicyId::new("test.browser.managed-event-limit").unwrap(),
            QuietPeriod::try_from(100_000).unwrap(),
            ActivityCount::new(0),
        )),
    );
    let collector_task = tokio::spawn({
        let manager = manager.clone();
        async move {
            capture_attempt_managed(&manager, &collector_spec, &CancellationToken::new()).await
        }
    });
    timeout(
        Duration::from_secs(10),
        fixture.barriers.event_flood_requested.wait(),
    )
    .await
    .expect("managed collector barrier timeout")
    .unwrap();
    let collector_result = timeout(Duration::from_secs(15), collector_task)
        .await
        .expect("managed collector timeout")
        .unwrap()
        .unwrap();
    assert!(matches!(
        collector_result.terminal().kind(),
        BrowserTerminalKind::EventLimitReached
    ));
    assert_eq!(
        collector_result.execution().unwrap().terminal().reason(),
        BrowserExecutionTerminalReason::ObservationLimitExceeded
    );
    assert_eq!(collector_result.facts().events().admitted().get(), 1);
    let lifecycle = collector_result
        .lifecycle()
        .expect("managed event-limit lifecycle");
    assert_eq!(lifecycle.admitted_events(), 1);
    assert_eq!(
        lifecycle.retained_events(),
        collector_result.facts().events().retained().get()
    );
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::EventLimitReached { event_limit }) if event_limit.get() == 1
    ));
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;

    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let disconnect_spec = spec(fixture.url("/partial").unwrap(), 2_000_000, 64, 64, None);
    let disconnect_task = tokio::spawn({
        let manager = manager.clone();
        async move {
            capture_attempt_managed(&manager, &disconnect_spec, &CancellationToken::new()).await
        }
    });
    timeout(
        Duration::from_secs(10),
        fixture.barriers.partial_requested.wait(),
    )
    .await
    .expect("managed disconnect barrier timeout")
    .unwrap();
    let disconnected = timeout(Duration::from_secs(15), disconnect_task)
        .await
        .expect("managed disconnect timeout")
        .unwrap()
        .unwrap();
    assert_main_resource_failed(&disconnected);
    let expected_reason = match disconnected.terminal().kind() {
        BrowserTerminalKind::ControllerCompleted => BrowserExecutionTerminalReason::Completed,
        BrowserTerminalKind::ProviderStopped {
            reason: BrowserProviderStop::BrowserDisconnected,
        } => BrowserExecutionTerminalReason::ProviderDisconnected,
        BrowserTerminalKind::ProviderStopped { .. } => {
            BrowserExecutionTerminalReason::ProviderFailure
        }
        BrowserTerminalKind::DeadlineReached { .. } => {
            BrowserExecutionTerminalReason::DeadlineExceeded
        }
        terminal => panic!("unexpected managed disconnect terminal: {terminal:?}"),
    };
    let execution = disconnected.execution().unwrap();
    assert_eq!(execution.terminal().reason(), expected_reason);
    assert_eq!(
        execution.accounting().phase(),
        BrowserExecutionAccountingPhase::Terminal
    );
    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn concurrent_fresh_contexts_do_not_share_browser_state() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let target = fixture.url("/isolated-state").unwrap();
    let first_spec = spec(target.clone(), 10_000_000, 64, 64, Some(100_000));
    let second_spec = spec(target, 10_000_000, 64, 64, Some(100_000));
    let first_cancel = CancellationToken::new();
    let second_cancel = CancellationToken::new();
    let (first, second) = Box::pin(timeout(Duration::from_secs(30), async {
        tokio::join!(
            capture_attempt(&first_spec, &first_cancel),
            capture_attempt(&second_spec, &second_cancel)
        )
    }))
    .await
    .expect("concurrent isolated attempts timed out");
    let expected =
        b"<output id=\"isolation-result\">cookie-fresh|local-fresh|session-fresh</output>";
    assert_fresh_isolation(&first.unwrap(), expected);
    assert_fresh_isolation(&second.unwrap(), expected);
    clean_shutdown(fixture).await;
}

fn parity_overrides() -> BrowserEnvironmentOverrides {
    BrowserEnvironmentOverrides {
        viewport: Some(Viewport::new(
            NonZeroU32::new(1024).unwrap(),
            NonZeroU32::new(768).unwrap(),
        )),
        device_scale_factor: Some(DeviceScaleFactor::new("1.25").unwrap()),
        user_agent: Some(UserAgent::new("Yosoi-CAS-331-Parity/1.0").unwrap()),
        locale: Some(Locale::new("en-US").unwrap()),
        time_zone: Some(TimeZone::new("UTC").unwrap()),
        color_scheme: Some(ColorScheme::Dark),
        reduced_motion: Some(ReducedMotion::Reduce),
    }
}

fn assert_rendering_parity(headful: &BrowserRenderingContext, headless: &BrowserRenderingContext) {
    assert_eq!(headful.viewport(), headless.viewport());
    assert_eq!(headful.user_agent(), headless.user_agent());
    assert_eq!(headful.locale(), headless.locale());
    assert_eq!(headful.time_zone(), headless.time_zone());
    assert_eq!(headful.color_scheme(), headless.color_scheme());
    assert_eq!(headful.reduced_motion(), headless.reduced_motion());

    let headful_dpr = headful
        .device_scale_factor()
        .as_known()
        .expect("headful DPR")
        .as_str()
        .parse::<f64>()
        .expect("numeric headful DPR");
    let headless_dpr = headless
        .device_scale_factor()
        .as_known()
        .expect("headless DPR")
        .as_str()
        .parse::<f64>()
        .expect("numeric headless DPR");
    let scale = headful_dpr.abs().max(headless_dpr.abs()).max(1.0);
    assert!(
        (headful_dpr - headless_dpr).abs() <= f64::from(f32::EPSILON) * scale,
        "headful DPR {headful_dpr} differs materially from headless DPR {headless_dpr}"
    );
}

#[tokio::test]
async fn headful_uses_shared_adapter_semantics_or_reports_missing_display() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let overrides = parity_overrides();
    let result = timeout(
        Duration::from_secs(30),
        capture_attempt(
            &spec_with_mode_and_overrides(
                &fixture.url("/shell").unwrap(),
                10_000_000,
                64,
                64,
                Some(100_000),
                true,
                SettlementPolicy::Disabled,
                BrowserMode::Headful,
                overrides.clone(),
            ),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("headful attempt timeout");
    match result {
        Ok(headful) => {
            let headless = timeout(
                Duration::from_secs(30),
                capture_attempt(
                    &spec_with_mode_and_overrides(
                        &fixture.url("/shell").unwrap(),
                        10_000_000,
                        64,
                        64,
                        Some(100_000),
                        true,
                        SettlementPolicy::Disabled,
                        BrowserMode::Headless,
                        overrides,
                    ),
                    &CancellationToken::new(),
                ),
            )
            .await
            .expect("headless parity attempt timeout")
            .unwrap();
            for (result, mode) in [
                (&headful, BrowserMode::Headful),
                (&headless, BrowserMode::Headless),
            ] {
                assert!(result.is_ready());
                assert_eq!(result.facts().environment().mode().as_known(), Some(&mode));
                assert_eq!(result.facts().cleanup(), CleanupState::Complete);
                assert_eq!(
                    result.terminal().kind(),
                    &BrowserTerminalKind::ControllerCompleted
                );
            }
            let states = |result: &BrowserAdapterResult| {
                result
                    .facts()
                    .staging()
                    .slots()
                    .iter()
                    .map(|slot| (slot.family(), slot.outcome().state()))
                    .collect::<Vec<_>>()
            };
            assert_eq!(states(&headful), states(&headless));
            assert_rendering_parity(
                headful.facts().environment().rendering(),
                headless.facts().environment().rendering(),
            );
        }
        Err(VoidCrawlAdapterError::HeadfulDisplayUnavailable) => {
            assert_eq!(fixture.requests().await, Vec::<String>::new());
        }
        Err(error) => panic!("unexpected headful result: {error:?}"),
    }
    clean_shutdown(fixture).await;
}

#[tokio::test]
async fn post_navigation_activity_resets_then_satisfies_quiet_settlement() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let policy = QuietPeriodPolicy::new(
        SettlementPolicyId::new("test.browser.quiet").unwrap(),
        QuietPeriod::try_from(200_000).unwrap(),
        ActivityCount::new(0),
    );
    let result = timeout(
        Duration::from_secs(30),
        capture_attempt(
            &spec_with_settlement(
                &fixture.url("/shell").unwrap(),
                10_000_000,
                256,
                64,
                None,
                true,
                SettlementPolicy::QuietPeriod(policy.clone()),
            ),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("quiet-settlement attempt timeout")
    .unwrap();
    assert!(
        result.is_ready(),
        "quiet result stopped at {:?}",
        result.terminal()
    );
    assert!(matches!(
        result.terminal().kind(),
        BrowserTerminalKind::QuietSettled
    ));
    let evidence = result.facts().settlement().expect("quiet evidence");
    assert_eq!(evidence.policy(), policy.id());
    assert!(evidence.satisfied_at() > evidence.quiet_since());
    assert_eq!(evidence.relevant_in_flight(), ActivityCount::new(0));
    assert_eq!(result.facts().cleanup(), CleanupState::Complete);
    clean_shutdown(fixture).await;
}

struct TestProfileRoot {
    path: PathBuf,
}

impl TestProfileRoot {
    fn new() -> Self {
        static NEXT_ROOT: AtomicU64 = AtomicU64::new(1);
        let sequence = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let path =
            env::temp_dir().join(format!("yosoi-cas354-profile-{}-{sequence}", process::id()));
        fs::create_dir(&path).expect("create isolated managed-profile registry root");
        Self { path }
    }

    fn registry(&self) -> ProfileRegistry {
        ProfileRegistry::new(self.path.clone())
    }
}

impl Drop for TestProfileRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.path);
    }
}

struct ProfileStateFixture {
    address: SocketAddr,
    shutdown: CancellationToken,
    task: JoinHandle<io::Result<()>>,
}

impl ProfileStateFixture {
    async fn start() -> io::Result<Self> {
        let listener = TcpListener::bind(SocketAddr::from((Ipv4Addr::LOCALHOST, 0))).await?;
        let address = listener.local_addr()?;
        let shutdown = CancellationToken::new();
        let task_shutdown = shutdown.clone();
        let task = tokio::spawn(async move {
            loop {
                tokio::select! {
                    () = task_shutdown.cancelled() => return Ok(()),
                    accepted = listener.accept() => {
                        let (stream, _) = accepted?;
                        let _ = serve_profile_state_request(stream).await;
                    }
                }
            }
        });
        Ok(Self {
            address,
            shutdown,
            task,
        })
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}:{}{path}", self.address.ip(), self.address.port())
    }

    async fn stop(self) {
        self.shutdown.cancel();
        self.task
            .await
            .expect("profile-state fixture task")
            .expect("profile-state fixture shutdown");
    }
}

async fn serve_profile_state_request(stream: TcpStream) -> io::Result<()> {
    let mut reader = BufReader::new(stream);
    let mut request_line = String::new();
    reader.read_line(&mut request_line).await?;
    let mut header_line = String::new();
    loop {
        header_line.clear();
        if reader.read_line(&mut header_line).await? == 0 || header_line == "\r\n" {
            break;
        }
    }

    let path = request_line
        .split_whitespace()
        .nth(1)
        .and_then(|target| target.split('?').next())
        .unwrap_or("/");
    let (status, body): (&str, &[u8]) = match path {
        "/write-managed" => (
            "200 OK",
            br##"<!doctype html><output id="state"></output><script>
const key = "yosoi-cas354-state";
const cookie = document.cookie.includes(key + "=managed") ? "managed" : "fresh";
const local = localStorage.getItem(key) || "fresh";
document.cookie = key + "=managed; Path=/; Max-Age=3600; SameSite=Lax";
localStorage.setItem(key, "managed");
document.querySelector("#state").textContent = cookie + "|" + local;
</script>"##,
        ),
        "/write-ephemeral" => (
            "200 OK",
            br##"<!doctype html><output id="state"></output><script>
const key = "yosoi-cas354-state";
const cookie = document.cookie.includes(key + "=managed") ? "managed" : "fresh";
const local = localStorage.getItem(key) || "fresh";
document.cookie = key + "=ephemeral; Path=/; Max-Age=3600; SameSite=Lax";
localStorage.setItem(key, "ephemeral");
document.querySelector("#state").textContent = cookie + "|" + local;
</script>"##,
        ),
        "/observe" => (
            "200 OK",
            br##"<!doctype html><output id="state"></output><script>
const key = "yosoi-cas354-state";
const cookie = document.cookie.includes(key + "=managed") ? "managed" :
  document.cookie.includes(key + "=ephemeral") ? "ephemeral" : "missing";
const local = localStorage.getItem(key) || "missing";
document.querySelector("#state").textContent = cookie + "|" + local;
</script>"##,
        ),
        _ => (
            "404 Not Found",
            b"<!doctype html><title>not found</title>".as_slice(),
        ),
    };
    let response_head = format!(
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let mut stream = reader.into_inner();
    stream.write_all(response_head.as_bytes()).await?;
    stream.write_all(body).await?;
    Ok(())
}

fn managed_profile_manager(
    registry: ProfileRegistry,
    profile_id: BrowserProfileId,
    generations: Arc<BrowserProfileLeaseGenerationRegistry>,
) -> BrowserExecutionManager {
    let lifecycle = ProfileLifecycleStore::new(registry.root().join(".yosoi/profile-lifecycle"))
        .expect("managed profile lifecycle store");
    if lifecycle
        .record(&profile_id)
        .expect("managed profile lifecycle read")
        .is_none()
    {
        lifecycle
            .stage_profile(&profile_id, SystemTime::now().into())
            .expect("seed managed profile staged lifecycle state");
        lifecycle
            .transition(
                &profile_id,
                SystemTime::now().into(),
                BrowserProfileLifecycleEvent::ProvisionSucceeded,
            )
            .expect("seed managed profile Available lifecycle state");
    }
    BrowserExecutionManager::new_managed_profile(
        execution_limits(),
        BrowserExecutionManagerConfig::default(),
        registry,
        profile_id,
        lifecycle,
        generations,
        Duration::from_secs(300),
    )
    .expect("managed profile manager configuration")
}

async fn capture_managed_url(manager: &BrowserExecutionManager, url: &str) -> BrowserAdapterResult {
    let capture_spec = spec(url.to_owned(), 30_000_000, 64, 64, Some(100_000));
    let cancellation = CancellationToken::new();
    timeout(
        Duration::from_secs(45),
        capture_attempt_managed(manager, &capture_spec, &cancellation),
    )
    .await
    .expect("managed profile capture timeout")
    .expect("managed profile capture")
}

fn assert_rendered_dom_contains(result: &BrowserAdapterResult, expected: &[u8]) {
    let dom = result
        .facts()
        .staging()
        .slots()
        .iter()
        .find(|slot| {
            slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom)
        })
        .and_then(|slot| slot.outcome().bytes())
        .expect("rendered DOM bytes");
    assert!(
        dom.windows(expected.len()).any(|part| part == expected),
        "rendered DOM did not contain {:?}: {}",
        String::from_utf8_lossy(expected),
        String::from_utf8_lossy(dom)
    );
}

#[tokio::test]
async fn managed_profile_state_persists_and_ephemeral_execution_cannot_mutate_it() {
    let _browser = browser_lock().lock().await;
    let profile_root = TestProfileRoot::new();
    let registry = profile_root.registry();
    registry
        .create_profile("persistent-state", None, Vec::new())
        .unwrap();
    let profile_id = BrowserProfileId::new("persistent-state").unwrap();
    let generations = Arc::new(BrowserProfileLeaseGenerationRegistry::default());
    let fixture = ProfileStateFixture::start().await.unwrap();

    let first_managed = managed_profile_manager(
        registry.clone(),
        profile_id.clone(),
        Arc::clone(&generations),
    );
    let initialized = Box::pin(capture_managed_url(
        &first_managed,
        &fixture.url("/write-managed"),
    ))
    .await;
    assert!(initialized.is_ready());
    assert_rendered_dom_contains(&initialized, b"fresh|fresh");
    first_managed.shutdown().await.unwrap();
    let first_receipt = first_managed
        .managed_profile_terminal_receipt()
        .expect("first managed profile terminal receipt");
    assert_eq!(
        first_receipt.outcome(),
        BrowserProfileLeaseTerminalOutcome::Released
    );

    let ephemeral =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let ephemeral_state = Box::pin(capture_managed_url(
        &ephemeral,
        &fixture.url("/write-ephemeral"),
    ))
    .await;
    assert!(ephemeral_state.is_ready());
    assert_rendered_dom_contains(&ephemeral_state, b"fresh|fresh");
    ephemeral.shutdown().await.unwrap();

    let reopened = managed_profile_manager(registry, profile_id, generations);
    let persisted = Box::pin(capture_managed_url(&reopened, &fixture.url("/observe"))).await;
    assert!(persisted.is_ready());
    assert_rendered_dom_contains(&persisted, b"managed|managed");
    reopened.shutdown().await.unwrap();
    assert_eq!(
        reopened
            .managed_profile_terminal_receipt()
            .expect("reopened managed profile terminal receipt")
            .outcome(),
        BrowserProfileLeaseTerminalOutcome::Released
    );

    fixture.stop().await;
}

fn override_set_a() -> BrowserEnvironmentOverrides {
    BrowserEnvironmentOverrides {
        viewport: Some(Viewport::new(
            NonZeroU32::new(1111).unwrap(),
            NonZeroU32::new(777).unwrap(),
        )),
        device_scale_factor: Some(DeviceScaleFactor::new("1.75").unwrap()),
        user_agent: Some(UserAgent::new("Yosoi-CAS-354-Override-A/1.0").unwrap()),
        locale: Some(Locale::new("fr-CA").unwrap()),
        time_zone: Some(TimeZone::new("Pacific/Honolulu").unwrap()),
        color_scheme: Some(ColorScheme::Dark),
        reduced_motion: Some(ReducedMotion::Reduce),
    }
}

fn override_set_b() -> BrowserEnvironmentOverrides {
    BrowserEnvironmentOverrides {
        viewport: Some(Viewport::new(
            NonZeroU32::new(913).unwrap(),
            NonZeroU32::new(617).unwrap(),
        )),
        device_scale_factor: Some(DeviceScaleFactor::new("1.5").unwrap()),
        user_agent: Some(UserAgent::new("Yosoi-CAS-354-Override-B/1.0").unwrap()),
        locale: Some(Locale::new("de-DE").unwrap()),
        time_zone: Some(TimeZone::new("America/New_York").unwrap()),
        color_scheme: Some(ColorScheme::Light),
        reduced_motion: Some(ReducedMotion::NoPreference),
    }
}

fn assert_rendering_matches_overrides(
    actual: &BrowserRenderingContext,
    expected: &BrowserEnvironmentOverrides,
) {
    assert_eq!(actual.viewport().as_known(), expected.viewport.as_ref());
    assert_eq!(
        actual.device_scale_factor().as_known(),
        expected.device_scale_factor.as_ref()
    );
    assert_eq!(actual.user_agent().as_known(), expected.user_agent.as_ref());
    assert_eq!(actual.locale().as_known(), expected.locale.as_ref());
    assert_eq!(actual.time_zone().as_known(), expected.time_zone.as_ref());
    assert_eq!(
        actual.color_scheme().as_known(),
        expected.color_scheme.as_ref()
    );
    assert_eq!(
        actual.reduced_motion().as_known(),
        expected.reduced_motion.as_ref()
    );
}

const fn execution_process_generation(result: &BrowserAdapterResult) -> BrowserProcessGeneration {
    result
        .execution()
        .expect("managed execution receipt")
        .terminal()
        .admission()
        .execution()
        .process()
        .generation()
}

async fn capture_managed_with_overrides(
    manager: &BrowserExecutionManager,
    target: &str,
    overrides: BrowserEnvironmentOverrides,
) -> Result<BrowserAdapterResult, VoidCrawlAdapterError> {
    let capture_spec = spec_with_mode_and_overrides(
        target,
        30_000_000,
        64,
        64,
        Some(100_000),
        true,
        SettlementPolicy::Disabled,
        BrowserMode::Headless,
        overrides,
    );
    let cancellation = CancellationToken::new();
    capture_attempt_managed(manager, &capture_spec, &cancellation).await
}

#[tokio::test]
async fn reused_ephemeral_process_resets_overrides_between_executions() {
    let _browser = browser_lock().lock().await;
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let manager =
        BrowserExecutionManager::new(execution_limits(), BrowserExecutionManagerConfig::default());
    let target = fixture.url("/shell").unwrap();

    let baseline = Box::pin(timeout(
        Duration::from_secs(45),
        capture_managed_with_overrides(&manager, &target, BrowserEnvironmentOverrides::default()),
    ))
    .await
    .expect("baseline capture timeout")
    .unwrap();
    let overrides_a = override_set_a();
    let overridden_a = Box::pin(timeout(
        Duration::from_secs(45),
        capture_managed_with_overrides(&manager, &target, overrides_a.clone()),
    ))
    .await
    .expect("override A capture timeout")
    .unwrap();
    let defaults_after_a = Box::pin(timeout(
        Duration::from_secs(45),
        capture_managed_with_overrides(&manager, &target, BrowserEnvironmentOverrides::default()),
    ))
    .await
    .expect("default-after-A capture timeout")
    .unwrap();
    let overrides_b = override_set_b();
    let overridden_b = Box::pin(timeout(
        Duration::from_secs(45),
        capture_managed_with_overrides(&manager, &target, overrides_b.clone()),
    ))
    .await
    .expect("override B capture timeout")
    .unwrap();

    for result in [&baseline, &overridden_a, &defaults_after_a, &overridden_b] {
        assert!(result.is_ready());
        assert_eq!(result.facts().cleanup(), CleanupState::Complete);
        assert_eq!(
            result
                .execution()
                .expect("reused-process execution receipt")
                .terminal()
                .cleanup()
                .process(),
            BrowserProcessCleanupDisposition::WarmRetained
        );
        assert_eq!(
            execution_process_generation(result),
            execution_process_generation(&baseline)
        );
    }
    assert_eq!(
        baseline.facts().environment().rendering(),
        defaults_after_a.facts().environment().rendering(),
        "default execution retained environment overrides from the prior execution"
    );
    assert_rendering_matches_overrides(
        overridden_a.facts().environment().rendering(),
        &overrides_a,
    );
    assert_rendering_matches_overrides(
        overridden_b.facts().environment().rendering(),
        &overrides_b,
    );

    manager.shutdown().await.unwrap();
    clean_shutdown(fixture).await;
}

#[test]
fn managed_profile_manager_rejects_multiple_context_tenancies() {
    let profile_id = BrowserProfileId::new("single-context").unwrap();
    let generations = Arc::new(BrowserProfileLeaseGenerationRegistry::default());
    for (contexts_total, contexts_per_process) in [(2, 1), (2, 2)] {
        let profile_root = tempfile::tempdir().unwrap();
        let lifecycle_root = tempfile::tempdir().unwrap();
        let error = BrowserExecutionManager::new_managed_profile(
            execution_limits_with_contexts(contexts_total, contexts_per_process),
            BrowserExecutionManagerConfig::default(),
            ProfileRegistry::new(profile_root.path().to_path_buf()),
            profile_id.clone(),
            ProfileLifecycleStore::new(lifecycle_root.path().to_path_buf()).unwrap(),
            Arc::clone(&generations),
            Duration::from_secs(60),
        )
        .unwrap_err();
        assert_eq!(
            error,
            BrowserExecutionManagerError::InvalidManagedProfileLimits
        );
    }
}
