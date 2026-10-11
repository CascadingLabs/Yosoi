use super::{JavaScriptModuleError, JavaScriptModuleLimits, JavaScriptModuleSource, validation};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::collections::BTreeMap;

/// An exact, bounded module graph captured at Flow construction time.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JavaScriptModuleBundle {
    pub(super) entry: String,
    pub(super) modules: BTreeMap<String, JavaScriptModuleSource>,
    pub(super) result_export: Option<String>,
    pub(super) limits: JavaScriptModuleLimits,
}

impl<'de> Deserialize<'de> for JavaScriptModuleBundle {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            entry: String,
            modules: BTreeMap<String, JavaScriptModuleSource>,
            result_export: Option<String>,
            limits: JavaScriptModuleLimits,
        }

        let wire = Wire::deserialize(deserializer)?;
        let bundle = Self {
            entry: wire.entry,
            modules: wire.modules,
            result_export: wire.result_export,
            limits: wire.limits,
        };
        bundle
            .validate(bundle.limits.max_total_source_bytes)
            .map_err(D::Error::custom)?;
        Ok(bundle)
    }
}

impl JavaScriptModuleBundle {
    /// Returns the normalized bundle-relative entry module ID.
    pub fn entry(&self) -> &str {
        &self.entry
    }

    /// Returns the captured modules keyed by normalized bundle-relative ID.
    pub fn modules(&self) -> &BTreeMap<String, JavaScriptModuleSource> {
        &self.modules
    }

    /// Returns the selected default or named export to return as JSON, if any.
    pub fn result_export(&self) -> Option<&str> {
        self.result_export.as_deref()
    }

    /// Returns the bounds used when this bundle was captured.
    pub const fn limits(&self) -> JavaScriptModuleLimits {
        self.limits
    }

    /// Returns total exact UTF-8 source bytes in the module graph.
    pub fn total_source_bytes(&self) -> usize {
        self.modules.values().fold(0_usize, |total, module| {
            total.saturating_add(module.snapshot.byte_len())
        })
    }

    /// Revalidates source digests, parser ranges, graph targets, reachability,
    /// and the requested aggregate source bound.
    pub fn validate(&self, maximum_total_source_bytes: usize) -> Result<(), JavaScriptModuleError> {
        validation::validate(self, maximum_total_source_bytes)
    }
}
