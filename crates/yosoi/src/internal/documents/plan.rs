#[path = "plan_authoring.rs"]
mod authoring;
#[path = "plan_compatibility.rs"]
mod compatibility;
#[path = "plan_model.rs"]
mod model;
#[path = "plan_validation.rs"]
mod validation;

pub use authoring::{
    NamedOutput, OutputId, OutputPlan, OutputSelection, RegionId, RegionPlan, output,
};
pub use model::CompiledOutput;
pub use model::{Plan, PlanError};
