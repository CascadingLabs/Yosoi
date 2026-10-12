use crate::internal::documents::{
    PinnedLocator, PinnedOutputLocator, Plan, PlanError, QueryError, output,
};
use thiserror::Error;

#[derive(Clone, Debug, Eq, Error, PartialEq)]
/// Pinned Contract locator declarations failed query construction or portable plan compilation.
pub enum ContractLocatorError {
    #[error(transparent)]
    /// A pinned root or field query/projection has invalid supported semantics.
    Query(#[from] QueryError),
    #[error(transparent)]
    /// Named pinned outputs and region declarations cannot form a supported plan.
    Plan(#[from] PlanError),
}

#[doc(hidden)]
pub fn compile_contract_plan(
    contract_id: &'static str,
    root: Option<PinnedLocator>,
    fields: &[(&'static str, PinnedOutputLocator)],
) -> Result<Plan, ContractLocatorError> {
    let region = root
        .map(|locator| locator.compile_region(contract_id))
        .transpose()?;
    let mut outputs = Vec::with_capacity(fields.len());
    for (field_id, locator) in fields {
        outputs.push(output(*field_id, locator.compile(region.as_ref())?)?);
    }
    Ok(Plan::new(outputs)?)
}
