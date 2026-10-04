use crate::decoded_text::{CompiledTextRegex, compile_regex};
use crate::json::{parse_json_path, parse_json_pointer};
use crate::query::validate_capture_projection;
use crate::{Projection, QueryAtom, QueryError, QuerySpec};

use super::model::PlanError;

pub(super) fn validate_authored_projection(projection: &Projection) -> Result<(), PlanError> {
    if matches!(projection, Projection::Attribute(name) if name.trim().is_empty()) {
        return Err(PlanError::EmptyProjectionArgument);
    }
    let Projection::MatchedTextWithCaptures { names } = projection else {
        return Ok(());
    };
    if names.is_empty() || names.iter().any(|name| name.trim().is_empty()) {
        return Err(PlanError::EmptyProjectionArgument);
    }
    let mut seen = Vec::<&str>::with_capacity(names.len());
    for name in names {
        if seen.iter().any(|previous| *previous == name) {
            return Err(PlanError::DuplicateCaptureName { name: name.clone() });
        }
        seen.push(name);
    }
    Ok(())
}

pub(super) fn validate_query_projection(
    query: &QuerySpec,
    projection: &Projection,
    compiled_text_regex: Option<&CompiledTextRegex>,
) -> Result<(), PlanError> {
    if let (QueryAtom::TextRegex(_), Projection::MatchedTextWithCaptures { names }) =
        (query.atom(), projection)
    {
        let compiled = compiled_text_regex.ok_or_else(|| PlanError::InvalidQuerySyntax {
            atom: query.atom().clone(),
        })?;
        for name in names {
            if !compiled
                .regex()
                .capture_names()
                .flatten()
                .any(|candidate| candidate == name)
            {
                return Err(PlanError::UnknownCaptureName { name: name.clone() });
            }
        }
        return Ok(());
    }
    validate_capture_projection(query, projection).map_err(|error| match error {
        QueryError::UnknownCaptureName { name } => PlanError::UnknownCaptureName { name },
        QueryError::InvalidRegexSyntax => PlanError::InvalidQuerySyntax {
            atom: query.atom().clone(),
        },
        _ => PlanError::InvalidCombination {
            atom: query.atom().clone(),
            result_shape: query.result_shape(),
            projection: format!("{:?}", projection.kind()),
        },
    })
}

pub(super) fn all_document_classes() -> Vec<crate::DocumentClass> {
    vec![
        crate::DocumentClass::SourceHtml,
        crate::DocumentClass::SourceXml,
        crate::DocumentClass::SourceJson,
        crate::DocumentClass::SourceText,
        crate::DocumentClass::RenderedDom,
        crate::DocumentClass::AccessibilityTree,
    ]
}

pub(super) fn intersect(
    current: &mut Vec<crate::DocumentClass>,
    accepted: &[crate::DocumentClass],
) {
    current.retain(|class| accepted.contains(class));
}

pub(super) fn push_unique<T: Eq + Copy>(values: &mut Vec<T>, value: T) {
    if !values.contains(&value) {
        values.push(value);
    }
}

pub(super) fn validate_authored_query(
    query: &QuerySpec,
    compiled_text_regex: Option<&CompiledTextRegex>,
) -> Result<(), PlanError> {
    match query.atom() {
        QueryAtom::TextRegex(_) if compiled_text_regex.is_some() => Ok(()),
        QueryAtom::TextRegex(expression) => {
            compile_regex(expression)
                .map(|_| ())
                .map_err(|_| PlanError::InvalidQuerySyntax {
                    atom: query.atom().clone(),
                })
        }
        QueryAtom::TextLiteral(expression) if !expression.is_empty() => Ok(()),
        QueryAtom::JsonPointer(expression) => {
            parse_json_pointer(expression)?;
            Ok(())
        }
        QueryAtom::JsonPath(expression) => {
            parse_json_path(expression)?;
            Ok(())
        }
        atom if atom.expression().trim().is_empty() => Err(PlanError::EmptyQueryExpression),
        _ => Ok(()),
    }?;
    query
        .validate_namespace_bindings()
        .map_err(PlanError::InvalidQueryNamespaces)
}
