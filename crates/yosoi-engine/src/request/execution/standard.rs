//! Package-owned standard execution contexts for authored page requests.

use std::num::NonZeroU32;

use thiserror::Error;
use yosoi_policy::policy::AcquisitionKind;
#[cfg(feature = "browser")]
use yosoi_policy::policy::DocumentRequest;
#[cfg(feature = "browser")]
use yosoi_types::{ActivityId, ReasonCode};
use yosoi_types::{NamespacedIdError, OperationId, Schema, SchemaId, SchemaVersion};
#[cfg(feature = "browser")]
use yosoi_web_capture::BrowserMode;
use yosoi_web_capture::{DirectHttpAcquisition, DirectHttpTransportProfile, HttpSessionUse};
use yosoi_web_capture_direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpCaptureSpecError,
    DirectHttpOutputSchemas, DirectHttpTransportError, SourceRetentionPolicy,
    UnsupportedSourceFormatBehavior, XmlSourceProfile, wreq_adapter_producer,
};

#[cfg(feature = "browser")]
use crate::resolution::BrowserResolutionInputs;
use crate::{PreparedPageRequest, resolution::DirectHttpResolutionInputs};

use super::RequestExecutor;

/// A checked construction failure while preparing a package-owned adapter context.
#[derive(Debug, Error)]
pub enum StandardExecutionSetupError {
    #[error("the standard Direct HTTP adapter identity could not be constructed")]
    DirectHttpProducer(#[source] DirectHttpTransportError),
    #[error("the standard Direct HTTP source formats could not be constructed")]
    DirectHttpFormats(#[source] DirectHttpCaptureSpecError),
    #[error("a standard execution identity could not be constructed")]
    Identity(#[source] NamespacedIdError),
    #[cfg(feature = "browser")]
    #[error("the standard VoidCrawl producer identity could not be constructed")]
    BrowserProducer(#[source] yosoi_web_capture::VoidCrawlAdapterProducerError),
    #[cfg(feature = "browser")]
    #[error("the standard browser capability profile could not be constructed")]
    BrowserProfile(#[source] yosoi_web_capture::WebProviderCapabilityProfileError),
    #[cfg(feature = "browser")]
    #[error("the standard browser capability certification could not be constructed")]
    BrowserCertification(#[source] yosoi_web_capture::BrowserCertificationError),
    #[cfg(not(feature = "browser"))]
    #[error("browser execution requires the yosoi browser feature")]
    BrowserFeatureDisabled,
}

pub(super) fn for_prepared(
    prepared: &PreparedPageRequest,
) -> Result<RequestExecutor, StandardExecutionSetupError> {
    let mut executor = RequestExecutor::new();

    for attempt in prepared.attempts() {
        match attempt.kind() {
            AcquisitionKind::DirectHttp if executor.direct_http.is_none() => {
                executor = executor.with_direct_http(direct_http_inputs()?);
            }
            AcquisitionKind::DirectHttp => {}
            AcquisitionKind::Browser { mode } => {
                #[cfg(feature = "browser")]
                if executor.browser_for_mode(mode).is_none() {
                    executor = executor.with_browser(
                        mode,
                        browser_inputs(
                            mode,
                            attempt.capture_id().activity_id(),
                            browser_completion(prepared, mode),
                        )?,
                    );
                }
                #[cfg(not(feature = "browser"))]
                {
                    let _ = mode;
                    return Err(StandardExecutionSetupError::BrowserFeatureDisabled);
                }
            }
        }
    }

    Ok(executor)
}

#[cfg(feature = "browser")]
fn browser_completion(
    prepared: &PreparedPageRequest,
    mode: BrowserMode,
) -> yosoi_web_capture::NavigationCompletionPolicy {
    let requires_response_document = prepared.attempts().iter().any(|attempt| {
        attempt.kind() == AcquisitionKind::Browser { mode }
            && attempt
                .documents()
                .contains(&DocumentRequest::ResponseDocument)
    });
    if requires_response_document {
        yosoi_web_capture::NavigationCompletionPolicy::ControllerCompleted
    } else {
        yosoi_web_capture::NavigationCompletionPolicy::DomContentLoaded
    }
}

pub(super) fn direct_http_inputs() -> Result<DirectHttpResolutionInputs, StandardExecutionSetupError>
{
    let accepted_formats = AcceptedSourceFormats::new([
        AcceptedSourceFormat::Html,
        AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
        AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml),
        AcceptedSourceFormat::Json,
        AcceptedSourceFormat::PlainText,
    ])
    .map_err(StandardExecutionSetupError::DirectHttpFormats)?;

    Ok(DirectHttpResolutionInputs {
        acquisition: DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        ),
        accepted_formats,
        unsupported_format: UnsupportedSourceFormatBehavior::RetainAndReport,
        retention: SourceRetentionPolicy::RepresentationAndUnicodeView,
        producer: wreq_adapter_producer()
            .map_err(StandardExecutionSetupError::DirectHttpProducer)?,
        operation: operation("com.cascadinglabs.yosoi.request.direct-http")?,
        output_schemas: DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.direct-http.source")?,
            schema("com.cascadinglabs.yosoi.direct-http.source-representation")?,
            None,
            Some(schema("com.cascadinglabs.yosoi.direct-http.unicode-view")?),
        ),
    })
}

fn operation(value: &'static str) -> Result<OperationId, StandardExecutionSetupError> {
    OperationId::new(value).map_err(StandardExecutionSetupError::Identity)
}

fn schema(value: &'static str) -> Result<Schema, StandardExecutionSetupError> {
    Ok(Schema::new(
        SchemaId::new(value).map_err(StandardExecutionSetupError::Identity)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

#[cfg(feature = "browser")]
fn browser_inputs(
    mode: BrowserMode,
    activity_id: ActivityId,
    completion: yosoi_web_capture::NavigationCompletionPolicy,
) -> Result<BrowserResolutionInputs, StandardExecutionSetupError> {
    use yosoi_web_capture::{
        AcquisitionCapabilityProfile, ArtifactCapability, ArtifactMultiplicity,
        BrowserArtifactIdentityPlan, BrowserCapabilityStatus, BrowserEnvironmentOverrides,
        BrowserEvidenceAdmissionPolicy, BrowserFamilyCapabilities, BrowserHeaderAdmission,
        BrowserInstrumentationMode, BrowserMainBodyAdmission, BrowserNavigationCapabilityProfile,
        BrowserNavigationPolicy, BrowserOutputSchemas, BrowserUrlAdmission, NavigationContext,
        SettlementPolicy, WebArtifactCapabilitySet, WebProviderCapabilityProfile,
    };

    let producer = yosoi_web_capture::void_crawl_adapter_producer()
        .map_err(StandardExecutionSetupError::BrowserProducer)?;
    let unsupported_reason = ReasonCode::new("voidcrawl.capability.not-implemented")
        .map_err(StandardExecutionSetupError::Identity)?;
    let supported = || ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let unsupported = || ArtifactCapability::Unsupported {
        reason: unsupported_reason.clone(),
    };
    let profile = WebProviderCapabilityProfile::new(
        producer.clone(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            mode,
        )),
        WebArtifactCapabilitySet::new(
            supported(),
            supported(),
            supported(),
            supported(),
            supported(),
            unsupported(),
            supported(),
            supported(),
            supported(),
        ),
    )
    .map_err(StandardExecutionSetupError::BrowserProfile)?;
    let unsupported_status = || BrowserCapabilityStatus::Unsupported {
        reason: unsupported_reason.clone(),
    };
    let capabilities = yosoi_web_capture::CertifiedBrowserCapabilities::new(
        profile,
        &producer,
        mode,
        BrowserInstrumentationMode::Normal,
        BrowserFamilyCapabilities::new(
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            unsupported_status(),
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
        ),
    )
    .map_err(StandardExecutionSetupError::BrowserCertification)?;

    Ok(BrowserResolutionInputs {
        navigation_context: NavigationContext::FreshTopLevel,
        navigation_policy: BrowserNavigationPolicy::new(completion),
        environment_overrides: BrowserEnvironmentOverrides::default(),
        capabilities,
        producer,
        operation: operation("com.cascadinglabs.yosoi.request.browser-navigation")?,
        output_schemas: BrowserOutputSchemas::new(
            Some(schema("com.cascadinglabs.yosoi.browser.cdp-source")?),
            Some(schema(
                "com.cascadinglabs.yosoi.browser.source-representation",
            )?),
            Some(schema("com.cascadinglabs.yosoi.browser.decoded-source")?),
            Some(schema("com.cascadinglabs.yosoi.browser.rendered-dom")?),
            Some(schema(
                "com.cascadinglabs.yosoi.browser.accessibility-tree",
            )?),
            Some(schema("com.cascadinglabs.yosoi.browser.network")?),
            None,
            None,
            None,
            None,
            None,
        ),
        identity_plan: BrowserArtifactIdentityPlan::sequential(activity_id),
        admission: BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::AdmitDecodedRepresentation,
        ),
        settlement: SettlementPolicy::Disabled,
    })
}
