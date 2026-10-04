#![allow(
    clippy::indexing_slicing,
    clippy::match_like_matches_macro,
    clippy::semicolon_if_nothing_returned,
    clippy::unwrap_used,
    reason = "integration fixtures use validated constants and compact assertions"
)]

#[path = "bounded_lifecycle/admission.rs"]
mod admission;
#[path = "bounded_lifecycle/adversarial.rs"]
mod adversarial;
#[path = "bounded_lifecycle/finalization.rs"]
mod finalization;
#[path = "bounded_lifecycle/remediation.rs"]
mod remediation;
#[path = "bounded_lifecycle/support.rs"]
mod support;
