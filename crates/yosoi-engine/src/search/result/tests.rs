use crate::search::{
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
