//! Static source HTML parsing and bounded locator evaluation.
//!
//! The `html5-static-utf8-v1` profile uses html5ever's HTML5 tree builder with
//! scripting disabled. It never executes scripts or loads page resources.
//! Input must be strict UTF-8; an initial UTF-8 BOM is ignored, while charset
//! declarations do not select another decoder. HTML5 repair, including implied
//! `html`, `head`, and `body` nodes, is visible to locators. Coordinates are
//! one-based element-child paths from the document node, with no source byte
//! range because repaired nodes do not map honestly to exact source spans.
//!
//! Unprefixed CSS and XPath name tests match local element names. HTML namespace
//! names are ASCII case-insensitive; foreign-content names are case-sensitive.
//! Namespace-qualified selectors are outside this profile. Attribute names are
//! ASCII case-insensitive on HTML elements and exact on foreign elements;
//! identifiers, classes, and attribute values are case-sensitive. Descendant
//! text joins text nodes in parser order, collapses ASCII whitespace runs to one
//! space, and trims the ends. Tree-text search uses the same normalized text and
//! returns the deepest matching elements. Script and style contents remain data
//! text, and template-content fragments are outside the traversed document tree.
//!
//! CSS v1 supports selector lists, type or universal names, IDs, classes,
//! attribute presence or exact-value tests, and descendant or child combinators.
//! A selector is limited to 16 list entries and 64 total components. CSS escapes,
//! pseudo-classes, sibling combinators, and namespaces are rejected. XPath v1
//! supports child and descendant paths with type or wildcard tests and one
//! attribute-presence or exact-value predicate per step; a path is limited to
//! 32 steps. Functions, unions, positional predicates, and namespaces are
//! rejected. CSS whitespace around groups and combinators is discarded when the
//! expression becomes its query AST. Projecting an attribute that a selected
//! element lacks fails the evaluation instead of silently dropping that node.

use std::{cell::OnceCell, fmt, str};

#[cfg(debug_assertions)]
use std::env;

use thiserror::Error;

use self::tree::{HtmlTextIndex, HtmlTree};
use crate::{
    Document, DocumentClass, DocumentId, LocateFailure, LocateOutcome, Plan, ResourceBudget,
    ResourceLimit,
};

mod css;
mod element;
mod evaluation;
mod failure;
mod output_size;
mod query;
mod select;
mod streaming;
mod text;
mod tree;
mod xpath;

pub use self::css::{
    Combinator, CssComplexSelector, CssSelectorList, compound_matches, is_name_character,
    is_name_start, parse_css,
};
pub use self::element::{
    SelectorElement, canonical_attribute_name, element_attribute, element_name_matches,
};
pub use self::failure::{invalid_failure, invalid_plan, limit_failure};
pub use self::query::{CompiledTreeOutput, CompiledTreePlan, TreeQuery, compile_tree_plan};
pub use self::select::{SelectorVisitBudget, push_limited_match, select_tree};
pub use self::text::{ElementTree, append_normalized_text, select_tree_text};
pub use self::tree::TextSegment;
pub use self::xpath::{XPathAxis, XPathPath, parse_xpath, xpath_step_matches};

pub const HTML_NAMESPACE: &str = "http://www.w3.org/1999/xhtml";

pub fn validate_tree_plan_budget(
    plan: &CompiledTreePlan,
    budget: ResourceBudget,
) -> Result<(), LocateFailure> {
    query::validate_tree_plan_budget(plan, budget)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HtmlStreamingStrategy {
    Selector,
    TreeText,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HtmlPreflightFallbackReason {
    PlanUnavailable,
    PlanOutsideCertifiedSubset,
    InvalidUtf8,
    UnsupportedSourceBytes,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HtmlAttemptFallbackReason {
    Certificate,
    ResourceProof,
    Materialization,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HtmlFallbackReason {
    Preflight(HtmlPreflightFallbackReason),
    Attempt(HtmlAttemptFallbackReason),
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct HtmlAttemptFacts {
    pub input_bytes_available: u64,
    /// Last committed parser cursor, not a count of bytes touched by lookahead.
    pub parser_offset: Option<u64>,
    /// Work charged by the candidate evaluator, not by retained-tree evaluation.
    pub candidate_work: Option<u64>,
}

#[cfg_attr(
    not(debug_assertions),
    allow(
        dead_code,
        reason = "private route facts are consumed by debug diagnostics"
    )
)]
pub enum HtmlLocateDispatch {
    Completed {
        strategy: HtmlStreamingStrategy,
        outcome: LocateOutcome,
        attempt: HtmlAttemptFacts,
    },
    Terminal {
        outcome: LocateOutcome,
    },
    RetainedTree {
        reason: HtmlFallbackReason,
        attempt: HtmlAttemptFacts,
    },
}

impl HtmlLocateDispatch {
    #[cfg(debug_assertions)]
    pub fn trace_if_requested(&self) {
        if env::var_os("YOSOI_ISLAND_TRACE").is_none() {
            return;
        }
        match self {
            Self::Completed {
                strategy, attempt, ..
            } => eprintln!(
                "island accepted: strategy={strategy:?}, input_bytes={}, parser_offset={:?}, candidate_work={:?}",
                attempt.input_bytes_available, attempt.parser_offset, attempt.candidate_work,
            ),
            Self::Terminal { .. } => eprintln!("island terminal: input resource limit"),
            Self::RetainedTree { reason, attempt } => eprintln!(
                "island retained-tree fallback: reason={reason:?}, input_bytes={}, parser_offset={:?}, candidate_work={:?}",
                attempt.input_bytes_available, attempt.parser_offset, attempt.candidate_work,
            ),
        }
    }
}

pub fn try_locate_streaming(
    document: &Document,
    plan: &Plan,
    budget: ResourceBudget,
) -> HtmlLocateDispatch {
    streaming::try_locate(document, plan, budget)
}

/// The parser profile is part of the meaning of source-HTML coordinates.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum HtmlParserProfile {
    /// html5ever 0.39, HTML5 tree construction, strict UTF-8, no scripting.
    StaticHtml5Utf8V1,
}

impl HtmlParserProfile {
    /// Stable profile identifier suitable for corpus and benchmark metadata.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::StaticHtml5Utf8V1 => "html5-static-utf8-v1",
        }
    }
}

/// A parsed, immutable HTML5 tree ready for synchronous locator evaluation.
pub struct ParsedHtmlDocument {
    pub(super) document_id: DocumentId,
    pub(super) input_bytes: u64,
    pub(super) profile: HtmlParserProfile,
    tree: HtmlTree,
    text_index: OnceCell<Result<HtmlTextIndex, HtmlParseError>>,
}

impl fmt::Debug for ParsedHtmlDocument {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ParsedHtmlDocument")
            .field("document_id", &self.document_id)
            .field("input_bytes", &self.input_bytes)
            .field("profile", &self.profile)
            .field("element_count", &self.tree.element_count())
            .field("arena_node_count", &self.tree.node_count())
            .field("max_depth", &self.tree.max_depth())
            .finish_non_exhaustive()
    }
}

/// Invalid source HTML input or a resource limit reached while parsing.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum HtmlParseError {
    #[error("HTML parser only accepts source HTML documents")]
    UnsupportedDocument { document: DocumentClass },
    #[error("HTML input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("HTML tree has {observed} nodes, above the {maximum}-node limit")]
    NodeLimitExceeded { maximum: u64, observed: u64 },
    #[error("HTML parser node count cannot be represented by the public contract")]
    NodeCountOverflow,
    #[error("HTML source is not valid UTF-8")]
    InvalidUtf8,
    #[error("HTML tree depth is {observed}, above the {maximum}-level limit")]
    DepthLimitExceeded { maximum: u32, observed: u32 },
    #[error("HTML parser tree cannot be represented by the public coordinate contract")]
    CoordinateOverflow,
    #[error("HTML parser returned an invalid tree structure")]
    InvalidParserTree,
}

pub fn parse_failure(error: &HtmlParseError) -> LocateFailure {
    match error {
        HtmlParseError::UnsupportedDocument { document } => LocateFailure::UnsupportedCombination {
            document: *document,
        },
        HtmlParseError::InputLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::InputBytes,
            maximum: *maximum,
            observed: *observed,
        },
        HtmlParseError::NodeLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::Nodes,
            maximum: *maximum,
            observed: *observed,
        },
        HtmlParseError::DepthLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::Depth,
            maximum: u64::from(*maximum),
            observed: u64::from(*observed),
        },
        HtmlParseError::NodeCountOverflow => parse_failed("html_node_count_overflow"),
        HtmlParseError::InvalidUtf8 => parse_failed("html_invalid_utf8"),
        HtmlParseError::CoordinateOverflow => parse_failed("html_coordinate_overflow"),
        HtmlParseError::InvalidParserTree => parse_failed("html_invalid_parser_tree"),
    }
}

fn parse_failed(code: &str) -> LocateFailure {
    LocateFailure::ParseFailed {
        code: code.to_owned(),
    }
}

impl ParsedHtmlDocument {
    /// Parses one immutable source-HTML document under the caller's input and
    /// depth limits. The returned tree does not retain the original byte span
    /// for nodes because HTML5 repair can synthesize or move elements.
    pub fn parse(document: &Document, limits: ResourceBudget) -> Result<Self, HtmlParseError> {
        if document.class() != DocumentClass::SourceHtml {
            return Err(HtmlParseError::UnsupportedDocument {
                document: document.class(),
            });
        }
        if document.byte_len() > limits.max_input_bytes() {
            return Err(HtmlParseError::InputLimitExceeded {
                maximum: limits.max_input_bytes(),
                observed: document.byte_len(),
            });
        }

        let source = str::from_utf8(document.bytes()).map_err(|_| HtmlParseError::InvalidUtf8)?;
        let source = source.strip_prefix('\u{feff}').unwrap_or(source);
        let tree = HtmlTree::parse(source, limits.max_depth(), limits.max_nodes())?;

        Ok(Self {
            document_id: document.id().clone(),
            input_bytes: document.byte_len(),
            profile: HtmlParserProfile::StaticHtml5Utf8V1,
            tree,
            text_index: OnceCell::new(),
        })
    }

    /// Returns the explicit parser and text-decoding profile used for this tree.
    pub const fn profile(&self) -> HtmlParserProfile {
        self.profile
    }

    /// Number of retained parser arena slots, including template fragments and
    /// detached HTML5 repair clones.
    pub const fn node_count(&self) -> u64 {
        self.tree.node_count()
    }

    fn text_index(&self) -> Result<&HtmlTextIndex, HtmlParseError> {
        match self.text_index.get_or_init(|| self.tree.text_index()) {
            Ok(index) => Ok(index),
            Err(error) => Err(*error),
        }
    }
}

#[cfg(test)]
mod advanced_tests;
