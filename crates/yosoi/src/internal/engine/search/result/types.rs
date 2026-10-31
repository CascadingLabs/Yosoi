use std::{fmt, num::NonZeroU16};

use crate::internal::web_capture::{RequestedWebTarget, WebUrlParseError};

/// A provider-reported destination that is safe to offer for a later Request.
/// Parsing accepts only absolute HTTP(S) URLs and rejects embedded credentials.
#[derive(Clone, Eq, Hash, PartialEq, serde::Serialize)]
#[serde(transparent)]
pub struct SearchResultUrl(RequestedWebTarget);

impl SearchResultUrl {
    /// Parses an absolute HTTP(S) destination without fetching it.
    ///
    /// Returns [`WebUrlParseError`] for invalid URLs, unsupported schemes, or
    /// embedded credentials. Validation does not establish destination trust.
    pub fn parse(value: &str) -> Result<Self, WebUrlParseError> {
        RequestedWebTarget::parse(value).map(Self)
    }

    /// Borrows the validated URL text for as long as this value is retained.
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    /// Creates an independent target for explicit caller handoff to Requests.
    pub fn as_request_target(&self) -> RequestedWebTarget {
        self.0.clone()
    }
}

impl fmt::Display for SearchResultUrl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&self.0, formatter)
    }
}

impl fmt::Debug for SearchResultUrl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SearchResultUrl(<redacted>)")
    }
}

/// Optional metadata shown by the provider; it is not fetched from the target.
#[derive(Clone, Default, Eq, PartialEq, serde::Serialize)]
pub struct SearchHitMetadata {
    /// Provider-displayed title, absent when the parser found no title.
    pub title: Option<String>,
    /// Provider-displayed excerpt; it is not verified destination content.
    pub snippet: Option<String>,
    /// Human-readable address shown by the provider, distinct from the destination URL.
    pub display_url: Option<String>,
    /// Provider-displayed publisher label, without independent identity verification.
    pub publisher: Option<String>,
    /// Provider-reported display date, not a verified publication date.
    pub published_at: Option<String>,
    /// Validated thumbnail destination, if supplied; the image has not been fetched.
    pub thumbnail_url: Option<SearchResultUrl>,
}

impl fmt::Debug for SearchHitMetadata {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchHitMetadata")
            .field("title_present", &self.title.is_some())
            .field("snippet_present", &self.snippet.is_some())
            .field("display_url_present", &self.display_url.is_some())
            .field("publisher_present", &self.publisher.is_some())
            .field("published_at_present", &self.published_at.is_some())
            .field("thumbnail_present", &self.thumbnail_url.is_some())
            .finish()
    }
}

/// The actual order of one accepted organic result within its provider page.
/// Gaps remain possible when an earlier row is rejected or duplicated.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
pub struct SearchHit {
    url: SearchResultUrl,
    organic_rank: NonZeroU16,
    placement_index: NonZeroU16,
    metadata: SearchHitMetadata,
}

impl SearchHit {
    pub(in crate::internal::engine) const fn new(
        url: SearchResultUrl,
        organic_rank: NonZeroU16,
        placement_index: NonZeroU16,
    ) -> Self {
        Self {
            url,
            organic_rank,
            placement_index,
            metadata: SearchHitMetadata {
                title: None,
                snippet: None,
                display_url: None,
                publisher: None,
                published_at: None,
                thumbnail_url: None,
            },
        }
    }

    /// Borrows the validated destination for an explicit later Request.
    pub const fn url(&self) -> &SearchResultUrl {
        &self.url
    }

    /// Returns the one-based organic row rank; rejected or duplicate rows can leave gaps.
    pub const fn organic_rank(&self) -> NonZeroU16 {
        self.organic_rank
    }

    /// Returns the one-based provider-page placement, which also counts rich features.
    pub const fn placement_index(&self) -> NonZeroU16 {
        self.placement_index
    }

    /// Borrows the provider-displayed title, or `None` if unavailable.
    pub fn title(&self) -> Option<&str> {
        self.metadata.title.as_deref()
    }

    /// Borrows the provider-displayed excerpt without fetching the destination.
    pub fn snippet(&self) -> Option<&str> {
        self.metadata.snippet.as_deref()
    }

    /// Borrows the displayed address, which need not equal the validated destination.
    pub fn display_url(&self) -> Option<&str> {
        self.metadata.display_url.as_deref()
    }

    /// Borrows the provider-reported publisher label, if present.
    pub fn publisher(&self) -> Option<&str> {
        self.metadata.publisher.as_deref()
    }

    /// Provider-reported display date. It is not a verified publication date.
    pub fn published_at(&self) -> Option<&str> {
        self.metadata.published_at.as_deref()
    }

    /// Borrows the validated thumbnail URL; no image fetch is implied.
    pub const fn thumbnail_url(&self) -> Option<&SearchResultUrl> {
        self.metadata.thumbnail_url.as_ref()
    }

    /// Borrows all optional provider-displayed metadata for this hit.
    pub const fn metadata(&self) -> &SearchHitMetadata {
        &self.metadata
    }

    pub(in crate::internal::engine) fn with_metadata(
        mut self,
        metadata: SearchHitMetadata,
    ) -> Self {
        self.metadata = metadata;
        self
    }
}

impl fmt::Debug for SearchHit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchHit")
            .field("organic_rank", &self.organic_rank)
            .field("placement_index", &self.placement_index)
            .field("url", &"<redacted>")
            .finish_non_exhaustive()
    }
}

/// Completeness of organic web-result extraction.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WebCoverage {
    /// Extraction completed within the supported response and configured limits.
    /// This is not a claim that the provider searched every possible web page.
    Complete,
    /// Some organic result evidence was omitted, limited, or obtained through query recovery.
    Partial,
}

/// Whether rich features were attempted, independent of whether any existed.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FeatureCoverage {
    /// Rich-feature extraction was not attempted; an empty feature list proves no absence.
    NotCollected,
    /// Supported rich-feature extraction completed, possibly finding no features.
    Collected,
    /// Rich-feature extraction was attempted but some feature evidence is incomplete.
    Partial,
}

/// Independent completeness claims for organic hits and supported rich features.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
pub struct SearchCoverage {
    web: WebCoverage,
    rich_features: FeatureCoverage,
}

impl SearchCoverage {
    /// Combines extraction coverage facts without changing or verifying either claim.
    pub const fn new(web: WebCoverage, rich_features: FeatureCoverage) -> Self {
        Self { web, rich_features }
    }

    /// Returns organic-result extraction coverage for the acquired provider page.
    pub const fn web(self) -> WebCoverage {
        self.web
    }

    /// Returns whether supported rich features were collected completely, partially, or not at all.
    pub const fn rich_features(self) -> FeatureCoverage {
        self.rich_features
    }
}

/// A typed rich placement. These never consume an organic web rank.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SearchFeature {
    /// A placement identified by the provider as sponsored content.
    Sponsored {
        /// One-based position among provider-page placements, not an organic rank.
        placement_index: NonZeroU16,
        /// Validated HTTP(S) destination; no destination fetch has occurred.
        destination: SearchResultUrl,
        /// Provider-displayed sponsorship label, when available.
        label: Option<String>,
    },
    /// A provider-displayed answer and its reported citation destinations.
    Answer {
        /// One-based position among provider-page placements.
        placement_index: NonZeroU16,
        /// Answer text shown by the provider, without factual verification.
        text: String,
        /// Validated citation destinations; their contents have not been fetched.
        citations: Vec<SearchResultUrl>,
    },
    /// A provider-displayed group of image results.
    ImageGallery {
        /// One-based position of the gallery among provider-page placements.
        placement_index: NonZeroU16,
        /// Image and source-page destinations extracted from the gallery.
        images: Vec<ImageResult>,
    },
    /// A provider-displayed collection of local places and an optional map destination.
    LocalPack {
        /// One-based position of the local pack among provider-page placements.
        placement_index: NonZeroU16,
        /// Provider-reported places, without independent business verification.
        places: Vec<LocalPlace>,
        /// Validated map destination, if supplied by the provider.
        map_url: Option<SearchResultUrl>,
    },
}

impl fmt::Debug for SearchFeature {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sponsored {
                placement_index, ..
            } => formatter
                .debug_struct("Sponsored")
                .field("placement_index", placement_index)
                .finish_non_exhaustive(),
            Self::Answer {
                placement_index,
                citations,
                ..
            } => formatter
                .debug_struct("Answer")
                .field("placement_index", placement_index)
                .field("citation_count", &citations.len())
                .finish_non_exhaustive(),
            Self::ImageGallery {
                placement_index,
                images,
            } => formatter
                .debug_struct("ImageGallery")
                .field("placement_index", placement_index)
                .field("image_count", &images.len())
                .finish(),
            Self::LocalPack {
                placement_index,
                places,
                ..
            } => formatter
                .debug_struct("LocalPack")
                .field("placement_index", placement_index)
                .field("place_count", &places.len())
                .finish_non_exhaustive(),
        }
    }
}

/// An image destination paired with the provider-reported page hosting it.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
pub struct ImageResult {
    /// Validated image destination; no image bytes are acquired by this value.
    pub image_url: SearchResultUrl,
    /// Validated source-page destination reported by the provider.
    pub source_page_url: SearchResultUrl,
}

impl fmt::Debug for ImageResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ImageResult(<redacted>)")
    }
}

/// A local-place label and destination extracted from a provider's local pack.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
pub struct LocalPlace {
    /// Provider-displayed place name, without independent identity verification.
    pub name: String,
    /// Validated destination for the place; it has not been fetched.
    pub place_url: SearchResultUrl,
}

impl fmt::Debug for LocalPlace {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LocalPlace(<redacted>)")
    }
}

/// Nonfatal extraction issue or uncertainty about query relevance.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchIssueKind {
    /// A row's destination failed absolute HTTP(S) URL validation.
    InvalidDestination,
    /// A destination already present in the extracted results was omitted.
    DuplicateDestination,
    /// A recognized result row lacked data required to construct a result.
    MissingRequiredField,
    /// A candidate row did not match a supported provider result layout.
    UnrecognizedResultRow,
    /// A configured output budget limited retained results or features.
    OutputLimit,
    /// Visible title, snippet, or destination path could not confirm the requested topic and intent.
    /// Hits remain available with partial coverage; this is not a mismatch.
    QueryRelevanceUnknown,
    /// A provider-owned redirect could not be resolved to a validated destination.
    RedirectResolutionFailed,
    /// The per-search limit of eight Google wrapper requests left this row unattempted.
    RedirectResolutionLimit,
    /// A Google result wrapper redirected to an observed Google challenge endpoint.
    RedirectChallenge,
    /// Bing supplied off-query rows for the original query; these hits came
    /// from one shorter, disclosed content-term query.
    QueryRelaxed,
}

/// Bounded evidence of an extraction issue or uncertain query relevance,
/// without response excerpts.
#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize)]
pub struct SearchIssue {
    /// One-based affected placement, or `None` for an issue spanning the response.
    pub placement_index: Option<NonZeroU16>,
    /// Classification explaining which evidence was rejected or limited.
    pub kind: SearchIssueKind,
}
