use super::plan::CompiledSelectorPlan;
use super::scanner::ScanResult;
use super::support::ResourceBudget;

pub(super) fn limits_are_safe(
    scan: &ScanResult,
    plan: &CompiledSelectorPlan,
    budget: ResourceBudget,
) -> bool {
    if scan.retained_node_upper > budget.max_nodes()
        || scan.depth_upper > u64::from(budget.max_depth())
    {
        return false;
    }
    let rightmost_work = scan
        .element_upper
        .saturating_mul(plan.rightmost_test_count.saturating_add(2))
        .saturating_add(
            scan.retained_node_upper
                .saturating_mul(plan.rightmost_test_count),
        )
        .saturating_add(
            scan.element_upper
                .saturating_mul(plan.rightmost_test_count)
                .saturating_mul(scan.max_attribute_count),
        );
    let ancestor_work = scan
        .rightmost_depth_sum_upper
        .saturating_mul(plan.leftmost_test_count.saturating_add(2))
        .saturating_add(
            scan.rightmost_match_count
                .saturating_mul(scan.max_attribute_count),
        );
    let selection_work = scan
        .element_upper
        .saturating_add(rightmost_work)
        .saturating_add(ancestor_work);
    scan.scan_work.saturating_add(selection_work) <= budget.max_selector_visits()
}
