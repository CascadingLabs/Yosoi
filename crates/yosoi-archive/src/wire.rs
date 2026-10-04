use std::io::{self, Write};

use serde::{Deserialize, Serialize, de::DeserializeOwned};
use serde_json::value::RawValue;

use crate::ArchiveError;
use crate::refs::RecordKey;

/// Physical directory and publication protocol understood by this build.
pub const ARCHIVE_FORMAT_VERSION: u32 = 1;
/// Cargo package recorded as automatic writer provenance.
pub const ARCHIVE_WRITER_PACKAGE: &str = env!("CARGO_PKG_NAME");
/// Exact Cargo package version recorded as automatic writer provenance.
pub const ARCHIVE_WRITER_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const MAX_RECORD_BYTES: u64 = 16_777_216;
const MAX_RECORD_BYTES_USIZE: usize = 16_777_216;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RecordKind {
    Capture,
    Policy,
    Plan,
    ContractSchema,
    RequestRun,
    Document,
    EvaluationRun,
    LocatorRun,
    ContractRun,
}

impl RecordKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Capture => "capture",
            Self::Policy => "policy",
            Self::Plan => "plan",
            Self::ContractSchema => "contract-schema",
            Self::RequestRun => "request-run",
            Self::Document => "document",
            Self::EvaluationRun => "evaluation-run",
            Self::LocatorRun => "locator-run",
            Self::ContractRun => "contract-run",
        }
    }

    pub const fn directory(self) -> &'static str {
        self.as_str()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct WriterInfo {
    package: String,
    version: String,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct WriterInfoRef {
    package: &'static str,
    version: &'static str,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct ArchiveEnvelopeRef<'value, T> {
    format_version: u32,
    writer: WriterInfoRef,
    kind: RecordKind,
    schema_version: u32,
    key: &'value RecordKey,
    value: &'value T,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawArchiveEnvelope {
    format_version: u32,
    writer: WriterInfo,
    kind: RecordKind,
    schema_version: u32,
    key: RecordKey,
    value: Box<RawValue>,
}

pub fn encode_record<T>(
    kind: RecordKind,
    schema_version: u32,
    key: &RecordKey,
    value: &T,
) -> Result<Vec<u8>, ArchiveError>
where
    T: Serialize,
{
    let mut writer = BoundedRecordWriter::new(MAX_RECORD_BYTES_USIZE);
    let result = serde_json::to_writer(
        &mut writer,
        &ArchiveEnvelopeRef {
            format_version: ARCHIVE_FORMAT_VERSION,
            writer: WriterInfoRef {
                package: ARCHIVE_WRITER_PACKAGE,
                version: ARCHIVE_WRITER_VERSION,
            },
            kind,
            schema_version,
            key,
            value,
        },
    );
    if writer.exceeded {
        return Err(ArchiveError::RecordTooLarge {
            maximum: MAX_RECORD_BYTES,
            observed: MAX_RECORD_BYTES.saturating_add(1),
        });
    }
    result.map_err(|source| ArchiveError::EncodeRecord {
        kind: kind.as_str(),
        source,
    })?;
    Ok(writer.bytes)
}

struct BoundedRecordWriter {
    bytes: Vec<u8>,
    maximum: usize,
    exceeded: bool,
}

impl BoundedRecordWriter {
    const fn new(maximum: usize) -> Self {
        Self {
            bytes: Vec::new(),
            maximum,
            exceeded: false,
        }
    }
}

impl Write for BoundedRecordWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let Some(next_length) = self.bytes.len().checked_add(buffer.len()) else {
            self.exceeded = true;
            return Err(io::Error::other("Archive record size exceeds its bound"));
        };
        if next_length > self.maximum {
            self.exceeded = true;
            return Err(io::Error::other("Archive record size exceeds its bound"));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub fn decode_record<T>(
    expected_kind: RecordKind,
    expected_schema: u32,
    expected_key: &RecordKey,
    bytes: &[u8],
) -> Result<T, ArchiveError>
where
    T: DeserializeOwned,
{
    let raw: RawArchiveEnvelope =
        serde_json::from_slice(bytes).map_err(ArchiveError::MalformedEnvelope)?;

    if raw.format_version != ARCHIVE_FORMAT_VERSION {
        return Err(ArchiveError::UnsupportedFormat {
            found: raw.format_version,
            supported: ARCHIVE_FORMAT_VERSION,
        });
    }
    if raw.kind != expected_kind {
        return Err(ArchiveError::WrongRecordKind {
            found: raw.kind.as_str().to_owned(),
            expected: expected_kind.as_str(),
        });
    }
    if raw.schema_version != expected_schema {
        return Err(ArchiveError::MigrationRequired {
            kind: expected_kind.as_str(),
            found_schema: raw.schema_version,
            supported_schema: expected_schema,
            writer_package: raw.writer.package,
            writer_version: raw.writer.version,
        });
    }
    if &raw.key != expected_key {
        return Err(ArchiveError::WrongRecordKey {
            found: raw.key.to_string(),
            expected: expected_key.to_string(),
        });
    }

    serde_json::from_str(raw.value.get()).map_err(|source| ArchiveError::InvalidRecordValue {
        kind: expected_kind.as_str(),
        source,
    })
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;
    use yosoi_policy::Policy;

    const POLICY_SCHEMA_VERSION: u32 = 1;

    fn key() -> Result<RecordKey, crate::ArchiveRefError> {
        RecordKey::parse("123e4567-e89b-42d3-a456-426614174000")
    }

    #[test]
    fn writer_provenance_is_automatic() -> Result<(), Box<dyn Error>> {
        let bytes = encode_record(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            &key()?,
            &Policy::default(),
        )?;
        let json: serde_json::Value = serde_json::from_slice(&bytes)?;
        let package = json
            .get("writer")
            .and_then(|writer| writer.get("package"))
            .and_then(serde_json::Value::as_str);
        if package != Some(ARCHIVE_WRITER_PACKAGE) {
            return Err("writer package was not sourced from Cargo".into());
        }
        let version = json
            .get("writer")
            .and_then(|writer| writer.get("version"))
            .and_then(serde_json::Value::as_str);
        if version != Some(ARCHIVE_WRITER_VERSION) {
            return Err("writer version was not sourced from Cargo".into());
        }
        Ok(())
    }

    #[test]
    fn future_schema_is_rejected_before_policy_value_decode() -> Result<(), Box<dyn Error>> {
        let key = key()?;
        let bytes = encode_record(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            &key,
            &Policy::default(),
        )?;
        let mut json: serde_json::Value = serde_json::from_slice(&bytes)?;
        let object = json
            .as_object_mut()
            .ok_or("Archive envelope must be an object")?;
        object.insert("schema_version".to_owned(), serde_json::json!(2));
        object.insert("value".to_owned(), serde_json::json!({"not": "a policy"}));
        let hostile = serde_json::to_vec(&json)?;

        let result =
            decode_record::<Policy>(RecordKind::Policy, POLICY_SCHEMA_VERSION, &key, &hostile);
        if !matches!(
            result,
            Err(ArchiveError::MigrationRequired {
                found_schema: 2,
                supported_schema: POLICY_SCHEMA_VERSION,
                ..
            })
        ) {
            return Err("future schema did not fail before Policy decoding".into());
        }
        Ok(())
    }

    #[test]
    fn kind_and_key_are_checked_before_policy_value_decode() -> Result<(), Box<dyn Error>> {
        let key = key()?;
        let bytes = encode_record(
            RecordKind::Capture,
            POLICY_SCHEMA_VERSION,
            &key,
            &serde_json::json!({"not": "a policy"}),
        )?;
        let wrong_kind =
            decode_record::<Policy>(RecordKind::Policy, POLICY_SCHEMA_VERSION, &key, &bytes);
        if !matches!(wrong_kind, Err(ArchiveError::WrongRecordKind { .. })) {
            return Err("record kind was not checked before Policy decoding".into());
        }

        let other_key = RecordKey::parse("123e4567-e89b-42d3-a456-426614174001")?;
        let bytes = encode_record(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            &key,
            &serde_json::json!({"not": "a policy"}),
        )?;
        let wrong_key = decode_record::<Policy>(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            &other_key,
            &bytes,
        );
        if !matches!(wrong_key, Err(ArchiveError::WrongRecordKey { .. })) {
            return Err("record key was not checked before Policy decoding".into());
        }
        Ok(())
    }

    #[test]
    fn encoding_stops_at_the_record_bound() -> Result<(), Box<dyn Error>> {
        let oversized = "x".repeat(MAX_RECORD_BYTES_USIZE);
        let result = encode_record(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            &key()?,
            &oversized,
        );
        if !matches!(result, Err(ArchiveError::RecordTooLarge { .. })) {
            return Err("oversized value was fully encoded instead of bounded".into());
        }
        Ok(())
    }
}
