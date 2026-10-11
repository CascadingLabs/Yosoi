use crate::internal::documents::{
    OutputPlan, QueryError, QuerySpec, RegionPlan, css, text_literal,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LocatorKind {
    Css,
    TextLiteral,
}

/// Static locator data suitable for inline Contract attributes or constants.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PinnedLocator {
    kind: LocatorKind,
    expression: &'static str,
}

impl PinnedLocator {
    const fn new(kind: LocatorKind, expression: &'static str) -> Self {
        Self { kind, expression }
    }

    /// Projects the located node or range as text for one Contract field.
    pub const fn text(self) -> PinnedOutputLocator {
        PinnedOutputLocator {
            query: self,
            projection: PinnedProjection::Text,
        }
    }

    /// Projects one attribute from a located element for a Contract field.
    pub const fn attribute(self, name: &'static str) -> PinnedOutputLocator {
        PinnedOutputLocator {
            query: self,
            projection: PinnedProjection::Attribute(name),
        }
    }

    #[doc(hidden)]
    pub fn compile(self) -> Result<QuerySpec, QueryError> {
        match self.kind {
            LocatorKind::Css => css(self.expression),
            LocatorKind::TextLiteral => text_literal(self.expression),
        }
    }

    #[doc(hidden)]
    pub fn compile_region(self, id: &'static str) -> Result<RegionPlan, QueryError> {
        RegionPlan::try_new(id, self.compile()?)
    }
}

/// Static query plus projection for one generated Contract output.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PinnedOutputLocator {
    query: PinnedLocator,
    projection: PinnedProjection,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PinnedProjection {
    Text,
    Attribute(&'static str),
}

impl PinnedOutputLocator {
    #[doc(hidden)]
    pub fn compile(self, region: Option<&RegionPlan>) -> Result<OutputPlan, QueryError> {
        let query = self.query.compile()?;
        match (region, self.projection) {
            (Some(region), PinnedProjection::Text) => Ok(region.find(query).text()),
            (None, PinnedProjection::Text) => Ok(query.text()),
            (Some(region), PinnedProjection::Attribute(name)) => region.find(query).attribute(name),
            (None, PinnedProjection::Attribute(name)) => query.attribute(name),
        }
    }
}

/// Const-friendly pinned locator declarations for Contract authoring.
pub mod locator {
    use super::{LocatorKind, PinnedLocator};

    pub const fn css(expression: &'static str) -> PinnedLocator {
        PinnedLocator::new(LocatorKind::Css, expression)
    }

    pub const fn text_literal(expression: &'static str) -> PinnedLocator {
        PinnedLocator::new(LocatorKind::TextLiteral, expression)
    }
}
