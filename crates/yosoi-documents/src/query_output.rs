use super::{Projection, ProjectionKind, QueryAtom, QueryError, QuerySpec};
use crate::OutputPlan;
use crate::decoded_text::compile_regex;

impl QuerySpec {
    /// Selects the query's natural text value.
    pub const fn text(self) -> OutputPlan {
        let projection = text_projection(&self.atom);
        OutputPlan::new(None, self, projection)
    }

    /// Selects one attribute from each matched element.
    pub fn attribute(self, name: impl Into<String>) -> Result<OutputPlan, QueryError> {
        let projection = attribute_projection(name)?;
        Ok(OutputPlan::new(None, self, projection))
    }

    /// Selects the matched JSON value.
    pub const fn value(self) -> OutputPlan {
        OutputPlan::new(None, self, Projection::JsonValue)
    }

    /// Selects a reference to each matched native node.
    pub const fn node(self) -> OutputPlan {
        OutputPlan::new(None, self, Projection::NodeReference)
    }

    /// Selects each matched accessibility node's accessible name.
    pub const fn name(self) -> OutputPlan {
        OutputPlan::new(None, self, Projection::AccessibleName)
    }

    /// Selects each regex match and the explicitly requested named captures.
    pub fn captures(
        self,
        names: impl IntoIterator<Item = impl Into<String>>,
    ) -> Result<OutputPlan, QueryError> {
        let projection = capture_projection(names)?;
        validate_capture_projection(&self, &projection)?;
        Ok(OutputPlan::new(None, self, projection))
    }
}

const fn text_projection(atom: &QueryAtom) -> Projection {
    match atom {
        QueryAtom::TextLiteral(_) | QueryAtom::TextRegex(_) => Projection::MatchedText,
        QueryAtom::AccessibilityText(_) => Projection::AccessibilityText,
        _ => Projection::DescendantText,
    }
}

fn attribute_projection(name: impl Into<String>) -> Result<Projection, QueryError> {
    let name = name.into();
    if name.trim().is_empty() {
        Err(QueryError::EmptyAttributeName)
    } else {
        Ok(Projection::Attribute(name))
    }
}

fn capture_projection(
    names: impl IntoIterator<Item = impl Into<String>>,
) -> Result<Projection, QueryError> {
    let mut requested = Vec::<String>::new();
    for value in names {
        let name = value.into();
        if name.trim().is_empty() {
            return Err(QueryError::EmptyCaptureName);
        }
        if requested.iter().any(|candidate| candidate == &name) {
            return Err(QueryError::DuplicateCaptureName { name });
        }
        requested.push(name);
    }
    if requested.is_empty() {
        return Err(QueryError::EmptyCaptureList);
    }
    Ok(Projection::MatchedTextWithCaptures { names: requested })
}

pub fn validate_capture_projection(
    query: &QuerySpec,
    projection: &Projection,
) -> Result<(), QueryError> {
    let (QueryAtom::TextRegex(expression), Projection::MatchedTextWithCaptures { names }) =
        (query.atom(), projection)
    else {
        return Ok(());
    };
    let compiled = compile_regex(expression).map_err(|_| QueryError::InvalidRegexSyntax)?;
    for name in names {
        if !compiled
            .capture_names()
            .flatten()
            .any(|candidate| candidate == name)
        {
            return Err(QueryError::UnknownCaptureName { name: name.clone() });
        }
    }
    Ok(())
}

impl Projection {
    pub const fn kind(&self) -> ProjectionKind {
        match self {
            Self::DescendantText => ProjectionKind::DescendantText,
            Self::Attribute(_) => ProjectionKind::Attribute,
            Self::JsonValue => ProjectionKind::JsonValue,
            Self::NodeReference => ProjectionKind::NodeReference,
            Self::AccessibleName => ProjectionKind::AccessibleName,
            Self::AccessibilityText => ProjectionKind::AccessibilityText,
            Self::MatchedText => ProjectionKind::MatchedText,
            Self::MatchedTextWithCaptures { .. } => ProjectionKind::MatchedTextWithCaptures,
        }
    }

    pub fn argument_bytes(&self) -> Result<u64, QueryError> {
        match self {
            Self::Attribute(name) => {
                u64::try_from(name.len()).map_err(|_| QueryError::LengthOverflow)
            }
            Self::DescendantText
            | Self::JsonValue
            | Self::NodeReference
            | Self::AccessibleName
            | Self::AccessibilityText
            | Self::MatchedText => Ok(0),
            Self::MatchedTextWithCaptures { names } => {
                let mut total = 0_u64;
                for name in names {
                    total = total
                        .checked_add(
                            u64::try_from(name.len()).map_err(|_| QueryError::LengthOverflow)?,
                        )
                        .ok_or(QueryError::LengthOverflow)?;
                }
                Ok(total)
            }
        }
    }
}
