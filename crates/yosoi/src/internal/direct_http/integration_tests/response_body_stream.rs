#![allow(
    clippy::absolute_paths,
    clippy::arithmetic_side_effects,
    clippy::as_conversions,
    clippy::cast_possible_truncation,
    clippy::panic,
    clippy::unwrap_used,
    reason = "bounded integration fixtures"
)]

#[path = "response_body_stream/decoding.rs"]
mod decoding;
#[path = "response_body_stream/failures.rs"]
mod failures;
#[path = "response_body_stream/limits.rs"]
mod limits;
#[path = "response_body_stream/support.rs"]
mod support;
