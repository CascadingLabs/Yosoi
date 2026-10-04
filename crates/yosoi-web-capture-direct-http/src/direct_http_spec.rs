//! Explicit, validated runtime input for one Direct HTTP capture attempt.

use std::collections::BTreeSet;

use thiserror::Error;
use yosoi_types::{CaptureId, OperationId, Producer, Schema};

use crate::{
    CaptureDeadline, DirectHttpAcquisition, ObservationPolicy, RequestedWebTarget,
    SettlementPolicy, WebAcquisitionStrategy, WebArtifactFamily, WebArtifactRequestSet,
    WebCaptureRequest,
};

mod redirect;
mod validation;

pub use redirect::{DirectHttpRedirectPolicy, RedirectHopLimit};
use validation::{validate_artifact_requests, validate_output_schemas};

/// XML interpretation accepted by a Direct HTTP source capture.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum XmlSourceProfile {
    /// Ordinary XML and media types using the `+xml` suffix.
    Generic,
    /// XHTML, which uses XML rather than HTML decoding and parsing semantics.
    Xhtml,
}

/// Closed initial source formats accepted by Direct HTTP capture.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum AcceptedSourceFormat {
    /// HTML source.
    Html,
    /// XML source with an explicit generic or XHTML profile.
    Xml(XmlSourceProfile),
    /// JSON source.
    Json,
    /// Explicitly declared plain text.
    PlainText,
}

/// Non-empty set of source formats accepted by one attempt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AcceptedSourceFormats(BTreeSet<AcceptedSourceFormat>);

impl AcceptedSourceFormats {
    /// Validates a non-empty accepted-format set.
    pub fn new(
        formats: impl IntoIterator<Item = AcceptedSourceFormat>,
    ) -> Result<Self, DirectHttpCaptureSpecError> {
        let formats = formats.into_iter().collect::<BTreeSet<_>>();
        if formats.is_empty() {
            return Err(DirectHttpCaptureSpecError::EmptyAcceptedFormats);
        }
        Ok(Self(formats))
    }

    /// Returns whether the format is accepted.
    pub fn contains(&self, format: AcceptedSourceFormat) -> bool {
        self.0.contains(&format)
    }

    /// Iterates in the stable closed-enum order.
    pub fn iter(&self) -> impl Iterator<Item = AcceptedSourceFormat> + '_ {
        self.0.iter().copied()
    }
}

/// Independent bounds for each body-processing byte domain.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct DirectHttpContentLimits {
    content_coded: crate::ByteLimit,
    representation: crate::ByteLimit,
    unicode_utf8: crate::ByteLimit,
}

impl DirectHttpContentLimits {
    /// Creates explicit limits for content-coded, decoded, and Unicode UTF-8 bytes.
    pub const fn new(
        content_coded_bytes: crate::ByteLimit,
        representation_bytes: crate::ByteLimit,
        unicode_utf8_bytes: crate::ByteLimit,
    ) -> Self {
        Self {
            content_coded: content_coded_bytes,
            representation: representation_bytes,
            unicode_utf8: unicode_utf8_bytes,
        }
    }

    /// Returns the admitted content-coded input bound.
    pub const fn content_coded_bytes(self) -> crate::ByteLimit {
        self.content_coded
    }

    /// Returns the retained decoded-representation bound.
    pub const fn representation_bytes(self) -> crate::ByteLimit {
        self.representation
    }

    /// Returns the decoded Unicode view bound, measured as UTF-8 bytes.
    pub const fn unicode_utf8_bytes(self) -> crate::ByteLimit {
        self.unicode_utf8
    }
}

/// Required retention for a requested source representation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceRetentionPolicy {
    /// Retain exact decoded representation bytes.
    Representation,
    /// Retain representation bytes and a provenance-linked Unicode view.
    RepresentationAndUnicodeView,
}

impl SourceRetentionPolicy {
    const fn retains_unicode_view(self) -> bool {
        matches!(self, Self::RepresentationAndUnicodeView)
    }
}

/// Behavior when classification selects a format outside the accepted set.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnsupportedSourceFormatBehavior {
    /// Retain source evidence and report the unsupported classification explicitly.
    RetainAndReport,
    /// Retain available source evidence but make the attempt outcome non-successful.
    FailAttempt,
}

/// Output schemas needed to construct source and network artifact provenance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DirectHttpOutputSchemas {
    source: Schema,
    source_representation: Schema,
    network: Option<Schema>,
    unicode_view: Option<Schema>,
}

impl DirectHttpOutputSchemas {
    /// Creates explicit output schemas. The resolved spec validates optional presence.
    pub const fn new(
        source: Schema,
        source_representation: Schema,
        network: Option<Schema>,
        unicode_view: Option<Schema>,
    ) -> Self {
        Self {
            source,
            source_representation,
            network,
            unicode_view,
        }
    }

    /// Returns the source representation schema.
    pub const fn source(&self) -> &Schema {
        &self.source
    }

    /// Returns the canonical source representation evidence schema.
    pub const fn source_representation(&self) -> &Schema {
        &self.source_representation
    }

    /// Returns the minimal HTTP exchange schema when requested.
    pub const fn network(&self) -> Option<&Schema> {
        self.network.as_ref()
    }

    /// Returns the decoded Unicode view schema when retained.
    pub const fn unicode_view(&self) -> Option<&Schema> {
        self.unicode_view.as_ref()
    }
}

/// Complete validated runtime input for one Direct HTTP capture occurrence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedDirectHttpCaptureSpec {
    request: WebCaptureRequest,
    direct_strategy: DirectHttpAcquisition,
    artifacts: WebArtifactRequestSet,
    observation: ObservationPolicy,
    content_limits: DirectHttpContentLimits,
    redirects: DirectHttpRedirectPolicy,
    accepted_formats: AcceptedSourceFormats,
    unsupported_format: UnsupportedSourceFormatBehavior,
    retention: SourceRetentionPolicy,
    producer: Producer,
    operation: OperationId,
    output_schemas: DirectHttpOutputSchemas,
}

/// Invalid combination in a resolved Direct HTTP capture specification.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum DirectHttpCaptureSpecError {
    /// The attempt selected a browser or context-bound acquisition strategy.
    #[error("resolved Direct HTTP capture requires a direct HTTP strategy")]
    WrongStrategy,
    /// No initial source format was accepted.
    #[error("at least one source format must be accepted")]
    EmptyAcceptedFormats,
    /// A redirect-following hop limit was zero.
    #[error("redirect hop limit must be greater than zero")]
    ZeroRedirectHopLimit,
    /// Source evidence was optional or not requested.
    #[error("Direct HTTP capture requires source evidence")]
    SourceMustBeRequired,
    /// A browser-only or otherwise unsupported artifact family was requested.
    #[error("Direct HTTP capture cannot request the {family:?} artifact family")]
    UnsupportedArtifactFamily {
        /// Family unavailable to the initial Direct HTTP producer.
        family: WebArtifactFamily,
    },
    /// Direct HTTP uses terminal response completion rather than quiet settlement.
    #[error("Direct HTTP observation settlement must be disabled")]
    SettlementMustBeDisabled,
    /// Source bytes and source representation facts used the same schema identity.
    #[error("source representation evidence requires a schema distinct from source bytes")]
    SourceRepresentationSchemaMustDiffer,
    /// A retained Unicode view must have its own representation schema.
    #[error("retained Unicode source view requires a schema distinct from source and evidence")]
    UnicodeViewSchemaMustDiffer,
    /// Network evidence was requested without its output schema.
    #[error("requested network evidence requires a network output schema")]
    MissingNetworkSchema,
    /// A network schema was supplied even though network evidence was not requested.
    #[error("unrequested network evidence cannot carry a network output schema")]
    UnexpectedNetworkSchema,
    /// A retained Unicode view lacked its independently versioned schema.
    #[error("retained Unicode source view requires an output schema")]
    MissingUnicodeViewSchema,
    /// A Unicode-view schema was supplied when no such view will be retained.
    #[error("source-only retention cannot carry a Unicode-view schema")]
    UnexpectedUnicodeViewSchema,
}

impl ResolvedDirectHttpCaptureSpec {
    /// Validates every runtime decision before network I/O begins.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        request: WebCaptureRequest,
        artifacts: WebArtifactRequestSet,
        observation: ObservationPolicy,
        content_limits: DirectHttpContentLimits,
        redirects: DirectHttpRedirectPolicy,
        accepted_formats: AcceptedSourceFormats,
        unsupported_format: UnsupportedSourceFormatBehavior,
        retention: SourceRetentionPolicy,
        producer: Producer,
        operation: OperationId,
        output_schemas: DirectHttpOutputSchemas,
    ) -> Result<Self, DirectHttpCaptureSpecError> {
        let WebAcquisitionStrategy::DirectHttp(direct_strategy) = request.strategy() else {
            return Err(DirectHttpCaptureSpecError::WrongStrategy);
        };
        validate_artifact_requests(artifacts)?;
        if !matches!(observation.settlement(), SettlementPolicy::Disabled) {
            return Err(DirectHttpCaptureSpecError::SettlementMustBeDisabled);
        }
        validate_output_schemas(artifacts, retention, &output_schemas)?;

        Ok(Self {
            direct_strategy: direct_strategy.clone(),
            request,
            artifacts,
            observation,
            content_limits,
            redirects,
            accepted_formats,
            unsupported_format,
            retention,
            producer,
            operation,
            output_schemas,
        })
    }

    /// Returns the complete request, including its fresh capture identity.
    pub const fn request(&self) -> &WebCaptureRequest {
        &self.request
    }

    /// Returns the capture occurrence allocated for this attempt.
    pub const fn capture_id(&self) -> CaptureId {
        self.request.capture_id()
    }

    /// Returns the requested target.
    pub const fn target(&self) -> &RequestedWebTarget {
        self.request.target()
    }

    /// Returns the validated Direct HTTP acquisition strategy.
    pub const fn strategy(&self) -> &DirectHttpAcquisition {
        &self.direct_strategy
    }

    /// Returns requested source and optional network artifact families.
    pub const fn artifacts(&self) -> WebArtifactRequestSet {
        self.artifacts
    }

    /// Returns the observation limits and disabled settlement policy.
    pub const fn observation(&self) -> &ObservationPolicy {
        &self.observation
    }

    /// Returns the overall attempt deadline from the observation policy.
    pub const fn maximum_elapsed(&self) -> CaptureDeadline {
        self.observation.limits().maximum_elapsed()
    }

    /// Returns response-body byte-domain limits.
    pub const fn content_limits(&self) -> DirectHttpContentLimits {
        self.content_limits
    }

    /// Returns redirect behavior.
    pub const fn redirects(&self) -> DirectHttpRedirectPolicy {
        self.redirects
    }

    /// Returns the non-empty accepted source-format set.
    pub const fn accepted_formats(&self) -> &AcceptedSourceFormats {
        &self.accepted_formats
    }

    /// Returns behavior for a classified but unsupported source format.
    pub const fn unsupported_format(&self) -> UnsupportedSourceFormatBehavior {
        self.unsupported_format
    }

    /// Returns source retention requirements.
    pub const fn retention(&self) -> SourceRetentionPolicy {
        self.retention
    }

    /// Returns the producer responsible for this attempt.
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }

    /// Returns the receipt operation identity.
    pub const fn operation(&self) -> &OperationId {
        &self.operation
    }

    /// Returns schemas for requested retained outputs.
    pub const fn output_schemas(&self) -> &DirectHttpOutputSchemas {
        &self.output_schemas
    }
}
