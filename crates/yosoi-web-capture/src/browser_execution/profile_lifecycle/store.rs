use std::{
    collections::BTreeMap,
    fmt,
    fs::{self, File, OpenOptions},
    io::{ErrorKind, Write},
    path::PathBuf,
    process,
    sync::atomic::{AtomicU64, Ordering},
};

#[cfg(test)]
use std::sync::Arc;

use chrono::{DateTime, Utc};

use super::super::BrowserProfileId;
use super::{
    BrowserProfileLifecycleError, BrowserProfileLifecycleEvent, BrowserProfileLifecycleReason,
    BrowserProfileLifecycleRecord, BrowserProfileLifecycleSource, BrowserProfileLifecycleState,
    ProfileLifecycleStoreError, classify_abandoned_on_startup,
};

const PROFILE_LIFECYCLE_LOCK_FILE: &str = ".profile-lifecycle.lock";
const TEMPORARY_FILE_ATTEMPTS: usize = 16;
static TEMPORARY_FILE_SEQUENCE: AtomicU64 = AtomicU64::new(1);

/// Local filesystem store for the latest validated record of each profile.
///
/// The caller chooses the root explicitly. Operations coordinate with other
/// store instances through a persistent lock file and replace each record via
/// a same-directory temporary file and atomic rename.
#[derive(Clone)]
pub struct ProfileLifecycleStore {
    root: PathBuf,
    #[cfg(test)]
    fail_after_commits: Arc<AtomicU64>,
}

impl fmt::Debug for ProfileLifecycleStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProfileLifecycleStore")
            .field("root", &"<redacted>")
            .finish()
    }
}

impl ProfileLifecycleStore {
    pub fn new(root: impl Into<PathBuf>) -> Result<Self, ProfileLifecycleStoreError> {
        let root = root.into();
        if root.as_os_str().is_empty() {
            return Err(ProfileLifecycleStoreError::EmptyRoot);
        }
        Ok(Self {
            root,
            #[cfg(test)]
            fail_after_commits: Arc::new(AtomicU64::new(0)),
        })
    }

    #[cfg(test)]
    pub(crate) fn fail_after_commits_for_test(&self, successful_commits: u64) {
        self.fail_after_commits
            .store(successful_commits.saturating_add(1), Ordering::Release);
    }

    /// Persists the initial staged state for a new profile identity.
    pub fn stage_profile(
        &self,
        profile_id: &BrowserProfileId,
        observed_at: DateTime<Utc>,
    ) -> Result<BrowserProfileLifecycleRecord, ProfileLifecycleStoreError> {
        let record = BrowserProfileLifecycleRecord::from_event(
            observed_at,
            BrowserProfileLifecycleState::Staged,
            None,
            BrowserProfileLifecycleEvent::ProfileStaged,
        )
        .map_err(|_| ProfileLifecycleStoreError::InvalidRecord)?;
        self.commit(profile_id, &record)?;
        Ok(record)
    }

    /// Loads the latest persisted state for one profile.
    pub fn record(
        &self,
        profile_id: &BrowserProfileId,
    ) -> Result<Option<BrowserProfileLifecycleRecord>, ProfileLifecycleStoreError> {
        let _lock = self.lock_root()?;
        self.read_profile_unlocked(profile_id)
    }

    /// Applies one lifecycle event while holding the store-wide filesystem
    /// lock, so concurrent managers cannot both acquire the same Available
    /// generation.
    pub fn transition(
        &self,
        profile_id: &BrowserProfileId,
        observed_at: DateTime<Utc>,
        event: BrowserProfileLifecycleEvent,
    ) -> Result<BrowserProfileLifecycleRecord, ProfileLifecycleStoreError> {
        let _lock = self.lock_root()?;
        let current = self
            .read_profile_unlocked(profile_id)?
            .ok_or(ProfileLifecycleStoreError::InvalidInitialRecord)?;
        let record = BrowserProfileLifecycleRecord::from_event(
            observed_at,
            current.next(),
            current.latest_generation(),
            event,
        )
        .map_err(|error| match error {
            BrowserProfileLifecycleError::StaleGeneration
            | BrowserProfileLifecycleError::InvalidTransition => {
                ProfileLifecycleStoreError::StaleTransition
            }
            BrowserProfileLifecycleError::InvalidRecord
            | BrowserProfileLifecycleError::UnsupportedSchemaVersion => {
                ProfileLifecycleStoreError::InvalidRecord
            }
        })?;
        self.write_record_unlocked(profile_id, &record)?;
        Ok(record)
    }

    /// Classifies an abandoned profile during manager startup. Only the
    /// requested identity is touched, so opening one manager does not
    /// quarantine unrelated profiles that may still be live in this process.
    pub fn classify_profile_abandoned_on_startup(
        &self,
        profile_id: &BrowserProfileId,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<BrowserProfileLifecycleRecord>, ProfileLifecycleStoreError> {
        let _lock = self.lock_root()?;
        let Some(current_record) = self.read_profile_unlocked(profile_id)? else {
            return Ok(None);
        };
        let previous = current_record.next();
        let next = classify_abandoned_on_startup(previous);
        if previous == next {
            return Ok(Some(current_record));
        }
        let reason = match previous {
            BrowserProfileLifecycleState::Staged => {
                BrowserProfileLifecycleReason::StartupProvisionInterrupted
            }
            BrowserProfileLifecycleState::Leased { .. } => {
                BrowserProfileLifecycleReason::StartupLeaseInterrupted
            }
            BrowserProfileLifecycleState::Available
            | BrowserProfileLifecycleState::Quarantined { .. }
            | BrowserProfileLifecycleState::Retired => {
                return Err(ProfileLifecycleStoreError::InvalidRecord);
            }
        };
        let record = BrowserProfileLifecycleRecord::new(
            observed_at,
            BrowserProfileLifecycleSource::StartupClassifier,
            previous,
            current_record.latest_generation(),
            next,
            current_record.latest_generation(),
            reason,
        )
        .map_err(|_| ProfileLifecycleStoreError::InvalidRecord)?;
        self.write_record_unlocked(profile_id, &record)?;
        Ok(Some(record))
    }

    /// Loads all latest records in deterministic profile-id order.
    pub fn load_all(
        &self,
    ) -> Result<BTreeMap<BrowserProfileId, BrowserProfileLifecycleRecord>, ProfileLifecycleStoreError>
    {
        let _lock = self.lock_root()?;
        self.load_all_unlocked()
    }

    /// Commits a record only when its prior state matches the stored state.
    pub fn commit(
        &self,
        profile_id: &BrowserProfileId,
        record: &BrowserProfileLifecycleRecord,
    ) -> Result<(), ProfileLifecycleStoreError> {
        let _lock = self.lock_root()?;
        let existing = self.read_profile_unlocked(profile_id)?;
        match existing {
            Some(existing)
                if existing.next() == record.previous()
                    && existing.latest_generation() == record.previous_latest_generation() => {}
            Some(_) => return Err(ProfileLifecycleStoreError::StaleTransition),
            None if record.previous() == BrowserProfileLifecycleState::Staged
                && record.previous_latest_generation().is_none()
                && record.latest_generation().is_none()
                && record.reason() == BrowserProfileLifecycleReason::ProfileStaged => {}
            None => return Err(ProfileLifecycleStoreError::InvalidInitialRecord),
        }
        self.write_record_unlocked(profile_id, record)
    }

    /// Quarantines persisted staged and leased states after process restart.
    /// Other states are left as-is; this method never recovers or deletes data.
    pub fn classify_abandoned_on_startup(
        &self,
        observed_at: DateTime<Utc>,
    ) -> Result<Vec<(BrowserProfileId, BrowserProfileLifecycleRecord)>, ProfileLifecycleStoreError>
    {
        let _lock = self.lock_root()?;
        let records = self.load_all_unlocked()?;
        let mut quarantined = Vec::new();
        for (profile_id, current_record) in records {
            let previous = current_record.next();
            let next = classify_abandoned_on_startup(previous);
            if previous == next {
                continue;
            }
            let Some(record) = Self::classify_record(&current_record, previous, next, observed_at)?
            else {
                continue;
            };
            self.write_record_unlocked(&profile_id, &record)?;
            quarantined.push((profile_id, record));
        }
        Ok(quarantined)
    }

    fn lock_root(&self) -> Result<File, ProfileLifecycleStoreError> {
        fs::create_dir_all(&self.root).map_err(|_| ProfileLifecycleStoreError::Io)?;
        let lock_path = self.root.join(PROFILE_LIFECYCLE_LOCK_FILE);
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(lock_path)
            .map_err(|_| ProfileLifecycleStoreError::Io)?;
        lock.lock()
            .map_err(|_| ProfileLifecycleStoreError::LockUnavailable)?;
        Ok(lock)
    }

    fn classify_record(
        current_record: &BrowserProfileLifecycleRecord,
        previous: BrowserProfileLifecycleState,
        next: BrowserProfileLifecycleState,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<BrowserProfileLifecycleRecord>, ProfileLifecycleStoreError> {
        if previous == next {
            return Ok(None);
        }
        let reason = match previous {
            BrowserProfileLifecycleState::Staged => {
                BrowserProfileLifecycleReason::StartupProvisionInterrupted
            }
            BrowserProfileLifecycleState::Leased { .. } => {
                BrowserProfileLifecycleReason::StartupLeaseInterrupted
            }
            BrowserProfileLifecycleState::Available
            | BrowserProfileLifecycleState::Quarantined { .. }
            | BrowserProfileLifecycleState::Retired => {
                return Err(ProfileLifecycleStoreError::InvalidRecord);
            }
        };
        let record = BrowserProfileLifecycleRecord::new(
            observed_at,
            BrowserProfileLifecycleSource::StartupClassifier,
            previous,
            current_record.latest_generation(),
            next,
            current_record.latest_generation(),
            reason,
        )
        .map_err(|_| ProfileLifecycleStoreError::InvalidRecord)?;
        Ok(Some(record))
    }

    fn load_all_unlocked(
        &self,
    ) -> Result<BTreeMap<BrowserProfileId, BrowserProfileLifecycleRecord>, ProfileLifecycleStoreError>
    {
        let entries = match fs::read_dir(&self.root) {
            Ok(entries) => entries,
            Err(error) if error.kind() == ErrorKind::NotFound => {
                return Ok(BTreeMap::new());
            }
            Err(_) => return Err(ProfileLifecycleStoreError::Io),
        };
        let mut records = BTreeMap::new();
        for entry in entries {
            let entry = entry.map_err(|_| ProfileLifecycleStoreError::Io)?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| ProfileLifecycleStoreError::CorruptStore)?;
            if name == PROFILE_LIFECYCLE_LOCK_FILE || is_temporary_lifecycle_file(&name) {
                continue;
            }
            let stem = name
                .strip_suffix(".json")
                .ok_or(ProfileLifecycleStoreError::CorruptStore)?;
            let profile_id = BrowserProfileId::new(stem.to_owned())
                .map_err(|_| ProfileLifecycleStoreError::CorruptStore)?;
            let file_type = entry
                .file_type()
                .map_err(|_| ProfileLifecycleStoreError::Io)?;
            if !file_type.is_file() {
                return Err(ProfileLifecycleStoreError::CorruptStore);
            }
            let bytes = fs::read(entry.path()).map_err(|_| ProfileLifecycleStoreError::Io)?;
            let record = serde_json::from_slice(&bytes)
                .map_err(|_| ProfileLifecycleStoreError::CorruptRecord)?;
            records.insert(profile_id, record);
        }
        Ok(records)
    }

    fn read_profile_unlocked(
        &self,
        profile_id: &BrowserProfileId,
    ) -> Result<Option<BrowserProfileLifecycleRecord>, ProfileLifecycleStoreError> {
        let path = self.record_path(profile_id);
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(ProfileLifecycleStoreError::Io),
        };
        if !metadata.file_type().is_file() {
            return Err(ProfileLifecycleStoreError::CorruptStore);
        }
        let bytes = fs::read(path).map_err(|_| ProfileLifecycleStoreError::Io)?;
        serde_json::from_slice(&bytes)
            .map(Some)
            .map_err(|_| ProfileLifecycleStoreError::CorruptRecord)
    }

    fn write_record_unlocked(
        &self,
        profile_id: &BrowserProfileId,
        record: &BrowserProfileLifecycleRecord,
    ) -> Result<(), ProfileLifecycleStoreError> {
        #[cfg(test)]
        if self
            .fail_after_commits
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |remaining| {
                remaining.checked_sub(1)
            })
            == Ok(1)
        {
            return Err(ProfileLifecycleStoreError::Io);
        }
        let bytes =
            serde_json::to_vec(record).map_err(|_| ProfileLifecycleStoreError::InvalidRecord)?;
        let destination = self.record_path(profile_id);
        for _ in 0..TEMPORARY_FILE_ATTEMPTS {
            let sequence = TEMPORARY_FILE_SEQUENCE
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                    value.checked_add(1)
                })
                .map_err(|_| ProfileLifecycleStoreError::TemporaryNameUnavailable)?;
            let temporary = self.root.join(format!(
                ".{}.{}.{}.tmp",
                profile_id.as_str(),
                process::id(),
                sequence
            ));
            let mut file = match OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)
            {
                Ok(file) => file,
                Err(error) if error.kind() == ErrorKind::AlreadyExists => continue,
                Err(_) => return Err(ProfileLifecycleStoreError::Io),
            };
            file.write_all(&bytes)
                .map_err(|_| ProfileLifecycleStoreError::Io)?;
            file.sync_all()
                .map_err(|_| ProfileLifecycleStoreError::Io)?;
            drop(file);
            fs::rename(&temporary, &destination).map_err(|_| ProfileLifecycleStoreError::Io)?;
            return Ok(());
        }
        Err(ProfileLifecycleStoreError::TemporaryNameUnavailable)
    }

    fn record_path(&self, profile_id: &BrowserProfileId) -> PathBuf {
        self.root.join(format!("{}.json", profile_id.as_str()))
    }
}

fn is_temporary_lifecycle_file(name: &str) -> bool {
    name.starts_with('.')
        && name
            .rsplit_once('.')
            .is_some_and(|(_, extension)| extension.eq_ignore_ascii_case("tmp"))
}
