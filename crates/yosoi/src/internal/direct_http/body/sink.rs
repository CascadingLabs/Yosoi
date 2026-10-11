use std::fmt;

use thiserror::Error;

use super::consume::READ_BUFFER_BYTES;

#[derive(Debug, Error)]
pub enum SinkError {
    #[error("payload sink operation failed")]
    Operation,
}

pub trait PayloadSink: fmt::Debug + Send {
    fn write(&mut self, bytes: &[u8]) -> Result<(), SinkError>;
    fn commit(self: Box<Self>) -> Result<Vec<u8>, SinkError>;
}

#[derive(Debug)]
pub(in crate::internal::direct_http) struct BoundedMemorySink {
    bytes: Vec<u8>,
}

impl BoundedMemorySink {
    pub(super) fn new(limit: u64) -> Self {
        let capacity = usize::try_from(limit)
            .unwrap_or(usize::MAX)
            .min(READ_BUFFER_BYTES);
        Self {
            bytes: Vec::with_capacity(capacity),
        }
    }
}

impl PayloadSink for BoundedMemorySink {
    fn write(&mut self, bytes: &[u8]) -> Result<(), SinkError> {
        self.bytes.extend_from_slice(bytes);
        Ok(())
    }

    fn commit(self: Box<Self>) -> Result<Vec<u8>, SinkError> {
        Ok(self.bytes)
    }
}
