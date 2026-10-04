use thiserror::Error;
use yosoi_documents::{PinnedLocator, PinnedOutputLocator, Plan, PlanError, QueryError, output};

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ContractLocatorError {
    #[error(transparent)]
    Query(#[from] QueryError),
    #[error(transparent)]
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
