//! Stage complete files beside their originals, then replace each with an atomic rename.
use std::{
    fs,
    io::{self, Write},
    path::Path,
};

use anyhow::{Context, Result, bail};
use tempfile::{Builder, NamedTempFile};

use super::Change;

struct Replacement<'a> {
    change: &'a Change,
    next: NamedTempFile,
    original: NamedTempFile,
}

pub(super) struct Staged<'a> {
    replacements: Vec<Replacement<'a>>,
}

fn verify<'a>(changes: impl Iterator<Item = &'a Change>) -> Result<()> {
    for change in changes {
        if fs::read_to_string(&change.path)? != change.before {
            bail!(
                "{} changed during version planning; rerun the command",
                change.path.display()
            );
        }
    }
    Ok(())
}

fn temporary(path: &Path, contents: &str, prefix: &str) -> Result<NamedTempFile> {
    let parent = path
        .parent()
        .context("release file has no parent directory")?;
    let mut temporary = Builder::new()
        .prefix(prefix)
        .tempfile_in(parent)
        .with_context(|| format!("failed to stage {}", path.display()))?;
    temporary.write_all(contents.as_bytes())?;
    temporary
        .as_file()
        .set_permissions(fs::metadata(path)?.permissions())?;
    temporary.as_file().sync_all()?;
    Ok(temporary)
}

pub(super) fn stage(changes: &[Change]) -> Result<Staged<'_>> {
    for change in changes {
        if fs::symlink_metadata(&change.path)?.file_type().is_symlink() {
            bail!(
                "release file {} must not be a symlink",
                change.path.display()
            );
        }
    }
    verify(changes.iter())?;
    let mut replacements = Vec::new();
    for change in changes {
        replacements.push(Replacement {
            change,
            next: temporary(&change.path, &change.after, ".yosoi-version-next-")?,
            original: temporary(&change.path, &change.before, ".yosoi-version-backup-")?,
        });
    }
    Ok(Staged { replacements })
}

impl Staged<'_> {
    pub(super) fn commit(self) -> Result<()> {
        self.commit_with(|from, to| fs::rename(from, to))
    }

    fn commit_with(self, mut rename: impl FnMut(&Path, &Path) -> io::Result<()>) -> Result<()> {
        verify(
            self.replacements
                .iter()
                .map(|replacement| replacement.change),
        )?;
        let mut committed: Vec<Replacement<'_>> = Vec::new();
        for replacement in self.replacements {
            // Keep the tempfile object available for cleanup and every backup until all renames succeed.
            if let Err(error) = rename(replacement.next.path(), &replacement.change.path) {
                let mut failures = Vec::new();
                for previous in committed.into_iter().rev() {
                    if let Err(restore_error) =
                        fs::rename(previous.original.path(), &previous.change.path)
                    {
                        let backup = previous.original.path().to_owned();
                        let retention = previous.original.keep();
                        failures.push(format!(
                            "{}: {restore_error}; backup at {}; retention: {}",
                            previous.change.path.display(),
                            backup.display(),
                            if retention.is_ok() {
                                "preserved"
                            } else {
                                "failed"
                            }
                        ));
                    }
                }
                if !failures.is_empty() {
                    bail!(
                        "release update failed: {error}; rollback failures: {}",
                        failures.join("; ")
                    );
                }
                return Err(error).context("release update failed; committed files restored");
            }
            committed.push(replacement);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::panic_in_result_fn)]
    use super::*;

    #[test]
    fn failure_after_first_rename_restores_originals_and_cleans_staging() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let mut changes = Vec::new();
        for name in ["one", "two"] {
            let path = directory.path().join(name);
            fs::write(&path, "before")?;
            changes.push(Change {
                path,
                before: "before".to_owned(),
                after: "after".to_owned(),
            });
        }
        let staged = stage(&changes)?;
        assert_eq!(fs::read_dir(directory.path())?.count(), 6);
        let mut first = true;
        let result = staged.commit_with(|from, to| {
            if first {
                first = false;
                fs::rename(from, to)
            } else {
                Err(io::Error::other("injected second rename failure"))
            }
        });
        assert!(result.is_err());
        for change in &changes {
            assert_eq!(fs::read_to_string(&change.path)?, "before");
        }
        assert_eq!(fs::read_dir(directory.path())?.count(), 2);
        Ok(())
    }

    #[test]
    fn edit_after_confirmation_staging_is_preserved() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("one");
        fs::write(&path, "before")?;
        let changes = vec![Change {
            path: path.clone(),
            before: "before".to_owned(),
            after: "after".to_owned(),
        }];
        let staged = stage(&changes)?;
        fs::write(&path, "concurrent edit")?;
        assert!(staged.commit().is_err());
        assert_eq!(fs::read_to_string(&path)?, "concurrent edit");
        assert_eq!(fs::read_dir(directory.path())?.count(), 1);
        Ok(())
    }
}
