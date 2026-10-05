//! Python conversion and lifecycle boundary over the public Rust SDK.

mod async_runtime;
mod contracts;
mod documents;
mod errors;
mod identities;
mod locators;
mod map;
mod parsed;
mod policy;
mod requests;
mod responses;
mod scalars;
mod search;
mod vocabulary;

use pyo3::prelude::*;

#[pymodule(gil_used = false)]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add_function(wrap_pyfunction!(scalars::validate_domain_model, module)?)?;
    module.add("browser_enabled", cfg!(feature = "browser"))?;
    module.add_function(wrap_pyfunction!(vocabulary::public_providers, module)?)?;
    module.add_function(wrap_pyfunction!(vocabulary::public_provider_name, module)?)?;
    module.add_function(wrap_pyfunction!(vocabulary::public_provider_endpoint, module)?)?;
    module.add_function(wrap_pyfunction!(vocabulary::search_result_url, module)?)?;
    module.add_function(wrap_pyfunction!(locators::validate_query, module)?)?;
    module.add_function(wrap_pyfunction!(locators::authored_query_info, module)?)?;
    module.add_function(wrap_pyfunction!(locators::compiled_query_info, module)?)?;
    module.add_function(wrap_pyfunction!(locators::compiled_query_namespace, module)?)?;
    module.add_function(wrap_pyfunction!(locators::validate_locator, module)?)?;
    module.add_function(wrap_pyfunction!(locators::validate_namespace, module)?)?;
    module.add_function(wrap_pyfunction!(locators::validate_region_id, module)?)?;
    module.add_function(wrap_pyfunction!(locators::validate_output_id, module)?)?;
    errors::register(module)?;
    module.add_function(wrap_pyfunction!(identities::activity_identity, module)?)?;
    module.add_function(wrap_pyfunction!(identities::activity_identity_bytes, module)?)?;
    module.add_class::<locators::NativePlan>()?;
    module.add_class::<contracts::NativeContract>()?;
    module.add_class::<contracts::NativeExtracted>()?;
    module.add_class::<contracts::NativeContractOutcome>()?;
    module.add_function(wrap_pyfunction!(contracts::validate_money, module)?)?;
    module.add_function(wrap_pyfunction!(contracts::validation_limits_defaults, module)?)?;
    module.add_function(wrap_pyfunction!(contracts::contract_schema_identity, module)?)?;
    module.add_function(wrap_pyfunction!(contracts::field_schema_validate, module)?)?;
    module.add_class::<documents::NativeDocument>()?;
    module.add_function(wrap_pyfunction!(documents::validate_profile, module)?)?;
    module.add_function(wrap_pyfunction!(documents::profile_class, module)?)?;
    module.add_class::<parsed::NativeParsedDocument>()?;
    module.add_class::<requests::NativeRequest>()?;
    module.add_class::<map::NativeMapRequest>()?;
    module.add_class::<map::NativeMapOutcome>()?;
    module.add_class::<search::NativeSearch>()?;
    module.add_class::<responses::NativeResponse>()?;
    module.add_class::<async_runtime::NativeCancellation>()?;
    module.add_function(wrap_pyfunction!(async_runtime::wait_for_idle, module)?)?;
    module.add_function(wrap_pyfunction!(policy::default_policy, module)?)?;
    module.add_function(wrap_pyfunction!(policy::validate_policy, module)?)?;
    module.add_function(wrap_pyfunction!(policy::effective_policy, module)?)?;
    module.add_function(wrap_pyfunction!(policy::policy_snapshot, module)?)?;
    module.add_function(wrap_pyfunction!(policy::policy_identity, module)?)
}
