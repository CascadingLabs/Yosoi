//! Private runtime components behind the public SDK namespaces.
//!
//! Component APIs are also exercised by in-crate tests and development tools.
//! Keeping their namespace private prevents implementation APIs from becoming
//! part of the SDK's compatibility contract.
#![allow(
    dead_code,
    unused_imports,
    reason = "component APIs remain private and are shared with development verification"
)]

pub mod archive;
#[cfg(feature = "browser")]
pub mod browser;
pub mod contract_validation;
pub mod contracts;
pub mod direct_http;
pub mod documents;
pub mod engine;
pub mod extractor;
pub mod map;
pub mod policy;
pub mod types;
pub mod web_capture;

#[cfg(test)]
mod test_support;
