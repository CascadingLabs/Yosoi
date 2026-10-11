//! Yosoi's user-facing Rust SDK.
//!
//! Use the named SDK namespaces for explicit imports, or [`prelude`] for
//! common authoring vocabulary. Implementation crates are not re-exported.

mod internal;

pub mod contracts;
pub mod documents;
pub mod locators;
pub mod map;
pub mod policy;
pub mod prelude;
pub mod request;
pub mod search;

// Common values are also available at the facade root for existing consumers.
pub use documents::{Document, DocumentId, DocumentProfile};
pub use locators::LocateOutcome;
pub use policy::{CountLimit, EffectivePolicyIdentity, Policy, PolicyError, StepLimit};
pub use request::{CancellationToken, ResponseTermination};

extern crate self as yosoi;

// Derive expansions run in the consumer's crate, so their narrowly scoped
// compiler support must be linkable. This is not an SDK authoring namespace.
#[doc(hidden)]
#[path = "macro_support.rs"]
pub mod __macro;
