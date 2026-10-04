//! Yosoi's user-facing Rust SDK.
//!
//! Use the named SDK namespaces for explicit imports, or [`prelude`] for
//! common authoring vocabulary. Implementation crates are not re-exported.

pub mod contracts;
pub mod documents;
pub mod locators;
pub mod map;
pub mod policy;
pub mod prelude;
pub mod request;

extern crate self as yosoi_sdk;

// Derive expansions run in the consumer's crate, so their narrowly scoped
// compiler support must be linkable. This is not an SDK authoring namespace.
#[doc(hidden)]
#[path = "macro_support.rs"]
pub mod __macro;
