#[cfg(windows)]
use std::fs as std_fs;
use std::io::{self, ErrorKind};
use std::path::Path;

use super::directory::sync_directory;

#[derive(Debug)]
pub(super) enum PublishError {
    AlreadyExists,
    BeforeCommit(io::Error),
    CommitUncertain(io::Error),
}

pub(super) fn publish_and_sync(
    staging_path: &Path,
    final_path: &Path,
    final_parent: &Path,
    staging_parent: &Path,
) -> Result<(), PublishError> {
    publish_and_sync_with_hook(
        staging_path,
        final_path,
        final_parent,
        staging_parent,
        || {},
    )
}

pub(super) fn publish_and_sync_with_hook<F>(
    staging_path: &Path,
    final_path: &Path,
    final_parent: &Path,
    staging_parent: &Path,
    after_rename: F,
) -> Result<(), PublishError>
where
    F: FnOnce(),
{
    match rename_no_replace(staging_path, final_path) {
        Ok(()) => {}
        Err(source) if source.kind() == ErrorKind::AlreadyExists => {
            return Err(PublishError::AlreadyExists);
        }
        Err(source) => return Err(PublishError::BeforeCommit(source)),
    }
    after_rename();
    sync_directory(final_parent).map_err(PublishError::CommitUncertain)?;
    sync_directory(staging_parent).map_err(PublishError::CommitUncertain)
}

#[cfg(any(
    target_os = "android",
    target_os = "linux",
    target_os = "macos",
    target_os = "ios",
    target_os = "tvos",
    target_os = "visionos",
    target_os = "watchos",
    target_os = "redox"
))]
pub(super) fn rename_no_replace(source: &Path, destination: &Path) -> io::Result<()> {
    use rustix::fs::{CWD, RenameFlags, renameat_with};

    renameat_with(CWD, source, CWD, destination, RenameFlags::NOREPLACE).map_err(io::Error::from)
}

#[cfg(windows)]
pub(super) fn rename_no_replace(source: &Path, destination: &Path) -> io::Result<()> {
    std_fs::rename(source, destination)
}

#[cfg(not(any(
    target_os = "android",
    target_os = "linux",
    target_os = "macos",
    target_os = "ios",
    target_os = "tvos",
    target_os = "visionos",
    target_os = "watchos",
    target_os = "redox",
    windows
)))]
pub(super) fn rename_no_replace(_source: &Path, _destination: &Path) -> io::Result<()> {
    Err(io::Error::new(
        ErrorKind::Unsupported,
        "this platform has no certified atomic no-replace rename",
    ))
}
