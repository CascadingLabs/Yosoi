use super::JavaScriptSourceSnapshot;
use crate::action::MAX_JAVASCRIPT_SOURCE_BYTES;
use serde::{Deserialize, Serialize};
use std::{ops::Range, path::PathBuf};

const MAX_MODULE_COUNT: usize = 64;
const MAX_BUNDLE_SOURCE_BYTES: usize = 65_536;
const MAX_EXPORT_NAME_BYTES: usize = 4_096;

/// Bounds applied while capturing a local JavaScript module graph.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
#[expect(
    clippy::struct_field_names,
    reason = "The public limits distinguish maximum bounds from observed module counts and sizes."
)]
pub struct JavaScriptModuleLimits {
    pub(super) max_modules: usize,
    pub(super) max_module_source_bytes: usize,
    pub(super) max_total_source_bytes: usize,
}

impl Default for JavaScriptModuleLimits {
    fn default() -> Self {
        Self {
            max_modules: MAX_MODULE_COUNT,
            max_module_source_bytes: MAX_JAVASCRIPT_SOURCE_BYTES,
            max_total_source_bytes: MAX_BUNDLE_SOURCE_BYTES,
        }
    }
}

impl JavaScriptModuleLimits {
    /// Creates tighter module limits. Values above the SDK hard caps are rejected.
    pub fn new(
        max_modules: usize,
        max_module_source_bytes: usize,
        max_total_source_bytes: usize,
    ) -> Result<Self, JavaScriptModuleError> {
        let limits = Self {
            max_modules,
            max_module_source_bytes,
            max_total_source_bytes,
        };
        limits.validate()?;
        Ok(limits)
    }

    /// Returns the maximum module count.
    pub const fn max_modules(self) -> usize {
        self.max_modules
    }

    /// Returns the maximum UTF-8 bytes in one module.
    pub const fn max_module_source_bytes(self) -> usize {
        self.max_module_source_bytes
    }

    /// Returns the maximum aggregate UTF-8 source bytes in the bundle.
    pub const fn max_total_source_bytes(self) -> usize {
        self.max_total_source_bytes
    }

    pub(super) const fn validate(self) -> Result<(), JavaScriptModuleError> {
        if self.max_modules == 0
            || self.max_modules > MAX_MODULE_COUNT
            || self.max_module_source_bytes == 0
            || self.max_module_source_bytes > MAX_JAVASCRIPT_SOURCE_BYTES
            || self.max_total_source_bytes == 0
            || self.max_total_source_bytes > MAX_BUNDLE_SOURCE_BYTES
        {
            return Err(JavaScriptModuleError::InvalidLimits);
        }
        Ok(())
    }
}

/// One source module in a local ESM bundle.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JavaScriptModuleSource {
    pub(super) snapshot: JavaScriptSourceSnapshot,
    pub(super) imports: Vec<JavaScriptModuleImport>,
}

impl JavaScriptModuleSource {
    /// Returns the exact source snapshot for this module.
    pub const fn snapshot(&self) -> &JavaScriptSourceSnapshot {
        &self.snapshot
    }

    /// Returns parsed import, re-export, and literal dynamic-import edges.
    pub fn imports(&self) -> &[JavaScriptModuleImport] {
        &self.imports
    }
}

/// One module specifier occurrence and its resolved virtual bundle target.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JavaScriptModuleImport {
    pub(super) specifier: String,
    pub(super) target_module: String,
    pub(super) source_range: Range<usize>,
    pub(super) kind: JavaScriptModuleImportKind,
}

impl JavaScriptModuleImport {
    /// Returns the authored module specifier after JavaScript string decoding.
    pub fn specifier(&self) -> &str {
        &self.specifier
    }

    /// Returns the normalized bundle-relative target module ID.
    pub fn target_module(&self) -> &str {
        &self.target_module
    }

    /// Returns the UTF-8 byte range of the full quoted specifier literal.
    pub const fn source_range(&self) -> &Range<usize> {
        &self.source_range
    }

    /// Returns whether this is a static import, re-export, or dynamic import.
    pub const fn kind(&self) -> JavaScriptModuleImportKind {
        self.kind
    }
}

/// The module syntax that created a resolved module edge.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JavaScriptModuleImportKind {
    /// `import ... from "..."` or a side-effect import.
    Static,
    /// `export ... from "..."`.
    ReExport,
    /// A literal `import("...")` expression.
    Dynamic,
}

/// A local module bundle could not be read, parsed, resolved, or validated.
#[derive(Debug, thiserror::Error)]
pub enum JavaScriptModuleError {
    /// Source snapshot loading failed.
    #[error(transparent)]
    Source(#[from] super::super::JavaScriptSourceError),
    /// The selected module parser could not be configured.
    #[error("JavaScript module parser configuration failed")]
    ParserConfiguration,
    /// The parser could not produce a module syntax tree.
    #[error("could not parse JavaScript module {module_id}")]
    ParseFailed {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// The source has a JavaScript syntax error.
    #[error("JavaScript module {module_id} contains invalid syntax")]
    InvalidSyntax {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// A parsed import declaration did not contain its expected source node.
    #[error("JavaScript module {module_id} has a malformed import declaration")]
    MalformedImport {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// A module source string literal could not be decoded safely.
    #[error("JavaScript module {module_id} has an unsupported string escape in an import")]
    InvalidStringSpecifier {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// A dynamic import must use a literal specifier so its graph can be bounded.
    #[error("JavaScript module {module_id} has a computed dynamic import; use a string literal")]
    ComputedDynamicImport {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// Import attributes require a module kind that this JavaScript-only bundle does not capture.
    #[error("JavaScript module {module_id} uses unsupported import attributes")]
    UnsupportedImportAttributes {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// The entry path could not be resolved.
    #[error("could not resolve JavaScript module entry {path}")]
    EntryUnreadable {
        /// Authored or resolved local entry path involved in the failure.
        path: PathBuf,
    },
    /// The entry path has no valid parent/name.
    #[error("JavaScript module entry path is invalid: {0}")]
    InvalidEntryPath(PathBuf),
    /// The caller's explicit bundle root is not an accessible directory.
    #[error("JavaScript module bundle root is not a directory: {0}")]
    InvalidRootPath(PathBuf),
    /// The selected entry is outside the caller's explicit bundle root.
    #[error("JavaScript module entry is outside the bundle root: {path}")]
    EntryOutsideBundle {
        /// Authored or resolved local entry path involved in the failure.
        path: PathBuf,
    },
    /// A module path could not be represented as UTF-8.
    #[error("JavaScript module paths must be valid UTF-8 relative paths")]
    InvalidModulePath,
    /// An ID is not a normalized bundle-relative path.
    #[error("invalid JavaScript module ID: {0}")]
    InvalidModuleId(String),
    /// A dependency was not found under the bundle root.
    #[error("module {importer} imports missing local module {specifier}")]
    ModuleNotFound {
        /// Bundle-relative module containing the rejected dependency edge.
        importer: String,
        /// Decoded authored module specifier involved in resolution.
        specifier: String,
    },
    /// A symlinked dependency points outside the bundle root.
    #[error("module {importer} imports {specifier}, which resolves outside the bundle root")]
    ModuleOutsideBundle {
        /// Bundle-relative module containing the rejected dependency edge.
        importer: String,
        /// Decoded authored module specifier involved in resolution.
        specifier: String,
    },
    /// Only local relative module specifiers can be captured in a bundle.
    #[error("module {importer} uses unsupported import specifier {specifier:?}")]
    UnsupportedSpecifier {
        /// Bundle-relative module containing the rejected dependency edge.
        importer: String,
        /// Decoded authored module specifier involved in resolution.
        specifier: String,
    },
    /// The bundle exceeded its module count bound.
    #[error("JavaScript module bundle has {actual} modules; maximum is {maximum}")]
    TooManyModules {
        /// Observed captured modules requiring capture.
        actual: usize,
        /// Maximum permitted captured modules.
        maximum: usize,
    },
    /// The bundle exceeded its aggregate UTF-8 source bound.
    #[error("JavaScript module bundle has {actual} source bytes; maximum is {maximum}")]
    BundleTooLarge {
        /// Observed aggregate UTF-8 source bytes requiring capture.
        actual: usize,
        /// Maximum permitted aggregate UTF-8 source bytes.
        maximum: usize,
    },
    /// A configured limit is zero or exceeds an SDK hard cap.
    #[error("JavaScript module limits must be positive and no greater than SDK hard caps")]
    InvalidLimits,
    /// The selected entry was absent from the module map.
    #[error("JavaScript module bundle entry is missing")]
    MissingEntry,
    /// Serialized module source and import edges disagree.
    #[error("JavaScript module {module_id} import graph does not match its source")]
    ImportGraphMismatch {
        /// Bundle-relative source module whose parsing or import metadata was rejected.
        module_id: String,
    },
    /// Serialized bundle contains modules unreachable from its entry.
    #[error("JavaScript module bundle contains unreachable modules")]
    UnreachableModule,
    /// A selected export name is empty or too long.
    #[error("selected JavaScript export name is empty or too long")]
    InvalidExportName,
}

pub(super) fn validate_result_export(
    export_name: Option<&str>,
) -> Result<(), JavaScriptModuleError> {
    if export_name.is_some_and(|name| name.trim().is_empty() || name.len() > MAX_EXPORT_NAME_BYTES)
    {
        return Err(JavaScriptModuleError::InvalidExportName);
    }
    Ok(())
}
