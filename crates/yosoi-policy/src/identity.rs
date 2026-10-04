use sha2::{Digest as _, Sha256};
use yosoi_types::Sha256Digest;

/// Version of the deterministic effective-policy identity projection.
pub const EFFECTIVE_POLICY_IDENTITY_VERSION: u16 = 5;

const IDENTITY_DOMAIN: &[u8] = b"yosoi-effective-policy\0v5\0";
const LEGACY_IDENTITY_DOMAIN_V4: &[u8] = b"yosoi-effective-policy\0v4\0";
const LEGACY_IDENTITY_DOMAIN_V2: &[u8] = b"yosoi-effective-policy\0v2\0";
const LEGACY_IDENTITY_DOMAIN_V3_MAP: &[u8] = b"yosoi-effective-policy\0v3\0";

/// Versioned SHA-256 identity of canonical, fully resolved policy behavior.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct EffectivePolicyIdentity {
    version: u16,
    digest: Sha256Digest,
}

impl EffectivePolicyIdentity {
    pub(crate) fn from_canonical_json(json: &str) -> Self {
        Self::from_json_version(EFFECTIVE_POLICY_IDENTITY_VERSION, IDENTITY_DOMAIN, json)
    }

    pub(crate) fn from_legacy_v4_json(json: &str) -> Self {
        Self::from_json_version(4, LEGACY_IDENTITY_DOMAIN_V4, json)
    }

    pub(crate) fn from_legacy_v2_json(json: &str) -> Self {
        Self::from_json_version(2, LEGACY_IDENTITY_DOMAIN_V2, json)
    }

    pub(crate) fn from_legacy_v3_map_json(json: &str) -> Self {
        Self::from_json_version(3, LEGACY_IDENTITY_DOMAIN_V3_MAP, json)
    }

    fn from_json_version(version: u16, domain: &[u8], json: &str) -> Self {
        let mut hasher = Sha256::new();
        hasher.update(domain);
        hasher.update(json.as_bytes());
        let digest = Sha256Digest::from_bytes(hasher.finalize().into());
        Self { version, digest }
    }

    /// Returns the projection version used to compute this identity.
    pub const fn version(self) -> u16 {
        self.version
    }

    /// Returns the SHA-256 digest of the canonical, domain-separated policy.
    pub const fn digest(self) -> Sha256Digest {
        self.digest
    }
}
