use yosoi_documents::Plan;

use crate::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::{Archive, ArchiveError, PlanArchiveRef};

const PLAN_SCHEMA_VERSION: u32 = 1;

impl sealed::Value for Plan {}

impl ArchiveValue for Plan {
    type Reference = PlanArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        let reference = PlanArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::Plan,
                PLAN_SCHEMA_VERSION,
                reference.key(),
                value,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for PlanArchiveRef {}

impl ArchiveReference for PlanArchiveRef {
    type Value = Plan;

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
            .read_record(RecordKind::Plan, PLAN_SCHEMA_VERSION, reference.key())
            .await
    }
}
