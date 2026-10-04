use std::fs::{self as std_fs, DirBuilder, File as StdFile};
use std::io::{self, ErrorKind};
#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt as _, PermissionsExt as _};
use std::path::Path;

use tokio::fs;
use tokio::task;

use crate::ArchiveError;

#[cfg(unix)]
const PRIVATE_DIRECTORY_MODE: u32 = 0o700;

pub(super) async fn ensure_root_directory(path: &Path) -> Result<(), ArchiveError> {
    match fs::metadata(path).await {
        Ok(metadata) if metadata.is_dir() => return Ok(()),
        Ok(_) => {
            return Err(ArchiveError::UnsafeArchivePath {
                path: path.to_path_buf(),
                reason: "caller-selected Archive root is not a directory",
            });
        }
        Err(source) if source.kind() == ErrorKind::NotFound => {}
        Err(source) => {
            return Err(ArchiveError::io(
                "inspect caller-selected Archive root",
                path,
                source,
            ));
        }
    }
    let parent = path.parent().ok_or(ArchiveError::UnsafeArchivePath {
        path: path.to_path_buf(),
        reason: "caller-selected Archive root has no parent",
    })?;
    let parent_metadata = fs::metadata(parent)
        .await
        .map_err(|source| ArchiveError::io("inspect Archive root parent", parent, source))?;
    if !parent_metadata.is_dir() {
        return Err(ArchiveError::UnsafeArchivePath {
            path: parent.to_path_buf(),
            reason: "caller-selected Archive root parent is not a directory",
        });
    }
    let owned = path.to_path_buf();
    let task_path = owned.clone();
    task::spawn_blocking(move || create_private_directory_sync(&task_path, false))
        .await
        .map_err(|source| ArchiveError::FilesystemTask {
            operation: "create caller-selected Archive root",
            source,
        })?
        .map_err(|source| ArchiveError::io("create caller-selected Archive root", &owned, source))
}

pub(super) async fn ensure_private_directory(
    path: &Path,
    recursive: bool,
) -> Result<(), ArchiveError> {
    let owned = path.to_path_buf();
    let task_path = owned.clone();
    task::spawn_blocking(move || create_private_directory_sync(&task_path, recursive))
        .await
        .map_err(|source| ArchiveError::FilesystemTask {
            operation: "create private Archive directory",
            source,
        })?
        .map_err(|source| ArchiveError::io("create private Archive directory", &owned, source))?;
    validate_private_directory(&owned).await
}

fn create_private_directory_sync(path: &Path, recursive: bool) -> io::Result<()> {
    match std_fs::symlink_metadata(path) {
        Ok(_) => return Ok(()),
        Err(source) if source.kind() == ErrorKind::NotFound => {}
        Err(source) => return Err(source),
    }

    let mut builder = DirBuilder::new();
    builder.recursive(recursive);
    #[cfg(unix)]
    builder.mode(PRIVATE_DIRECTORY_MODE);
    match builder.create(path) {
        Ok(()) => {}
        Err(source) if source.kind() == ErrorKind::AlreadyExists => return Ok(()),
        Err(source) => return Err(source),
    }
    sync_directory(path)?;
    if let Some(parent) = path.parent() {
        sync_directory(parent)?;
    }
    Ok(())
}

pub(super) async fn validate_private_directory(path: &Path) -> Result<(), ArchiveError> {
    let metadata = fs::symlink_metadata(path)
        .await
        .map_err(|source| ArchiveError::io("inspect Archive directory", path, source))?;
    if metadata.file_type().is_symlink() {
        return Err(ArchiveError::UnsafeArchivePath {
            path: path.to_path_buf(),
            reason: "Archive-owned directories must not be symbolic links",
        });
    }
    if !metadata.is_dir() {
        return Err(ArchiveError::UnsafeArchivePath {
            path: path.to_path_buf(),
            reason: "Archive-owned path is not a directory",
        });
    }
    validate_private_directory_permissions(path, &metadata)
}

#[cfg(unix)]
fn validate_private_directory_permissions(
    path: &Path,
    metadata: &std_fs::Metadata,
) -> Result<(), ArchiveError> {
    let mode = metadata.permissions().mode() & 0o777;
    if mode & 0o077 != 0 {
        return Err(ArchiveError::InsecurePermissions {
            path: path.to_path_buf(),
            mode,
        });
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_private_directory_permissions(
    _path: &Path,
    _metadata: &std_fs::Metadata,
) -> Result<(), ArchiveError> {
    Ok(())
}

#[cfg(unix)]
pub(super) fn validate_private_file_permissions(
    path: &Path,
    metadata: &std_fs::Metadata,
) -> Result<(), ArchiveError> {
    let mode = metadata.permissions().mode() & 0o777;
    if mode & 0o077 != 0 {
        return Err(ArchiveError::InsecurePermissions {
            path: path.to_path_buf(),
            mode,
        });
    }
    Ok(())
}

#[cfg(not(unix))]
pub(super) fn validate_private_file_permissions(
    _path: &Path,
    _metadata: &std_fs::Metadata,
) -> Result<(), ArchiveError> {
    Ok(())
}

pub(super) fn sync_directory(path: &Path) -> io::Result<()> {
    StdFile::open(path)?.sync_all()
}
