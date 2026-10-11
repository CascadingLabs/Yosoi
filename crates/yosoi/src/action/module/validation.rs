use super::{
    JavaScriptModuleError,
    bundle::JavaScriptModuleBundle,
    graph::{is_normalized_module_id, module_import, resolve_import_id},
    parser::parse_imports,
};
use std::collections::BTreeSet;

pub(super) fn validate(
    bundle: &JavaScriptModuleBundle,
    maximum_total_source_bytes: usize,
) -> Result<(), JavaScriptModuleError> {
    bundle.limits.validate()?;
    super::types::validate_result_export(bundle.result_export.as_deref())?;
    if !is_normalized_module_id(&bundle.entry) || !bundle.modules.contains_key(&bundle.entry) {
        return Err(JavaScriptModuleError::MissingEntry);
    }
    if bundle.modules.len() > bundle.limits.max_modules {
        return Err(JavaScriptModuleError::TooManyModules {
            actual: bundle.modules.len(),
            maximum: bundle.limits.max_modules,
        });
    }

    let maximum_total = maximum_total_source_bytes.min(bundle.limits.max_total_source_bytes);
    let mut total = 0_usize;
    for (module_id, module) in &bundle.modules {
        if !is_normalized_module_id(module_id) {
            return Err(JavaScriptModuleError::InvalidModuleId(module_id.clone()));
        }
        module
            .snapshot
            .validate(bundle.limits.max_module_source_bytes)?;
        total = total.checked_add(module.snapshot.byte_len()).ok_or(
            JavaScriptModuleError::BundleTooLarge {
                actual: usize::MAX,
                maximum: maximum_total,
            },
        )?;
        if total > maximum_total {
            return Err(JavaScriptModuleError::BundleTooLarge {
                actual: total,
                maximum: maximum_total,
            });
        }

        let parsed = parse_imports(module.snapshot.source(), module_id)?;
        let expected = parsed
            .into_iter()
            .map(|item| {
                let target = resolve_import_id(module_id, &item.specifier)?;
                Ok(module_import(item, target))
            })
            .collect::<Result<Vec<_>, JavaScriptModuleError>>()?;
        if expected != module.imports {
            return Err(JavaScriptModuleError::ImportGraphMismatch {
                module_id: module_id.clone(),
            });
        }
        for import in &module.imports {
            let literal = module
                .snapshot
                .source()
                .get(import.source_range.clone())
                .ok_or_else(|| JavaScriptModuleError::ImportGraphMismatch {
                    module_id: module_id.clone(),
                })?;
            if literal.is_empty() || !bundle.modules.contains_key(&import.target_module) {
                return Err(JavaScriptModuleError::ImportGraphMismatch {
                    module_id: module_id.clone(),
                });
            }
        }
    }

    let mut reachable = BTreeSet::new();
    let mut pending = vec![bundle.entry.clone()];
    while let Some(module_id) = pending.pop() {
        if !reachable.insert(module_id.clone()) {
            continue;
        }
        let module = bundle.modules.get(&module_id).ok_or_else(|| {
            JavaScriptModuleError::ImportGraphMismatch {
                module_id: module_id.clone(),
            }
        })?;
        pending.extend(
            module
                .imports
                .iter()
                .map(|import| import.target_module.clone()),
        );
    }
    if reachable.len() != bundle.modules.len() {
        return Err(JavaScriptModuleError::UnreachableModule);
    }
    Ok(())
}
