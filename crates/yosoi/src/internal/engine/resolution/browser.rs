use crate::internal::types as yosoi_types;

use std::num::NonZeroU64;

use crate::internal::web_capture::{
    ArtifactRequest, BrowserAttemptEnvironment, BrowserBudgetScope, BrowserByteBound,
    BrowserByteDomain, BrowserInstrumentationMode, BrowserLimitEnforcement, BrowserOutputSchemas,
    BrowserProviderBounds, DocumentNavigationAcquisition, NavigationCompletionPolicy,
    ObservationLimits, ObservationPolicy, ResolvedBrowserCaptureSpec, SettlementPolicy,
    WebAcquisitionStrategy, WebArtifactFamily, WebArtifactRequestSet, byte_domain_for,
};

use crate::internal::engine::{
    EffectivePolicy, EffectivePolicyIdentity, PreparedAttempt,
    policy::{AddressableByteLimit, BrowserMode, DocumentRequest, Request},
};

use super::{
    AppliedPolicy, AppliedPolicyLimit, PolicyResolutionError, ResolvedPolicySpec,
    applied_decisions,
    inputs::{BrowserResolutionInputs, family_for_document},
};

pub(super) fn resolve(
    identity: EffectivePolicyIdentity,
    policy: &EffectivePolicy,
    attempt: &PreparedAttempt,
    mode: BrowserMode,
    inputs: BrowserResolutionInputs,
) -> Result<super::ResolvedPolicyAttempt, PolicyResolutionError> {
    let completion = inputs.navigation_policy.completion();
    if !matches!(
        completion,
        NavigationCompletionPolicy::DomContentLoaded
            | NavigationCompletionPolicy::ControllerCompleted
    ) {
        return Err(PolicyResolutionError::UnsupportedBrowserCompletion { completion });
    }
    let decisions = applied_decisions(attempt);
    let mut artifacts = PageArtifactRequests::default();

    for document in attempt.documents() {
        if *document == DocumentRequest::NetworkTree {
            // NetworkTree remains a shaped public outcome until its Document
            // schema lands. Do not collect unusable network payloads meanwhile.
            continue;
        }
        let family = family_for_document(*document);
        if let Some(error) =
            PolicyResolutionError::required_capability_error(inputs.capabilities.families(), family)
        {
            return Err(error);
        }
        artifacts.set(family, ArtifactRequest::Required);
    }

    let artifact_requests = artifacts.into_request_set();
    let output_schemas = select_output_schemas(&inputs.output_schemas, artifact_requests);
    let byte_bounds = select_byte_bounds(&policy.request, artifact_requests)?;
    let bounds = BrowserProviderBounds::new(
        byte_bounds,
        NonZeroU64::new(policy.request.browser.max_events.get())
            .ok_or(PolicyResolutionError::InvalidBrowserBound)?,
        policy
            .request
            .browser
            .max_resources
            .to_nonzero()
            .map_err(|_| PolicyResolutionError::InvalidBrowserBound)?,
        policy
            .request
            .browser
            .max_accessibility_nodes
            .to_nonzero()
            .map_err(|_| PolicyResolutionError::InvalidBrowserBound)?,
    )?;
    let observation = ObservationPolicy::new(
        ObservationLimits::new(
            policy
                .request
                .maximum_elapsed
                .to_capture_deadline()
                .map_err(PolicyResolutionError::DeadlineConversion)?,
            None,
            None,
        ),
        inputs.settlement,
    );
    let environment = BrowserAttemptEnvironment::with_overrides(mode, inputs.environment_overrides);
    let request_value = super::capture_request(
        attempt,
        WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
            inputs.navigation_context,
        )),
    );
    let spec = ResolvedBrowserCaptureSpec::new(
        request_value,
        artifact_requests,
        observation,
        inputs.navigation_policy,
        environment,
        bounds,
        inputs.capabilities,
        inputs.producer,
        inputs.operation,
        output_schemas,
        inputs.identity_plan,
        inputs.admission,
    )
    .map_err(PolicyResolutionError::BrowserSpec)?;
    validate_instrumentation(&spec)?;

    let mut limits = vec![
        AppliedPolicyLimit::MaximumElapsed {
            microseconds: policy.request.maximum_elapsed.as_microseconds(),
        },
        AppliedPolicyLimit::BrowserEvents {
            limit: policy.request.browser.max_events,
        },
        AppliedPolicyLimit::BrowserResources {
            limit: policy.request.browser.max_resources,
        },
        AppliedPolicyLimit::AccessibilityNodes {
            limit: policy.request.browser.max_accessibility_nodes,
        },
    ];
    for bound in spec.bounds().byte_bounds() {
        let limit = policy_limit_for_domain(&policy.request, bound.domain())?;
        limits.push(AppliedPolicyLimit::BrowserBytes {
            domain: bound.domain(),
            limit,
            enforcement: bound.enforcement(),
            scope: bound.budget_scope(),
        });
    }

    Ok(super::ResolvedPolicyAttempt::new(
        ResolvedPolicySpec::Browser(Box::new(spec)),
        AppliedPolicy::new(identity, decisions, limits),
    ))
}

#[derive(Clone, Copy, Debug)]
struct PageArtifactRequests {
    source: ArtifactRequest,
    rendered_dom: ArtifactRequest,
    accessibility_tree: ArtifactRequest,
    network: ArtifactRequest,
}

impl PageArtifactRequests {
    const fn set(&mut self, family: WebArtifactFamily, request: ArtifactRequest) {
        match family {
            WebArtifactFamily::Source => self.source = request,
            WebArtifactFamily::RenderedDom => self.rendered_dom = request,
            WebArtifactFamily::AccessibilityTree => self.accessibility_tree = request,
            WebArtifactFamily::Network => self.network = request,
            _ => {}
        }
    }

    const fn into_request_set(self) -> WebArtifactRequestSet {
        WebArtifactRequestSet::new(
            self.source,
            self.rendered_dom,
            self.accessibility_tree,
            self.network,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
        )
    }
}

impl Default for PageArtifactRequests {
    fn default() -> Self {
        Self {
            source: ArtifactRequest::NotRequested,
            rendered_dom: ArtifactRequest::NotRequested,
            accessibility_tree: ArtifactRequest::NotRequested,
            network: ArtifactRequest::NotRequested,
        }
    }
}

/// Mirrors the concrete adapter's closed collector subset, without provider I/O.
/// The document policy has no runtime-diagnostics request, so runtime escalation cannot fit.
fn validate_instrumentation(
    spec: &ResolvedBrowserCaptureSpec,
) -> Result<(), PolicyResolutionError> {
    let network = spec.artifacts().source() != ArtifactRequest::NotRequested
        || spec.artifacts().network() != ArtifactRequest::NotRequested
        || matches!(
            spec.observation().settlement(),
            SettlementPolicy::QuietPeriod(_)
        );
    let instrumentation = spec.capabilities().instrumentation();
    let supported = match instrumentation {
        BrowserInstrumentationMode::Normal => true,
        BrowserInstrumentationMode::Minimal => !network,
        BrowserInstrumentationMode::MinimalNetworkEscalated => network,
        BrowserInstrumentationMode::MinimalRuntimeEscalated
        | BrowserInstrumentationMode::MinimalBothEscalated => false,
    };
    if !supported {
        return Err(PolicyResolutionError::BrowserInstrumentationMismatch { instrumentation });
    }
    Ok(())
}

fn select_output_schemas(
    candidates: &BrowserOutputSchemas,
    artifacts: WebArtifactRequestSet,
) -> BrowserOutputSchemas {
    let source_requested = artifacts.source() != ArtifactRequest::NotRequested;
    BrowserOutputSchemas::new(
        selected_schema(candidates, WebArtifactFamily::Source, source_requested),
        if source_requested {
            candidates.source_representation().cloned()
        } else {
            None
        },
        selected_schema(
            candidates,
            WebArtifactFamily::DecodedSource,
            source_requested,
        ),
        selected_schema(
            candidates,
            WebArtifactFamily::RenderedDom,
            artifacts.rendered_dom() != ArtifactRequest::NotRequested,
        ),
        selected_schema(
            candidates,
            WebArtifactFamily::AccessibilityTree,
            artifacts.accessibility_tree() != ArtifactRequest::NotRequested,
        ),
        selected_schema(
            candidates,
            WebArtifactFamily::Network,
            artifacts.network() != ArtifactRequest::NotRequested,
        ),
        None,
        None,
        None,
        None,
        None,
    )
}

fn selected_schema(
    candidates: &BrowserOutputSchemas,
    family: WebArtifactFamily,
    requested: bool,
) -> Option<yosoi_types::Schema> {
    if requested {
        candidates.get(family).cloned()
    } else {
        None
    }
}

fn select_byte_bounds(
    policy: &Request,
    artifacts: WebArtifactRequestSet,
) -> Result<Vec<BrowserByteBound>, PolicyResolutionError> {
    let families = [
        WebArtifactFamily::Source,
        WebArtifactFamily::RenderedDom,
        WebArtifactFamily::AccessibilityTree,
        WebArtifactFamily::Network,
    ];
    let mut bounds = Vec::with_capacity(families.len());
    for family in families {
        let requested = match family {
            WebArtifactFamily::Source => artifacts.source(),
            WebArtifactFamily::RenderedDom => artifacts.rendered_dom(),
            WebArtifactFamily::AccessibilityTree => artifacts.accessibility_tree(),
            WebArtifactFamily::Network => artifacts.network(),
            _ => ArtifactRequest::NotRequested,
        };
        if requested == ArtifactRequest::NotRequested {
            continue;
        }
        let domain = match family {
            WebArtifactFamily::Network => None,
            _ => Some(
                byte_domain_for(family)
                    .ok_or(PolicyResolutionError::MissingBrowserByteDomain { family })?,
            ),
        };
        let Some(domain) = domain else {
            continue;
        };
        let limit = policy_limit_for_domain(policy, domain)?;
        let nonzero_limit =
            NonZeroU64::new(limit.get()).ok_or(PolicyResolutionError::InvalidBrowserBound)?;
        bounds.push(BrowserByteBound::new(
            domain,
            nonzero_limit,
            BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ));
    }
    if artifacts.source() != ArtifactRequest::NotRequested {
        let domain = BrowserByteDomain::DecodedSourceUtf8;
        let limit = policy_limit_for_domain(policy, domain)?;
        let nonzero_limit =
            NonZeroU64::new(limit.get()).ok_or(PolicyResolutionError::InvalidBrowserBound)?;
        bounds.push(BrowserByteBound::new(
            domain,
            nonzero_limit,
            BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ));
    }
    Ok(bounds)
}

const fn policy_limit_for_domain(
    policy: &Request,
    domain: BrowserByteDomain,
) -> Result<AddressableByteLimit, PolicyResolutionError> {
    match domain {
        BrowserByteDomain::CdpDecodedBody => Ok(policy.source.representation_bytes),
        BrowserByteDomain::DecodedSourceUtf8 => Ok(policy.source.unicode_utf8_bytes),
        BrowserByteDomain::RenderedDomUtf8 => Ok(policy.browser.dom_utf8_bytes),
        BrowserByteDomain::AccessibilityJsonUtf8 => Ok(policy.browser.ax_json_utf8_bytes),
        BrowserByteDomain::RuntimeDiagnosticUtf8 | BrowserByteDomain::ScreenshotPng => {
            Err(PolicyResolutionError::UnexpectedBrowserByteDomain { domain })
        }
    }
}
