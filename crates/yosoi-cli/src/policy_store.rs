//! Read-only, version-keyed Policy profiles authored in JSON.

use std::{
    collections::BTreeMap,
    env, io,
    path::{Path, PathBuf},
};

use serde::Deserialize;
use serde_json::Value;
use thiserror::Error;
use yosoi_engine::{Policy, PolicyError};

mod overrides;
mod storage;
use overrides::PolicyOverrides;
use storage::{read_store_file, validate_store_buckets};

const STORE_FORMAT_VERSION: u32 = 1;
const CLI_VERSION: &str = env!("CARGO_PKG_VERSION");
const MAX_STORE_BYTES: usize = 4_194_304;
const MAX_CLI_VERSIONS: usize = 64;
const MAX_PROFILES_PER_VERSION: usize = 256;
const MAX_NAME_BYTES: usize = 128;

#[derive(Debug, Error)]
pub enum PolicyStoreError {
    #[error("cannot determine a platform config directory for yosoi")]
    ConfigDirectoryUnavailable,
    #[error("failed to read policy store {path}: {source}")]
    Read {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("invalid policy store JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error(
        "unsupported policy store format version {0}; this CLI supports format version {STORE_FORMAT_VERSION}"
    )]
    UnsupportedFormat(u32),
    #[error("profile '{0}' does not exist")]
    MissingProfile(String),
    #[error("saved policy for profile '{profile}' is invalid: {source}")]
    InvalidPolicy {
        profile: String,
        #[source]
        source: PolicyError,
    },
    #[error("policy store {path} exceeds the {max_bytes} byte limit")]
    TooLarge { path: PathBuf, max_bytes: usize },
    #[error("policy store has more than {0} CLI version buckets")]
    TooManyVersions(usize),
    #[error("CLI version '{version}' has more than {max_profiles} profiles")]
    TooManyProfiles {
        version: String,
        max_profiles: usize,
    },
    #[error("CLI version or profile name exceeds {0} UTF-8 bytes")]
    NameTooLong(usize),
    #[error("policy store contains an empty version or profile name")]
    InvalidStoreName,
}

#[derive(Debug)]
pub struct PolicyStore {
    current_version: Option<VersionProfiles>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StoreFile {
    format_version: u32,
    #[serde(default)]
    cli_versions: BTreeMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct VersionProfiles {
    #[serde(default)]
    active_profile: Option<String>,
    #[serde(default)]
    profiles: BTreeMap<String, PolicyOverrides>,
}

impl PolicyStore {
    pub fn path() -> Result<PathBuf, PolicyStoreError> {
        config_directory()
            .map(|directory| directory.join("yosoi").join("policies.json"))
            .ok_or(PolicyStoreError::ConfigDirectoryUnavailable)
    }

    pub fn load() -> Result<Self, PolicyStoreError> {
        Self::load_from(&Self::path()?)
    }

    pub fn load_from(path: &Path) -> Result<Self, PolicyStoreError> {
        let Some(source_contents) = read_store_file(path)? else {
            return Ok(Self {
                current_version: None,
            });
        };
        let file: StoreFile = serde_json::from_slice(&source_contents)?;
        if file.format_version != STORE_FORMAT_VERSION {
            return Err(PolicyStoreError::UnsupportedFormat(file.format_version));
        }
        validate_store_buckets(&file.cli_versions)?;
        let current_version = file
            .cli_versions
            .get(CLI_VERSION)
            .cloned()
            .map(serde_json::from_value)
            .transpose()?;
        Ok(Self { current_version })
    }

    pub fn list_profiles(&self) -> Vec<String> {
        self.current_version
            .as_ref()
            .map(|version| version.profiles.keys().cloned().collect())
            .unwrap_or_default()
    }

    pub fn active_profile(&self) -> Option<&str> {
        self.current_version
            .as_ref()
            .and_then(|version| version.active_profile.as_deref())
    }

    pub fn current(&self) -> Result<Policy, PolicyStoreError> {
        self.active_profile().map_or_else(
            || Self::resolve(None, None),
            |name| self.resolve_profile(name),
        )
    }

    pub fn resolve_profile(&self, name: &str) -> Result<Policy, PolicyStoreError> {
        let overrides = self
            .current_version
            .as_ref()
            .and_then(|version| version.profiles.get(name))
            .ok_or_else(|| PolicyStoreError::MissingProfile(name.to_owned()))?;
        Self::resolve(Some(name), Some(overrides))
    }

    fn resolve(
        profile: Option<&str>,
        overrides: Option<&PolicyOverrides>,
    ) -> Result<Policy, PolicyStoreError> {
        let mut policy = Policy::default();
        if let Some(values) = overrides {
            values.apply(&mut policy);
        }
        policy
            .validate()
            .map_err(|source| PolicyStoreError::InvalidPolicy {
                profile: profile.unwrap_or("<defaults>").to_owned(),
                source,
            })?;
        Ok(policy)
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
fn config_directory() -> Option<PathBuf> {
    env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .or_else(|| {
            env::var_os("HOME")
                .map(PathBuf::from)
                .filter(|path| path.is_absolute())
                .map(|home| home.join(".config"))
        })
}

#[cfg(target_os = "macos")]
fn config_directory() -> Option<PathBuf> {
    env::var_os("HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .map(|home| home.join("Library").join("Application Support"))
}

#[cfg(windows)]
fn config_directory() -> Option<PathBuf> {
    env::var_os("APPDATA")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
}

#[cfg(not(any(unix, windows)))]
fn config_directory() -> Option<PathBuf> {
    None
}

#[cfg(test)]
mod tests;
