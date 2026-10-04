//! Secure, synchronous XML source parsing and bounded locator evaluation.

mod css;
mod evaluation;
mod output;
mod parser;
mod query;
mod region_evaluation;
mod text;
mod xpath;

pub(crate) use query::CompiledXmlPlan;

use roxmltree::Node;
use thiserror::Error;

use crate::{Document, DocumentClass, LocateFailure, NamespaceBinding, QueryAtom, QuerySpec};

const XML_NODE_LIMIT: u32 = 2_000_000;
const XML_NODE_VISIT_LIMIT: u64 = 20_000_000;

/// A deterministic error from XML parsing or evaluation.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum XmlError {
    #[error("XML locators require a source XML document, received {actual:?}")]
    WrongDocumentClass { actual: DocumentClass },
    #[error("XML input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("XML byte input must be UTF-8")]
    InvalidUtf8,
    #[error("XML with a non-empty DTD is prohibited")]
    DtdProhibited,
    #[error("XML parser rejected the document")]
    MalformedXml,
    #[error("XML document has {observed} nodes, above the {maximum}-node limit")]
    NodeLimitExceeded { maximum: u64, observed: u64 },
    #[error("XML parser node count cannot be represented by the public contract")]
    NodeCountOverflow,
    #[error("XML nesting depth is {observed}, above the {maximum}-level limit")]
    DepthLimitExceeded { maximum: u32, observed: u32 },
    #[error("compiled locator plan cannot be evaluated against this XML document")]
    IncompatiblePlan,
    #[error("XML locator syntax is malformed or outside the supported subset")]
    InvalidQuery,
    #[error("XML locator references an unbound namespace prefix")]
    UnboundNamespacePrefix,
    #[error("XML query has {observed} operations, above the {maximum}-operation limit")]
    QueryStepLimitExceeded { maximum: u32, observed: u32 },
    #[error("XML query used {observed} operations, above the {maximum}-operation traversal limit")]
    TraversalLimitExceeded { maximum: u64, observed: u64 },
    #[error("XML locator produced {observed} matches, above the {maximum}-match limit")]
    MatchLimitExceeded { maximum: u64, observed: u64 },
    #[error("XML results use {observed} bytes, above the {maximum}-byte output limit")]
    OutputLimitExceeded { maximum: u64, observed: u64 },
    #[error("XML attribute projection did not find its requested attribute")]
    MissingProjectedAttribute,
    #[error("XML result coordinates or outcomes could not be constructed")]
    InvalidResult,
}

pub(crate) fn parse_failure(error: &XmlError) -> LocateFailure {
    evaluation::evaluation_failure(error)
}

pub(crate) fn supports_query_syntax(query: &QuerySpec) -> bool {
    match query.atom() {
        QueryAtom::Css(expression) => {
            css::validate_syntax(expression, query.namespace_bindings()).is_ok()
        }
        QueryAtom::XPath(expression) => {
            xpath::validate_syntax(expression, query.namespace_bindings()).is_ok()
        }
        _ => false,
    }
}

/// An owned parser view over one immutable UTF-8 XML source document.
///
/// DTDs are disabled, no entity resolver is installed, and the parser never
/// opens files or makes network requests. Fixed node and traversal caps bound
/// parser allocations and repeated query work independently of result limits.
#[derive(Debug)]
pub struct XmlDocument<'input> {
    document: &'input Document,
    tree: roxmltree::Document<'input>,
    node_count: u64,
    depth: u32,
}

pub(crate) struct QueryWorkBudget {
    node_visits: u64,
    maximum_visits: u64,
}

impl QueryWorkBudget {
    pub(crate) fn new(maximum_visits: u64) -> Self {
        Self {
            node_visits: 0,
            maximum_visits: maximum_visits.min(XML_NODE_VISIT_LIMIT),
        }
    }

    pub(crate) fn visit(&mut self) -> Result<(), XmlError> {
        let observed = self
            .node_visits
            .checked_add(1)
            .ok_or(XmlError::TraversalLimitExceeded {
                maximum: self.maximum_visits,
                observed: u64::MAX,
            })?;
        self.node_visits = observed;
        if self.node_visits > self.maximum_visits {
            return Err(XmlError::TraversalLimitExceeded {
                maximum: self.maximum_visits,
                observed: self.node_visits,
            });
        }
        Ok(())
    }
}

impl XmlDocument<'_> {
    /// Number of nodes retained by the XML parser, including its root node.
    pub const fn node_count(&self) -> u64 {
        self.node_count
    }
}

pub(crate) fn namespace_uri(
    bindings: &[NamespaceBinding],
    prefix: Option<&str>,
    default_for_unprefixed: bool,
) -> Result<Option<String>, XmlError> {
    match prefix {
        Some("xml") => Ok(Some(roxmltree::NS_XML_URI.to_owned())),
        Some("xmlns") => Ok(Some(roxmltree::NS_XMLNS_URI.to_owned())),
        Some(value) => bindings
            .iter()
            .find(|binding| binding.prefix() == value)
            .map(|binding| Some(binding.namespace_uri().to_owned()))
            .ok_or(XmlError::UnboundNamespacePrefix),
        None if default_for_unprefixed => Ok(bindings
            .iter()
            .find(|binding| binding.prefix().is_empty())
            .map(|binding| binding.namespace_uri().to_owned())),
        None => Ok(None),
    }
}

pub(crate) fn enforce_match_limit(count: usize, maximum: u64) -> Result<(), XmlError> {
    let observed = u64::try_from(count).map_err(|_| XmlError::InvalidResult)?;
    if observed > maximum {
        Err(XmlError::MatchLimitExceeded { maximum, observed })
    } else {
        Ok(())
    }
}

pub(crate) fn order_unique_nodes<'tree, 'input>(
    mut nodes: Vec<Node<'tree, 'input>>,
) -> Vec<Node<'tree, 'input>> {
    nodes.sort();
    nodes.dedup_by_key(|node| node.id());
    nodes
}

pub(crate) fn query_steps_exceeded(maximum: u32, observed: usize) -> XmlError {
    let observed = u32::try_from(observed).unwrap_or(u32::MAX);
    XmlError::QueryStepLimitExceeded { maximum, observed }
}
