//! Yosoi's user-facing Rust SDK.
//!
//! Use the named SDK namespaces for explicit imports, or [`prelude`] for
//! common authoring vocabulary. Implementation crates are not re-exported.

#![deny(missing_docs)]

mod internal;

pub mod action;
pub mod archive;
pub mod assertions;
pub mod automation_record;
pub mod contracts;
pub mod documents;
pub mod expect;
pub mod flow;
pub mod locators;
pub mod map;
pub mod policy;
pub mod prelude;
pub mod request;
pub mod search;
pub mod session;
pub mod surface;
pub mod timing;
pub mod view;
pub use crate::internal::engine::Archive;

// Common values are also available at the facade root for existing consumers.
pub use documents::{Document, DocumentId, DocumentProfile};
pub use locators::LocateOutcome;
pub use policy::{
    Continuation, CountLimit, EffectivePolicyIdentity, FlowPolicy, Policy, PolicyError, StepLimit,
    StopScope,
};
pub use request::{CancellationToken, ResponseTermination};

extern crate self as yosoi;

// Derive expansions run in the consumer's crate, so their narrowly scoped
// compiler support must be linkable. This is not an SDK authoring namespace.
#[doc(hidden)]
#[path = "macro_support.rs"]
pub mod __macro;
