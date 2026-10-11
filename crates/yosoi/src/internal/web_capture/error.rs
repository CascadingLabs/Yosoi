//! Central error vocabulary for Web Capture domain failures.
//! Domain constructors keep returning their specific `thiserror` types so Rust
//! callers can match precise variants. Implementing [`StructuredWebCaptureError`]
//! gives each error a stable identifier and category. Callers add a static logical
//! path with [`StructuredWebCaptureError::at`] at aggregate, logging, or agent boundaries.
//! # Adding an error
//! 1. Keep the error beside the invariant it describes and give it a safe
//!    `Display` message that contains no captured values or credentials.
//! 2. Add its code mapping in this module. Never reuse or change a published
//!    code to mean something different.
//! 3. Choose the category by cause: wire bounds are invalid input, while exhausting
//!    an operational capture limit is limit exhaustion.
//! 4. Attach context at the boundary with a static schema path.
//! 5. Test the variant, code, category, context, and source chain.

use std::{error::Error, fmt};

use crate::internal::types::{
    ActivityReceiptError, ArtifactIdError, ArtifactRecordError, CaptureReceiptError,
    NamespacedIdError, OccurrenceIdParseError, ProducerVersionError, SchemaVersionError,
    Sha256DigestParseError,
};
use serde::Serialize;

use crate::internal::web_capture::{
    ArtifactByteExtentError, ArtifactCollectionError, ByteAccountingError, ByteLimitError,
    CaptureDeadlineError, CaptureObservationError, CaptureResolutionError, DeviceScaleFactorError,
    EventAccountingError, EventLimitError, HttpBrowserImpersonationProfileError,
    HttpRedirectStatusError, InFlightActivityError, LocaleError, MediaTypeError,
    ObservationWindowError, PreferredLanguagesError, QuietPeriodError, SettlementEvidenceError,
    SettlementPolicyIdError, TimeZoneError, TupleWebOriginParseError, UserAgentError,
    WebAcquisitionRecordError, WebArtifactManifestError, WebArtifactMetadataError, WebCaptureError,
    WebProviderCapabilityProfileError, WebUrlParseError,
};

/// Broad cause of a Web Capture failure.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
#[non_exhaustive]
pub enum WebCaptureErrorCategory {
    /// Supplied or decoded facts violate the domain model.
    InvalidInput,
    /// The requested behavior is not supported by the implementation.
    UnsupportedCapability,
    /// Declared policy intentionally refuses the requested behavior.
    PolicyRefusal,
    /// A runtime capture resource or configured operational limit was exhausted.
    LimitExhaustion,
    /// The implementation failed independently of the supplied capture facts.
    InternalFailure,
}

/// Stable machine-readable identity for one failure condition.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct WebCaptureErrorCode(&'static str);

impl WebCaptureErrorCode {
    const fn new(value: &'static str) -> Self {
        Self(value)
    }

    /// Defines a producer-owned stable error code.
    ///
    /// This extension point is public because producer crates cannot use the
    /// foundation's private registry constructor. Callers must supply a
    /// namespaced, immutable code; user-controlled text does not belong here.
    pub const fn from_static(value: &'static str) -> Self {
        Self::new(value)
    }

    /// Returns the stable namespaced code.
    pub const fn as_str(self) -> &'static str {
        self.0
    }
}

impl fmt::Display for WebCaptureErrorCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}

/// Static logical location of invalid data in a Web Capture value.
///
/// Contexts use JSON Pointer-like schema paths. The static lifetime prevents a
/// captured URL, credential, or artifact body from accidentally becoming path
/// metadata.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct WebCaptureErrorContext(&'static str);

impl WebCaptureErrorContext {
    /// Creates a context from a static logical schema path.
    pub const fn new(path: &'static str) -> Self {
        Self(path)
    }

    /// Returns the logical schema path.
    pub const fn as_str(self) -> &'static str {
        self.0
    }
}

impl fmt::Display for WebCaptureErrorContext {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}

/// Common metadata implemented by every centralized Web Capture domain error.
pub trait StructuredWebCaptureError: Error + Sized {
    /// Returns the stable condition code.
    fn code(&self) -> WebCaptureErrorCode;

    /// Returns the broad cause category.
    fn category(&self) -> WebCaptureErrorCategory {
        WebCaptureErrorCategory::InvalidInput
    }

    /// Adds aggregate context while preserving this concrete error as a source.
    fn at(self, context: WebCaptureErrorContext) -> ContextualWebCaptureError<Self> {
        ContextualWebCaptureError {
            context,
            source: self,
        }
    }
}

/// A concrete domain error annotated with its location in a larger value.
#[derive(Debug)]
pub struct ContextualWebCaptureError<E> {
    context: WebCaptureErrorContext,
    source: E,
}

impl<E: StructuredWebCaptureError> ContextualWebCaptureError<E> {
    /// Returns the stable condition code.
    pub fn code(&self) -> WebCaptureErrorCode {
        self.source.code()
    }

    /// Returns the broad cause category.
    pub fn category(&self) -> WebCaptureErrorCategory {
        self.source.category()
    }

    /// Returns the logical location supplied by the aggregate boundary.
    pub const fn context(&self) -> WebCaptureErrorContext {
        self.context
    }

    /// Returns the concrete underlying domain error.
    pub const fn domain_error(&self) -> &E {
        &self.source
    }

    /// Builds a small secret-safe representation for logs and agent handoffs.
    pub fn summary(&self) -> WebCaptureErrorSummary {
        WebCaptureErrorSummary {
            category: self.category(),
            code: self.code(),
            context: self.context,
            message: self.source.to_string(),
        }
    }
}

impl<E: StructuredWebCaptureError> fmt::Display for ContextualWebCaptureError<E> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{} at {}", self.source, self.context)
    }
}

impl<E: StructuredWebCaptureError + 'static> Error for ContextualWebCaptureError<E> {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.source)
    }
}

/// Serializable, source-free summary for logs and agent handoffs.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct WebCaptureErrorSummary {
    category: WebCaptureErrorCategory,
    code: WebCaptureErrorCode,
    context: WebCaptureErrorContext,
    message: String,
}

impl WebCaptureErrorSummary {
    /// Returns the broad cause category.
    pub const fn category(&self) -> WebCaptureErrorCategory {
        self.category
    }

    /// Returns the stable condition code.
    pub const fn code(&self) -> WebCaptureErrorCode {
        self.code
    }

    /// Returns the logical schema location.
    pub const fn context(&self) -> WebCaptureErrorContext {
        self.context
    }

    /// Returns the secret-safe human explanation.
    pub fn message(&self) -> &str {
        &self.message
    }
}

macro_rules! map_error_codes {
    ($error:ty { $($pattern:pat => $code:literal),+ $(,)? }) => {
        impl StructuredWebCaptureError for $error {
            fn code(&self) -> WebCaptureErrorCode {
                let code = match self {
                    $($pattern => $code),+
                };
                WebCaptureErrorCode::new(code)
            }
        }
    };
}

macro_rules! map_unit_error_code {
    ($error:ty => $code:literal) => {
        impl StructuredWebCaptureError for $error {
            fn code(&self) -> WebCaptureErrorCode {
                WebCaptureErrorCode::new($code)
            }
        }
    };
}

impl StructuredWebCaptureError for WebUrlParseError {
    fn code(&self) -> WebCaptureErrorCode {
        let code = match self {
            Self::InvalidUrl(_) => "web_capture.url.invalid",
            Self::UnsupportedScheme => "web_capture.url.unsupported_scheme",
            Self::MissingHost => "web_capture.url.missing_host",
            Self::CredentialsNotAllowed => "web_capture.url.credentials_not_allowed",
        };
        WebCaptureErrorCode::new(code)
    }

    fn category(&self) -> WebCaptureErrorCategory {
        match self {
            Self::UnsupportedScheme => WebCaptureErrorCategory::UnsupportedCapability,
            Self::InvalidUrl(_) | Self::MissingHost | Self::CredentialsNotAllowed => {
                WebCaptureErrorCategory::InvalidInput
            }
        }
    }
}
map_error_codes!(TupleWebOriginParseError {
    TupleWebOriginParseError::InvalidUrl(_) => "web_capture.origin.invalid_url",
    TupleWebOriginParseError::NonCanonical => "web_capture.origin.non_canonical",
});
map_error_codes!(HttpBrowserImpersonationProfileError {
    HttpBrowserImpersonationProfileError::Empty => "web_capture.http_profile.empty",
    HttpBrowserImpersonationProfileError::TooLong => "web_capture.http_profile.too_long",
    HttpBrowserImpersonationProfileError::InvalidCharacter => "web_capture.http_profile.invalid_character",
});
map_unit_error_code!(HttpRedirectStatusError => "web_capture.redirect.status_invalid");
map_error_codes!(CaptureResolutionError {
    CaptureResolutionError::DiscontinuousRedirects => "web_capture.resolution.redirects_discontinuous",
    CaptureResolutionError::RedirectFinalUrlMismatch => "web_capture.resolution.final_url_mismatch",
});
map_error_codes!(WebAcquisitionRecordError {
    WebAcquisitionRecordError::ReceiptIdentityMismatch => "web_capture.acquisition.receipt_identity_mismatch",
    WebAcquisitionRecordError::RedirectInitialUrlMismatch => "web_capture.acquisition.initial_url_mismatch",
    WebAcquisitionRecordError::ResourceOriginMismatch => "web_capture.acquisition.resource_origin_mismatch",
    WebAcquisitionRecordError::ForeignOpaqueOrigin => "web_capture.acquisition.foreign_opaque_origin",
});
map_unit_error_code!(InFlightActivityError => "web_capture.observation.in_flight_subset_invalid");
map_error_codes!(EventAccountingError {
    EventAccountingError::RetainedExceedsAdmitted => "web_capture.observation.events.retained_exceeds_admitted",
    EventAccountingError::KnownLossMismatch => "web_capture.observation.events.known_loss_mismatch",
    EventAccountingError::Overflow => "web_capture.observation.events.overflow",
});
map_error_codes!(ByteAccountingError {
    ByteAccountingError::RetainedExceedsAdmitted => "web_capture.observation.bytes.retained_exceeds_admitted",
    ByteAccountingError::KnownLossMismatch => "web_capture.observation.bytes.known_loss_mismatch",
    ByteAccountingError::Overflow => "web_capture.observation.bytes.overflow",
});
map_error_codes!(CaptureObservationError {
    CaptureObservationError::TerminalOffsetMismatch => "web_capture.observation.terminal_offset_mismatch",
    CaptureObservationError::WindowExceedsMaximum => "web_capture.observation.window_exceeds_maximum",
    CaptureObservationError::SettlementDisabled => "web_capture.observation.settlement_disabled",
    CaptureObservationError::SettlementPolicyMismatch => "web_capture.observation.settlement_policy_mismatch",
    CaptureObservationError::QuietPeriodNotSatisfied => "web_capture.observation.quiet_period_not_satisfied",
    CaptureObservationError::SettlementInFlightExceeded => "web_capture.observation.settlement_in_flight_exceeded",
    CaptureObservationError::SettlementOutsideWindow => "web_capture.observation.settlement_outside_window",
    CaptureObservationError::SettlementTerminalStateMismatch => "web_capture.observation.settlement_terminal_state_mismatch",
    CaptureObservationError::DeadlineMismatch => "web_capture.observation.deadline_mismatch",
    CaptureObservationError::DeadlineNotReached => "web_capture.observation.deadline_not_reached",
    CaptureObservationError::EventLimitMismatch => "web_capture.observation.event_limit_mismatch",
    CaptureObservationError::EventLimitNotReached => "web_capture.observation.event_limit_not_reached",
    CaptureObservationError::EventLimitExceeded => "web_capture.observation.event_limit_exceeded",
    CaptureObservationError::ByteLimitMismatch => "web_capture.observation.byte_limit_mismatch",
    CaptureObservationError::ByteLimitNotReached => "web_capture.observation.byte_limit_not_reached",
    CaptureObservationError::ByteLimitExceeded => "web_capture.observation.byte_limit_exceeded",
});
map_error_codes!(SettlementPolicyIdError {
    SettlementPolicyIdError::Empty => "web_capture.settlement.policy_id_empty",
    SettlementPolicyIdError::TooLong => "web_capture.settlement.policy_id_too_long",
    SettlementPolicyIdError::Invalid => "web_capture.settlement.policy_id_invalid",
});
map_unit_error_code!(QuietPeriodError => "web_capture.settlement.quiet_period_zero");
map_error_codes!(SettlementEvidenceError {
    SettlementEvidenceError::InvalidTimeOrder => "web_capture.settlement.invalid_time_order",
    SettlementEvidenceError::RelevantEventsObserved => "web_capture.settlement.relevant_events_observed",
    SettlementEvidenceError::RelevantLossUnavailable => "web_capture.settlement.relevant_loss_unavailable",
});
map_unit_error_code!(CaptureDeadlineError => "web_capture.observation.maximum_elapsed_zero");
map_unit_error_code!(EventLimitError => "web_capture.observation.event_limit_zero");
map_error_codes!(ByteLimitError {
    ByteLimitError::Zero => "web_capture.observation.byte_limit_zero",
    ByteLimitError::TooLarge => "web_capture.observation.byte_limit_too_large",
});
map_unit_error_code!(ObservationWindowError => "web_capture.observation.window_time_order_invalid");
map_error_codes!(DeviceScaleFactorError {
    DeviceScaleFactorError::Empty => "web_capture.environment.device_scale_factor_empty",
    DeviceScaleFactorError::TooLong => "web_capture.environment.device_scale_factor_too_long",
    DeviceScaleFactorError::InvalidCharacter => "web_capture.environment.device_scale_factor_invalid_character",
    DeviceScaleFactorError::Zero => "web_capture.environment.device_scale_factor_zero",
    DeviceScaleFactorError::NonCanonical => "web_capture.environment.device_scale_factor_non_canonical",
});
map_error_codes!(UserAgentError {
    UserAgentError::TooLong => "web_capture.environment.user_agent_too_long",
    UserAgentError::ControlCharacter => "web_capture.environment.user_agent_control_character",
});
map_unit_error_code!(PreferredLanguagesError => "web_capture.environment.preferred_languages_too_many");
map_error_codes!(LocaleError {
    LocaleError::Empty => "web_capture.environment.locale_empty",
    LocaleError::TooLong => "web_capture.environment.locale_too_long",
    LocaleError::InvalidCharacter => "web_capture.environment.locale_invalid_character",
});
map_error_codes!(TimeZoneError {
    TimeZoneError::Empty => "web_capture.environment.time_zone_empty",
    TimeZoneError::TooLong => "web_capture.environment.time_zone_too_long",
    TimeZoneError::InvalidCharacter => "web_capture.environment.time_zone_invalid_character",
});

// Shared core-model errors live here so consumers keep one registry and `yosoi-types` stays clean.
map_error_codes!(OccurrenceIdParseError {
    OccurrenceIdParseError::InvalidUuid => "web_capture.identity.uuid_invalid",
    OccurrenceIdParseError::NonCanonical => "web_capture.identity.uuid_non_canonical",
    OccurrenceIdParseError::NotRandomV4 => "web_capture.identity.uuid_not_random_v4",
});
map_unit_error_code!(ArtifactIdError => "web_capture.artifact.id_zero");
map_error_codes!(NamespacedIdError {
    NamespacedIdError::Empty => "web_capture.vocabulary.id_empty",
    NamespacedIdError::TooLong => "web_capture.vocabulary.id_too_long",
    NamespacedIdError::InvalidStart => "web_capture.vocabulary.id_invalid_start",
    NamespacedIdError::InvalidEnd => "web_capture.vocabulary.id_invalid_end",
    NamespacedIdError::InvalidCharacter => "web_capture.vocabulary.id_invalid_character",
    NamespacedIdError::MissingNamespace => "web_capture.vocabulary.id_missing_namespace",
    NamespacedIdError::EmptySegment => "web_capture.vocabulary.id_empty_segment",
});
map_error_codes!(ProducerVersionError {
    ProducerVersionError::Empty => "web_capture.producer.version_empty",
    ProducerVersionError::TooLong => "web_capture.producer.version_too_long",
    ProducerVersionError::InvalidCharacter => "web_capture.producer.version_invalid_character",
});
map_unit_error_code!(SchemaVersionError => "web_capture.schema.version_zero");
map_error_codes!(Sha256DigestParseError {
    Sha256DigestParseError::InvalidLength => "web_capture.digest.sha256_invalid_length",
    Sha256DigestParseError::InvalidEncoding => "web_capture.digest.sha256_invalid_encoding",
});
map_error_codes!(ArtifactRecordError {
    ArtifactRecordError::MissingDigest => "web_capture.artifact.digest_missing",
    ArtifactRecordError::UnexpectedDigest => "web_capture.artifact.digest_unexpected",
    ArtifactRecordError::MissingReason => "web_capture.artifact.availability_reason_missing",
    ArtifactRecordError::UnexpectedReason => "web_capture.artifact.availability_reason_unexpected",
});
map_error_codes!(ActivityReceiptError {
    ActivityReceiptError::InvalidTimeWindow => "web_capture.receipt.time_window_invalid",
    ActivityReceiptError::UnexpectedSignal => "web_capture.receipt.signal_unexpected",
    ActivityReceiptError::MissingSignal => "web_capture.receipt.signal_missing",
    ActivityReceiptError::DuplicateArtifactId => "web_capture.receipt.artifact_id_duplicate",
    ActivityReceiptError::ForeignOutputActivity => "web_capture.receipt.output_activity_foreign",
    ActivityReceiptError::OutputTimeOutsideActivity => "web_capture.receipt.output_time_outside_activity",
});
map_unit_error_code!(CaptureReceiptError => "web_capture.receipt.capture_identity_mismatch");

map_error_codes!(MediaTypeError {
    MediaTypeError::Empty => "web_capture.artifact.media_type_empty",
    MediaTypeError::TooLong => "web_capture.artifact.media_type_too_long",
    MediaTypeError::InvalidFormat => "web_capture.artifact.media_type_invalid_format",
    MediaTypeError::InvalidCharacter => "web_capture.artifact.media_type_invalid_character",
});
map_unit_error_code!(ArtifactByteExtentError => "web_capture.artifact.byte_extent_invalid");
map_unit_error_code!(WebArtifactMetadataError => "web_capture.artifact.metadata_invalid");
map_unit_error_code!(ArtifactCollectionError => "web_capture.artifact.collection_empty");
map_error_codes!(WebProviderCapabilityProfileError {
    WebProviderCapabilityProfileError::BrowserArtifactOnHttpProfile { .. } =>
        "web_capture.artifact.provider_profile_browser_artifact_on_http",
});
map_error_codes!(WebArtifactManifestError {
    WebArtifactManifestError::UnexpectedResult { .. } =>
        "web_capture.artifact.manifest_unexpected_result",
    WebArtifactManifestError::MissingResult { .. } =>
        "web_capture.artifact.manifest_missing_result",
});
map_error_codes!(WebCaptureError {
    WebCaptureError::AcquisitionCapabilityMismatch => "web_capture.finalization.acquisition_capability_mismatch",
    WebCaptureError::EnvironmentMismatch => "web_capture.finalization.environment_mismatch",
    WebCaptureError::BrowserModeMismatch => "web_capture.finalization.browser_mode_mismatch",
    WebCaptureError::CapabilityProducerMismatch => "web_capture.finalization.capability_producer_mismatch",
    WebCaptureError::CapabilityResultMismatch { .. } => "web_capture.finalization.capability_result_mismatch",
    WebCaptureError::ArtifactMultiplicityExceeded { .. } => "web_capture.finalization.artifact_multiplicity_exceeded",
    WebCaptureError::ForeignArtifact => "web_capture.finalization.artifact_foreign",
    WebCaptureError::ArtifactTimeOutsideWindow => "web_capture.finalization.artifact_time_outside_window",
    WebCaptureError::DuplicateArtifact => "web_capture.finalization.artifact_duplicate",
    WebCaptureError::ReceiptOutputMismatch => "web_capture.finalization.receipt_output_mismatch",
    WebCaptureError::ForeignBrowserExecution => "web_capture.finalization.browser_execution_foreign",
    WebCaptureError::BrowserExecutionStrategyMismatch => "web_capture.finalization.browser_execution_strategy_mismatch",
    WebCaptureError::BrowserExecutionEnvironmentMismatch => "web_capture.finalization.browser_execution_environment_mismatch",
    WebCaptureError::BrowserChallengeStrategyMismatch => "web_capture.finalization.browser_challenge_strategy_mismatch",
    WebCaptureError::BrowserChallengeEnvironmentMismatch => "web_capture.finalization.browser_challenge_environment_mismatch",
    WebCaptureError::InvalidBrowserChallenge => "web_capture.finalization.browser_challenge_invalid",
    WebCaptureError::ForeignRelationship => "web_capture.finalization.relationship_foreign",
    WebCaptureError::BrowserArtifactContextMismatch => "web_capture.finalization.browser_artifact_context_mismatch",
    WebCaptureError::CompletenessMismatch => "web_capture.finalization.completeness_mismatch",
});
