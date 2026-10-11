use super::{
    JavaScriptModuleError, JavaScriptModuleImportKind, JavaScriptModuleLimits,
    parser::parse_imports,
};
use crate::{action::run_module_from_root, flow::Step};
use serde_json::{Value, json};
use std::{
    error::Error,
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);

struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Result<Self, Box<dyn Error>> {
        let id = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("yosoi-js-module-{}-{id}", std::process::id()));
        fs::create_dir_all(&path)?;
        Ok(Self(path))
    }

    fn path(&self) -> &std::path::Path {
        &self.0
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn parser_finds_imports_reexports_and_literal_dynamic_imports_only() -> Result<(), Box<dyn Error>> {
    let source = r#"
const text = "import('./string-only.js')";
const regex = /export from ['"]fake\.js/;
const template = `import('./template-only.js')`;
// import "./comment-line.js";
/* export * from "./comment-block.js"; */
import defaultValue,
  { value as renamed }
  from /* module comments are allowed */ "./dep.js";
export * as namespace from "../shared.js";
export { renamed } from './other.js';
const loaded = import(
  /* dynamic import can span lines */
  "./lazy.js",
);
const interpolated = `${import("./inside-template.js")}`;
"#;
    let imports = parse_imports(source, "./entry.js")?;
    let observed: Vec<_> = imports
        .iter()
        .map(|item| (item.specifier.as_str(), item.kind))
        .collect();
    assert_eq!(
        observed,
        vec![
            ("./dep.js", JavaScriptModuleImportKind::Static),
            ("../shared.js", JavaScriptModuleImportKind::ReExport),
            ("./other.js", JavaScriptModuleImportKind::ReExport),
            ("./lazy.js", JavaScriptModuleImportKind::Dynamic),
            ("./inside-template.js", JavaScriptModuleImportKind::Dynamic),
        ]
    );
    for import in imports {
        assert!(source.get(import.source_range).is_some());
    }
    Ok(())
}

#[test]
fn parser_decodes_escaped_specifiers_and_rejects_unbounded_import_forms()
-> Result<(), Box<dyn Error>> {
    let imports = parse_imports(
        "import './m\\x2ejs'; export { value } from './\\u006dep.js';",
        "./entry.js",
    )?;
    assert_eq!(
        imports.first().map(|item| item.specifier.as_str()),
        Some("./m.js")
    );
    assert_eq!(
        imports.get(1).map(|item| item.specifier.as_str()),
        Some("./mep.js")
    );

    assert!(matches!(
        parse_imports("import('./' + name)", "./entry.js"),
        Err(JavaScriptModuleError::ComputedDynamicImport { .. })
    ));
    assert!(matches!(
        parse_imports(
            "import data from './data.json' with { type: 'json' }",
            "./entry.js"
        ),
        Err(JavaScriptModuleError::UnsupportedImportAttributes { .. })
    ));
    assert!(matches!(
        parse_imports(
            "export { value } from './data.json' with { type: 'json' }",
            "./entry.js"
        ),
        Err(JavaScriptModuleError::UnsupportedImportAttributes { .. }
            | JavaScriptModuleError::InvalidSyntax { .. })
    ));
    assert!(matches!(
        parse_imports(
            "import('./module.js', { with: { type: 'json' } })",
            "./entry.js"
        ),
        Err(JavaScriptModuleError::UnsupportedImportAttributes { .. })
    ));
    Ok(())
}

#[test]
fn explicit_root_captures_cycles_and_deserialization_rejects_tampered_ranges()
-> Result<(), Box<dyn Error>> {
    let directory = TempDir::new()?;
    let subdirectory = directory.path().join("nested");
    fs::create_dir_all(&subdirectory)?;
    let entry = subdirectory.join("entry.js");
    let shared = directory.path().join("shared.js");
    fs::write(
        &entry,
        "import { shared } from '../shared.js'; export const entry = shared;",
    )?;
    fs::write(
        &shared,
        "export { entry } from './nested/entry.js'; export const shared = 'ok';",
    )?;

    let step = run_module_from_root(directory.path(), "nested/entry.js")?;
    let Step::EvaluateModule { bundle } = step else {
        return Err("module action returned the wrong step".into());
    };
    assert_eq!(bundle.entry(), "./nested/entry.js");
    assert_eq!(bundle.modules().len(), 2);
    assert_eq!(
        bundle.total_source_bytes(),
        fs::read(&entry)?.len() + fs::read(&shared)?.len()
    );
    bundle.validate(65_536)?;

    let mut encoded = serde_json::to_value(&bundle)?;
    let module_map = encoded
        .get_mut("modules")
        .and_then(Value::as_object_mut)
        .ok_or("serialized bundle omitted modules")?;
    let entry_module = module_map
        .get_mut("./nested/entry.js")
        .ok_or("serialized entry module is missing")?;
    let imports = entry_module
        .get_mut("imports")
        .and_then(Value::as_array_mut)
        .ok_or("serialized import list is missing")?;
    let first_import = imports.first_mut().ok_or("entry import is missing")?;
    let source_range = first_import
        .get_mut("source_range")
        .and_then(Value::as_object_mut)
        .ok_or("serialized source range is missing")?;
    let old_start = source_range
        .get("start")
        .and_then(Value::as_u64)
        .ok_or("source range start is missing")?;
    source_range.insert("start".to_owned(), json!(old_start.saturating_add(1)));
    assert!(serde_json::from_value::<super::JavaScriptModuleBundle>(encoded).is_err());
    Ok(())
}

#[test]
fn module_bundle_limits_cannot_exceed_sdk_hard_caps() {
    let result = JavaScriptModuleLimits::new(65, 65_536, 65_536);
    assert!(matches!(result, Err(JavaScriptModuleError::InvalidLimits)));
}

#[test]
fn graph_rejects_external_and_parent_escape_imports() -> Result<(), Box<dyn Error>> {
    let directory = TempDir::new()?;
    let entry = directory.path().join("entry.js");

    fs::write(&entry, "import React from 'react';")?;
    assert!(matches!(
        run_module_from_root(directory.path(), "entry.js"),
        Err(JavaScriptModuleError::UnsupportedSpecifier { .. })
    ));

    fs::write(&entry, "import '../outside.js';")?;
    assert!(matches!(
        run_module_from_root(directory.path(), "entry.js"),
        Err(JavaScriptModuleError::ModuleOutsideBundle { .. })
    ));
    Ok(())
}
