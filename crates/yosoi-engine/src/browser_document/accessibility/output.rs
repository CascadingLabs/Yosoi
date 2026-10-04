use std::io::{self, Write};
pub(super) struct BoundedOutput {
    bytes: Vec<u8>,
    maximum: u64,
    pub(super) exceeded_limit: bool,
    pub(super) capacity_failed: bool,
}

impl BoundedOutput {
    pub(super) const fn new(maximum: u64) -> Self {
        Self {
            bytes: Vec::new(),
            maximum,
            exceeded_limit: false,
            capacity_failed: false,
        }
    }

    pub(super) fn into_inner(self) -> Vec<u8> {
        self.bytes
    }
}

impl Write for BoundedOutput {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let Ok(current) = u64::try_from(self.bytes.len()) else {
            self.capacity_failed = true;
            return Err(io::Error::other("output length overflow"));
        };
        let Ok(additional) = u64::try_from(buffer.len()) else {
            self.capacity_failed = true;
            return Err(io::Error::other("output length overflow"));
        };
        let Some(next) = current.checked_add(additional) else {
            self.exceeded_limit = true;
            return Err(io::Error::other("output limit exceeded"));
        };
        if next > self.maximum {
            self.exceeded_limit = true;
            return Err(io::Error::other("output limit exceeded"));
        }
        if usize::try_from(next).is_err() || self.bytes.try_reserve_exact(buffer.len()).is_err() {
            self.capacity_failed = true;
            return Err(io::Error::other("output capacity unavailable"));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
