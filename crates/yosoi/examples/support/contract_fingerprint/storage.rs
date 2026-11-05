//! Fingerprint attachments use ordinary JSON Documents in the real SDK Archive.
use super::Result;
use serde::{Serialize, de::DeserializeOwned};
use std::{fs, path::Path};
use yosoi::{Archive, archive::DocumentArchiveRef, documents::Document};

pub(super) async fn save_json<T: Serialize + Sync>(
    archive: &Archive,
    id: &str,
    value: &T,
) -> Result<DocumentArchiveRef> {
    let document = Document::json(id, serde_json::to_vec(value)?)?;
    Ok(archive.write_document(&document).await?)
}

pub(super) async fn read_json<T: DeserializeOwned>(
    archive: &Archive,
    reference: &DocumentArchiveRef,
) -> Result<T> {
    let document = archive.read_document(reference).await?;
    Ok(serde_json::from_slice(document.bytes())?)
}

pub(super) fn write_ref(path: &Path, reference: &DocumentArchiveRef) -> Result {
    fs::write(path, serde_json::to_vec_pretty(reference)?)?;
    Ok(())
}

pub(super) fn read_ref(path: &Path) -> Result<DocumentArchiveRef> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

// Git preserves executable bits, not Archive's owner-private permission modes.
// Materialize immutable public fixture bytes in a private store before opening it.
pub(super) fn stage_archive(output: &Path) -> Result<tempfile::TempDir> {
    let temporary = tempfile::tempdir()?;
    let mut pending = vec![(output.join("archive"), temporary.path().join("store"))];
    while let Some((source, destination)) = pending.pop() {
        let metadata = fs::symlink_metadata(&source)?;
        if metadata.file_type().is_symlink() {
            return super::fail("fixture staging rejects symlinks");
        }
        if metadata.is_dir() {
            fs::create_dir(&destination)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&destination, fs::Permissions::from_mode(0o700))?;
            }
            for entry in fs::read_dir(&source)? {
                let entry = entry?;
                pending.push((entry.path(), destination.join(entry.file_name())));
            }
        } else if metadata.is_file() {
            fs::copy(&source, &destination)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&destination, fs::Permissions::from_mode(0o600))?;
            }
        } else {
            return super::fail("unsupported fixture file type");
        }
    }
    Ok(temporary)
}
