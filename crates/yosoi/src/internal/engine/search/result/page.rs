use std::fmt;

use super::{SearchCoverage, SearchFeature, SearchHit, SearchIssue, SearchIssueKind, WebCoverage};

/// Normalized content for one provider response.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
pub struct SearchPage {
    hits: Vec<SearchHit>,
    features: Vec<SearchFeature>,
    coverage: SearchCoverage,
    issues: Vec<SearchIssue>,
}

impl SearchPage {
    pub(in crate::internal::engine) const fn new(
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

    pub(in crate::internal::engine) fn with_query_relaxation(
        mut self,
        maximum_issues: usize,
    ) -> Self {
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
    pub(in crate::internal::engine) fn retained_string_bytes(&self) -> Option<usize> {
        let mut total = 0_usize;
        for hit in &self.hits {
            add_bytes(&mut total, hit.url().as_str())?;
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
