use std::io::{self, Write};

use serde::Serialize;

use super::XmlError;

pub(super) fn serialized_size<T: Serialize>(value: &T) -> Result<u64, XmlError> {
    let mut writer = CountingWriter { bytes: 0 };
    serde_json::to_writer(&mut writer, value).map_err(|_| XmlError::InvalidResult)?;
    Ok(writer.bytes)
}

struct CountingWriter {
    bytes: u64,
}

impl Write for CountingWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let length = u64::try_from(buffer.len())
            .map_err(|_| io::Error::other("serialized XML result length overflowed"))?;
        self.bytes = self
            .bytes
            .checked_add(length)
            .ok_or_else(|| io::Error::other("serialized XML result length overflowed"))?;
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
