use yosoi_documents::{
    DocumentExecutionTuning, ResourceBudget, ResourceBudgetError, ResourceBudgetValues,
};
use yosoi_policy::{Policy, Tuning, TuningMode};

/// Maps passive SDK tuning into the Documents owner's execution vocabulary.
pub const fn document_tuning(tuning: Tuning) -> DocumentExecutionTuning {
    match tuning.mode() {
        TuningMode::Default => DocumentExecutionTuning::Default,
    }
}

/// Resolves passive policy declarations into the private document budget used
/// by one facade-owned parse or locate operation.
///
/// Policy chooses bounds. Document profiles, query/projection meaning,
/// coordinates, completeness, and failure behavior remain owned by the
/// Documents and Locators domain.
pub fn resource_budget_for_policy(policy: &Policy) -> Result<ResourceBudget, ResourceBudgetError> {
    ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: policy.documents.max_input_bytes.get(),
        max_nodes: policy.documents.max_nodes.get(),
        max_selector_visits: policy.locators.max_selector_visits.get(),
        max_query_bytes: policy.locators.max_query_bytes.get(),
        max_query_steps: policy.locators.max_query_steps.get(),
        max_regions: policy.locators.max_regions.get(),
        max_matches: policy.locators.max_matches.get(),
        max_captures: policy.locators.max_captures.get(),
        max_depth: policy.documents.max_depth.get(),
        max_output_bytes: policy.locators.max_output_bytes.get(),
    })
}
