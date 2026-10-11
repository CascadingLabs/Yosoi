use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use crate::internal::documents::RegionPlan;

#[path = "query_builders.rs"]
mod builders;
#[path = "query_error.rs"]
mod error;
#[path = "query_namespace.rs"]
mod namespace;
#[path = "query_output.rs"]
mod output;

pub use builders::{
    accessibility_state, accessibility_text, accessible_name, css, json_path, json_pointer, regex,
    role, text_literal, tree_text_contains, xpath,
};
pub use error::QueryError;
pub use output::validate_capture_projection;

use namespace::{
    css_uses_namespace_syntax, valid_namespace_prefix, validate_css_prefixes,
    validate_xpath_prefixes, xpath_uses_namespace_syntax,
};

/// Scalar accessibility states supported by the static AX schema v1.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AccessibilityStateName {
    /// Whether an accessibility node is expanded in the retained snapshot.
    Expanded,
    /// Whether an accessibility node is focused in the retained snapshot.
    Focused,
}

impl AccessibilityStateName {
    /// Returns the portable lowercase state field name without evaluating browser state.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Expanded => "expanded",
            Self::Focused => "focused",
        }
    }
}

/// One closed, portable locator operation.
///
/// Text meanings are intentionally separate. Tree descendant text, accessible
/// names, and decoded text ranges must never silently substitute for one
/// another.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum QueryAtom {
    /// Authored CSS expression selecting source-tree nodes.
    Css(String),
    /// Authored supported XPath expression selecting source-tree nodes.
    XPath(String),
    /// Literal substring match against tree descendant text, distinct from decoded-text ranges.
    TreeTextContains(String),
    /// JSON Pointer selecting a native JSON value; the empty pointer denotes the root.
    JsonPointer(String),
    /// Authored supported JSONPath expression selecting native JSON values.
    JsonPath(String),
    /// Role match against immutable accessibility-node evidence.
    AccessibilityRole(String),
    /// Accessible-name match, not source-tree descendant text.
    AccessibleName(String),
    /// Text match against immutable accessibility-node evidence.
    AccessibilityText(String),
    /// Boolean match against one supported accessibility snapshot state.
    AccessibilityState {
        /// Expanded or focused state to inspect.
        name: AccessibilityStateName,
        /// Required boolean value, without mutating browser state.
        value: bool,
    },
    /// Literal match yielding decoded-text ranges rather than tree nodes.
    TextLiteral(String),
    /// Supported regular expression yielding decoded-text ranges and capture evidence.
    TextRegex(String),
}

impl QueryAtom {
    /// Borrows authored expression text, or the state name for a boolean state query.
    /// The boolean operand remains separate in `AccessibilityState`.
    pub fn expression(&self) -> &str {
        match self {
            Self::Css(value)
            | Self::XPath(value)
            | Self::TreeTextContains(value)
            | Self::JsonPointer(value)
            | Self::JsonPath(value)
            | Self::AccessibilityRole(value)
            | Self::AccessibleName(value)
            | Self::AccessibilityText(value)
            | Self::TextLiteral(value)
            | Self::TextRegex(value) => value,
            Self::AccessibilityState { name, .. } => name.as_str(),
        }
    }
}

/// The representation-native shape produced before projection.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryResultShape {
    /// HTML/XML tree nodes before text, attribute, or node projection.
    TreeNodes,
    /// Native JSON values before a supported JSON projection.
    JsonValues,
    /// Immutable accessibility nodes before name, text, or node projection.
    AccessibilityNodes,
    /// Decoded-text ranges before matched-text or named-capture projection.
    TextRanges,
}

/// A query-local namespace prefix binding used by XML CSS and XPath queries.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NamespaceBinding {
    prefix: String,
    namespace_uri: String,
}

impl NamespaceBinding {
    /// Borrows the authored query prefix; an empty prefix is a default CSS namespace binding.
    pub fn prefix(&self) -> &str {
        &self.prefix
    }

    /// Borrows the namespace URI used for expanded-name matching, not source prefix spelling.
    pub fn namespace_uri(&self) -> &str {
        &self.namespace_uri
    }
}

/// A query atom plus its declared result shape.
///
/// Public construction is deliberate: deserialized plans are hostile input,
/// so compilation validates the complete atom/shape/projection combination.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuerySpec {
    atom: QueryAtom,
    result_shape: QueryResultShape,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    namespace_bindings: Vec<NamespaceBinding>,
}

impl QuerySpec {
    /// Owns an atom and declared result shape without checking their compatibility.
    /// Plan compilation validates atom, shape, namespaces, and projections
    /// together before execution; construction does not search any document.
    pub const fn new(atom: QueryAtom, result_shape: QueryResultShape) -> Self {
        Self {
            atom,
            result_shape,
            namespace_bindings: Vec::new(),
        }
    }

    /// Borrows the closed query operation and authored operand.
    pub const fn atom(&self) -> &QueryAtom {
        &self.atom
    }

    /// Returns the declared native result capability, not match count or completeness.
    pub const fn result_shape(&self) -> QueryResultShape {
        self.result_shape
    }

    /// Borrows explicit query-local XML bindings. Builders sort by prefix;
    /// imported plan compilation rejects noncanonical order before execution.
    pub fn namespace_bindings(&self) -> &[NamespaceBinding] {
        &self.namespace_bindings
    }

    /// Binds one non-default prefix for namespace-aware XML locators.
    pub fn with_namespace(
        mut self,
        prefix: impl Into<String>,
        namespace_uri: impl Into<String>,
    ) -> Result<Self, QueryError> {
        if !matches!(&self.atom, QueryAtom::Css(_) | QueryAtom::XPath(_)) {
            return Err(QueryError::NamespacesRequireXmlLocator);
        }
        self.add_namespace(prefix.into(), namespace_uri.into())?;
        Ok(self)
    }

    /// Sets the namespace used by unprefixed CSS element selectors.
    ///
    /// XPath keeps its standard 1.0 rule that unprefixed element tests match
    /// elements in no namespace.
    pub fn with_default_namespace(
        mut self,
        namespace_uri: impl Into<String>,
    ) -> Result<Self, QueryError> {
        if !matches!(&self.atom, QueryAtom::Css(_)) {
            return Err(QueryError::DefaultNamespaceOnlyForCss);
        }
        self.add_namespace(String::new(), namespace_uri.into())?;
        Ok(self)
    }

    fn add_namespace(&mut self, prefix: String, namespace_uri: String) -> Result<(), QueryError> {
        if namespace_uri.trim().is_empty() {
            return Err(QueryError::EmptyNamespaceUri);
        }
        if !prefix.is_empty() && !valid_namespace_prefix(&prefix) {
            return Err(QueryError::InvalidNamespacePrefix);
        }
        if matches!(prefix.as_str(), "xml" | "xmlns") {
            return Err(QueryError::ReservedNamespacePrefix);
        }
        if self
            .namespace_bindings
            .iter()
            .any(|binding| binding.prefix == prefix)
        {
            return Err(QueryError::DuplicateNamespacePrefix);
        }
        self.namespace_bindings.push(NamespaceBinding {
            prefix,
            namespace_uri,
        });
        self.namespace_bindings
            .sort_by(|left, right| left.prefix.cmp(&right.prefix));
        Ok(())
    }

    /// Accounts UTF-8 expression and namespace metadata bytes for locator resource budgets.
    /// Boolean state operands include their portable spelling. Returns
    /// [`QueryError::LengthOverflow`] if a size or sum cannot fit u64 accounting.
    pub fn query_bytes(&self) -> Result<u64, QueryError> {
        let bytes = match &self.atom {
            QueryAtom::AccessibilityState { name, value } => {
                let boolean_bytes = if *value { 4_usize } else { 5_usize };
                name.as_str()
                    .len()
                    .checked_add(boolean_bytes)
                    .and_then(|bytes| bytes.checked_add(1))
                    .ok_or(QueryError::LengthOverflow)?
            }
            _ => self.atom.expression().len(),
        };
        self.namespace_bindings.iter().try_fold(
            u64::try_from(bytes).map_err(|_| QueryError::LengthOverflow)?,
            |total, binding| {
                let prefix =
                    u64::try_from(binding.prefix.len()).map_err(|_| QueryError::LengthOverflow)?;
                let uri = u64::try_from(binding.namespace_uri.len())
                    .map_err(|_| QueryError::LengthOverflow)?;
                total
                    .checked_add(prefix)
                    .and_then(|value| value.checked_add(uri))
                    .ok_or(QueryError::LengthOverflow)
            },
        )
    }

    pub(in crate::internal::documents) fn validate_namespace_bindings(
        &self,
    ) -> Result<(), QueryError> {
        let mut seen = BTreeSet::new();
        let mut previous_prefix = None;
        for binding in &self.namespace_bindings {
            if binding.namespace_uri.trim().is_empty() {
                return Err(QueryError::EmptyNamespaceUri);
            }
            if !binding.prefix.is_empty() && !valid_namespace_prefix(&binding.prefix) {
                return Err(QueryError::InvalidNamespacePrefix);
            }
            if matches!(binding.prefix.as_str(), "xml" | "xmlns") {
                return Err(QueryError::ReservedNamespacePrefix);
            }
            if !seen.insert(binding.prefix.as_str()) {
                return Err(QueryError::DuplicateNamespacePrefix);
            }
            if previous_prefix.is_some_and(|previous| previous > binding.prefix.as_str()) {
                return Err(QueryError::NonCanonicalNamespaceBindingOrder);
            }
            previous_prefix = Some(binding.prefix.as_str());
        }
        match &self.atom {
            QueryAtom::Css(expression) => validate_css_prefixes(expression, &seen),
            QueryAtom::XPath(expression) => validate_xpath_prefixes(expression, &seen),
            _ if self.namespace_bindings.is_empty() => Ok(()),
            _ => Err(QueryError::NamespacesRequireXmlLocator),
        }
    }

    pub(in crate::internal::documents) fn requires_xml_namespace_semantics(&self) -> bool {
        !self.namespace_bindings.is_empty()
            || match &self.atom {
                QueryAtom::Css(expression) => css_uses_namespace_syntax(expression),
                QueryAtom::XPath(expression) => xpath_uses_namespace_syntax(expression),
                _ => false,
            }
    }

    pub(in crate::internal::documents) fn validate_attribute_projection(
        &self,
        name: &str,
    ) -> Result<(), QueryError> {
        if !matches!(&self.atom, QueryAtom::Css(_) | QueryAtom::XPath(_)) {
            return Ok(());
        }
        let mut parts = name.split(':');
        let Some(first) = parts.next() else {
            return Err(QueryError::InvalidAttributeNamespaceName);
        };
        let second = parts.next();
        if first.is_empty() || second.is_some_and(str::is_empty) || parts.next().is_some() {
            return Err(QueryError::InvalidAttributeNamespaceName);
        }
        if second.is_some() {
            if first == "xmlns" {
                return Err(QueryError::ReservedNamespacePrefix);
            }
            if first != "xml"
                && !self
                    .namespace_bindings
                    .iter()
                    .any(|binding| binding.prefix == first)
            {
                return Err(QueryError::UnboundNamespacePrefix);
            }
        }
        Ok(())
    }

    /// Consumes query intent into an authored repeated-region root with nonblank lineage identity. Returns QueryError for invalid identity; no document is searched.
    pub fn each_as_region(self, id: impl Into<String>) -> Result<RegionPlan, QueryError> {
        RegionPlan::try_new(id, self)
    }
}

/// What value an output returns from the query result.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum Projection {
    DescendantText,
    Attribute(String),
    JsonValue,
    NodeReference,
    AccessibleName,
    AccessibilityText,
    MatchedText,
    MatchedTextWithCaptures { names: Vec<String> },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectionKind {
    DescendantText,
    Attribute,
    JsonValue,
    NodeReference,
    AccessibleName,
    AccessibilityText,
    MatchedText,
    MatchedTextWithCaptures,
}
