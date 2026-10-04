#![allow(clippy::unwrap_used, reason = "black-box fixtures")]
use std::num::{NonZeroU32, NonZeroU64};
use std::{slice, sync::Arc};
use yosoi_types::{
    CaptureId, OperationId, Producer, ProducerId, ProducerVersion, ReasonCode, Schema, SchemaId,
    SchemaVersion,
};
use yosoi_web_capture::*;
const FAMILIES: [WebArtifactFamily; 9] = [
    WebArtifactFamily::Source,
    WebArtifactFamily::RenderedDom,
    WebArtifactFamily::AccessibilityTree,
    WebArtifactFamily::Network,
    WebArtifactFamily::Cookies,
    WebArtifactFamily::Storage,
    WebArtifactFamily::Layout,
    WebArtifactFamily::Visual,
    WebArtifactFamily::RuntimeDiagnostics,
];
fn reason() -> ReasonCode {
    ReasonCode::new("test.unavailable").unwrap()
}
fn producer() -> Producer {
    Producer::new(
        ProducerId::new("test.browser").unwrap(),
        ProducerVersion::new("1").unwrap(),
    )
}
fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::new(NonZeroU32::MIN),
    )
}
fn capabilities(
    mode: BrowserInstrumentationMode,
    network: bool,
    runtime: bool,
) -> Result<CertifiedBrowserCapabilities, BrowserCertificationError> {
    let yes = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let profile = WebProviderCapabilityProfile::new(
        producer(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headless,
        )),
        WebArtifactCapabilitySet::new(
            yes.clone(),
            yes.clone(),
            yes.clone(),
            yes.clone(),
            yes.clone(),
            ArtifactCapability::Unsupported { reason: reason() },
            yes.clone(),
            yes.clone(),
            yes,
        ),
    )
    .unwrap();
    let enabled = |yes| {
        if yes {
            BrowserCapabilityStatus::Supported
        } else {
            BrowserCapabilityStatus::Disabled { reason: reason() }
        }
    };
    CertifiedBrowserCapabilities::new(
        profile,
        &producer(),
        BrowserMode::Headless,
        mode,
        BrowserFamilyCapabilities::new(
            enabled(network),
            enabled(true),
            enabled(true),
            enabled(network),
            enabled(true),
            BrowserCapabilityStatus::Unsupported { reason: reason() },
            enabled(true),
            enabled(true),
            enabled(runtime),
        ),
    )
}
fn bounds(
    family: WebArtifactFamily,
    request: ArtifactRequest,
    omit: Option<BrowserByteDomain>,
) -> BrowserProviderBounds {
    BrowserProviderBounds::new(
        [
            BrowserByteDomain::CdpDecodedBody,
            BrowserByteDomain::DecodedSourceUtf8,
            BrowserByteDomain::RenderedDomUtf8,
            BrowserByteDomain::AccessibilityJsonUtf8,
            BrowserByteDomain::RuntimeDiagnosticUtf8,
            BrowserByteDomain::ScreenshotPng,
        ]
        .into_iter()
        .filter(|domain| {
            request != ArtifactRequest::NotRequested
                && Some(*domain) != omit
                && matches!(
                    (family, domain),
                    (
                        WebArtifactFamily::Source,
                        BrowserByteDomain::CdpDecodedBody | BrowserByteDomain::DecodedSourceUtf8
                    ) | (
                        WebArtifactFamily::RenderedDom,
                        BrowserByteDomain::RenderedDomUtf8
                    ) | (
                        WebArtifactFamily::AccessibilityTree,
                        BrowserByteDomain::AccessibilityJsonUtf8
                    ) | (WebArtifactFamily::Visual, BrowserByteDomain::ScreenshotPng)
                        | (
                            WebArtifactFamily::RuntimeDiagnostics,
                            BrowserByteDomain::RuntimeDiagnosticUtf8
                        )
                )
        })
        .map(|domain| {
            BrowserByteBound::new(
                domain,
                NonZeroU64::new(100).unwrap(),
                BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                BrowserBudgetScope::PerPayload,
            )
        })
        .collect(),
        NonZeroU64::new(10).unwrap(),
        NonZeroU32::new(10).unwrap(),
        NonZeroU32::new(10).unwrap(),
    )
    .unwrap()
}
fn spec(
    family: WebArtifactFamily,
    request: ArtifactRequest,
    has_schema: bool,
    omit: Option<BrowserByteDomain>,
    settlement: SettlementPolicy,
) -> Result<ResolvedBrowserCaptureSpec, BrowserCaptureSpecError> {
    let capture_id = CaptureId::random();
    let r = |f| {
        if f == family {
            request
        } else {
            ArtifactRequest::NotRequested
        }
    };
    let s = |f| {
        if f == family && has_schema {
            Some(schema("test.output"))
        } else {
            None
        }
    };
    ResolvedBrowserCaptureSpec::new(
        WebCaptureRequest::new(
            capture_id,
            RequestedWebTarget::parse("https://example.test/").unwrap(),
            WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
                NavigationContext::FreshTopLevel,
            )),
        ),
        WebArtifactRequestSet::new(
            r(FAMILIES[0]),
            r(FAMILIES[1]),
            r(FAMILIES[2]),
            r(FAMILIES[3]),
            r(FAMILIES[4]),
            r(FAMILIES[5]),
            r(FAMILIES[6]),
            r(FAMILIES[7]),
            r(FAMILIES[8]),
        ),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(100).unwrap(), None, None),
            settlement,
        ),
        BrowserNavigationPolicy::new(NavigationCompletionPolicy::LoadEvent),
        BrowserAttemptEnvironment::new(BrowserMode::Headless),
        bounds(family, request, omit),
        capabilities(BrowserInstrumentationMode::Normal, true, true).unwrap(),
        producer(),
        OperationId::new("test.capture").unwrap(),
        BrowserOutputSchemas::new(
            s(FAMILIES[0]),
            if family == WebArtifactFamily::Source && has_schema {
                Some(schema("test.representation"))
            } else {
                None
            },
            if family == WebArtifactFamily::Source && has_schema {
                Some(schema("test.decoded-source"))
            } else {
                None
            },
            s(FAMILIES[1]),
            s(FAMILIES[2]),
            s(FAMILIES[3]),
            s(FAMILIES[4]),
            s(FAMILIES[5]),
            s(FAMILIES[6]),
            s(FAMILIES[7]),
            s(FAMILIES[8]),
        ),
        BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::Omit,
        ),
    )
}
#[allow(clippy::needless_pass_by_value, reason = "uniform owned fixture API")]
fn staging(family: WebArtifactFamily, outcome: ArtifactStagingOutcome) -> BrowserArtifactStaging {
    let derived_outcome = || match outcome.state() {
        StagingState::Unrequested => ArtifactStagingOutcome::unrequested(),
        StagingState::Failed => ArtifactStagingOutcome::failed(reason()),
        StagingState::Disabled => ArtifactStagingOutcome::disabled(reason()),
        StagingState::Unsupported => ArtifactStagingOutcome::unsupported(reason()),
        _ => ArtifactStagingOutcome::unavailable(reason()),
    };
    let slot = |f| {
        BrowserStagingSlot::new(
            BrowserStagingFamily::Artifact(f),
            if f == family {
                outcome.clone()
            } else {
                ArtifactStagingOutcome::unrequested()
            },
        )
        .unwrap()
    };
    let staging = BrowserArtifactStaging::new(
        slot(FAMILIES[0]),
        BrowserStagingSlot::new(
            BrowserStagingFamily::SourceRepresentation,
            if family == WebArtifactFamily::Source {
                derived_outcome()
            } else {
                ArtifactStagingOutcome::unrequested()
            },
        )
        .unwrap(),
        slot(FAMILIES[1]),
        slot(FAMILIES[2]),
        slot(FAMILIES[3]),
        slot(FAMILIES[4]),
        slot(FAMILIES[5]),
        slot(FAMILIES[6]),
        slot(FAMILIES[7]),
        slot(FAMILIES[8]),
    )
    .unwrap();
    let decoded = BrowserStagingSlot::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
        if family == WebArtifactFamily::Source {
            derived_outcome()
        } else {
            ArtifactStagingOutcome::unrequested()
        },
    )
    .unwrap();
    staging.with_decoded_source(decoded).unwrap()
}
fn environment() -> BrowserCaptureEnvironment {
    BrowserCaptureEnvironment::new(
        producer(),
        producer(),
        EnvironmentValue::Known {
            value: BrowserMode::Headless,
        },
        BrowserRenderingContext::new(
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
        ),
    )
}
fn facts(
    spec: ResolvedBrowserCaptureSpec,
    staging: BrowserArtifactStaging,
    at: u64,
) -> Result<BrowserAdapterFacts, BrowserAdapterOutputError> {
    BrowserAdapterFacts::new(
        CaptureOffset::from_microseconds(at),
        staging,
        environment(),
        spec,
        EventAccounting::new(
            EventCount::new(0),
            EventCount::new(0),
            MeasuredCount::Known(EventCount::new(0)),
        )
        .unwrap(),
        InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
        true,
        None,
        CleanupState::Complete,
        BrowserChallengeFact::unavailable(
            BrowserResponseSignalUnavailableReason::NavigationNotCollected,
        ),
    )
}

#[path = "browser_contract_matrix/accounting.rs"]
mod accounting;
#[path = "browser_contract_matrix/lifecycle.rs"]
mod lifecycle;
#[path = "browser_contract_matrix/staging.rs"]
mod staging;
