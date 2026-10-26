//! Local immutable evidence storage and typed references.
//!
//! Archive format 1 is certified on Unix filesystems. Opening a handle owns no
//! browser or background writer. Reads validate recorded identity, versions,
//! payload length and integrity; saved evidence never restores live authority.

use crate::documents::Document;
mod portable;
mod surface;
pub use crate::internal::archive::{
    Archive, ArchiveError, ArchiveRefError, DocumentArchiveRef, PlanArchiveRef,
};

impl Archive {
    /// Saves an SDK Document with its exact identity, profile and bytes.
    ///
    /// Returns an immutable reference, or an Archive error for unsupported
    /// platforms, unsafe paths, excessive payloads, or failed durable storage.
    /// Cancellation may leave unreferenced staging data; no partial reference is
    /// returned. Repeating a write creates a distinct immutable occurrence.
    pub async fn write_document(
        &self,
        document: &Document,
    ) -> Result<DocumentArchiveRef, ArchiveError> {
        self.write(document.inner.archive_value()).await
    }

    /// Restores and validates one exact SDK Document without network or browser I/O.
    ///
    /// Missing records, unsupported versions and corrupt payloads return typed
    /// Archive errors. The result owns its bytes independently of this handle.
    pub async fn read_document(
        &self,
        reference: &DocumentArchiveRef,
    ) -> Result<Document, ArchiveError> {
        let document = self.read(reference).await?;
        Document::from_profile(
            document.id().clone(),
            document.profile(),
            document.bytes().to_vec(),
        )
        .map_err(ArchiveError::InvalidDocument)
    }
}
