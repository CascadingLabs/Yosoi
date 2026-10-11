//! Best-effort diagnostics stored inside VoidCrawl advisory lock files.
//! The OS lock remains authoritative; this metadata is never used to unlock.

use std::{
    fs::File,
    io::{self, Read, Seek, SeekFrom, Write},
    path::Path,
    process,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LeaseMetadata {
    pub pid: u32,
    pub acquired_at: u64,
}

impl LeaseMetadata {
    #[must_use]
    pub fn current() -> Self {
        Self {
            pid: process::id(),
            acquired_at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or_default(),
        }
    }
}

pub fn write_metadata(file: &mut File) -> io::Result<LeaseMetadata> {
    let metadata = LeaseMetadata::current();
    let bytes = serde_json::to_vec(&metadata).map_err(io::Error::other)?;
    file.seek(SeekFrom::Start(0))?;
    file.set_len(0)?;
    file.write_all(&bytes)?;
    file.sync_data()?;
    Ok(metadata)
}

#[must_use]
pub fn read_metadata(path: &Path) -> Option<LeaseMetadata> {
    let mut file = File::open(path).ok()?;
    let mut raw = Vec::new();
    file.read_to_end(&mut raw).ok()?;
    serde_json::from_slice(&raw).ok()
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use std::{fs, fs::OpenOptions};

    use super::*;

    #[test]
    fn stale_metadata_is_replaced() {
        let tmp = tempfile::NamedTempFile::new().unwrap();
        fs::write(tmp.path(), br#"{"pid":1,"acquired_at":2}"#).unwrap();
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(tmp.path())
            .unwrap();
        let written = write_metadata(&mut file).unwrap();
        assert_eq!(read_metadata(tmp.path()), Some(written.clone()));
        assert_eq!(written.pid, process::id());
    }
}
