//! Private Chromiumoxide controller and generated CDP modules.

// Private embedding makes unused upstream exports and protocol types visible
// to rustc; retain them for the complete reviewed controller/schema surface.
#![allow(dead_code, unused_imports, missing_debug_implementations)]

// These modules retain reviewed upstream and Yosoi code that was previously
// built as separate crates. Keep their lint exceptions at this private vendor
// boundary; `unsafe_code = forbid` remains in force for the SDK.
#[allow(
    clippy::all,
    clippy::pedantic,
    clippy::nursery,
    clippy::absolute_paths,
    clippy::arithmetic_side_effects,
    clippy::as_conversions,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::string_slice,
    clippy::unwrap_used,
    reason = "preserve the separately reviewed controller source and generated protocol output"
)]
#[path = "chromiumoxide/src/lib.rs"]
pub(super) mod chromiumoxide;

// Generated protocol code keeps its upstream style and the checked event
// downcast helper; it does not inherit allowances for controller panics.
#[allow(
    clippy::all,
    clippy::pedantic,
    clippy::nursery,
    clippy::absolute_paths,
    clippy::unwrap_used,
    reason = "retain generated protocol output and its checked type-erasure downcast"
)]
#[path = "chromiumoxide_cdp/src/lib.rs"]
pub(super) mod chromiumoxide_cdp;
