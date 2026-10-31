use std::{
    env,
    fs::{self, File, OpenOptions},
    io::{ErrorKind, Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
};

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::values::MAX_STATE_BYTES;
use super::{Backend, Change, Coordination, RegistryError, Revision, Snapshot};

const VERSION: u16 = 1;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Record {
    version: u16,
    event: Event,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Event {
    Checkpoint {
        snapshot: Snapshot,
    },
    Commit {
        expected: Revision,
        changes: Vec<Change>,
    },
}

pub(super) struct Jsonl {
    path: PathBuf,
    lock_path: PathBuf,
}

impl Jsonl {
    pub(super) fn open(path: &Path) -> Result<Self, RegistryError> {
        let path = if path.is_absolute() {
            path.to_owned()
        } else {
            env::current_dir()?.join(path)
        };
        let parent = path.parent().ok_or(RegistryError::InvalidState)?;
        fs::create_dir_all(parent)?;
        let path = if path.exists() {
            fs::canonicalize(&path)?
        } else {
            fs::canonicalize(parent)?.join(path.file_name().ok_or(RegistryError::InvalidState)?)
        };
        let mut lock_name = path.as_os_str().to_owned();
        lock_name.push(".lock");
        let backend = Self {
            path,
            lock_path: lock_name.into(),
        };
        let _lock = backend.lock()?;
        match file_options().create_new(true).open(&backend.path) {
            Ok(mut file) => {
                let record = Record {
                    version: VERSION,
                    event: Event::Checkpoint {
                        snapshot: Snapshot::empty(),
                    },
                };
                append(&mut file, &record)?;
                sync_parent(&backend.path)?;
            }
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                backend.read()?.0.validate()?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(backend)
    }

    fn lock(&self) -> Result<File, RegistryError> {
        let file = file_options()
            .create(true)
            .truncate(false)
            .open(&self.lock_path)?;
        file.try_lock().map_err(|error| match error {
            fs::TryLockError::WouldBlock => RegistryError::Busy,
            fs::TryLockError::Error(error) => RegistryError::Io(error),
        })?;
        Ok(file)
    }

    /// Ignore only a final unterminated write. Every newline-terminated record
    /// must decode and validate. The next append truncates that abandoned tail.
    fn read(&self) -> Result<(Snapshot, u64), RegistryError> {
        if !fs::metadata(&self.path)?.is_file() {
            return Err(RegistryError::InvalidState);
        }
        let mut bytes = Vec::new();
        File::open(&self.path)?
            .take(MAX_JOURNAL_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if byte_count(bytes.len())? > MAX_JOURNAL_BYTES {
            return Err(RegistryError::CapacityExceeded);
        }
        let mut state: Option<Snapshot> = None;
        let mut committed_bytes = 0_u64;
        for line in bytes.split_inclusive(|byte| *byte == b'\n') {
            if !line.ends_with(b"\n") {
                break;
            }
            if line.len() > MAX_STATE_BYTES + 1024 * 1024 {
                return Err(RegistryError::CapacityExceeded);
            }
            let record: Record =
                serde_json::from_slice(line).map_err(|_| RegistryError::InvalidState)?;
            if record.version != VERSION {
                return Err(RegistryError::InvalidState);
            }
            state = Some(match (state, record.event) {
                (None, Event::Checkpoint { snapshot }) => {
                    snapshot.validate()?;
                    snapshot
                }
                (Some(snapshot), Event::Commit { expected, changes }) if !changes.is_empty() => {
                    snapshot
                        .changed(&expected, &changes)
                        .map_err(|_| RegistryError::InvalidState)?
                }
                _ => return Err(RegistryError::InvalidState),
            });
            committed_bytes = committed_bytes
                .checked_add(byte_count(line.len())?)
                .ok_or(RegistryError::CapacityExceeded)?;
        }
        Ok((state.ok_or(RegistryError::InvalidState)?, committed_bytes))
    }
}

impl Backend for Jsonl {
    fn coordination(&self) -> Coordination {
        Coordination::LocalProcesses
    }

    fn snapshot(&self) -> Result<Snapshot, RegistryError> {
        let _lock = self.lock()?;
        Ok(self.read()?.0)
    }

    fn commit(&self, expected: &Revision, changes: &[Change]) -> Result<Snapshot, RegistryError> {
        let _lock = self.lock()?;
        let (state, committed_bytes) = self.read()?;
        let next = state.changed(expected, changes)?;
        if !changes.is_empty() {
            let record = Record {
                version: VERSION,
                event: Event::Commit {
                    expected: expected.clone(),
                    changes: changes.to_vec(),
                },
            };
            let mut file = file_options().open(&self.path)?;
            file.set_len(committed_bytes)?;
            file.seek(SeekFrom::Start(committed_bytes))?;
            append(&mut file, &record)?;
        }
        Ok(next)
    }

    fn compact(&self) -> Result<(), RegistryError> {
        let _lock = self.lock()?;
        let (snapshot, _) = self.read()?;
        let mut staging_name = self.path.as_os_str().to_owned();
        staging_name.push(format!(".{}.tmp", Uuid::new_v4()));
        let staging = PathBuf::from(staging_name);
        let result = (|| {
            let mut file = file_options().create_new(true).open(&staging)?;
            append(
                &mut file,
                &Record {
                    version: VERSION,
                    event: Event::Checkpoint { snapshot },
                },
            )?;
            drop(file);
            fs::rename(&staging, &self.path)?;
            sync_parent(&self.path)
        })();
        if result.is_err() {
            let _ = fs::remove_file(staging);
        }
        result
    }
}

fn append(file: &mut File, record: &Record) -> Result<(), RegistryError> {
    let mut bytes = serde_json::to_vec(record)?;
    bytes.push(b'\n');
    if bytes.len() > MAX_STATE_BYTES + 1024 * 1024 {
        return Err(RegistryError::CapacityExceeded);
    }
    let end = file
        .stream_position()?
        .checked_add(byte_count(bytes.len())?)
        .ok_or(RegistryError::CapacityExceeded)?;
    if end > MAX_JOURNAL_BYTES {
        return Err(RegistryError::CapacityExceeded);
    }
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn file_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
}

fn byte_count(length: usize) -> Result<u64, RegistryError> {
    u64::try_from(length).map_err(|_| RegistryError::CapacityExceeded)
}

fn sync_parent(path: &Path) -> Result<(), RegistryError> {
    #[cfg(not(unix))]
    let _ = path;
    #[cfg(unix)]
    File::open(path.parent().ok_or(RegistryError::InvalidState)?)?.sync_all()?;
    Ok(())
}

pub(super) fn global_path() -> Result<PathBuf, RegistryError> {
    #[cfg(windows)]
    let base = env::var_os("LOCALAPPDATA").map(PathBuf::from);
    #[cfg(not(windows))]
    let base = env::var_os("XDG_STATE_HOME").map_or_else(
        || env::var_os("HOME").map(|path| PathBuf::from(path).join(".local/state")),
        |path| Some(PathBuf::from(path)),
    );
    base.filter(|path| path.is_absolute())
        .map(|path| path.join("yosoi/registry.jsonl"))
        .ok_or(RegistryError::NoGlobalLocation)
}
