use super::{
    JavaScriptModuleBundle, JavaScriptModuleError, JavaScriptModuleImport, JavaScriptModuleLimits,
    JavaScriptModuleSource, JavaScriptSourceSnapshot,
    parser::{ParsedImport, parse_imports},
    types::validate_result_export,
};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fs,
    path::{Component, Path, PathBuf},
};

impl JavaScriptModuleBundle {
    pub(in crate::action) fn from_entry_with_limits(
        entry_path: &Path,
        limits: JavaScriptModuleLimits,
        result_export: Option<String>,
    ) -> Result<Self, JavaScriptModuleError> {
        let canonical_entry =
            fs::canonicalize(entry_path).map_err(|_| JavaScriptModuleError::EntryUnreadable {
                path: entry_path.to_path_buf(),
            })?;
        let root = canonical_entry
            .parent()
            .ok_or_else(|| JavaScriptModuleError::InvalidEntryPath(entry_path.to_path_buf()))?
            .to_path_buf();
        Self::from_canonical_root(&root, canonical_entry, limits, result_export)
    }

    pub(in crate::action) fn from_root_and_entry(
        root_path: &Path,
        entry_path: &Path,
        limits: JavaScriptModuleLimits,
        result_export: Option<String>,
    ) -> Result<Self, JavaScriptModuleError> {
        let root = fs::canonicalize(root_path)
            .map_err(|_| JavaScriptModuleError::InvalidRootPath(root_path.to_path_buf()))?;
        if !root.is_dir() {
            return Err(JavaScriptModuleError::InvalidRootPath(
                root_path.to_path_buf(),
            ));
        }
        let requested_entry = if entry_path.is_absolute() {
            entry_path.to_path_buf()
        } else {
            root.join(entry_path)
        };
        let canonical_entry = fs::canonicalize(&requested_entry).map_err(|_| {
            JavaScriptModuleError::EntryUnreadable {
                path: requested_entry.clone(),
            }
        })?;
        if !canonical_entry.starts_with(&root) {
            return Err(JavaScriptModuleError::EntryOutsideBundle {
                path: canonical_entry,
            });
        }
        Self::from_canonical_root(&root, canonical_entry, limits, result_export)
    }
}

impl JavaScriptModuleBundle {
    fn from_canonical_root(
        root: &Path,
        canonical_entry: PathBuf,
        limits: JavaScriptModuleLimits,
        result_export: Option<String>,
    ) -> Result<Self, JavaScriptModuleError> {
        limits.validate()?;
        validate_result_export(result_export.as_deref())?;
        let entry_relative = canonical_entry
            .strip_prefix(root)
            .map_err(|_| JavaScriptModuleError::InvalidEntryPath(canonical_entry.clone()))?;
        let entry = module_id_from_relative(entry_relative)?;

        let mut queue = VecDeque::from([(entry.clone(), canonical_entry)]);
        let mut queued = BTreeSet::from([entry.clone()]);
        let mut modules = BTreeMap::new();
        let mut total_source_bytes = 0_usize;

        while let Some((module_id, read_path)) = queue.pop_front() {
            if modules.len() >= limits.max_modules {
                return Err(JavaScriptModuleError::TooManyModules {
                    actual: modules.len().saturating_add(1),
                    maximum: limits.max_modules,
                });
            }
            let snapshot =
                JavaScriptSourceSnapshot::from_file(&read_path, limits.max_module_source_bytes)?;
            total_source_bytes = total_source_bytes.checked_add(snapshot.byte_len()).ok_or(
                JavaScriptModuleError::BundleTooLarge {
                    actual: usize::MAX,
                    maximum: limits.max_total_source_bytes,
                },
            )?;
            if total_source_bytes > limits.max_total_source_bytes {
                return Err(JavaScriptModuleError::BundleTooLarge {
                    actual: total_source_bytes,
                    maximum: limits.max_total_source_bytes,
                });
            }

            let parsed = parse_imports(snapshot.source(), &module_id)?;
            let mut imports = Vec::with_capacity(parsed.len());
            for parsed_import in parsed {
                let target_module = resolve_import_id(&module_id, &parsed_import.specifier)?;
                let target_path = path_for_module_id(root, &target_module)?;
                let canonical_target = fs::canonicalize(&target_path).map_err(|_| {
                    JavaScriptModuleError::ModuleNotFound {
                        importer: module_id.clone(),
                        specifier: parsed_import.specifier.clone(),
                    }
                })?;
                if !canonical_target.starts_with(root) {
                    return Err(JavaScriptModuleError::ModuleOutsideBundle {
                        importer: module_id,
                        specifier: parsed_import.specifier,
                    });
                }
                imports.push(module_import(parsed_import, target_module.clone()));
                if queued.insert(target_module.clone()) {
                    if queued.len() > limits.max_modules {
                        return Err(JavaScriptModuleError::TooManyModules {
                            actual: queued.len(),
                            maximum: limits.max_modules,
                        });
                    }
                    queue.push_back((target_module, canonical_target));
                }
            }
            modules.insert(module_id, JavaScriptModuleSource { snapshot, imports });
        }

        let bundle = Self {
            entry,
            modules,
            result_export,
            limits,
        };
        bundle.validate(limits.max_total_source_bytes)?;
        Ok(bundle)
    }
}

pub(super) fn module_import(parsed: ParsedImport, target_module: String) -> JavaScriptModuleImport {
    JavaScriptModuleImport {
        specifier: parsed.specifier,
        target_module,
        source_range: parsed.source_range,
        kind: parsed.kind,
    }
}

pub(super) fn resolve_import_id(
    importer: &str,
    specifier: &str,
) -> Result<String, JavaScriptModuleError> {
    if !(specifier.starts_with("./") || specifier.starts_with("../"))
        || specifier.contains(['\\', '%', '?', '#'])
    {
        return Err(JavaScriptModuleError::UnsupportedSpecifier {
            importer: importer.to_owned(),
            specifier: specifier.to_owned(),
        });
    }
    let importer_path = module_path(importer)?;
    let parent = importer_path.parent().unwrap_or_else(|| Path::new(""));
    let requested = parent.join(specifier);
    let mut components = Vec::new();
    for component in requested.components() {
        match component {
            Component::CurDir => {}
            Component::Normal(value) => components.push(value.to_os_string()),
            Component::ParentDir => {
                if components.pop().is_none() {
                    return Err(JavaScriptModuleError::ModuleOutsideBundle {
                        importer: importer.to_owned(),
                        specifier: specifier.to_owned(),
                    });
                }
            }
            Component::RootDir | Component::Prefix(_) => {
                return Err(JavaScriptModuleError::UnsupportedSpecifier {
                    importer: importer.to_owned(),
                    specifier: specifier.to_owned(),
                });
            }
        }
    }
    if components.is_empty() {
        return Err(JavaScriptModuleError::UnsupportedSpecifier {
            importer: importer.to_owned(),
            specifier: specifier.to_owned(),
        });
    }
    let mut id = String::from("./");
    for (index, component) in components.iter().enumerate() {
        if index > 0 {
            id.push('/');
        }
        let value = component
            .to_str()
            .ok_or(JavaScriptModuleError::InvalidModulePath)?;
        id.push_str(value);
    }
    Ok(id)
}

pub(super) fn is_normalized_module_id(module_id: &str) -> bool {
    let Ok(path) = module_path(module_id) else {
        return false;
    };
    module_id_from_relative(&path).is_ok_and(|normalized| normalized == module_id)
}

fn module_path(module_id: &str) -> Result<PathBuf, JavaScriptModuleError> {
    if !module_id.starts_with("./") {
        return Err(JavaScriptModuleError::InvalidModuleId(module_id.to_owned()));
    }
    let relative = module_id
        .strip_prefix("./")
        .ok_or_else(|| JavaScriptModuleError::InvalidModuleId(module_id.to_owned()))?;
    Ok(PathBuf::from(relative))
}

fn path_for_module_id(root: &Path, module_id: &str) -> Result<PathBuf, JavaScriptModuleError> {
    Ok(root.join(module_path(module_id)?))
}

fn module_id_from_relative(path: &Path) -> Result<String, JavaScriptModuleError> {
    let mut id = String::from("./");
    let mut first = true;
    for component in path.components() {
        let Component::Normal(value) = component else {
            return Err(JavaScriptModuleError::InvalidModulePath);
        };
        if !first {
            id.push('/');
        }
        id.push_str(
            value
                .to_str()
                .ok_or(JavaScriptModuleError::InvalidModulePath)?,
        );
        first = false;
    }
    if first {
        return Err(JavaScriptModuleError::InvalidModulePath);
    }
    Ok(id)
}
