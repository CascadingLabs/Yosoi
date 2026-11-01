#[path = "module/bundle.rs"]
mod bundle;
#[path = "module/graph.rs"]
mod graph;
#[path = "module/parser.rs"]
mod parser;
#[path = "module/types.rs"]
mod types;
#[path = "module/validation.rs"]
mod validation;

use super::JavaScriptSourceSnapshot;

pub use bundle::JavaScriptModuleBundle;
pub use types::{
    JavaScriptModuleError, JavaScriptModuleImport, JavaScriptModuleImportKind,
    JavaScriptModuleLimits, JavaScriptModuleSource,
};

#[cfg(test)]
#[path = "module/tests.rs"]
mod tests;
