use crate::internal::contracts::ContractSchema;

use crate::internal::archive::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::internal::archive::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::internal::archive::{Archive, ArchiveError, ContractSchemaArchiveRef};

const CONTRACT_SCHEMA_RECORD_VERSION: u32 = 1;

impl sealed::Value for ContractSchema {}

impl ArchiveValue for ContractSchema {
    type Reference = ContractSchemaArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        let reference = ContractSchemaArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::ContractSchema,
                CONTRACT_SCHEMA_RECORD_VERSION,
                reference.key(),
                value,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for ContractSchemaArchiveRef {}

impl ArchiveReference for ContractSchemaArchiveRef {
    type Value = ContractSchema;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        if reference.format_version() != ARCHIVE_FORMAT_VERSION {
            return Err(ArchiveError::UnsupportedFormat {
                found: reference.format_version(),
                supported: ARCHIVE_FORMAT_VERSION,
            });
        }
        archive
            .read_record(
                RecordKind::ContractSchema,
                CONTRACT_SCHEMA_RECORD_VERSION,
                reference.key(),
            )
            .await
    }
}
