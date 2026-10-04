//! Bounded Policy store reads and structural limits.

use std::{
    collections::BTreeMap,
    fs::File,
    io::{self, Read},
    path::Path,
};

use serde_json::Value;

use super::{
    MAX_CLI_VERSIONS, MAX_NAME_BYTES, MAX_PROFILES_PER_VERSION, MAX_STORE_BYTES, PolicyStoreError,
};

const MAX_STORE_READ_BYTES: u64 = 4_194_305;

pub(super) fn read_store_file(path: &Path) -> Result<Option<Vec<u8>>, PolicyStoreError> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(source) => {
            return Err(PolicyStoreError::Read {
                path: path.to_path_buf(),
                source,
            });
        }
    };
    let mut bytes = Vec::new();
    file.take(MAX_STORE_READ_BYTES)
        .read_to_end(&mut bytes)
        .map_err(|source| PolicyStoreError::Read {
            path: path.to_path_buf(),
            source,
        })?;
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PolicyStoreError::TooLarge {
            path: path.to_path_buf(),
            max_bytes: MAX_STORE_BYTES,
        });
    }
    Ok(Some(bytes))
}

pub(super) fn validate_store_buckets(
    versions: &BTreeMap<String, Value>,
) -> Result<(), PolicyStoreError> {
    if versions.len() > MAX_CLI_VERSIONS {
        return Err(PolicyStoreError::TooManyVersions(MAX_CLI_VERSIONS));
    }
    for (version, value) in versions {
        validate_stored_name(version)?;
        if let Some(bucket) = value.as_object() {
            if let Some(active) = bucket.get("active_profile").and_then(Value::as_str) {
                validate_stored_name(active)?;
            }
            if let Some(profiles) = bucket.get("profiles").and_then(Value::as_object) {
                if profiles.len() > MAX_PROFILES_PER_VERSION {
                    return Err(PolicyStoreError::TooManyProfiles {
                        version: version.clone(),
                        max_profiles: MAX_PROFILES_PER_VERSION,
                    });
                }
                for name in profiles.keys() {
                    validate_stored_name(name)?;
                }
            }
        }
    }
    Ok(())
}

const fn validate_stored_name(name: &str) -> Result<(), PolicyStoreError> {
    if name.is_empty() {
        Err(PolicyStoreError::InvalidStoreName)
    } else if name.len() > MAX_NAME_BYTES {
        Err(PolicyStoreError::NameTooLong(MAX_NAME_BYTES))
    } else {
        Ok(())
    }
}
