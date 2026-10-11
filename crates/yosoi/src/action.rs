//! Constructors for the actions collected in a Flow.

mod builder;
mod module;
mod source;

pub use builder::AssertionBuilder;
pub use module::{
    JavaScriptModuleBundle, JavaScriptModuleError, JavaScriptModuleImport,
    JavaScriptModuleImportKind, JavaScriptModuleLimits, JavaScriptModuleSource,
};
pub use source::{
    JavaScriptSourceError, JavaScriptSourceOrigin, JavaScriptSourceProvenance,
    JavaScriptSourceSnapshot, MAX_JAVASCRIPT_SOURCE_BYTES,
};

use crate::{
    assertions::{Check, LocalAssertion},
    contracts::ValidateContract,
    flow::{Condition, Step},
    locators::Plan,
};
use std::path::Path;

pub use crate::assertions::check;

/// Builds a typed local Contract assertion using owned Rust predicates.
/// Convert it into [`Step`] for one immediate capture, or call `.until()` to
/// keep observing until its predicates pass.
pub fn assert_all<C: ValidateContract + 'static>(
    plan: &Plan,
    checks: impl IntoIterator<Item = Check<'static, C>>,
) -> AssertionBuilder {
    AssertionBuilder::new_contract(LocalAssertion::new::<C>(plan.clone(), checks))
}

/// Creates a navigation step.
pub fn navigate(url: impl Into<String>) -> Step {
    Step::Navigate { url: url.into() }
}

/// Creates a click step for one selector-resolved element.
pub fn click(selector: impl Into<String>) -> Step {
    Step::Click {
        selector: selector.into(),
    }
}

/// Creates a text-entry step for one selector-resolved element.
pub fn enter_text(selector: impl Into<String>, text: impl Into<String>) -> Step {
    Step::EnterText {
        selector: selector.into(),
        text: text.into(),
    }
}

/// Creates an explicit delay step, measured in milliseconds.
pub const fn wait(milliseconds: u64) -> Step {
    Step::Wait { milliseconds }
}

/// Creates a screenshot step.
pub const fn screenshot() -> Step {
    Step::Screenshot
}

/// Builds a typed condition assertion that can run once or wait through `.until()`.
///
/// Convert it into [`Step`] for one immediate check, or call `.until()` to wait
/// for the condition without a separate trigger action.
pub fn assert(condition: Condition) -> AssertionBuilder {
    AssertionBuilder::new_condition(condition)
}

/// Creates a typed assertion step bounded by a positive timeout in milliseconds.
pub fn wait_until(condition: Condition, timeout_ms: u64) -> Step {
    Step::WaitUntil {
        condition,
        timeout_ms,
    }
}

/// Creates a policy-approved script evaluation step.
pub fn evaluate(source: impl Into<String>) -> Step {
    Step::Evaluate {
        source: source.into(),
    }
}

/// Snapshots a UTF-8 JavaScript file now, before a Flow can be serialized or run.
/// The source is read under [`MAX_JAVASCRIPT_SOURCE_BYTES`] and later file edits
/// cannot change this step.
pub fn evaluate_file(path: impl AsRef<Path>) -> Result<Step, JavaScriptSourceError> {
    evaluate_file_with_limit(path, MAX_JAVASCRIPT_SOURCE_BYTES)
}

/// Snapshots a UTF-8 JavaScript file now with an explicit byte limit.
pub fn evaluate_file_with_limit(
    path: impl AsRef<Path>,
    maximum_bytes: usize,
) -> Result<Step, JavaScriptSourceError> {
    let snapshot = JavaScriptSourceSnapshot::from_file(path.as_ref(), maximum_bytes)?;
    Ok(Step::EvaluateFile { snapshot })
}

/// Snapshots an entry module and its local relative import graph now.
/// The entry file's parent directory is the bundle root; use
/// [`run_module_from_root`] when imports must reach sibling directories.
///
/// Imports, re-exports, and literal dynamic imports become one bounded module
/// bundle. Bare, absolute, computed dynamic, and external module specifiers are
/// rejected while constructing the bundle.
pub fn run_module(path: impl AsRef<Path>) -> Result<Step, JavaScriptModuleError> {
    run_module_with_limits(path, JavaScriptModuleLimits::default())
}

/// Snapshots an entry module and its local relative import graph with an
/// optional selected export returned as JSON after module evaluation.
/// The selected export is read, never invoked.
pub fn run_module_with_export(
    path: impl AsRef<Path>,
    export_name: impl Into<String>,
) -> Result<Step, JavaScriptModuleError> {
    let bundle = JavaScriptModuleBundle::from_entry_with_limits(
        path.as_ref(),
        JavaScriptModuleLimits::default(),
        Some(export_name.into()),
    )?;
    Ok(Step::EvaluateModule { bundle })
}

/// Snapshots an entry module and its local import graph under an explicit
/// filesystem root. Relative imports may reach sibling directories inside
/// `root`; symlinks and paths that escape the root are rejected.
pub fn run_module_from_root(
    root: impl AsRef<Path>,
    entry: impl AsRef<Path>,
) -> Result<Step, JavaScriptModuleError> {
    let bundle = JavaScriptModuleBundle::from_root_and_entry(
        root.as_ref(),
        entry.as_ref(),
        JavaScriptModuleLimits::default(),
        None,
    )?;
    Ok(Step::EvaluateModule { bundle })
}

/// Snapshots an entry module under an explicit filesystem root and selects a
/// default or named export to return as JSON after evaluation. The export is
/// read, never invoked.
pub fn run_module_from_root_with_export(
    root: impl AsRef<Path>,
    entry: impl AsRef<Path>,
    export_name: impl Into<String>,
) -> Result<Step, JavaScriptModuleError> {
    let bundle = JavaScriptModuleBundle::from_root_and_entry(
        root.as_ref(),
        entry.as_ref(),
        JavaScriptModuleLimits::default(),
        Some(export_name.into()),
    )?;
    Ok(Step::EvaluateModule { bundle })
}

/// Snapshots an entry module and its local relative import graph under the
/// supplied bundle bounds.
pub fn run_module_with_limits(
    path: impl AsRef<Path>,
    limits: JavaScriptModuleLimits,
) -> Result<Step, JavaScriptModuleError> {
    let bundle = JavaScriptModuleBundle::from_entry_with_limits(path.as_ref(), limits, None)?;
    Ok(Step::EvaluateModule { bundle })
}
