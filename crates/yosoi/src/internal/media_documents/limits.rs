use serde::{Deserialize, Serialize};

use super::FileDocumentError;

/// Default maximum size accepted for one media or binary file.
pub const DEFAULT_FILE_MAX_BYTES: u64 = 67_108_864;
/// Hard maximum size accepted for one media or binary file or Archive record.
pub const MAX_FILE_BYTES: u64 = 268_435_456;

/// Per-file materialization limit. The effective limit may not exceed [`MAX_FILE_BYTES`].
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FileLimits {
    /// Largest file payload accepted by constructors and bounded reads.
    pub max_bytes: u64,
}

impl FileLimits {
    /// Creates limits for a file up to `max_bytes`, rejecting values over the hard cap.
    pub fn new(max_bytes: u64) -> Result<Self, FileDocumentError> {
        let limits = Self { max_bytes };
        limits.validate()?;
        Ok(limits)
    }

    /// Returns the configured byte limit.
    pub const fn max_bytes(self) -> u64 {
        self.max_bytes
    }

    pub(super) const fn validate(self) -> Result<(), FileDocumentError> {
        if self.max_bytes > MAX_FILE_BYTES {
            return Err(FileDocumentError::LimitExceedsHardMaximum {
                configured: self.max_bytes,
                maximum: MAX_FILE_BYTES,
            });
        }
        Ok(())
    }
}

impl Default for FileLimits {
    fn default() -> Self {
        Self {
            max_bytes: DEFAULT_FILE_MAX_BYTES,
        }
    }
}
