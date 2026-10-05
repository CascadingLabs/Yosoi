// Assertions fail the harness; Result is used for fixture/setup failures.
#![allow(clippy::panic_in_result_fn)]
#![allow(
    clippy::absolute_paths,
    reason = "tests exercise the documented ys::policy namespace"
)]

use std::{error::Error, io, num::NonZeroU32};

use yosoi_engine::prelude as ys;
use yosoi_engine::{
    AcquisitionCapabilityProfile, ActivityId, ArtifactCapability, ArtifactMultiplicity,
    BrowserArtifactIdentityPlan, BrowserCapabilityStatus, BrowserContextRef,
    BrowserEnvironmentOverrides, BrowserEvidenceAdmissionPolicy, BrowserFamilyCapabilities,
    BrowserHeaderAdmission, BrowserInstrumentationMode, BrowserMainBodyAdmission,
    BrowserNavigationCapabilityProfile, BrowserNavigationPolicy, BrowserOutputSchemas,
    BrowserResolutionInputs, BrowserUrlAdmission, CaptureId, CertifiedBrowserCapabilities,
    NavigationCompletionPolicy, NavigationContext, OperationId, PolicyDecision,
    PolicyResolutionContext, PolicyResolutionError, PolicyResolver, PreparedAttempt,
    PreparedPageRequest, Producer, ProducerId, ProducerVersion, ReasonCode, ResolvedPolicyAttempt,
    ResolvedPolicySpec, Schema, SchemaId, SchemaVersion, SettlementPolicy,
    WebArtifactCapabilitySet, WebProviderCapabilityProfile,
};
use yosoi_web_capture::{
    ActivityCount, ArtifactRequest, BrowserCaptureSpecError, BrowserMode, QuietPeriod,
    QuietPeriodPolicy, ResolvedBrowserCaptureSpec, SettlementPolicyId,
};

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn test_producer() -> TestResult<Producer> {
    Ok(Producer::new(
        ProducerId::new("test.browser")?,
        ProducerVersion::new("1")?,
    ))
}

fn test_operation() -> TestResult<OperationId> {
    Ok(OperationId::new("test.policy-resolution")?)
}

fn test_schema(name: &str) -> TestResult<Schema> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

fn prepared(policy: &ys::Policy, target: &str) -> TestResult<PreparedPageRequest> {
    Ok(ys::request::new(target).bind(policy).prepare()?)
}

fn first_attempt(prepared: &PreparedPageRequest) -> TestResult<&PreparedAttempt> {
    prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("prepared browser request has no attempt").into())
}

fn browser_capabilities(
    producer: &Producer,
    mode: BrowserMode,
    instrumentation: BrowserInstrumentationMode,
) -> TestResult<CertifiedBrowserCapabilities> {
    let supported = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let unsupported_storage = ArtifactCapability::Unsupported {
        reason: ReasonCode::new("test.unavailable")?,
    };
    let profile = WebProviderCapabilityProfile::new(
        producer.clone(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            mode,
        )),
        WebArtifactCapabilitySet::new(
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            unsupported_storage,
            supported.clone(),
            supported.clone(),
            supported,
        ),
    )?;
    let disabled = BrowserCapabilityStatus::Disabled {
        reason: ReasonCode::new("test.instrumentation-disabled")?,
    };
    let network_status = if matches!(
        instrumentation,
        BrowserInstrumentationMode::Normal
            | BrowserInstrumentationMode::MinimalNetworkEscalated
            | BrowserInstrumentationMode::MinimalBothEscalated
    ) {
        BrowserCapabilityStatus::Supported
    } else {
        disabled.clone()
    };
    let runtime_status = if matches!(
        instrumentation,
        BrowserInstrumentationMode::Normal
            | BrowserInstrumentationMode::MinimalRuntimeEscalated
            | BrowserInstrumentationMode::MinimalBothEscalated
    ) {
        BrowserCapabilityStatus::Supported
    } else {
        disabled
    };
    let unsupported_status = BrowserCapabilityStatus::Unsupported {
        reason: ReasonCode::new("test.unavailable")?,
    };
    Ok(CertifiedBrowserCapabilities::new(
        profile,
        producer,
        mode,
        instrumentation,
        BrowserFamilyCapabilities::new(
            network_status.clone(),
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            network_status,
            BrowserCapabilityStatus::Supported,
            unsupported_status,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            runtime_status,
        ),
    )?)
}

fn browser_context(
    capture_id: CaptureId,
    capability_mode: BrowserMode,
    completion: NavigationCompletionPolicy,
    instrumentation: BrowserInstrumentationMode,
    settlement: SettlementPolicy,
) -> TestResult<PolicyResolutionContext> {
    let producer = test_producer()?;
    Ok(PolicyResolutionContext::browser(BrowserResolutionInputs {
        navigation_context: NavigationContext::FreshTopLevel,
        navigation_policy: BrowserNavigationPolicy::new(completion),
        environment_overrides: BrowserEnvironmentOverrides::default(),
        capabilities: browser_capabilities(&producer, capability_mode, instrumentation)?,
        producer,
        operation: test_operation()?,
        output_schemas: BrowserOutputSchemas::new(
            Some(test_schema("test.policy.browser-source")?),
            Some(test_schema("test.policy.browser-source-representation")?),
            Some(test_schema("test.policy.browser-decoded-source")?),
            Some(test_schema("test.policy.browser-dom")?),
            Some(test_schema("test.policy.browser-ax")?),
            Some(test_schema("test.policy.browser-network")?),
            None,
            None,
            None,
            None,
            None,
        ),
        identity_plan: BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        admission: BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::Omit,
        ),
        settlement,
    }))
}

fn browser_spec(attempt: &ResolvedPolicyAttempt) -> TestResult<&ResolvedBrowserCaptureSpec> {
    match attempt.spec() {
        ResolvedPolicySpec::Browser(spec) => Ok(spec),
        ResolvedPolicySpec::DirectHttp { .. } => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "browser resolved to Direct HTTP",
        )
        .into()),
    }
}

#[test]
fn current_and_exact_browser_documents_map_for_headless_and_headful() -> TestResult {
    for mode in [BrowserMode::Headless, BrowserMode::Headful] {
        let mut current_policy = ys::Policy::default();
        current_policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(mode)];
        let current_prepared = prepared(&current_policy, "https://example.test/current")?;
        let current_attempt = first_attempt(&current_prepared)?;
        let resolved_current = PolicyResolver::resolve(
            &current_prepared,
            current_attempt,
            browser_context(
                current_attempt.capture_id(),
                mode,
                NavigationCompletionPolicy::ControllerCompleted,
                BrowserInstrumentationMode::Normal,
                SettlementPolicy::Disabled,
            )?,
        )?;
        assert_eq!(
            resolved_current.applied_policy().identity(),
            current_prepared.effective_policy_identity()
        );
        assert!(
            resolved_current
                .applied_policy()
                .decisions()
                .iter()
                .any(|decision| matches!(
                    decision,
                    PolicyDecision::DocumentSelection {
                        selection: ys::policy::DocumentSelectionKind::Current
                    }
                ))
        );
        let current_spec = browser_spec(&resolved_current)?;
        assert_eq!(current_spec.environment().mode(), mode);
        assert_eq!(current_spec.artifacts().source(), ArtifactRequest::Required);
        assert_eq!(
            current_spec.artifacts().rendered_dom(),
            ArtifactRequest::NotRequested
        );
        assert_eq!(
            current_spec.artifacts().accessibility_tree(),
            ArtifactRequest::NotRequested
        );
        assert_eq!(
            current_spec.artifacts().network(),
            ArtifactRequest::NotRequested
        );

        let mut exact_policy = ys::Policy::default();
        exact_policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(mode).documents([
            ys::policy::DocumentRequest::ResponseDocument,
            ys::policy::DocumentRequest::RenderedDom,
            ys::policy::DocumentRequest::AccessibilityTree,
            ys::policy::DocumentRequest::NetworkTree,
        ])];
        let exact_prepared = prepared(&exact_policy, "https://example.test/exact")?;
        let exact_attempt = first_attempt(&exact_prepared)?;
        let resolved_exact = PolicyResolver::resolve(
            &exact_prepared,
            exact_attempt,
            browser_context(
                exact_attempt.capture_id(),
                mode,
                NavigationCompletionPolicy::ControllerCompleted,
                BrowserInstrumentationMode::Normal,
                SettlementPolicy::Disabled,
            )?,
        )?;
        assert_eq!(
            resolved_exact.applied_policy().identity(),
            exact_prepared.effective_policy_identity()
        );
        assert!(
            resolved_exact
                .applied_policy()
                .decisions()
                .iter()
                .any(|decision| matches!(
                    decision,
                    PolicyDecision::DocumentSelection {
                        selection: ys::policy::DocumentSelectionKind::Exact
                    }
                ))
        );
        for document in exact_attempt.documents() {
            assert!(
                resolved_exact
                    .applied_policy()
                    .decisions()
                    .iter()
                    .any(|decision| matches!(
                        decision,
                        PolicyDecision::DocumentRequested { document: requested }
                            if requested == document
                    ))
            );
        }
        let exact_spec = browser_spec(&resolved_exact)?;
        assert_eq!(exact_spec.environment().mode(), mode);
        assert_eq!(exact_spec.artifacts().source(), ArtifactRequest::Required);
        assert_eq!(
            exact_spec.artifacts().rendered_dom(),
            ArtifactRequest::Required
        );
        assert_eq!(
            exact_spec.artifacts().accessibility_tree(),
            ArtifactRequest::Required
        );
        assert_eq!(
            exact_spec.artifacts().network(),
            ArtifactRequest::NotRequested
        );
    }
    Ok(())
}

#[test]
fn browser_mode_must_match_the_caller_supplied_certification() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(BrowserMode::Headful)];
    let prepared = prepared(&policy, "https://example.test/headful")?;
    let attempt = first_attempt(&prepared)?;
    let result = PolicyResolver::resolve(
        &prepared,
        attempt,
        browser_context(
            attempt.capture_id(),
            BrowserMode::Headless,
            NavigationCompletionPolicy::ControllerCompleted,
            BrowserInstrumentationMode::Normal,
            SettlementPolicy::Disabled,
        )?,
    );
    assert!(matches!(
        result,
        Err(PolicyResolutionError::BrowserSpec(
            BrowserCaptureSpecError::ModeMismatch
        ))
    ));
    Ok(())
}

#[test]
fn shaped_network_tree_does_not_collect_unprojectable_network_payloads() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::Browser(BrowserMode::Headless)
            .documents([ys::policy::DocumentRequest::NetworkTree]),
    ];
    let prepared = prepared(&policy, "https://example.test/no-network")?;
    let attempt = first_attempt(&prepared)?;
    let resolved = PolicyResolver::resolve(
        &prepared,
        attempt,
        browser_context(
            attempt.capture_id(),
            BrowserMode::Headless,
            NavigationCompletionPolicy::ControllerCompleted,
            BrowserInstrumentationMode::Minimal,
            SettlementPolicy::Disabled,
        )?,
    )?;
    let spec = browser_spec(&resolved)?;
    assert_eq!(spec.artifacts().network(), ArtifactRequest::NotRequested);
    assert!(
        resolved
            .applied_policy()
            .decisions()
            .contains(&PolicyDecision::DocumentRequested {
                document: ys::policy::DocumentRequest::NetworkTree,
            })
    );
    Ok(())
}

#[test]
fn browser_resolution_rejects_unsupported_navigation_completion() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(BrowserMode::Headless)];
    let prepared = prepared(&policy, "https://example.test/unsupported-completion")?;
    let attempt = first_attempt(&prepared)?;
    let result = PolicyResolver::resolve(
        &prepared,
        attempt,
        browser_context(
            attempt.capture_id(),
            BrowserMode::Headless,
            NavigationCompletionPolicy::LoadEvent,
            BrowserInstrumentationMode::Normal,
            SettlementPolicy::Disabled,
        )?,
    );
    assert!(matches!(
        result,
        Err(PolicyResolutionError::UnsupportedBrowserCompletion {
            completion: NavigationCompletionPolicy::LoadEvent
        })
    ));
    Ok(())
}

#[test]
fn quiet_period_requires_network_capability_for_minimal_instrumentation() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::Browser(BrowserMode::Headless)
            .documents([ys::policy::DocumentRequest::RenderedDom]),
    ];
    let prepared = prepared(&policy, "https://example.test/minimal-quiet")?;
    let attempt = first_attempt(&prepared)?;
    let settlement = SettlementPolicy::QuietPeriod(QuietPeriodPolicy::new(
        SettlementPolicyId::new("test.quiet")?,
        QuietPeriod::try_from(10_u64)?,
        ActivityCount::new(0),
    ));
    let result = PolicyResolver::resolve(
        &prepared,
        attempt,
        browser_context(
            attempt.capture_id(),
            BrowserMode::Headless,
            NavigationCompletionPolicy::ControllerCompleted,
            BrowserInstrumentationMode::Minimal,
            settlement,
        )?,
    );
    assert!(matches!(
        result,
        Err(PolicyResolutionError::BrowserInstrumentationMismatch {
            instrumentation: BrowserInstrumentationMode::Minimal
        })
    ));
    Ok(())
}

#[test]
fn browser_resolution_rejects_an_existing_context_the_adapter_cannot_resolve() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(BrowserMode::Headless)];
    let prepared = prepared(&policy, "https://example.test/existing-context")?;
    let attempt = first_attempt(&prepared)?;
    let PolicyResolutionContext::Browser(mut inputs) = browser_context(
        attempt.capture_id(),
        BrowserMode::Headless,
        NavigationCompletionPolicy::ControllerCompleted,
        BrowserInstrumentationMode::Normal,
        SettlementPolicy::Disabled,
    )?
    else {
        return Err(io::Error::other("browser helper returned a Direct HTTP context").into());
    };
    inputs.navigation_context = NavigationContext::TopLevel(BrowserContextRef::new(
        ActivityId::random(),
        NonZeroU32::MIN,
    ));

    let result =
        PolicyResolver::resolve(&prepared, attempt, PolicyResolutionContext::Browser(inputs));
    assert!(matches!(
        result,
        Err(PolicyResolutionError::BrowserSpec(
            BrowserCaptureSpecError::ExistingBrowserContextUnsupported
        ))
    ));
    Ok(())
}
