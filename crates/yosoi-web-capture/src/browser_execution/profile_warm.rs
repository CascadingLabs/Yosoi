//! Provider-neutral specifications and receipts for bounded profile warming.
//!
//! Warm plans retain caller-supplied URLs for execution, so their `Debug`
//! output is deliberately redacted and plans are not serialized. Receipts use
//! stable opaque step identities and never retain a URL.

mod plan;
mod receipt;

pub use plan::*;
pub use receipt::*;
