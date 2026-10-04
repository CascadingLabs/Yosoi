//! Incremental, bounded response-body processing.
//! Lifecycle byte accounting uses decoded representation bytes offered and staged for retention.
//! Content-coded transport bytes are counted separately, so decompression expansion cannot make
//! retained bytes exceed admitted bytes. Staged retention is rolled back unless its sink commits.

mod consume;
mod counted;
mod encoding;
mod outcome;
mod sink;
mod termination;

pub use consume::consume_response_body;
#[cfg(test)]
pub(crate) use consume::{consume_with_sink, consume_with_sink_forced_invariant_failure, publish};
pub use encoding::parse_content_encoding;
pub(crate) use outcome::terminal_reason;
pub use outcome::{
    BodyTerminal, ContentEncodingError, HttpContentCoding, ResponseBodyError, ResponseBodyFailure,
    ResponseBodyOutcome,
};
#[cfg(test)]
pub(crate) use sink::{BoundedMemorySink, PayloadSink, SinkError};

#[cfg(test)]
#[path = "body_tests.rs"]
mod tests;
