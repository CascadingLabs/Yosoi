use super::{Contract, ExtractionLimits, ExtractorOutput};
use crate::internal::{
    documents as yosoi_documents, extractor as yosoi_extractor, policy as yosoi_policy,
};

#[doc(hidden)]
pub fn extract_contract<T: Contract>(
    located: &yosoi_documents::LocateOutcome,
) -> ExtractorOutput<T> {
    let policy = yosoi_policy::Policy::default();
    let max_matches = policy.locators.max_matches.get();
    let max_regions = u64::from(policy.locators.max_regions.get());
    yosoi_extractor::extract_contract_with_limits(
        located,
        ExtractionLimits {
            max_scanned_regions: max_matches,
            max_scanned_findings: max_matches,
            max_matching_findings: max_matches,
            max_candidates: max_regions,
            max_values_per_field: max_matches,
            max_retained_evidence: max_matches,
            max_diagnostics: max_matches,
        },
    )
}

#[doc(hidden)]
pub fn extract_contract_with_limit<T: Contract>(
    located: &yosoi_documents::LocateOutcome,
    maximum_findings: u64,
) -> ExtractorOutput<T> {
    yosoi_extractor::extract_contract_with_limit(located, maximum_findings)
}

#[doc(hidden)]
pub fn extract_contract_with_limits<T: Contract>(
    located: &yosoi_documents::LocateOutcome,
    limits: ExtractionLimits,
) -> ExtractorOutput<T> {
    yosoi_extractor::extract_contract_with_limits(located, limits)
}
