//! Normalized provider result types and bounded retained content.

mod page;
#[cfg(test)]
mod tests;
mod types;

pub use page::SearchPage;
pub use types::{
    FeatureCoverage, ImageResult, LocalPlace, SearchCoverage, SearchFeature, SearchHit,
    SearchHitMetadata, SearchIssue, SearchIssueKind, SearchResultUrl, WebCoverage,
};
