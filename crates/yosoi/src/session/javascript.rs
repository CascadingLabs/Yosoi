use super::SessionError;
use crate::action::{JavaScriptModuleBundle, JavaScriptModuleImport};
use std::collections::BTreeMap;

const MAX_MODULES_PER_BUNDLE: usize = 64;
const MAX_MODULE_ID_BYTES: usize = 4 * 1024;
const MAX_RETAINED_BUNDLES_PER_DOCUMENT: usize = 16;
const MAX_RETAINED_BYTES_PER_DOCUMENT: usize = 8 * 1024 * 1024;
const GENERATED_SOURCE_AMPLIFICATION_FACTOR: usize = 8;
const GENERATED_RUNTIME_OVERHEAD_BYTES: usize = 16 * 1024;
const GENERATED_MODULE_METADATA_BYTES: usize = 32;
const MAX_GENERATED_MODULE_EXPRESSION_BYTES: usize = 8 * 1024 * 1024;
const MODULE_RUNTIME: &str = include_str!("javascript/runtime.js");

/// Produces one bounded CDP expression that evaluates the captured graph as
/// native browser ESM. Parser-provided ranges are the only source edits.
pub(super) fn module_expression(
    bundle: &JavaScriptModuleBundle,
    maximum_input_bytes: usize,
) -> Result<String, SessionError> {
    bundle
        .validate(maximum_input_bytes)
        .map_err(|_| SessionError::InvalidInput)?;
    if bundle.modules().is_empty()
        || bundle.modules().len() > MAX_MODULES_PER_BUNDLE
        || !bundle.modules().contains_key(bundle.entry())
    {
        return Err(SessionError::InvalidInput);
    }

    let nonce = super::new_operation_id();
    let entry_specifier = format!("__yosoi_entry_{nonce}");
    let loader_specifier = format!("__yosoi_loader_{nonce}");
    let mut next_edge = 0_usize;
    let mut total_source_bytes = 0_usize;
    let mut module_id_bytes = 0_usize;
    let mut rewritten_modules = BTreeMap::new();
    let mut import_targets = BTreeMap::new();

    for (module_id, module) in bundle.modules() {
        if module_id.len() > MAX_MODULE_ID_BYTES {
            return Err(SessionError::InvalidInput);
        }
        module_id_bytes = module_id_bytes
            .checked_add(module_id.len())
            .ok_or(SessionError::InvalidInput)?;
        let snapshot = module.snapshot();
        snapshot
            .validate(maximum_input_bytes)
            .map_err(|_| SessionError::InvalidInput)?;
        total_source_bytes = total_source_bytes
            .checked_add(snapshot.byte_len())
            .ok_or(SessionError::InvalidInput)?;
        if total_source_bytes > maximum_input_bytes {
            return Err(SessionError::InvalidInput);
        }

        let source = rewrite_imports(
            module_id,
            snapshot.source(),
            module.imports(),
            bundle,
            &nonce,
            &mut next_edge,
            &mut import_targets,
        )?;
        rewritten_modules.insert(module_id.clone(), source);
    }

    let payload = serde_json::json!({
        "entry": bundle.entry(),
        "entrySpecifier": entry_specifier,
        "loaderSpecifier": loader_specifier,
        "modules": rewritten_modules,
        "imports": import_targets,
        "resultExport": bundle.result_export(),
        "maximumRetainedBundles": MAX_RETAINED_BUNDLES_PER_DOCUMENT,
        "maximumRetainedBytes": MAX_RETAINED_BYTES_PER_DOCUMENT,
    });
    let payload = serde_json::to_string(&payload).map_err(|_| SessionError::EvidenceUnavailable)?;
    let retained_bytes = payload.len();

    let retained_bytes_text = retained_bytes.to_string();
    let expression_length = 1_usize
        .checked_add(MODULE_RUNTIME.len())
        .and_then(|length| length.checked_add(2))
        .and_then(|length| length.checked_add(payload.len()))
        .and_then(|length| length.checked_add(1))
        .and_then(|length| length.checked_add(retained_bytes_text.len()))
        .and_then(|length| length.checked_add(1))
        .ok_or(SessionError::InvalidInput)?;
    let metadata_overhead = module_id_bytes
        .checked_mul(2)
        .and_then(|bytes| {
            bundle
                .modules()
                .len()
                .checked_mul(GENERATED_MODULE_METADATA_BYTES)
                .and_then(|module_bytes| bytes.checked_add(module_bytes))
        })
        .and_then(|bytes| bytes.checked_add(bundle.result_export().map_or(0, str::len)))
        .and_then(|bytes| bytes.checked_add(GENERATED_RUNTIME_OVERHEAD_BYTES))
        .ok_or(SessionError::InvalidInput)?;
    let generated_limit = maximum_input_bytes
        .checked_mul(GENERATED_SOURCE_AMPLIFICATION_FACTOR)
        .and_then(|bound| bound.checked_add(metadata_overhead))
        .ok_or(SessionError::InvalidInput)?
        .min(MAX_GENERATED_MODULE_EXPRESSION_BYTES);
    if expression_length > generated_limit {
        return Err(SessionError::InvalidInput);
    }

    let mut expression = String::new();
    expression
        .try_reserve_exact(expression_length)
        .map_err(|_| SessionError::EvidenceUnavailable)?;
    expression.push('(');
    expression.push_str(MODULE_RUNTIME);
    expression.push_str(")(");
    expression.push_str(&payload);
    expression.push(',');
    expression.push_str(&retained_bytes_text);
    expression.push(')');
    if expression.len() != expression_length {
        return Err(SessionError::EvidenceUnavailable);
    }
    Ok(expression)
}

fn rewrite_imports(
    module_id: &str,
    source: &str,
    imports: &[JavaScriptModuleImport],
    bundle: &JavaScriptModuleBundle,
    nonce: &str,
    next_edge: &mut usize,
    import_targets: &mut BTreeMap<String, String>,
) -> Result<String, SessionError> {
    let mut ordered_imports: Vec<_> = imports.iter().collect();
    ordered_imports.sort_by_key(|edge| edge.source_range().start);

    let mut rewritten = String::new();
    let mut cursor = 0_usize;
    for edge in ordered_imports {
        let range = edge.source_range().to_owned();
        if range.start < cursor
            || range.end <= range.start
            || !bundle.modules().contains_key(edge.target_module())
        {
            return Err(SessionError::InvalidInput);
        }
        let prefix = source
            .get(cursor..range.start)
            .ok_or(SessionError::InvalidInput)?;
        let literal = source
            .get(range.clone())
            .ok_or(SessionError::InvalidInput)?;
        let first = literal.chars().next().ok_or(SessionError::InvalidInput)?;
        let last = literal.chars().last().ok_or(SessionError::InvalidInput)?;
        if !matches!(first, '\'' | '"') || last != first {
            return Err(SessionError::InvalidInput);
        }

        rewritten.push_str(prefix);
        let specifier = format!("__yosoi_bundle_{nonce}_{}", *next_edge);
        let replacement =
            serde_json::to_string(&specifier).map_err(|_| SessionError::EvidenceUnavailable)?;
        rewritten.push_str(&replacement);
        if import_targets
            .insert(specifier, edge.target_module().to_owned())
            .is_some()
        {
            return Err(SessionError::InvalidInput);
        }
        *next_edge = next_edge.checked_add(1).ok_or(SessionError::InvalidInput)?;
        cursor = range.end;
    }

    rewritten.push_str(source.get(cursor..).ok_or(SessionError::InvalidInput)?);
    if rewritten.is_empty() || module_id.is_empty() {
        return Err(SessionError::InvalidInput);
    }
    Ok(rewritten)
}
