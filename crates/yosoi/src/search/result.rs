use std::{fmt, num::NonZeroU16};

use yosoi_web_capture::{RequestedWebTarget, WebUrlParseError};

/// A provider-reported destination that is safe to offer for a later Request.
/// Parsing accepts only absolute HTTP(S) URLs and rejects embedded credentials.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct SearchResultUrl(RequestedWebTarget);

impl SearchResultUrl {
    pub fn parse(value: &str) -> Result<Self, WebUrlParseError> {
        RequestedWebTarget::parse(value).map(Self)
    }

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
#[derive(Clone, Default, Eq, PartialEq)]
pub struct SearchHitMetadata {
    pub title: Option<String>,
    pub snippet: Option<String>,
    pub display_url: Option<String>,
    pub publisher: Option<String>,
    /// Provider-reported display date, not a verified publication date.
    pub published_at: Option<String>,
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
#[derive(Clone, Eq, PartialEq)]
pub struct SearchHit {
    url: SearchResultUrl,
    organic_rank: NonZeroU16,
    placement_index: NonZeroU16,
    metadata: SearchHitMetadata,
}

impl SearchHit {
    pub(crate) const fn new(
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

    pub const fn url(&self) -> &SearchResultUrl {
        &self.url
    }

    pub const fn organic_rank(&self) -> NonZeroU16 {
        self.organic_rank
    }

    pub const fn placement_index(&self) -> NonZeroU16 {
        self.placement_index
    }

    pub fn title(&self) -> Option<&str> {
        self.metadata.title.as_deref()
    }

    pub fn snippet(&self) -> Option<&str> {
        self.metadata.snippet.as_deref()
    }

    pub fn display_url(&self) -> Option<&str> {
        self.metadata.display_url.as_deref()
    }

    pub fn publisher(&self) -> Option<&str> {
        self.metadata.publisher.as_deref()
    }

    /// Provider-reported display date. It is not a verified publication date.
    pub fn published_at(&self) -> Option<&str> {
        self.metadata.published_at.as_deref()
    }

    pub const fn thumbnail_url(&self) -> Option<&SearchResultUrl> {
        self.metadata.thumbnail_url.as_ref()
    }

    pub const fn metadata(&self) -> &SearchHitMetadata {
        &self.metadata
    }

    pub(crate) fn with_metadata(mut self, metadata: SearchHitMetadata) -> Self {
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
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WebCoverage {
    Complete,
    Partial,
}

/// Whether rich features were attempted, independent of whether any existed.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FeatureCoverage {
    NotCollected,
    Collected,
    Partial,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SearchCoverage {
    web: WebCoverage,
    rich_features: FeatureCoverage,
}

impl SearchCoverage {
    pub const fn new(web: WebCoverage, rich_features: FeatureCoverage) -> Self {
        Self { web, rich_features }
    }

    pub const fn web(self) -> WebCoverage {
        self.web
    }

    pub const fn rich_features(self) -> FeatureCoverage {
        self.rich_features
    }
}

/// A typed rich placement. These never consume an organic web rank.
#[derive(Clone, Eq, PartialEq)]
pub enum SearchFeature {
    Sponsored {
        placement_index: NonZeroU16,
        destination: SearchResultUrl,
        label: Option<String>,
    },
    Answer {
        placement_index: NonZeroU16,
        text: String,
        citations: Vec<SearchResultUrl>,
    },
    ImageGallery {
        placement_index: NonZeroU16,
        images: Vec<ImageResult>,
    },
    LocalPack {
        placement_index: NonZeroU16,
        places: Vec<LocalPlace>,
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

#[derive(Clone, Eq, PartialEq)]
pub struct ImageResult {
    pub image_url: SearchResultUrl,
    pub source_page_url: SearchResultUrl,
}

impl fmt::Debug for ImageResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ImageResult(<redacted>)")
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct LocalPlace {
    pub name: String,
    pub place_url: SearchResultUrl,
}

impl fmt::Debug for LocalPlace {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LocalPlace(<redacted>)")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SearchIssueKind {
    InvalidDestination,
    DuplicateDestination,
    MissingRequiredField,
    UnrecognizedResultRow,
    OutputLimit,
    /// Bing supplied off-query rows for the original query; these hits came
    /// from one shorter, disclosed content-term query.
    QueryRelaxed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SearchIssue {
    pub placement_index: Option<NonZeroU16>,
    pub kind: SearchIssueKind,
}

/// Normalized content for one provider response.
#[derive(Clone, Eq, PartialEq)]
pub struct SearchPage {
    hits: Vec<SearchHit>,
    features: Vec<SearchFeature>,
    coverage: SearchCoverage,
    issues: Vec<SearchIssue>,
}

impl SearchPage {
    pub(crate) const fn new(
        hits: Vec<SearchHit>,
        features: Vec<SearchFeature>,
        coverage: SearchCoverage,
        issues: Vec<SearchIssue>,
    ) -> Self {
        Self {
            hits,
            features,
            coverage,
            issues,
        }
    }

    pub fn hits(&self) -> &[SearchHit] {
        &self.hits
    }

    pub fn features(&self) -> &[SearchFeature] {
        &self.features
    }

    pub const fn coverage(&self) -> SearchCoverage {
        self.coverage
    }

    pub fn issues(&self) -> &[SearchIssue] {
        &self.issues
    }

    pub(crate) fn with_query_relaxation(mut self, maximum_issues: usize) -> Self {
        self.coverage = SearchCoverage::new(WebCoverage::Partial, self.coverage.rich_features());
        if maximum_issues > 0 {
            if self.issues.len() >= maximum_issues {
                self.issues.truncate(maximum_issues.saturating_sub(1));
            }
            self.issues.push(SearchIssue {
                placement_index: None,
                kind: SearchIssueKind::QueryRelaxed,
            });
        }
        self
    }

    /// Checked retained URL and text bytes for the Search scheduler's shared
    /// output budget. Record framing and JSON escaping are separate concerns.
    pub(crate) fn retained_string_bytes(&self) -> Option<usize> {
        let mut total = 0_usize;
        for hit in &self.hits {
            add_bytes(&mut total, hit.url.as_str())?;
            for value in [
                hit.title(),
                hit.snippet(),
                hit.display_url(),
                hit.publisher(),
                hit.published_at(),
            ]
            .into_iter()
            .flatten()
            {
                add_bytes(&mut total, value)?;
            }
            if let Some(thumbnail) = hit.thumbnail_url() {
                add_bytes(&mut total, thumbnail.as_str())?;
            }
        }
        for feature in &self.features {
            match feature {
                SearchFeature::Sponsored {
                    destination, label, ..
                } => {
                    add_bytes(&mut total, destination.as_str())?;
                    if let Some(label) = label {
                        add_bytes(&mut total, label)?;
                    }
                }
                SearchFeature::Answer {
                    text, citations, ..
                } => {
                    add_bytes(&mut total, text)?;
                    for citation in citations {
                        add_bytes(&mut total, citation.as_str())?;
                    }
                }
                SearchFeature::ImageGallery { images, .. } => {
                    for image in images {
                        add_bytes(&mut total, image.image_url.as_str())?;
                        add_bytes(&mut total, image.source_page_url.as_str())?;
                    }
                }
                SearchFeature::LocalPack {
                    places, map_url, ..
                } => {
                    for place in places {
                        add_bytes(&mut total, &place.name)?;
                        add_bytes(&mut total, place.place_url.as_str())?;
                    }
                    if let Some(map_url) = map_url {
                        add_bytes(&mut total, map_url.as_str())?;
                    }
                }
            }
        }
        Some(total)
    }
}

fn add_bytes(total: &mut usize, value: &str) -> Option<()> {
    *total = total.checked_add(value.len())?;
    Some(())
}

impl fmt::Debug for SearchPage {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchPage")
            .field("hit_count", &self.hits.len())
            .field("feature_count", &self.features.len())
            .field("issue_count", &self.issues.len())
            .field("coverage", &self.coverage)
            .finish()
    }
}

#[cfg(test)]
mod recovery_tests {
    use super::{
        FeatureCoverage, SearchCoverage, SearchIssue, SearchIssueKind, SearchPage, WebCoverage,
    };

    #[test]
    fn recovery_issue_stays_within_the_per_provider_issue_limit() {
        let page = SearchPage::new(
            Vec::new(),
            Vec::new(),
            SearchCoverage::new(WebCoverage::Complete, FeatureCoverage::NotCollected),
            vec![SearchIssue {
                placement_index: None,
                kind: SearchIssueKind::InvalidDestination,
            }],
        );
        let page = page.with_query_relaxation(1);
        assert_eq!(page.coverage().web(), WebCoverage::Partial);
        assert_eq!(page.issues().len(), 1);
        assert_eq!(
            page.issues().first().map(|issue| issue.kind),
            Some(SearchIssueKind::QueryRelaxed)
        );
    }
}
