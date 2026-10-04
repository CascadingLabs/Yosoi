use std::num::NonZeroU16;

use crate::PolicyError;

use super::plan::required_total_results;

#[test]
fn total_hit_budget_uses_checked_multiplication_and_conversion() {
    assert_eq!(
        required_total_results(usize::MAX, NonZeroU16::MAX),
        Err(PolicyError::SearchPlanArithmeticOverflow)
    );
    assert_eq!(
        required_total_results(4, NonZeroU16::new(10).unwrap_or(NonZeroU16::MIN)),
        Ok(40)
    );
}
