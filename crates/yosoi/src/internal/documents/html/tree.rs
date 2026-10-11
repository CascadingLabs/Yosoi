mod compact;
mod finalize;
mod node;
mod text;

use std::{fmt, ops::Range};

use html5ever::{ParseOpts, parse_document, tendril::TendrilSink, tree_builder::TreeBuilderOpts};

use super::HtmlParseError;

use self::compact::CompactHtmlSink;
pub(super) use self::node::HtmlNode;
use self::node::HtmlNodeKind;
pub(super) use self::text::HtmlTextIndex;
pub use self::text::TextSegment;

pub(super) struct HtmlTree {
    nodes: Vec<HtmlNode>,
    elements: Vec<usize>,
    element_children: Vec<usize>,
    element_child_ranges: Vec<Range<usize>>,
    node_count: u64,
    max_depth: u32,
}

impl fmt::Debug for HtmlTree {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("HtmlTree")
            .field("arena_node_count", &self.node_count)
            .field("max_depth", &self.max_depth)
            .finish_non_exhaustive()
    }
}

impl HtmlTree {
    pub(super) fn parse(
        source: &str,
        max_depth: u32,
        max_nodes: u64,
    ) -> Result<Self, HtmlParseError> {
        let options = ParseOpts {
            tree_builder: TreeBuilderOpts {
                scripting_enabled: false,
                ..TreeBuilderOpts::default()
            },
            ..ParseOpts::default()
        };
        parse_document(CompactHtmlSink::default(), options)
            .one(source)
            .into_tree(max_depth, max_nodes)
    }
    pub(super) const fn node_count(&self) -> u64 {
        self.node_count
    }
    pub(super) const fn max_depth(&self) -> u32 {
        self.max_depth
    }
    pub(super) const fn element_count(&self) -> usize {
        self.elements.len()
    }
    pub(super) fn element(&self, index: usize) -> Option<&HtmlNode> {
        let id = self.elements.get(index).copied()?;
        self.nodes
            .get(id)
            .filter(|node| node.in_document && matches!(&node.kind, HtmlNodeKind::Element { .. }))
    }
    pub(super) fn element_children(&self, index: usize) -> Option<&[usize]> {
        let range = self.element_child_ranges.get(index)?.clone();
        self.element_children.get(range)
    }
}
