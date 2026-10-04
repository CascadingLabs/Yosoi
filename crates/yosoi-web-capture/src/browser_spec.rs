//! Validated, provider-neutral input for one browser document-navigation attempt.
#![allow(clippy::missing_const_for_fn)]

use crate::{
    AcquisitionCapabilityProfile, ArtifactCapability, ArtifactRequest, BrowserMode, ColorScheme,
    DeviceScaleFactor, DocumentNavigationAcquisition, EventLimit, Locale, ObservationLimits,
    ObservationPolicy, ReducedMotion, RequestedWebTarget, TimeZone, UserAgent, Viewport,
    WebAcquisitionStrategy, WebArtifactFamily, WebArtifactRequestSet, WebCaptureRequest,
    WebProviderCapabilityProfile,
};
use std::{
    collections::HashSet,
    num::{NonZeroU32, NonZeroU64},
};
use thiserror::Error;
pub use yosoi_types::{
    BudgetScope as BrowserBudgetScope, LimitEnforcement as BrowserLimitEnforcement,
};
use yosoi_types::{OperationId, Producer, ReasonCode, Schema};

mod families;

use families::{FAMILIES, family_index, profile_capability};
pub use families::{byte_domain_for, byte_domain_for_staging, request_for};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FreshBrowserIsolation {
    FreshIsolatedContext,
}
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct BrowserEnvironmentOverrides {
    pub viewport: Option<Viewport>,
    pub device_scale_factor: Option<DeviceScaleFactor>,
    pub user_agent: Option<UserAgent>,
    pub locale: Option<Locale>,
    pub time_zone: Option<TimeZone>,
    pub color_scheme: Option<ColorScheme>,
    pub reduced_motion: Option<ReducedMotion>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserAttemptEnvironment {
    mode: BrowserMode,
    isolation: FreshBrowserIsolation,
    overrides: BrowserEnvironmentOverrides,
}
impl BrowserAttemptEnvironment {
    pub fn new(mode: BrowserMode) -> Self {
        Self::with_overrides(mode, BrowserEnvironmentOverrides::default())
    }
    pub const fn with_overrides(mode: BrowserMode, overrides: BrowserEnvironmentOverrides) -> Self {
        Self {
            mode,
            isolation: FreshBrowserIsolation::FreshIsolatedContext,
            overrides,
        }
    }
    pub const fn mode(&self) -> BrowserMode {
        self.mode
    }
    pub const fn isolation(&self) -> FreshBrowserIsolation {
        self.isolation
    }
    pub const fn overrides(&self) -> &BrowserEnvironmentOverrides {
        &self.overrides
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NavigationCompletionPolicy {
    DomContentLoaded,
    LoadEvent,
    NetworkIdle,
    ControllerCompleted,
}
/// Navigation has no independent deadline. Every phase uses the observation deadline.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserNavigationPolicy {
    completion: NavigationCompletionPolicy,
}
impl BrowserNavigationPolicy {
    pub const fn new(completion: NavigationCompletionPolicy) -> Self {
        Self { completion }
    }
    pub const fn completion(self) -> NavigationCompletionPolicy {
        self.completion
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum BrowserByteDomain {
    CdpDecodedBody,
    DecodedSourceUtf8,
    RenderedDomUtf8,
    AccessibilityJsonUtf8,
    RuntimeDiagnosticUtf8,
    ScreenshotPng,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserByteBound {
    domain: BrowserByteDomain,
    limit: NonZeroU64,
    enforcement: BrowserLimitEnforcement,
    budget_scope: BrowserBudgetScope,
}
impl BrowserByteBound {
    pub const fn new(
        domain: BrowserByteDomain,
        limit: NonZeroU64,
        enforcement: BrowserLimitEnforcement,
        budget_scope: BrowserBudgetScope,
    ) -> Self {
        Self {
            domain,
            limit,
            enforcement,
            budget_scope,
        }
    }
    pub const fn domain(self) -> BrowserByteDomain {
        self.domain
    }
    pub const fn limit(self) -> NonZeroU64 {
        self.limit
    }
    pub const fn enforcement(self) -> BrowserLimitEnforcement {
        self.enforcement
    }
    pub const fn budget_scope(self) -> BrowserBudgetScope {
        self.budget_scope
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserProviderBounds {
    byte_bounds: Vec<BrowserByteBound>,
    /// Shared provider/lifecycle cap, exposed as the resolved observation event limit.
    max_events: NonZeroU64,
    max_resources: NonZeroU32,
    max_accessibility_nodes: NonZeroU32,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserBoundsError {
    #[error("a browser byte domain is duplicated")]
    DuplicateByteDomain,
    #[error("provider bounds exceed addressable memory")]
    UnaddressableBound,
    #[error("certified byte collection uses post-materialization retention")]
    UnsupportedEnforcement,
}
impl BrowserProviderBounds {
    pub fn new(
        byte_bounds: Vec<BrowserByteBound>,
        max_events: NonZeroU64,
        max_resources: NonZeroU32,
        max_accessibility_nodes: NonZeroU32,
    ) -> Result<Self, BrowserBoundsError> {
        if usize::try_from(max_events.get()).is_err()
            || byte_bounds
                .iter()
                .any(|bound| usize::try_from(bound.limit().get()).is_err())
        {
            return Err(BrowserBoundsError::UnaddressableBound);
        }
        if byte_bounds.iter().any(|bound| {
            let expected = match bound.domain() {
                BrowserByteDomain::CdpDecodedBody
                | BrowserByteDomain::DecodedSourceUtf8
                | BrowserByteDomain::RenderedDomUtf8
                | BrowserByteDomain::AccessibilityJsonUtf8
                | BrowserByteDomain::RuntimeDiagnosticUtf8
                | BrowserByteDomain::ScreenshotPng => {
                    BrowserLimitEnforcement::RetentionAfterProviderMaterialization
                }
            };
            bound.enforcement() != expected
        }) {
            return Err(BrowserBoundsError::UnsupportedEnforcement);
        }
        let mut seen = HashSet::new();
        if byte_bounds.iter().any(|b| !seen.insert(b.domain)) {
            return Err(BrowserBoundsError::DuplicateByteDomain);
        }
        Ok(Self {
            byte_bounds,
            max_events,
            max_resources,
            max_accessibility_nodes,
        })
    }
    pub fn byte_bounds(&self) -> &[BrowserByteBound] {
        &self.byte_bounds
    }
    pub const fn max_events(&self) -> NonZeroU64 {
        self.max_events
    }
    pub const fn max_resources(&self) -> NonZeroU32 {
        self.max_resources
    }
    pub const fn max_accessibility_nodes(&self) -> NonZeroU32 {
        self.max_accessibility_nodes
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserInstrumentationMode {
    Normal,
    Minimal,
    MinimalNetworkEscalated,
    MinimalRuntimeEscalated,
    MinimalBothEscalated,
}
impl BrowserInstrumentationMode {
    const fn network_enabled(self) -> bool {
        matches!(
            self,
            Self::Normal | Self::MinimalNetworkEscalated | Self::MinimalBothEscalated
        )
    }
    const fn runtime_enabled(self) -> bool {
        matches!(
            self,
            Self::Normal | Self::MinimalRuntimeEscalated | Self::MinimalBothEscalated
        )
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BrowserCapabilityStatus {
    Supported,
    Disabled { reason: ReasonCode },
    Unavailable { reason: ReasonCode },
    Unsupported { reason: ReasonCode },
}
impl BrowserCapabilityStatus {
    pub const fn is_supported(&self) -> bool {
        matches!(self, Self::Supported)
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserFamilyCapabilities {
    states: [BrowserCapabilityStatus; 9],
}
impl BrowserFamilyCapabilities {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source: BrowserCapabilityStatus,
        rendered_dom: BrowserCapabilityStatus,
        accessibility_tree: BrowserCapabilityStatus,
        network: BrowserCapabilityStatus,
        cookies: BrowserCapabilityStatus,
        storage: BrowserCapabilityStatus,
        layout: BrowserCapabilityStatus,
        visual: BrowserCapabilityStatus,
        runtime_diagnostics: BrowserCapabilityStatus,
    ) -> Self {
        Self {
            states: [
                source,
                rendered_dom,
                accessibility_tree,
                network,
                cookies,
                storage,
                layout,
                visual,
                runtime_diagnostics,
            ],
        }
    }
    pub fn get(&self, family: WebArtifactFamily) -> Option<&BrowserCapabilityStatus> {
        self.states.get(family_index(family))
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CertifiedBrowserCapabilities {
    profile: WebProviderCapabilityProfile,
    instrumentation: BrowserInstrumentationMode,
    families: BrowserFamilyCapabilities,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserCertificationError {
    #[error("capability producer does not match certified producer")]
    ProducerMismatch,
    #[error("capability acquisition is not document navigation")]
    AcquisitionMismatch,
    #[error("capability browser mode does not match certified mode")]
    ModeMismatch,
    #[error("declared state contradicts provider capability for {family:?}")]
    FamilyMismatch { family: WebArtifactFamily },
}
impl CertifiedBrowserCapabilities {
    pub fn new(
        profile: WebProviderCapabilityProfile,
        producer: &Producer,
        mode: BrowserMode,
        instrumentation: BrowserInstrumentationMode,
        families: BrowserFamilyCapabilities,
    ) -> Result<Self, BrowserCertificationError> {
        if profile.producer() != producer {
            return Err(BrowserCertificationError::ProducerMismatch);
        }
        match profile.acquisition() {
            AcquisitionCapabilityProfile::DocumentNavigation(p) if p.mode() == mode => {}
            AcquisitionCapabilityProfile::DocumentNavigation(_) => {
                return Err(BrowserCertificationError::ModeMismatch);
            }
            _ => return Err(BrowserCertificationError::AcquisitionMismatch),
        }
        for family in FAMILIES {
            let provider = profile_capability(&profile, family);
            let status = families.get(family);
            let agrees = match provider {
                ArtifactCapability::Supported { .. } => {
                    !matches!(status, Some(BrowserCapabilityStatus::Unsupported { .. }))
                }
                ArtifactCapability::Unsupported { .. } => {
                    matches!(status, Some(BrowserCapabilityStatus::Unsupported { .. }))
                }
            };
            if !agrees {
                return Err(BrowserCertificationError::FamilyMismatch { family });
            }
        }
        for family in FAMILIES {
            let status = families.get(family);
            let expected_enabled = match family {
                WebArtifactFamily::Source | WebArtifactFamily::Network => {
                    Some(instrumentation.network_enabled())
                }
                WebArtifactFamily::RuntimeDiagnostics => Some(instrumentation.runtime_enabled()),
                _ => None,
            };
            let valid = if family == WebArtifactFamily::Storage {
                matches!(status, Some(BrowserCapabilityStatus::Unsupported { .. }))
            } else if let Some(enabled) = expected_enabled {
                enabled == matches!(status, Some(BrowserCapabilityStatus::Supported))
            } else {
                matches!(status, Some(BrowserCapabilityStatus::Supported))
            };
            if !valid {
                return Err(BrowserCertificationError::FamilyMismatch { family });
            }
        }
        if families
            .get(WebArtifactFamily::Source)
            .map(BrowserCapabilityStatus::is_supported)
            != families
                .get(WebArtifactFamily::Network)
                .map(BrowserCapabilityStatus::is_supported)
        {
            return Err(BrowserCertificationError::FamilyMismatch {
                family: WebArtifactFamily::Network,
            });
        }
        Ok(Self {
            profile,
            instrumentation,
            families,
        })
    }
    pub const fn profile(&self) -> &WebProviderCapabilityProfile {
        &self.profile
    }
    pub const fn instrumentation(&self) -> BrowserInstrumentationMode {
        self.instrumentation
    }
    pub const fn families(&self) -> &BrowserFamilyCapabilities {
        &self.families
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserOutputSchemas {
    schemas: [Option<Schema>; 9],
    source_representation: Option<Schema>,
    decoded_source: Option<Schema>,
}
impl BrowserOutputSchemas {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source: Option<Schema>,
        source_representation: Option<Schema>,
        decoded_source: Option<Schema>,
        rendered_dom: Option<Schema>,
        accessibility_tree: Option<Schema>,
        network: Option<Schema>,
        cookies: Option<Schema>,
        storage: Option<Schema>,
        layout: Option<Schema>,
        visual: Option<Schema>,
        runtime_diagnostics: Option<Schema>,
    ) -> Self {
        Self {
            schemas: [
                source,
                rendered_dom,
                accessibility_tree,
                network,
                cookies,
                storage,
                layout,
                visual,
                runtime_diagnostics,
            ],
            source_representation,
            decoded_source,
        }
    }
    pub fn get(&self, family: WebArtifactFamily) -> Option<&Schema> {
        if family == WebArtifactFamily::DecodedSource {
            return self.decoded_source.as_ref();
        }
        self.schemas
            .get(family_index(family))
            .and_then(Option::as_ref)
    }
    pub const fn source_representation(&self) -> Option<&Schema> {
        self.source_representation.as_ref()
    }
    pub const fn decoded_source(&self) -> Option<&Schema> {
        self.decoded_source.as_ref()
    }
}
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum BrowserCaptureSpecError {
    #[error("quiet period exceeds the overall maximum elapsed bound")]
    ImpossibleSettlement,
    #[error("resolved browser capture requires document-navigation strategy")]
    WrongStrategy,
    #[error("resolved browser capture requires a top-level navigation")]
    FrameNavigationUnsupported,
    #[error("the current browser adapter cannot resolve an existing browser context")]
    ExistingBrowserContextUnsupported,
    #[error("browser capture rejects unresolved {family:?} policy semantics")]
    UnsupportedArtifactFamily { family: WebArtifactFamily },
    #[error("requested {family:?} output requires a schema")]
    MissingSchema { family: WebArtifactFamily },
    #[error("unrequested {family:?} output cannot carry a schema")]
    UnexpectedSchema { family: WebArtifactFamily },
    #[error("source requires a representation schema")]
    MissingSourceRepresentationSchema,
    #[error("source representation schema is only valid with source")]
    UnexpectedSourceRepresentationSchema,
    #[error("decoded source schema is required when source is requested")]
    MissingDecodedSourceSchema,
    #[error("decoded source schema is only valid with source")]
    UnexpectedDecodedSourceSchema,
    #[error("source, decoded source, and source representation schemas must be distinct")]
    IdenticalSourceSchemas,
    #[error("required {family:?} capability is not supported")]
    RequiredCapabilityMismatch { family: WebArtifactFamily },
    #[error("capture producer contradicts certification")]
    ProducerMismatch,
    #[error("browser artifact identity activity contradicts the capture request")]
    IdentityActivityMismatch,
    #[error("requested byte family lacks its domain bound: {family:?}")]
    MissingByteBound { family: WebArtifactFamily },
    #[error("byte bound is not implied by any requested byte-bearing family: {domain:?}")]
    UnexpectedByteBound { domain: BrowserByteDomain },
    #[error("requested browser mode contradicts certification")]
    ModeMismatch,
    #[error("observation event limit contradicts the browser provider event bound")]
    EventLimitMismatch,
}
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
    identity_plan: crate::BrowserArtifactIdentityPlan,
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
        identity_plan: crate::BrowserArtifactIdentityPlan,
        admission: BrowserEvidenceAdmissionPolicy,
    ) -> Result<Self, BrowserCaptureSpecError> {
        let observation = bind_provider_event_limit(&observation, bounds.max_events())?;
        if let crate::SettlementPolicy::QuietPeriod(policy) = observation.settlement()
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
            crate::NavigationContext::FreshTopLevel => {}
            crate::NavigationContext::TopLevel(_) => {
                return Err(BrowserCaptureSpecError::ExistingBrowserContextUnsupported);
            }
            crate::NavigationContext::Frame(_) => {
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
    pub const fn identity_plan(&self) -> &crate::BrowserArtifactIdentityPlan {
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
mod tests {
    #![allow(clippy::unwrap_used, reason = "fixed nonzero test fixtures")]

    use super::*;
    use crate::{CaptureDeadline, SettlementPolicy};

    fn observation(event_limit: Option<u64>) -> ObservationPolicy {
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(100).unwrap(),
                event_limit.map(|limit| EventLimit::try_from(limit).unwrap()),
                None,
            ),
            SettlementPolicy::Disabled,
        )
    }

    #[test]
    fn provider_event_bound_is_the_effective_observation_limit() {
        let effective =
            bind_provider_event_limit(&observation(None), NonZeroU64::new(7).unwrap()).unwrap();
        assert_eq!(
            effective.limits().event_limit().map(EventLimit::get),
            Some(7)
        );
    }

    #[test]
    fn contradictory_event_limits_are_rejected() {
        assert_eq!(
            bind_provider_event_limit(&observation(Some(6)), NonZeroU64::new(7).unwrap()),
            Err(BrowserCaptureSpecError::EventLimitMismatch)
        );
    }
}
