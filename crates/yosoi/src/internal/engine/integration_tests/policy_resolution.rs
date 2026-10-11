// Assertions fail the harness; Result is used for fixture/setup failures.
#![allow(clippy::panic_in_result_fn)]
#![allow(
    clippy::absolute_paths,
    reason = "tests exercise the documented ys::policy namespace"
)]

use std::{error::Error, io, num::NonZeroU32};

use crate::internal::engine::prelude as ys;
use crate::internal::engine::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpAcquisition, DirectHttpOutputSchemas,
    DirectHttpRedirectPolicy, DirectHttpRedirectTargetPolicy, DirectHttpResolutionInputs,
    DirectHttpTransportProfile, HttpSessionUse, OperationId, PolicyDecision,
    PolicyResolutionContext, PolicyResolutionContextKind, PolicyResolutionError, PolicyResolver,
    PreparedAttempt, PreparedPageRequest, Producer, ProducerId, ProducerVersion, RedirectHopLimit,
    ResolvedDirectHttpCaptureSpec, ResolvedPolicyAttempt, ResolvedPolicySpec, Schema, SchemaId,
    SchemaVersion, SourceRetentionPolicy, UnsupportedSourceFormatBehavior,
};
use crate::internal::web_capture::ArtifactRequest;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn test_producer() -> TestResult<Producer> {
    Ok(Producer::new(
        ProducerId::new("test.policy-direct-http")?,
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
        .ok_or_else(|| io::Error::other("prepared request has no acquisition attempt").into())
}

fn direct_context() -> TestResult<PolicyResolutionContext> {
    Ok(PolicyResolutionContext::direct_http(
        DirectHttpResolutionInputs {
            acquisition: DirectHttpAcquisition::new(
                DirectHttpTransportProfile::Standard,
                HttpSessionUse::Isolated,
            ),
            accepted_formats: AcceptedSourceFormats::new([AcceptedSourceFormat::Html])?,
            unsupported_format: UnsupportedSourceFormatBehavior::RetainAndReport,
            retention: SourceRetentionPolicy::RepresentationAndUnicodeView,
            producer: test_producer()?,
            operation: test_operation()?,
            output_schemas: DirectHttpOutputSchemas::new(
                test_schema("test.policy.direct-source")?,
                test_schema("test.policy.direct-source-representation")?,
                None,
                Some(test_schema("test.policy.direct-unicode-view")?),
            ),
        },
    ))
}

fn direct_spec(attempt: &ResolvedPolicyAttempt) -> TestResult<&ResolvedDirectHttpCaptureSpec> {
    match attempt.spec() {
        ResolvedPolicySpec::DirectHttp { spec, .. } => Ok(spec),
        ResolvedPolicySpec::Browser(_) => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Direct HTTP resolved to a browser spec",
        )
        .into()),
    }
}

#[test]
fn current_and_exact_response_documents_resolve_to_source_required_specs() -> TestResult {
    let secret_target = "https://example.test/private?token=policy-resolution-secret";
    let current_policy = ys::Policy::default();
    let current_prepared = prepared(&current_policy, secret_target)?;
    let current_attempt = first_attempt(&current_prepared)?;
    let resolved = PolicyResolver::resolve(&current_prepared, current_attempt, direct_context()?)?;

    assert_eq!(
        resolved.applied_policy().identity(),
        current_prepared.effective_policy_identity()
    );
    assert!(
        resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::AcquisitionSelected {
                    acquisition: ys::policy::AcquisitionKind::DirectHttp
                }
            ))
    );
    assert!(
        resolved
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
    assert!(
        resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DocumentRequested {
                    document: ys::policy::DocumentRequest::ResponseDocument
                }
            ))
    );
    let spec = direct_spec(&resolved)?;
    let resolved_debug = format!("{resolved:?}");
    assert!(!resolved_debug.contains(secret_target));
    assert!(!resolved_debug.contains("policy-resolution-secret"));
    assert_eq!(spec.artifacts().source(), ArtifactRequest::Required);
    assert_eq!(
        spec.artifacts().rendered_dom(),
        ArtifactRequest::NotRequested
    );
    assert_eq!(
        spec.artifacts().accessibility_tree(),
        ArtifactRequest::NotRequested
    );
    assert_eq!(spec.maximum_elapsed().as_microseconds(), 10_000_000);
    assert_eq!(spec.content_limits().content_coded_bytes().get(), 8_000_000);
    assert_eq!(
        spec.content_limits().representation_bytes().get(),
        16_000_000
    );
    assert_eq!(spec.content_limits().unicode_utf8_bytes().get(), 32_000_000);
    assert_eq!(
        spec.redirects().max_hops().map(RedirectHopLimit::get),
        Some(10)
    );
    let redirect_targets = match resolved.spec() {
        ResolvedPolicySpec::DirectHttp {
            redirect_targets, ..
        } => *redirect_targets,
        ResolvedPolicySpec::Browser(_) => {
            return Err(io::Error::other("Direct HTTP resolved to a browser spec").into());
        }
    };
    assert_eq!(
        redirect_targets,
        DirectHttpRedirectTargetPolicy::AllowHttpAndHttps
    );
    let explanation = format!("{:?}", resolved.applied_policy().decisions());
    assert!(!explanation.contains(secret_target));
    assert!(!explanation.contains("policy-resolution-secret"));

    let mut exact_policy = ys::Policy::default();
    exact_policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp
            .documents([ys::policy::DocumentRequest::ResponseDocument]),
    ];
    let exact_prepared = prepared(&exact_policy, "https://example.test/exact")?;
    let exact_attempt = first_attempt(&exact_prepared)?;
    let exact = PolicyResolver::resolve(&exact_prepared, exact_attempt, direct_context()?)?;
    assert_eq!(
        exact.applied_policy().identity(),
        exact_prepared.effective_policy_identity()
    );
    assert!(
        exact
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
    assert_eq!(
        direct_spec(&exact)?.artifacts().source(),
        ArtifactRequest::Required
    );
    Ok(())
}

#[test]
fn custom_direct_http_bounds_and_redirect_targets_reach_the_spec() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.request.maximum_elapsed = ys::policy::MaximumElapsed::try_from(29_109_u64)?;
    policy.request.source.content_coded_bytes =
        ys::policy::AddressableByteLimit::try_from(17_101_u64)?;
    policy.request.source.representation_bytes =
        ys::policy::AddressableByteLimit::try_from(19_103_u64)?;
    policy.request.source.unicode_utf8_bytes =
        ys::policy::AddressableByteLimit::try_from(23_107_u64)?;
    policy.request.direct_http_redirects = ys::policy::DirectHttpRedirects::Follow {
        max_hops: ys::policy::RedirectHopLimit::try_from(5_u32)?,
        targets: ys::policy::DirectHttpRedirectTargets::SameOrigin,
    };
    let prepared = prepared(&policy, "https://example.test/source")?;
    let resolved =
        PolicyResolver::resolve(&prepared, first_attempt(&prepared)?, direct_context()?)?;
    let spec = direct_spec(&resolved)?;

    assert_eq!(
        resolved.applied_policy().identity(),
        prepared.effective_policy_identity()
    );
    assert_eq!(spec.maximum_elapsed().as_microseconds(), 29_109);
    assert_eq!(spec.content_limits().content_coded_bytes().get(), 17_101);
    assert_eq!(spec.content_limits().representation_bytes().get(), 19_103);
    assert_eq!(spec.content_limits().unicode_utf8_bytes().get(), 23_107);
    assert_eq!(spec.artifacts().source(), ArtifactRequest::Required);
    assert_eq!(
        spec.redirects().max_hops().map(RedirectHopLimit::get),
        Some(5)
    );
    assert!(
        resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DirectHttpRedirects {
                    policy: DirectHttpRedirectPolicy::Follow { max_hops }
                } if max_hops.get() == 5
            ))
    );
    assert!(
        resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DirectHttpRedirectTargets {
                    policy: DirectHttpRedirectTargetPolicy::SameOrigin
                }
            ))
    );
    Ok(())
}

#[test]
fn disabled_direct_http_redirects_reach_spec_and_applied_decisions() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.request.direct_http_redirects = ys::policy::DirectHttpRedirects::Disabled;
    let prepared = prepared(&policy, "https://example.test/no-redirect")?;
    let resolved =
        PolicyResolver::resolve(&prepared, first_attempt(&prepared)?, direct_context()?)?;
    assert_eq!(direct_spec(&resolved)?.redirects().max_hops(), None);
    assert!(
        resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DirectHttpRedirects {
                    policy: DirectHttpRedirectPolicy::Disabled
                }
            ))
    );
    Ok(())
}

#[test]
fn unsupported_direct_http_documents_fail_during_prepare_without_provider_io() -> TestResult {
    for document in [
        ys::policy::DocumentRequest::RenderedDom,
        ys::policy::DocumentRequest::AccessibilityTree,
        ys::policy::DocumentRequest::NetworkTree,
    ] {
        let mut policy = ys::Policy::default();
        policy.page.acquisitions = vec![ys::policy::Acquisition::DirectHttp.documents([document])];
        let error = ys::request::new("https://example.test/no-io")
            .bind(&policy)
            .prepare()
            .err()
            .ok_or_else(|| io::Error::other("unsupported Direct HTTP document prepared"))?;
        assert!(matches!(
            error,
            ys::RequestPreparationError::InvalidPolicy(
                ys::PolicyError::UnsupportedDirectHttpDocument
            )
        ));
    }
    Ok(())
}

#[test]
fn empty_exact_direct_http_selection_keeps_internal_source_without_public_request() -> TestResult {
    let mut empty_policy = ys::Policy::default();
    empty_policy.page.acquisitions = vec![ys::policy::Acquisition::DirectHttp.documents([])];
    let empty_prepared = prepared(&empty_policy, "https://example.test/empty")?;
    let resolved_empty = PolicyResolver::resolve(
        &empty_prepared,
        first_attempt(&empty_prepared)?,
        direct_context()?,
    )?;
    assert_eq!(
        resolved_empty.applied_policy().identity(),
        empty_prepared.effective_policy_identity()
    );
    assert!(matches!(
        resolved_empty.applied_policy().decisions().first(),
        Some(PolicyDecision::AcquisitionSelected {
            acquisition: ys::policy::AcquisitionKind::DirectHttp
        })
    ));
    assert!(
        resolved_empty
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
    assert!(
        !resolved_empty
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(decision, PolicyDecision::DocumentRequested { .. }))
    );
    assert_eq!(
        direct_spec(&resolved_empty)?.artifacts().source(),
        ArtifactRequest::Required
    );
    Ok(())
}

#[test]
fn resolver_handles_one_selected_attempt_and_rejects_context_mismatch() -> TestResult {
    let mut multiple_policy = ys::Policy::default();
    multiple_policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless),
    ];
    let multiple = prepared(&multiple_policy, "https://example.test/multiple")?;
    assert_eq!(multiple.attempts().len(), 2);
    let direct = multiple
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("Direct HTTP attempt is missing"))?;
    let resolved = PolicyResolver::resolve(&multiple, direct, direct_context()?)?;
    assert!(matches!(
        resolved.spec(),
        ResolvedPolicySpec::DirectHttp { .. }
    ));

    let browser = multiple
        .attempts()
        .get(1)
        .ok_or_else(|| io::Error::other("browser attempt is missing"))?;
    let context_error = PolicyResolver::resolve(&multiple, browser, direct_context()?)
        .err()
        .ok_or_else(|| io::Error::other("acquisition/context mismatch was accepted"))?;
    assert!(matches!(
        context_error,
        PolicyResolutionError::AcquisitionContextMismatch {
            policy_acquisition: ys::policy::AcquisitionKind::Browser {
                mode: ys::policy::BrowserMode::Headless
            },
            supplied_context: PolicyResolutionContextKind::DirectHttp
        }
    ));
    Ok(())
}

#[test]
fn resolver_rejects_an_attempt_from_a_different_prepared_request() -> TestResult {
    let mut multiple_policy = ys::Policy::default();
    multiple_policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless),
    ];
    let multiple = prepared(&multiple_policy, "https://example.test/multiple")?;
    let other_prepared = prepared(&ys::Policy::default(), "https://example.test/other")?;
    let unrelated_attempt = first_attempt(&other_prepared)?;
    let error = PolicyResolver::resolve(&multiple, unrelated_attempt, direct_context()?)
        .err()
        .ok_or_else(|| io::Error::other("attempt from another request was accepted"))?;
    assert!(matches!(
        error,
        PolicyResolutionError::PreparedAttemptNotInRequest
    ));
    Ok(())
}
