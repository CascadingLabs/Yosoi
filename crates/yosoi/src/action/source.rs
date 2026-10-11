use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{self, Read},
    path::{Path, PathBuf},
};

/// Default maximum source size for one JavaScript file snapshot.
pub const MAX_JAVASCRIPT_SOURCE_BYTES: usize = 65_536;

const READ_CHUNK_BYTES: usize = 8_192;

/// Exact UTF-8 source captured when the file action is constructed.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JavaScriptSourceSnapshot {
    source: String,
    provenance: JavaScriptSourceProvenance,
}

impl<'de> Deserialize<'de> for JavaScriptSourceSnapshot {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            source: String,
            provenance: JavaScriptSourceProvenance,
        }

        let wire = Wire::deserialize(deserializer)?;
        let snapshot = Self {
            source: wire.source,
            provenance: wire.provenance,
        };
        snapshot
            .validate(MAX_JAVASCRIPT_SOURCE_BYTES)
            .map_err(D::Error::custom)?;
        Ok(snapshot)
    }
}

impl JavaScriptSourceSnapshot {
    pub(super) fn from_file(
        path: &Path,
        maximum_bytes: usize,
    ) -> Result<Self, JavaScriptSourceError> {
        if maximum_bytes > MAX_JAVASCRIPT_SOURCE_BYTES {
            return Err(JavaScriptSourceError::InvalidLimit {
                maximum: maximum_bytes,
            });
        }
        let bytes = read_bounded(path, maximum_bytes)?;
        let source = String::from_utf8(bytes).map_err(|_| JavaScriptSourceError::InvalidUtf8 {
            path: path.to_path_buf(),
        })?;
        let snapshot = Self::new(
            source,
            JavaScriptSourceOrigin::File {
                path: path.to_path_buf(),
            },
        );
        snapshot.validate(maximum_bytes)?;
        Ok(snapshot)
    }

    pub(super) fn new(source: String, origin: JavaScriptSourceOrigin) -> Self {
        let byte_len = source.len();
        let sha256 = sha256_hex(source.as_bytes());
        Self {
            source,
            provenance: JavaScriptSourceProvenance {
                origin,
                byte_len,
                sha256,
            },
        }
    }

    /// Returns the exact captured source text.
    pub fn source(&self) -> &str {
        &self.source
    }

    /// Returns where this snapshot came from and its content identity.
    pub const fn provenance(&self) -> &JavaScriptSourceProvenance {
        &self.provenance
    }

    /// Returns the captured source length in UTF-8 bytes.
    pub const fn byte_len(&self) -> usize {
        self.provenance.byte_len
    }

    /// Rechecks the serialized snapshot before it can be dispatched.
    pub fn validate(&self, maximum_bytes: usize) -> Result<(), JavaScriptSourceError> {
        let maximum_bytes = maximum_bytes.min(MAX_JAVASCRIPT_SOURCE_BYTES);
        if self.source.trim().is_empty() {
            return Err(JavaScriptSourceError::Empty);
        }
        if self.source.len() > maximum_bytes {
            return Err(JavaScriptSourceError::TooLarge {
                path: self.provenance.origin.path().map(Path::to_path_buf),
                actual: self.source.len(),
                maximum: maximum_bytes,
            });
        }
        if self.provenance.byte_len != self.source.len() {
            return Err(JavaScriptSourceError::ByteLengthMismatch {
                declared: self.provenance.byte_len,
                actual: self.source.len(),
            });
        }
        if self.provenance.sha256 != sha256_hex(self.source.as_bytes()) {
            return Err(JavaScriptSourceError::DigestMismatch);
        }
        Ok(())
    }
}

/// Source identity retained with a JavaScript snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JavaScriptSourceProvenance {
    origin: JavaScriptSourceOrigin,
    byte_len: usize,
    sha256: String,
}

impl JavaScriptSourceProvenance {
    /// Returns the authored source location.
    pub const fn origin(&self) -> &JavaScriptSourceOrigin {
        &self.origin
    }

    /// Returns the captured source length in UTF-8 bytes.
    pub const fn byte_len(&self) -> usize {
        self.byte_len
    }

    /// Returns the lowercase SHA-256 digest of the exact captured UTF-8 bytes.
    pub fn sha256(&self) -> &str {
        &self.sha256
    }
}

/// The source's construction-time provenance.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum JavaScriptSourceOrigin {
    /// A source authored directly in the Flow.
    Inline,
    /// A source captured from a local file.
    File { path: PathBuf },
}

impl JavaScriptSourceOrigin {
    pub(super) fn path(&self) -> Option<&Path> {
        match self {
            Self::Inline => None,
            Self::File { path } => Some(path.as_path()),
        }
    }
}

/// A source snapshot could not be read or failed its integrity/size checks.
#[derive(Debug, thiserror::Error)]
pub enum JavaScriptSourceError {
    /// The source file could not be opened or read.
    #[error("could not read JavaScript source {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    /// The bounded reader observed more than the configured number of bytes.
    #[error("JavaScript source {path:?} exceeds {maximum} UTF-8 bytes")]
    TooLarge {
        path: Option<PathBuf>,
        actual: usize,
        maximum: usize,
    },
    /// The captured bytes are not valid UTF-8.
    #[error("JavaScript source {path} is not valid UTF-8")]
    InvalidUtf8 { path: PathBuf },
    /// The source contains no non-whitespace text.
    #[error("JavaScript source is empty")]
    Empty,
    /// A caller-supplied byte limit exceeds the SDK hard cap.
    #[error(
        "JavaScript source limit {maximum} exceeds the SDK maximum of {MAX_JAVASCRIPT_SOURCE_BYTES} bytes"
    )]
    InvalidLimit { maximum: usize },
    /// The stored byte length does not match the source text.
    #[error("JavaScript snapshot declares {declared} bytes but contains {actual}")]
    ByteLengthMismatch { declared: usize, actual: usize },
    /// The stored digest does not match the source text.
    #[error("JavaScript snapshot SHA-256 does not match its source")]
    DigestMismatch,
    /// The source exceeded a bound before an allocation could be made safely.
    #[error("could not reserve {requested} bytes for JavaScript source {path}")]
    AllocationFailed { path: PathBuf, requested: usize },
}

pub(super) fn read_bounded(
    path: &Path,
    maximum_bytes: usize,
) -> Result<Vec<u8>, JavaScriptSourceError> {
    let mut file = File::open(path).map_err(|source| JavaScriptSourceError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; READ_CHUNK_BYTES];

    loop {
        let remaining = maximum_bytes.saturating_sub(bytes.len());
        let requested = if remaining < buffer.len() {
            remaining.saturating_add(1).min(buffer.len())
        } else {
            buffer.len()
        };
        let Some(read_buffer) = buffer.get_mut(..requested) else {
            return Err(JavaScriptSourceError::Io {
                path: path.to_path_buf(),
                source: io::Error::other("invalid bounded read size"),
            });
        };
        let count = file
            .read(read_buffer)
            .map_err(|source| JavaScriptSourceError::Io {
                path: path.to_path_buf(),
                source,
            })?;
        if count == 0 {
            break;
        }
        if count > remaining {
            return Err(JavaScriptSourceError::TooLarge {
                path: Some(path.to_path_buf()),
                actual: maximum_bytes.saturating_add(1),
                maximum: maximum_bytes,
            });
        }
        bytes
            .try_reserve(count)
            .map_err(|_| JavaScriptSourceError::AllocationFailed {
                path: path.to_path_buf(),
                requested: count,
            })?;
        let Some(chunk) = buffer.get(..count) else {
            return Err(JavaScriptSourceError::Io {
                path: path.to_path_buf(),
                source: io::Error::other("invalid bounded read result"),
            });
        };
        bytes.extend_from_slice(chunk);
    }
    Ok(bytes)
}

pub(super) fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::{JavaScriptSourceError, MAX_JAVASCRIPT_SOURCE_BYTES};
    use crate::action::{JavaScriptSourceOrigin, evaluate_file, evaluate_file_with_limit};
    use crate::flow::Step;
    use std::env as std_env;
    use std::path as std_path;
    use std::process as std_process;
    use std::{
        error::Error,
        fs,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };

    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Result<Self, Box<dyn Error>> {
            let id = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
            let path =
                std_env::temp_dir().join(format!("yosoi-js-source-{}-{id}", std_process::id()));
            fs::create_dir_all(&path)?;
            Ok(Self(path))
        }

        fn path(&self) -> &std_path::Path {
            &self.0
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
    )]
    fn file_action_keeps_exact_bounded_utf8_snapshot_and_provenance() -> Result<(), Box<dyn Error>>
    {
        let directory = TempDir::new()?;
        let path = directory.path().join("check.js");
        let source = "export const city = '東京';\r\n";
        fs::write(&path, source.as_bytes())?;

        let step = evaluate_file(&path)?;
        let Step::EvaluateFile { snapshot } = step else {
            return Err("file action returned the wrong step".into());
        };
        assert_eq!(snapshot.source(), source);
        assert_eq!(snapshot.byte_len(), source.len());
        assert_eq!(snapshot.provenance().byte_len(), source.len());
        assert_eq!(snapshot.provenance().sha256().len(), 64);
        assert!(matches!(
            snapshot.provenance().origin(),
            JavaScriptSourceOrigin::File { path: recorded } if recorded == &path
        ));

        fs::write(&path, "export const city = 'changed';")?;
        assert_eq!(snapshot.source(), source);
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
    )]
    fn file_snapshot_rejects_missing_oversized_and_non_utf8_sources() -> Result<(), Box<dyn Error>>
    {
        let directory = TempDir::new()?;
        let missing = directory.path().join("missing.js");
        assert!(matches!(
            evaluate_file(&missing),
            Err(JavaScriptSourceError::Io { .. })
        ));

        let oversized = directory.path().join("oversized.js");
        fs::write(&oversized, b"12345")?;
        assert!(matches!(
            evaluate_file_with_limit(&oversized, 4),
            Err(JavaScriptSourceError::TooLarge {
                maximum: 4,
                actual: 5,
                ..
            })
        ));
        assert!(matches!(
            evaluate_file_with_limit(&oversized, MAX_JAVASCRIPT_SOURCE_BYTES + 1),
            Err(JavaScriptSourceError::InvalidLimit { .. })
        ));

        let invalid_utf8 = directory.path().join("invalid.js");
        fs::write(&invalid_utf8, [0xff, 0xfe])?;
        assert!(matches!(
            evaluate_file(&invalid_utf8),
            Err(JavaScriptSourceError::InvalidUtf8 { .. })
        ));
        assert_eq!(MAX_JAVASCRIPT_SOURCE_BYTES, 65_536);
        Ok(())
    }
}
