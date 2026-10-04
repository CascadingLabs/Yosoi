//! Provider-neutral, bounded navigation scheduling contracts.
//!
//! These types describe scheduler intent and receipts only. They deliberately
//! do not name CDP targets, sessions, provider event identifiers, or URLs.

mod limits;
mod receipt;
mod request;

pub use limits::*;
pub use receipt::*;
pub use request::*;
