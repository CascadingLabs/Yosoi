use std::{
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    path::Path,
    result::Result as StdResult,
};

use crate::error::{Result, VoidCrawlError};

use super::{
    fork::{
        ManagedProfileForkError, ManagedProfileForkErrorKind, ManagedProfileForkOperation,
        fork_io_error,
    },
    seed_standalone_profile,
};

pub(super) fn copy_snapshot_recursively_bounded(
    source: &Path,
    destination: &Path,
    child_index: usize,
    aggregate_byte_quota: u64,
    copied_bytes: &mut u64,
) -> StdResult<u64, ManagedProfileForkError> {
    fs::create_dir_all(destination).map_err(|error| {
        fork_io_error(
            ManagedProfileForkOperation::CreateStagingDirectory,
            Some(child_index),
            error,
        )
    })?;

    let entries = fs::read_dir(source).map_err(|error| {
        fork_io_error(
            ManagedProfileForkOperation::ReadSourceDirectory,
            Some(child_index),
            error,
        )
    })?;
    let mut copied_here = 0_u64;
    for entry in entries {
        let entry = entry.map_err(|error| {
            fork_io_error(
                ManagedProfileForkOperation::ReadSourceEntry,
                Some(child_index),
                error,
            )
        })?;
        let name = entry.file_name();
        let name_text = name.to_string_lossy();
        if name_text == ".voidcrawl.lock" || name_text.starts_with("Singleton") {
            continue;
        }

        let source_path = entry.path();
        let destination_path = destination.join(name);
        let file_type = entry.file_type().map_err(|error| {
            fork_io_error(
                ManagedProfileForkOperation::ReadSourceEntry,
                Some(child_index),
                error,
            )
        })?;
        if file_type.is_symlink() {
            continue;
        }
        if file_type.is_dir() {
            let nested_bytes = copy_snapshot_recursively_bounded(
                &source_path,
                &destination_path,
                child_index,
                aggregate_byte_quota,
                copied_bytes,
            )?;
            copied_here = copied_here.checked_add(nested_bytes).ok_or_else(|| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
            })?;
        } else if file_type.is_file() {
            let file_bytes = copy_regular_file_bounded(
                &source_path,
                &destination_path,
                child_index,
                aggregate_byte_quota,
                copied_bytes,
            )?;
            copied_here = copied_here.checked_add(file_bytes).ok_or_else(|| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
            })?;
        }
    }
    Ok(copied_here)
}

pub(super) fn copy_regular_file_bounded(
    source: &Path,
    destination: &Path,
    child_index: usize,
    aggregate_byte_quota: u64,
    copied_bytes: &mut u64,
) -> StdResult<u64, ManagedProfileForkError> {
    let mut source_file = File::open(source).map_err(|error| {
        fork_io_error(
            ManagedProfileForkOperation::ReadSourceFile,
            Some(child_index),
            error,
        )
    })?;
    let source_metadata = source_file.metadata().map_err(|error| {
        fork_io_error(
            ManagedProfileForkOperation::ReadSourceFile,
            Some(child_index),
            error,
        )
    })?;
    if !source_metadata.is_file() {
        return Ok(0);
    }
    let mut destination_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|error| {
            fork_io_error(
                ManagedProfileForkOperation::CreateDestinationFile,
                Some(child_index),
                error,
            )
        })?;

    let mut buffer = vec![0_u8; 64 * 1024].into_boxed_slice();
    let mut copied_file_bytes = 0_u64;
    loop {
        let read_count = source_file.read(&mut buffer).map_err(|error| {
            fork_io_error(
                ManagedProfileForkOperation::ReadSourceFile,
                Some(child_index),
                error,
            )
        })?;
        if read_count == 0 {
            break;
        }
        let chunk_bytes = u64::try_from(read_count).map_err(|_| {
            ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
        })?;
        let attempted_bytes = copied_bytes.checked_add(chunk_bytes).ok_or_else(|| {
            ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
        })?;
        if attempted_bytes > aggregate_byte_quota {
            return Err(ManagedProfileForkError::new(
                ManagedProfileForkErrorKind::AggregateByteQuotaExceeded {
                    quota_bytes: aggregate_byte_quota,
                    attempted_bytes,
                },
            ));
        }

        let mut written_in_chunk = 0_usize;
        while written_in_chunk < read_count {
            let remaining = buffer.get(written_in_chunk..read_count).ok_or_else(|| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
            })?;
            let written = destination_file.write(remaining).map_err(|error| {
                fork_io_error(
                    ManagedProfileForkOperation::WriteDestinationFile,
                    Some(child_index),
                    error,
                )
            })?;
            if written == 0 {
                return Err(fork_io_error(
                    ManagedProfileForkOperation::WriteDestinationFile,
                    Some(child_index),
                    io::Error::from(io::ErrorKind::WriteZero),
                ));
            }
            let written_bytes = u64::try_from(written).map_err(|_| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
            })?;
            *copied_bytes = copied_bytes.checked_add(written_bytes).ok_or_else(|| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
            })?;
            copied_file_bytes = copied_file_bytes
                .checked_add(written_bytes)
                .ok_or_else(|| {
                    ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
                })?;
            written_in_chunk = written_in_chunk.checked_add(written).ok_or_else(|| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::ByteCountOverflow)
            })?;
        }
    }

    let destination_length = destination_file
        .metadata()
        .map_err(|error| {
            fork_io_error(
                ManagedProfileForkOperation::ReadDestinationMetadata,
                Some(child_index),
                error,
            )
        })?
        .len();
    if destination_length != copied_file_bytes {
        let mut error =
            ManagedProfileForkError::new(ManagedProfileForkErrorKind::CopiedFileLengthMismatch {
                child_index,
            });
        error.facts.child_index = Some(child_index);
        error.facts.copied_bytes = *copied_bytes;
        return Err(error);
    }
    fs::set_permissions(destination, source_metadata.permissions()).map_err(|error| {
        fork_io_error(
            ManagedProfileForkOperation::SetDestinationPermissions,
            Some(child_index),
            error,
        )
    })?;
    Ok(destination_length)
}

pub(super) fn copy_regular_file_if_present(source: &Path, destination: &Path) -> Result<()> {
    let Ok(metadata) = source.symlink_metadata() else {
        return Ok(());
    };
    if !metadata.file_type().is_file() {
        return Ok(());
    }
    fs::copy(source, destination).map_err(|e| {
        VoidCrawlError::Other(format!(
            "copy profile metadata {} to {}: {e}",
            source.display(),
            destination.display()
        ))
    })?;
    Ok(())
}

pub(super) fn copy_snapshot_recursively(source: &Path, destination: &Path) -> Result<()> {
    fs::create_dir_all(destination).map_err(|e| {
        VoidCrawlError::Other(format!(
            "create snapshot dir {}: {e}",
            destination.display()
        ))
    })?;
    for entry in fs::read_dir(source).map_err(|e| {
        VoidCrawlError::Other(format!("read snapshot source {}: {e}", source.display()))
    })? {
        let entry =
            entry.map_err(|e| VoidCrawlError::Other(format!("read snapshot entry: {e}")))?;
        let name = entry.file_name();
        let name_text = name.to_string_lossy();
        if name_text == ".voidcrawl.lock" || name_text.starts_with("Singleton") {
            continue;
        }
        let from = entry.path();
        let to = destination.join(name);
        let file_type = entry.file_type().map_err(|e| {
            VoidCrawlError::Other(format!("read snapshot file type {}: {e}", from.display()))
        })?;
        // Chrome profiles should be self-contained. Never follow arbitrary
        // links out of the leased source tree into a worker snapshot.
        if file_type.is_symlink() {
            continue;
        }
        if file_type.is_dir() {
            copy_snapshot_recursively(&from, &to)?;
        } else if file_type.is_file() {
            fs::copy(&from, &to).map_err(|e| {
                VoidCrawlError::Other(format!(
                    "copy snapshot {} to {}: {e}",
                    from.display(),
                    to.display()
                ))
            })?;
        }
    }
    Ok(())
}

pub(super) fn copy_dir_recursively(source: &Path, destination: &Path) -> Result<()> {
    fs::create_dir_all(destination).map_err(|e| {
        VoidCrawlError::Other(format!(
            "create clone destination {}: {e}",
            destination.display()
        ))
    })?;
    for entry in fs::read_dir(source)
        .map_err(|e| VoidCrawlError::Other(format!("read_dir {}: {e}", source.display())))?
    {
        let entry = entry.map_err(|e| VoidCrawlError::Other(format!("read_dir entry: {e}")))?;
        let source_path = entry.path();
        if source_path.file_name().and_then(|s| s.to_str()) == Some(".voidcrawl.lock") {
            continue;
        }
        let destination_path = destination.join(entry.file_name());
        let metadata = entry.metadata().map_err(|e| {
            VoidCrawlError::Other(format!("metadata {}: {e}", source_path.display()))
        })?;
        if metadata.is_dir() {
            copy_dir_recursively(&source_path, &destination_path)?;
        } else {
            fs::copy(&source_path, &destination_path).map_err(|e| {
                VoidCrawlError::Other(format!(
                    "copy {} to {}: {e}",
                    source_path.display(),
                    destination_path.display()
                ))
            })?;
        }
    }
    seed_standalone_profile(destination)
}
