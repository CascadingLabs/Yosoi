//! Validated, provider-neutral input for one browser document-navigation attempt.
#![allow(clippy::missing_const_for_fn)]
use crate::internal::web_capture as yosoi_web_capture;

mod schemas;
pub use schemas::{BrowserCaptureSpecError, BrowserOutputSchemas};
mod environment;
pub use environment::{
    BrowserAttemptEnvironment, BrowserEnvironmentOverrides, BrowserNavigationPolicy,
    FreshBrowserIsolation, NavigationCompletionPolicy,
};
mod certification;
pub use certification::{
    BrowserCapabilityStatus, BrowserCertificationError, BrowserFamilyCapabilities,
    BrowserInstrumentationMode, CertifiedBrowserCapabilities,
};
mod bounds;
pub use bounds::{BrowserBoundsError, BrowserByteBound, BrowserByteDomain, BrowserProviderBounds};

pub use crate::internal::types::{
    BudgetScope as BrowserBudgetScope, LimitEnforcement as BrowserLimitEnforcement,
};
use crate::internal::types::{OperationId, Producer};
use crate::internal::web_capture::{
    AcquisitionCapabilityProfile, ArtifactRequest, DocumentNavigationAcquisition, EventLimit,
    ObservationLimits, ObservationPolicy, RequestedWebTarget, WebAcquisitionStrategy,
    WebArtifactFamily, WebArtifactRequestSet, WebCaptureRequest,
};
use std::{collections::HashSet, num::NonZeroU64};

mod families;

use families::FAMILIES;
pub use families::{byte_domain_for, byte_domain_for_staging, request_for};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserUrlAdmission {
    Omit,
    AdmitNetworkUrls,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserHeaderAdmission {
    Omit,
    /// Admit only the fixed, non-credential-bearing main-document allowlist.
    AdmitSafeMainDocument,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserMainBodyAdmission {
    Omit,
    AdmitDecodedRepresentation,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserEvidenceAdmissionPolicy {
    urls: BrowserUrlAdmission,
    headers: BrowserHeaderAdmission,
    main_body: BrowserMainBodyAdmission,
}
impl BrowserEvidenceAdmissionPolicy {
    pub const fn new(
        urls: BrowserUrlAdmission,
        headers: BrowserHeaderAdmission,
        main_body: BrowserMainBodyAdmission,
    ) -> Self {
        Self {
            urls,
            headers,
            main_body,
        }
    }
    pub const fn urls(self) -> BrowserUrlAdmission {
        self.urls
    }
    pub const fn headers(self) -> BrowserHeaderAdmission {
        self.headers
    }
    pub const fn main_body(self) -> BrowserMainBodyAdmission {
        self.main_body
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedBrowserCaptureSpec {
    request: WebCaptureRequest,
    navigation: DocumentNavigationAcquisition,
    artifacts: WebArtifactRequestSet,
    observation: ObservationPolicy,
    navigation_policy: BrowserNavigationPolicy,
    environment: BrowserAttemptEnvironment,
    bounds: BrowserProviderBounds,
    capabilities: CertifiedBrowserCapabilities,
    producer: Producer,
    operation: OperationId,
    output_schemas: BrowserOutputSchemas,
    identity_plan: yosoi_web_capture::BrowserArtifactIdentityPlan,
    admission: BrowserEvidenceAdmissionPolicy,
}
impl ResolvedBrowserCaptureSpec {
    #[allow(
        clippy::needless_pass_by_value,
        clippy::too_many_arguments,
        reason = "the public resolved-spec constructor takes ownership of every input and stores the provider-bound replacement policy"
    )]
    pub fn new(
        request: WebCaptureRequest,
        artifacts: WebArtifactRequestSet,
        observation: ObservationPolicy,
        navigation_policy: BrowserNavigationPolicy,
        environment: BrowserAttemptEnvironment,
        bounds: BrowserProviderBounds,
        capabilities: CertifiedBrowserCapabilities,
        producer: Producer,
        operation: OperationId,
        output_schemas: BrowserOutputSchemas,
        identity_plan: yosoi_web_capture::BrowserArtifactIdentityPlan,
        admission: BrowserEvidenceAdmissionPolicy,
    ) -> Result<Self, BrowserCaptureSpecError> {
        let observation = bind_provider_event_limit(&observation, bounds.max_events())?;
        if let yosoi_web_capture::SettlementPolicy::QuietPeriod(policy) = observation.settlement()
            && policy.required_quiet().as_microseconds()
                > observation.limits().maximum_elapsed().as_microseconds()
        {
            return Err(BrowserCaptureSpecError::ImpossibleSettlement);
        }
        let navigation = match request.strategy() {
            WebAcquisitionStrategy::DocumentNavigation(v) => *v,
            _ => return Err(BrowserCaptureSpecError::WrongStrategy),
        };
        match navigation.context() {
            yosoi_web_capture::NavigationContext::FreshTopLevel => {}
            yosoi_web_capture::NavigationContext::TopLevel(_) => {
                return Err(BrowserCaptureSpecError::ExistingBrowserContextUnsupported);
            }
            yosoi_web_capture::NavigationContext::Frame(_) => {
                return Err(BrowserCaptureSpecError::FrameNavigationUnsupported);
            }
        }
        if capabilities.profile().producer() != &producer {
            return Err(BrowserCaptureSpecError::ProducerMismatch);
        }
        if identity_plan.activity() != request.capture_id().activity_id() {
            return Err(BrowserCaptureSpecError::IdentityActivityMismatch);
        }
        match capabilities.profile().acquisition() {
            AcquisitionCapabilityProfile::DocumentNavigation(p)
                if p.mode() == environment.mode() => {}
            _ => return Err(BrowserCaptureSpecError::ModeMismatch),
        }
        for family in FAMILIES {
            let requested = request_for(artifacts, family);
            if matches!(
                family,
                WebArtifactFamily::Cookies | WebArtifactFamily::Storage
            ) && !matches!(requested, ArtifactRequest::NotRequested)
            {
                return Err(BrowserCaptureSpecError::UnsupportedArtifactFamily { family });
            }
            match (requested, output_schemas.get(family)) {
                (ArtifactRequest::NotRequested, Some(_)) => {
                    return Err(BrowserCaptureSpecError::UnexpectedSchema { family });
                }
                (ArtifactRequest::Optional | ArtifactRequest::Required, None) => {
                    return Err(BrowserCaptureSpecError::MissingSchema { family });
                }
                _ => {}
            }
            if !matches!(requested, ArtifactRequest::NotRequested)
                && byte_domain_for(family).is_some_and(|domain| {
                    !bounds
                        .byte_bounds()
                        .iter()
                        .any(|bound| bound.domain() == domain)
                })
            {
                return Err(BrowserCaptureSpecError::MissingByteBound { family });
            }
            if matches!(requested, ArtifactRequest::Required)
                && !capabilities
                    .families()
                    .get(family)
                    .is_some_and(BrowserCapabilityStatus::is_supported)
            {
                return Err(BrowserCaptureSpecError::RequiredCapabilityMismatch { family });
            }
        }
        let required_byte_domains: HashSet<_> = FAMILIES
            .into_iter()
            .filter(|family| {
                !matches!(
                    request_for(artifacts, *family),
                    ArtifactRequest::NotRequested
                )
            })
            .filter_map(byte_domain_for)
            .collect();
        let mut required_byte_domains = required_byte_domains;
        if artifacts.source() != ArtifactRequest::NotRequested {
            if !bounds
                .byte_bounds()
                .iter()
                .any(|bound| bound.domain() == BrowserByteDomain::DecodedSourceUtf8)
            {
                return Err(BrowserCaptureSpecError::MissingByteBound {
                    family: WebArtifactFamily::DecodedSource,
                });
            }
            required_byte_domains.insert(BrowserByteDomain::DecodedSourceUtf8);
        }
        if let Some(bound) = bounds
            .byte_bounds()
            .iter()
            .find(|bound| !required_byte_domains.contains(&bound.domain()))
        {
            return Err(BrowserCaptureSpecError::UnexpectedByteBound {
                domain: bound.domain(),
            });
        }
        match (artifacts.source(), output_schemas.source_representation()) {
            (ArtifactRequest::NotRequested, Some(_)) => {
                return Err(BrowserCaptureSpecError::UnexpectedSourceRepresentationSchema);
            }
            (ArtifactRequest::Optional | ArtifactRequest::Required, None) => {
                return Err(BrowserCaptureSpecError::MissingSourceRepresentationSchema);
            }
            _ => {}
        }
        match (artifacts.source(), output_schemas.decoded_source()) {
            (ArtifactRequest::NotRequested, Some(_)) => {
                return Err(BrowserCaptureSpecError::UnexpectedDecodedSourceSchema);
            }
            (ArtifactRequest::Optional | ArtifactRequest::Required, None) => {
                return Err(BrowserCaptureSpecError::MissingDecodedSourceSchema);
            }
            _ => {}
        }
        if let (Some(source), Some(representation), Some(decoded)) = (
            output_schemas.get(WebArtifactFamily::Source),
            output_schemas.source_representation(),
            output_schemas.decoded_source(),
        ) && (source == representation || source == decoded || representation == decoded)
        {
            return Err(BrowserCaptureSpecError::IdenticalSourceSchemas);
        }
        Ok(Self {
            request,
            navigation,
            artifacts,
            observation,
            navigation_policy,
            environment,
            bounds,
            capabilities,
            producer,
            operation,
            output_schemas,
            identity_plan,
            admission,
        })
    }
    pub const fn request(&self) -> &WebCaptureRequest {
        &self.request
    }
    pub const fn target(&self) -> &RequestedWebTarget {
        self.request.target()
    }
    pub const fn strategy(&self) -> DocumentNavigationAcquisition {
        self.navigation
    }
    pub const fn artifacts(&self) -> WebArtifactRequestSet {
        self.artifacts
    }
    pub const fn observation(&self) -> &ObservationPolicy {
        &self.observation
    }
    pub const fn navigation_policy(&self) -> BrowserNavigationPolicy {
        self.navigation_policy
    }
    pub const fn environment(&self) -> &BrowserAttemptEnvironment {
        &self.environment
    }
    pub const fn bounds(&self) -> &BrowserProviderBounds {
        &self.bounds
    }
    pub const fn capabilities(&self) -> &CertifiedBrowserCapabilities {
        &self.capabilities
    }
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }
    pub const fn operation(&self) -> &OperationId {
        &self.operation
    }
    pub const fn output_schemas(&self) -> &BrowserOutputSchemas {
        &self.output_schemas
    }
    pub const fn identity_plan(&self) -> &yosoi_web_capture::BrowserArtifactIdentityPlan {
        &self.identity_plan
    }
    pub const fn admission(&self) -> BrowserEvidenceAdmissionPolicy {
        self.admission
    }
}

fn bind_provider_event_limit(
    observation: &ObservationPolicy,
    max_events: NonZeroU64,
) -> Result<ObservationPolicy, BrowserCaptureSpecError> {
    let provider_event_limit = EventLimit::try_from(max_events.get())
        .map_err(|_| BrowserCaptureSpecError::EventLimitMismatch)?;
    if observation
        .limits()
        .event_limit()
        .is_some_and(|event_limit| event_limit != provider_event_limit)
    {
        return Err(BrowserCaptureSpecError::EventLimitMismatch);
    }
    Ok(ObservationPolicy::new(
        ObservationLimits::new(
            observation.limits().maximum_elapsed(),
            Some(provider_event_limit),
            observation.limits().byte_limit(),
        ),
        observation.settlement().clone(),
    ))
}

#[cfg(test)]
mod tests;
