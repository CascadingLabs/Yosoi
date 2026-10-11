mod sink;

#[cfg(test)]
mod tests;

use std::cell::{Cell, Ref, RefCell};

use html5ever::{
    QualName,
    tendril::StrTendril,
    tree_builder::{ElemName, QuirksMode},
};

use super::super::HtmlParseError;
use super::{
    HtmlNode, HtmlTree,
    node::{HtmlNodeKind, NodeLink},
};

#[derive(Debug)]
pub(super) enum ArenaName<'a> {
    Valid(Ref<'a, QualName>),
    Fallback(&'a QualName),
}
impl ElemName for ArenaName<'_> {
    fn ns(&self) -> &html5ever::Namespace {
        match self {
            Self::Valid(name) => &name.ns,
            Self::Fallback(name) => &name.ns,
        }
    }
    fn local_name(&self) -> &html5ever::LocalName {
        match self {
            Self::Valid(name) => &name.local,
            Self::Fallback(name) => &name.local,
        }
    }
}

#[derive(Debug)]
pub(super) struct CompactHtmlSink {
    nodes: RefCell<Vec<HtmlNode>>,
    invalid: Cell<bool>,
    quirks: Cell<QuirksMode>,
    fallback_name: QualName,
}
impl Default for CompactHtmlSink {
    fn default() -> Self {
        Self {
            nodes: RefCell::new(vec![HtmlNode::new(HtmlNodeKind::Document)]),
            invalid: Cell::new(false),
            quirks: Cell::new(QuirksMode::NoQuirks),
            fallback_name: QualName::new(None, "".into(), "div".into()),
        }
    }
}
impl CompactHtmlSink {
    fn allocate(&self, kind: HtmlNodeKind) -> usize {
        let mut nodes = self.nodes.borrow_mut();
        let id = nodes.len();
        nodes.push(HtmlNode::new(kind));
        id
    }
    fn fail(&self) {
        self.invalid.set(true);
    }

    fn element_name(nodes: &[HtmlNode], id: usize) -> Option<&str> {
        match &nodes.get(id)?.kind {
            HtmlNodeKind::Element { name, .. } => Some(name.local.as_ref()),
            _ => None,
        }
    }

    fn has_attribute(nodes: &[HtmlNode], id: usize, requested: &str) -> bool {
        match nodes.get(id).map(|node| &node.kind) {
            Some(HtmlNodeKind::Element { attributes, .. }) => attributes.iter().any(|attribute| {
                attribute
                    .name
                    .local
                    .as_ref()
                    .eq_ignore_ascii_case(requested)
            }),
            _ => false,
        }
    }

    fn nearest_ancestor_select(nodes: &[HtmlNode], option: usize) -> Option<usize> {
        let mut current = nodes.get(option)?.parent.get();
        let mut saw_optgroup = false;
        let mut visited = 0_usize;
        while let Some(id) = current {
            visited = visited.checked_add(1)?;
            if visited > nodes.len() {
                return None;
            }
            match Self::element_name(nodes, id) {
                Some("datalist" | "hr" | "option") => return None,
                Some("optgroup") if saw_optgroup => return None,
                Some("optgroup") => saw_optgroup = true,
                Some("select") => return Some(id),
                _ => {}
            }
            current = nodes.get(id)?.parent.get();
        }
        None
    }

    fn selectedcontent(nodes: &[HtmlNode], select: usize) -> Option<usize> {
        if Self::has_attribute(nodes, select, "multiple") {
            return None;
        }

        let mut pending = Vec::new();
        let mut queued_children = 0_usize;
        Self::push_children_in_reverse(nodes, select, &mut pending, &mut queued_children)?;
        let mut visited = 0_usize;
        while let Some(id) = pending.pop() {
            visited = visited.checked_add(1)?;
            if visited > nodes.len() {
                return None;
            }
            if Self::element_name(nodes, id) == Some("selectedcontent") {
                return Some(id);
            }
            Self::push_children_in_reverse(nodes, id, &mut pending, &mut queued_children)?;
        }
        None
    }

    fn push_children_in_reverse(
        nodes: &[HtmlNode],
        parent: usize,
        pending: &mut Vec<usize>,
        queued_children: &mut usize,
    ) -> Option<()> {
        let mut child = nodes.get(parent)?.last_child.get();
        while let Some(id) = child {
            let next_count = queued_children.checked_add(1)?;
            if next_count > nodes.len() {
                return None;
            }
            let node = nodes.get(id)?;
            pending.push(id);
            *queued_children = next_count;
            child = node.previous.get();
        }
        Some(())
    }

    fn clone_shallow(nodes: &mut Vec<HtmlNode>, original: usize) -> Option<usize> {
        let kind = match &nodes.get(original)?.kind {
            HtmlNodeKind::Document => HtmlNodeKind::Document,
            HtmlNodeKind::Element {
                name,
                attributes,
                mathml_integration,
                ..
            } => HtmlNodeKind::Element {
                name: name.clone(),
                attributes: attributes.clone(),
                template: None,
                mathml_integration: *mathml_integration,
            },
            HtmlNodeKind::Text(text) => HtmlNodeKind::Text(text.clone()),
            HtmlNodeKind::Other => HtmlNodeKind::Other,
        };
        let id = nodes.len();
        nodes.push(HtmlNode::new(kind));
        Some(id)
    }

    fn append_fresh(nodes: &mut [HtmlNode], parent: usize, child: usize) -> bool {
        let Some(parent_link) = NodeLink::from_index(parent) else {
            return false;
        };
        let Some(child_link) = NodeLink::from_index(child) else {
            return false;
        };
        let Some(parent_node) = nodes.get(parent) else {
            return false;
        };
        let previous = parent_node.last_child;
        let previous_index = previous.get();
        let Some(child_node) = nodes.get_mut(child) else {
            return false;
        };
        if !child_node.parent.is_absent()
            || !child_node.previous.is_absent()
            || !child_node.next.is_absent()
        {
            return false;
        }
        child_node.parent = parent_link;
        child_node.previous = previous;
        if let Some(previous_index) = previous_index {
            let Some(previous_node) = nodes.get_mut(previous_index) else {
                return false;
            };
            previous_node.next = child_link;
        } else {
            let Some(parent_node) = nodes.get_mut(parent) else {
                return false;
            };
            parent_node.first_child = child_link;
        }
        let Some(parent_node) = nodes.get_mut(parent) else {
            return false;
        };
        parent_node.last_child = child_link;
        true
    }

    fn clone_subtree(nodes: &mut Vec<HtmlNode>, original: usize) -> Option<usize> {
        let root = Self::clone_shallow(nodes, original)?;
        let mut pending = vec![(original, root)];
        let mut visited = 0_usize;
        while let Some((source, target)) = pending.pop() {
            visited = visited.checked_add(1)?;
            if visited > nodes.len() {
                return None;
            }
            let template = match nodes.get(source).map(|node| &node.kind) {
                Some(HtmlNodeKind::Element { template, .. }) => *template,
                _ => None,
            };
            let mut children = Vec::new();
            let mut child = nodes.get(source)?.first_child.get();
            while let Some(id) = child {
                children.push(id);
                child = nodes.get(id)?.next.get();
            }
            for child in children {
                let clone = Self::clone_shallow(nodes, child)?;
                if !Self::append_fresh(nodes, target, clone) {
                    return None;
                }
                pending.push((child, clone));
            }
            if let Some(original_template) = template {
                let clone = Self::clone_shallow(nodes, original_template)?;
                let Some(HtmlNode {
                    kind:
                        HtmlNodeKind::Element {
                            template: target_template,
                            ..
                        },
                    ..
                }) = nodes.get_mut(target)
                else {
                    return None;
                };
                *target_template = Some(clone);
                pending.push((original_template, clone));
            }
        }
        Some(root)
    }

    fn replace_children_with_clones(
        nodes: &mut Vec<HtmlNode>,
        option: usize,
        selectedcontent: usize,
    ) -> bool {
        let mut originals = Vec::new();
        let mut child = nodes.get(option).and_then(|node| node.first_child.get());
        while let Some(id) = child {
            originals.push(id);
            child = nodes.get(id).and_then(|node| node.next.get());
        }
        let mut clones = Vec::with_capacity(originals.len());
        for original in originals {
            let Some(clone) = Self::clone_subtree(nodes, original) else {
                return false;
            };
            clones.push(clone);
        }

        let mut old_child = nodes
            .get(selectedcontent)
            .and_then(|node| node.first_child.get());
        while let Some(id) = old_child {
            let Some(node) = nodes.get_mut(id) else {
                return false;
            };
            old_child = node.next.get();
            node.parent = NodeLink::absent();
            node.previous = NodeLink::absent();
            node.next = NodeLink::absent();
        }
        let Some(target) = nodes.get_mut(selectedcontent) else {
            return false;
        };
        target.first_child = NodeLink::absent();
        target.last_child = NodeLink::absent();
        for clone in clones {
            if !Self::append_fresh(nodes, selectedcontent, clone) {
                return false;
            }
        }
        true
    }
    fn detach(nodes: &mut [HtmlNode], id: usize) -> bool {
        let Some(node) = nodes.get(id) else {
            return false;
        };
        let Some(id_link) = NodeLink::from_index(id) else {
            return false;
        };
        let (parent, previous, next) = (node.parent, node.previous, node.next);
        if let Some(previous_index) = previous.get() {
            let Some(node) = nodes.get_mut(previous_index) else {
                return false;
            };
            node.next = next;
        }
        if let Some(next_index) = next.get() {
            let Some(node) = nodes.get_mut(next_index) else {
                return false;
            };
            node.previous = previous;
        }
        if let Some(parent_index) = parent.get() {
            let Some(node) = nodes.get_mut(parent_index) else {
                return false;
            };
            if node.first_child == id_link {
                node.first_child = next;
            }
            if node.last_child == id_link {
                node.last_child = previous;
            }
        }
        let Some(node) = nodes.get_mut(id) else {
            return false;
        };
        node.parent = NodeLink::absent();
        node.previous = NodeLink::absent();
        node.next = NodeLink::absent();
        true
    }
    fn append_node(&self, parent: usize, child: usize) {
        let mut nodes = self.nodes.borrow_mut();
        if !Self::append_fresh(&mut nodes, parent, child) {
            self.fail();
        }
    }
    fn append_text(&self, parent: usize, text: StrTendril) {
        let mut nodes = self.nodes.borrow_mut();
        if let Some(previous) = nodes.get(parent).and_then(|node| node.last_child.get())
            && let Some(HtmlNode {
                kind: HtmlNodeKind::Text(existing),
                ..
            }) = nodes.get_mut(previous)
        {
            existing.push_tendril(&text);
            return;
        }
        if nodes.get(parent).is_none() {
            self.fail();
            return;
        }
        let child = nodes.len();
        nodes.push(HtmlNode::new(HtmlNodeKind::Text(text)));
        if !Self::append_fresh(&mut nodes, parent, child) {
            self.fail();
        }
    }
    pub(super) fn into_tree(
        self,
        max_depth: u32,
        max_nodes: u64,
    ) -> Result<HtmlTree, HtmlParseError> {
        if self.invalid.get() {
            return Err(HtmlParseError::InvalidParserTree);
        }
        let nodes = self.nodes.into_inner();
        let allocated_node_count =
            u64::try_from(nodes.len()).map_err(|_| HtmlParseError::NodeCountOverflow)?;
        if allocated_node_count > max_nodes {
            return Err(HtmlParseError::NodeLimitExceeded {
                maximum: max_nodes,
                observed: allocated_node_count,
            });
        }
        let capacity = nodes.len();
        let mut tree = HtmlTree {
            nodes,
            elements: Vec::with_capacity(capacity),
            element_children: Vec::new(),
            element_child_ranges: Vec::new(),
            node_count: allocated_node_count,
            max_depth: 0,
        };
        tree.finalize(max_depth)?;
        Ok(tree)
    }
}
