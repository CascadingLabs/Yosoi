//! VoidCrawl-owned Chromium profile registry.
//!
//! Managed profiles are standalone Chrome `user_data_dir` roots below
//! `$VOIDCRAWL_PROFILE_ROOT` (or the platform data-dir default). They are not
//! subprofiles inside the user's daily Chrome data directory.

use std::{
    collections::BTreeMap,
    env, fmt, fs,
    fs::{File, OpenOptions, TryLockError},
    io,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::internal::browser::{
    error::{Result, VoidCrawlError},
    lease::{read_metadata, write_metadata},
};

const MANIFEST_FILE: &str = "registry.json";
const STAGING_DIRECTORY: &str = ".staging";

mod copy;
mod fork;
mod staging;

pub use fork::{
    MAX_PROFILE_SPLIT_COPIES, ManagedProfileForkBatch, ManagedProfileForkError,
    ManagedProfileForkErrorKind, ManagedProfileForkFailureFacts, ManagedProfileForkOperation,
    ManagedProfileSnapshot,
};
pub use staging::{
    ManagedProfileLeaseRelease, ManagedProfileStagingDisposition, ManagedProfileStagingError,
    ManagedProfileStagingErrorKind, ManagedProfileStagingOperation, StagedManagedProfile,
};

#[derive(Debug, Clone)]
pub struct ProfileRegistry {
    root: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ManagedProfile {
    pub id: String,
    pub path: PathBuf,
    pub created_at: u64,
    pub last_used_at: Option<u64>,
    pub labels: Vec<String>,
    pub description: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ManagedProfileDescription {
    #[serde(flatten)]
    pub profile: ManagedProfile,
    pub size: u64,
    pub status: ProfileStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProfileStatus {
    Available,
    Locked,
    Missing,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ProfilePool {
    pub name: String,
    pub profile_ids: Vec<String>,
    pub max_active: usize,
    pub round_robin: bool,
    #[serde(default)]
    pub next_index: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ResolvedProfilePool {
    pub pool: ProfilePool,
    pub profiles: Vec<ManagedProfileDescription>,
}

pub struct ManagedProfileLease {
    id: String,
    path: PathBuf,
    _lock: File,
}

impl fmt::Debug for ManagedProfileLease {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ManagedProfileLease")
            .field("id", &self.id)
            .field("path", &self.path)
            .finish_non_exhaustive()
    }
}

impl ManagedProfileLease {
    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct Manifest {
    #[serde(default)]
    profiles: BTreeMap<String, ManagedProfile>,
    #[serde(default)]
    pools: BTreeMap<String, ProfilePool>,
}

impl Default for ProfileRegistry {
    fn default() -> Self {
        Self {
            root: default_profile_root(),
        }
    }
}

impl ProfileRegistry {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn create_profile(
        &self,
        id: &str,
        description: Option<String>,
        labels: Vec<String>,
    ) -> Result<ManagedProfileDescription> {
        validate_name(id, "profile id")?;
        self.with_manifest_write(|manifest| {
            let profile_path = self.profile_path(id);
            let staged_path = self.staged_profile_path(id);
            if manifest.profiles.contains_key(id)
                || path_entry_exists(&profile_path).map_err(|error| {
                    VoidCrawlError::Other(format!("inspect managed profile destination: {error}"))
                })?
                || path_entry_exists(&staged_path).map_err(|error| {
                    VoidCrawlError::Other(format!("inspect managed profile staging: {error}"))
                })?
            {
                return Err(VoidCrawlError::Other(format!(
                    "managed profile {id:?} already exists"
                )));
            }
            let path = profile_path;
            fs::create_dir_all(&path).map_err(|e| {
                VoidCrawlError::Other(format!("create profile dir {}: {e}", path.display()))
            })?;
            seed_standalone_profile(&path)?;
            let profile = ManagedProfile {
                id: id.to_string(),
                path,
                created_at: now_epoch_secs(),
                last_used_at: None,
                labels,
                description,
            };
            manifest.profiles.insert(id.to_string(), profile.clone());
            Self::describe_existing(profile)
        })
    }

    pub fn clone_profile(
        &self,
        source_id_or_path: &str,
        id: &str,
        description: Option<String>,
        labels: Vec<String>,
    ) -> Result<ManagedProfileDescription> {
        validate_name(id, "profile id")?;
        self.with_manifest_write(|manifest| {
            if manifest.profiles.contains_key(id) {
                return Err(VoidCrawlError::Other(format!(
                    "managed profile {id:?} already exists"
                )));
            }
            let source = manifest.profiles.get(source_id_or_path).map_or_else(
                || PathBuf::from(expand_tilde(source_id_or_path)),
                |p| p.path.clone(),
            );
            if !source.is_dir() {
                return Err(VoidCrawlError::ProfileNotFound {
                    name: source_id_or_path.to_string(),
                    searched: vec![self.root.display().to_string()],
                });
            }
            let path = self.profile_path(id);
            copy::copy_dir_recursively(&source, &path)?;
            let profile = ManagedProfile {
                id: id.to_string(),
                path,
                created_at: now_epoch_secs(),
                last_used_at: None,
                labels,
                description,
            };
            manifest.profiles.insert(id.to_string(), profile.clone());
            Self::describe_existing(profile)
        })
    }

    pub fn list_profiles(&self) -> Result<Vec<ManagedProfileDescription>> {
        let manifest = self.load_manifest()?;
        manifest
            .profiles
            .into_values()
            .map(Self::describe_existing)
            .collect()
    }

    pub fn describe_profile(&self, id: &str) -> Result<ManagedProfileDescription> {
        let manifest = self.load_manifest()?;
        let profile =
            manifest
                .profiles
                .get(id)
                .cloned()
                .ok_or_else(|| VoidCrawlError::ProfileNotFound {
                    name: id.to_string(),
                    searched: vec![self.root.display().to_string()],
                })?;
        Self::describe_existing(profile)
    }

    pub fn delete_profile(&self, id: &str) -> Result<bool> {
        self.with_manifest_write(|manifest| {
            let Some(profile) = manifest.profiles.get(id).cloned() else {
                return Ok(false);
            };
            if matches!(lock_status(&profile.path)?, ProfileStatus::Locked) {
                return Err(profile_busy(id, &profile.path.join(".voidcrawl.lock")));
            }
            if profile.path.exists() {
                fs::remove_dir_all(&profile.path).map_err(|e| {
                    VoidCrawlError::Other(format!(
                        "delete profile dir {}: {e}",
                        profile.path.display()
                    ))
                })?;
            }
            manifest.profiles.remove(id);
            for pool in manifest.pools.values_mut() {
                pool.profile_ids.retain(|profile_id| profile_id != id);
                if pool.profile_ids.is_empty() {
                    pool.next_index = 0;
                } else {
                    pool.next_index = pool
                        .next_index
                        .checked_rem(pool.profile_ids.len())
                        .unwrap_or(0);
                }
            }
            Ok(true)
        })
    }

    pub fn create_pool(
        &self,
        name: &str,
        profile_ids: Vec<String>,
        max_active: usize,
    ) -> Result<ProfilePool> {
        validate_name(name, "pool name")?;
        if profile_ids.is_empty() {
            return Err(VoidCrawlError::Other(
                "profile pool requires at least one profile".into(),
            ));
        }
        self.with_manifest_write(|manifest| {
            for profile_id in &profile_ids {
                if !manifest.profiles.contains_key(profile_id) {
                    return Err(VoidCrawlError::ProfileNotFound {
                        name: profile_id.clone(),
                        searched: vec![self.root.display().to_string()],
                    });
                }
            }
            let pool = ProfilePool {
                name: name.to_string(),
                profile_ids,
                max_active: max_active.max(1),
                round_robin: true,
                next_index: 0,
            };
            manifest.pools.insert(name.to_string(), pool.clone());
            Ok(pool)
        })
    }

    pub fn list_pools(&self) -> Result<Vec<ProfilePool>> {
        let manifest = self.load_manifest()?;
        Ok(manifest.pools.into_values().collect())
    }

    pub fn resolve_pool(&self, name: &str) -> Result<ResolvedProfilePool> {
        let manifest = self.load_manifest()?;
        let pool = manifest.pools.get(name).cloned().ok_or_else(|| {
            VoidCrawlError::Other(format!("managed profile pool {name:?} not found"))
        })?;
        let mut profiles = Vec::with_capacity(pool.profile_ids.len());
        for id in &pool.profile_ids {
            let profile = manifest.profiles.get(id).cloned().ok_or_else(|| {
                VoidCrawlError::ProfileNotFound {
                    name: id.clone(),
                    searched: vec![self.root.display().to_string()],
                }
            })?;
            profiles.push(Self::describe_existing(profile)?);
        }
        Ok(ResolvedProfilePool { pool, profiles })
    }

    pub fn acquire_profile(&self, id: &str) -> Result<ManagedProfileLease> {
        self.with_manifest_write(|manifest| {
            let profile =
                manifest
                    .profiles
                    .get_mut(id)
                    .ok_or_else(|| VoidCrawlError::ProfileNotFound {
                        name: id.to_string(),
                        searched: vec![self.root.display().to_string()],
                    })?;
            let lease = acquire_profile_lock(&profile.id, &profile.path)?;
            profile.last_used_at = Some(now_epoch_secs());
            Ok(lease)
        })
    }

    pub fn acquire_from_pool(&self, name: &str) -> Result<ManagedProfileLease> {
        self.with_manifest_write(|manifest| {
            let pool = manifest.pools.get_mut(name).ok_or_else(|| {
                VoidCrawlError::Other(format!("managed profile pool {name:?} not found"))
            })?;
            if pool.profile_ids.is_empty() {
                return Err(VoidCrawlError::Other(format!(
                    "managed profile pool {name:?} is empty"
                )));
            }

            let active_cap = pool.max_active.max(1).min(pool.profile_ids.len());
            let start = if pool.round_robin {
                pool.next_index
                    .checked_rem(pool.profile_ids.len())
                    .unwrap_or(0)
            } else {
                0
            };
            let mut last_busy: Option<String> = None;
            for offset in 0..active_cap {
                let index = start
                    .checked_add(offset)
                    .and_then(|value| value.checked_rem(pool.profile_ids.len()))
                    .unwrap_or(0);
                let Some(id) = pool.profile_ids.get(index).cloned() else {
                    return Err(VoidCrawlError::Other(
                        "managed profile pool index is invalid".into(),
                    ));
                };
                let profile = manifest.profiles.get_mut(&id).ok_or_else(|| {
                    VoidCrawlError::ProfileNotFound {
                        name: id.clone(),
                        searched: vec![self.root.display().to_string()],
                    }
                })?;
                match acquire_profile_lock(&profile.id, &profile.path) {
                    Ok(lease) => {
                        pool.next_index = index
                            .checked_add(1)
                            .and_then(|value| value.checked_rem(pool.profile_ids.len()))
                            .unwrap_or(0);
                        profile.last_used_at = Some(now_epoch_secs());
                        return Ok(lease);
                    }
                    Err(VoidCrawlError::ProfileBusy { name, .. }) => {
                        last_busy = Some(name);
                    }
                    Err(err) => return Err(err),
                }
            }
            Err(VoidCrawlError::ProfileBusy {
                name: last_busy.unwrap_or_else(|| name.to_string()),
                pid: None,
                acquired_at: None,
            })
        })
    }

    fn profile_path(&self, id: &str) -> PathBuf {
        self.root.join(id)
    }

    fn staging_root(&self) -> PathBuf {
        self.root.join(STAGING_DIRECTORY)
    }

    fn staged_profile_path(&self, id: &str) -> PathBuf {
        self.staging_root().join(id)
    }

    fn manifest_path(&self) -> PathBuf {
        self.root.join(MANIFEST_FILE)
    }

    fn load_manifest(&self) -> Result<Manifest> {
        let path = self.manifest_path();
        if !path.exists() {
            return Ok(Manifest::default());
        }
        let raw = fs::read_to_string(&path)
            .map_err(|e| VoidCrawlError::Other(format!("read manifest {}: {e}", path.display())))?;
        serde_json::from_str(&raw).map_err(|e| {
            VoidCrawlError::Other(format!(
                "parse managed profile manifest {}: {e}",
                path.display()
            ))
        })
    }

    fn with_manifest_write<T>(&self, f: impl FnOnce(&mut Manifest) -> Result<T>) -> Result<T> {
        fs::create_dir_all(&self.root).map_err(|e| {
            VoidCrawlError::Other(format!(
                "create profile registry root {}: {e}",
                self.root.display()
            ))
        })?;
        let lock_path = self.root.join(".manifest.lock");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|e| VoidCrawlError::Other(format!("open {}: {e}", lock_path.display())))?;
        file.lock()
            .map_err(|e| VoidCrawlError::Other(format!("lock {}: {e}", lock_path.display())))?;
        let mut manifest = self.load_manifest()?;
        let result = f(&mut manifest)?;
        let raw = serde_json::to_string_pretty(&manifest).map_err(|e| {
            VoidCrawlError::Other(format!("serialize managed profile manifest: {e}"))
        })?;
        let manifest_path = self.manifest_path();
        let tmp_path = manifest_path.with_extension("json.tmp");
        fs::write(&tmp_path, raw).map_err(|e| {
            VoidCrawlError::Other(format!("write manifest temp {}: {e}", tmp_path.display()))
        })?;
        fs::rename(&tmp_path, &manifest_path).map_err(|e| {
            VoidCrawlError::Other(format!(
                "replace manifest {} with {}: {e}",
                manifest_path.display(),
                tmp_path.display()
            ))
        })?;
        Ok(result)
    }

    fn describe_existing(profile: ManagedProfile) -> Result<ManagedProfileDescription> {
        let status = if profile.path.is_dir() {
            lock_status(&profile.path)?
        } else {
            ProfileStatus::Missing
        };
        let size = if profile.path.is_dir() {
            dir_size(&profile.path)?
        } else {
            0
        };
        Ok(ManagedProfileDescription {
            profile,
            size,
            status,
        })
    }
}

pub fn default_profile_root() -> PathBuf {
    if let Ok(root) = env::var("VOIDCRAWL_PROFILE_ROOT") {
        return PathBuf::from(expand_tilde(&root));
    }
    #[cfg(target_os = "linux")]
    {
        if let Some(data_home) = env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
        {
            return data_home.join("voidcrawl").join("profiles");
        }
        if let Some(home) = env::var_os("HOME").map(PathBuf::from) {
            return home
                .join(".local")
                .join("share")
                .join("voidcrawl")
                .join("profiles");
        }
    }
    #[cfg(target_os = "macos")]
    {
        if let Some(home) = env::var_os("HOME").map(PathBuf::from) {
            return home
                .join("Library")
                .join("Application Support")
                .join("voidcrawl")
                .join("profiles");
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Some(local) = env::var_os("LOCALAPPDATA").map(PathBuf::from) {
            return local.join("voidcrawl").join("profiles");
        }
    }
    PathBuf::from(".voidcrawl").join("profiles")
}

fn expand_tilde(path: &str) -> String {
    let Some(rest) = path.strip_prefix('~') else {
        return path.to_owned();
    };
    let Ok(home) = env::var("HOME") else {
        return path.to_owned();
    };
    if rest.is_empty() {
        home
    } else if let Some(tail) = rest.strip_prefix('/') {
        format!("{home}/{tail}")
    } else {
        path.to_owned()
    }
}

fn resolve_profile(name: &str) -> Result<PathBuf> {
    let bases = chrome_user_data_dirs();
    let mut searched = Vec::with_capacity(bases.len());
    for base in bases {
        searched.push(base.display().to_string());
        let candidate = base.join(name);
        if candidate.is_dir() && candidate.join("Preferences").is_file() {
            return Ok(candidate);
        }
    }
    Err(VoidCrawlError::ProfileNotFound {
        name: name.to_string(),
        searched,
    })
}

fn chrome_user_data_dirs() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    #[cfg(target_os = "linux")]
    {
        let config = env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .filter(|path| path.is_absolute())
            .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")));
        if let Some(config) = config {
            paths.push(config.join("google-chrome"));
            paths.push(config.join("chromium"));
            paths.push(config.join("google-chrome-beta"));
            paths.push(config.join("google-chrome-unstable"));
        }
    }
    #[cfg(target_os = "macos")]
    {
        if let Some(home) = env::var_os("HOME").map(PathBuf::from) {
            let application_support = home.join("Library").join("Application Support");
            paths.push(application_support.join("Google").join("Chrome"));
            paths.push(application_support.join("Chromium"));
            paths.push(application_support.join("Google").join("Chrome Canary"));
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Some(local) = env::var_os("LOCALAPPDATA").map(PathBuf::from) {
            paths.push(local.join("Google").join("Chrome").join("User Data"));
            paths.push(local.join("Chromium").join("User Data"));
        }
    }
    paths
}

fn validate_name(value: &str, label: &str) -> Result<()> {
    if !is_valid_name(value) {
        return Err(VoidCrawlError::Other(format!("invalid {label}: {value:?}")));
    }
    Ok(())
}

fn is_valid_name(value: &str) -> bool {
    !(value.is_empty()
        || value == "."
        || value == ".."
        || value.contains('/')
        || value.contains('\\')
        || value.contains('\0'))
}

fn now_epoch_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or_default()
}

fn seed_standalone_profile(path: &Path) -> Result<()> {
    let default_dir = path.join("Default");
    fs::create_dir_all(&default_dir)
        .map_err(|e| VoidCrawlError::Other(format!("create {}: {e}", default_dir.display())))?;
    let preferences = default_dir.join("Preferences");
    if !preferences.exists() {
        fs::write(&preferences, "{}")
            .map_err(|e| VoidCrawlError::Other(format!("write {}: {e}", preferences.display())))?;
    }
    Ok(())
}

fn acquire_profile_lock(id: &str, path: &Path) -> Result<ManagedProfileLease> {
    if !path.is_dir() {
        return Err(VoidCrawlError::ProfileNotFound {
            name: id.to_string(),
            searched: vec![path.display().to_string()],
        });
    }
    let lock_path = path.join(".voidcrawl.lock");
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|e| VoidCrawlError::Other(format!("open {}: {e}", lock_path.display())))?;

    match file.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => {
            return Err(profile_busy(id, &lock_path));
        }
        Err(TryLockError::Error(error)) => {
            return Err(VoidCrawlError::Other(format!(
                "lock {}: {error}",
                lock_path.display()
            )));
        }
    }
    write_metadata(&mut file).map_err(|e| {
        VoidCrawlError::Other(format!("write lease metadata {}: {e}", lock_path.display()))
    })?;
    Ok(ManagedProfileLease {
        id: id.to_string(),
        path: path.to_path_buf(),
        _lock: file,
    })
}

fn profile_busy(name: &str, lock_path: &Path) -> VoidCrawlError {
    let owner = read_metadata(lock_path);
    VoidCrawlError::ProfileBusy {
        name: name.to_string(),
        pid: owner.as_ref().map(|m| m.pid),
        acquired_at: owner.map(|m| m.acquired_at),
    }
}

fn lock_status(path: &Path) -> Result<ProfileStatus> {
    if !path.is_dir() {
        return Ok(ProfileStatus::Missing);
    }
    let lock_path = path.join(".voidcrawl.lock");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|e| VoidCrawlError::Other(format!("open {}: {e}", lock_path.display())))?;
    match file.try_lock() {
        Ok(()) => Ok(ProfileStatus::Available),
        Err(TryLockError::WouldBlock) => Ok(ProfileStatus::Locked),
        Err(TryLockError::Error(error)) => Err(VoidCrawlError::Other(format!(
            "lock {}: {error}",
            lock_path.display()
        ))),
    }
}

fn dir_size(path: &Path) -> Result<u64> {
    let mut total: u64 = 0;
    let entries = fs::read_dir(path)
        .map_err(|e| VoidCrawlError::Other(format!("read_dir {}: {e}", path.display())))?;
    for entry in entries {
        let entry = entry.map_err(|e| VoidCrawlError::Other(format!("read_dir entry: {e}")))?;
        let path = entry.path();
        let metadata = entry
            .metadata()
            .map_err(|e| VoidCrawlError::Other(format!("metadata {}: {e}", path.display())))?;
        if metadata.is_dir() {
            total = total
                .checked_add(dir_size(&path)?)
                .ok_or_else(|| VoidCrawlError::Other("profile directory size overflowed".into()))?;
        } else {
            total = total
                .checked_add(metadata.len())
                .ok_or_else(|| VoidCrawlError::Other("profile directory size overflowed".into()))?;
        }
    }
    Ok(total)
}

fn path_entry_exists(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}
