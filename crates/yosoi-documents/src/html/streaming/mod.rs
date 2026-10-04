mod config;
mod limits;
mod materialize;
mod names;
mod plan;
mod record_certification;
mod record_metrics;
mod routing;
mod scanner;
mod support;
mod tag_rules;
mod tokenizer;
mod tree_text;

pub(super) use plan::{CompiledStreamingPlan, compile_plan};
pub(super) use routing::try_locate;

#[cfg(test)]
#[path = "streaming_test_support_tests.rs"]
mod test_support_tests;

#[cfg(test)]
#[path = "streaming_admission_tests.rs"]
mod admission_tests;

#[cfg(test)]
#[path = "streaming_fallback_tests.rs"]
mod fallback_tests;

#[cfg(test)]
#[path = "streaming_resource_proof_tests.rs"]
mod resource_proof_tests;
