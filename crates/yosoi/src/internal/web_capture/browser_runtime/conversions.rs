mod accounting_scope;
mod browser_native;
mod environment;
mod source_network;

pub use accounting_scope::{
    document_scope, main_document_scope, map_provider_error, missing_observation_accounting,
    reason, rendered_dom,
};
pub use browser_native::{accessibility, layout, runtime, visual};
pub use environment::{environment, verify_environment};
pub use source_network::{browser_challenge, navigation_event_accounting, network, source};

#[cfg(test)]
use crate::internal::browser as provider;
#[cfg(test)]
use crate::internal::web_capture as yosoi;
#[cfg(test)]
use accounting_scope::{ProviderResultDescriptor, byte_domain, event_accounting, payload_extent};
#[cfg(test)]
use environment::{
    CapabilityClass, capability_class, environment_reason, environment_value,
    instrumentation_agrees, omission_reason,
};
#[cfg(test)]
use source_network::source_unavailable_outcome;

#[cfg(test)]
#[path = "conversions_tests.rs"]
mod tests;
