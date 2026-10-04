use super::{BrowserByteDomain, families::family_index};
use crate::WebArtifactFamily;
use thiserror::Error;
use yosoi_types::Schema;
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
