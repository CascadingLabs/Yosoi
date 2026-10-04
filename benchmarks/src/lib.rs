//! Repository-wide benchmark package.
//!
//! This crate contains no production API. It owns cross-crate benchmark fixtures,
//! harnesses, measurement-tool dependencies, and result publication conventions.
#![allow(
    clippy::absolute_paths,
    clippy::arithmetic_side_effects,
    clippy::as_conversions,
    clippy::missing_panics_doc,
    clippy::panic,
    clippy::unwrap_used,
    clippy::wildcard_imports,
    reason = "benchmark-only support fails fast when committed fixtures are invalid"
)]

pub mod browser_support;
pub mod finalization_support;
pub mod stealth_support;
pub mod support;
