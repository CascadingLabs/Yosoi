use super::super::HtmlParseError;
use super::{
    HtmlNode, HtmlTree,
    node::{ElementIndex, HtmlNodeKind},
};

struct FinalizeItem {
    node: usize,
    element_parent: Option<usize>,
    element_depth: u32,
    element_ordinal: u32,
    in_document: bool,
}

impl HtmlTree {
    pub(super) fn finalize(&mut self, max_depth: u32) -> Result<(), HtmlParseError> {
        let mut seen = vec![false; self.nodes.len()];
        let mut pending = Vec::with_capacity(self.nodes.len());
        pending.push(FinalizeItem {
            node: 0,
            element_parent: None,
            element_depth: 0,
            element_ordinal: 0,
            in_document: true,
        });
        while let Some(item) = pending.pop() {
            let flag = seen
                .get_mut(item.node)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            if *flag {
                continue;
            }
            *flag = true;
            let node = self
                .nodes
                .get(item.node)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            let is_element = matches!(&node.kind, HtmlNodeKind::Element { .. });
            let template = match &node.kind {
                HtmlNodeKind::Element { template, .. } => *template,
                _ => None,
            };
            let (child_parent, child_depth) = if item.in_document && is_element {
                if item.element_depth > max_depth {
                    return Err(HtmlParseError::DepthLimitExceeded {
                        maximum: max_depth,
                        observed: item.element_depth,
                    });
                }
                self.max_depth = self.max_depth.max(item.element_depth);
                let element_index = self.elements.len();
                self.elements.push(item.node);
                let element = self
                    .nodes
                    .get_mut(item.node)
                    .ok_or(HtmlParseError::InvalidParserTree)?;
                element.in_document = true;
                element.element_index = ElementIndex::from_option(Some(element_index))?;
                element.element_parent = ElementIndex::from_option(item.element_parent)?;
                element.ordinal = Some(item.element_ordinal);
                (Some(element_index), item.element_depth)
            } else {
                (item.element_parent, item.element_depth)
            };
            if let Some(template) = template {
                pending.push(FinalizeItem {
                    node: template,
                    element_parent: None,
                    element_depth: 0,
                    element_ordinal: 0,
                    in_document: false,
                });
            }
            self.push_finalize_children(
                item.node,
                child_parent,
                child_depth,
                item.in_document,
                &mut pending,
            )?;
        }
        self.build_element_children()
    }

    fn push_finalize_children(
        &self,
        parent: usize,
        element_parent: Option<usize>,
        element_depth: u32,
        in_document: bool,
        pending: &mut Vec<FinalizeItem>,
    ) -> Result<(), HtmlParseError> {
        let parent_node = self
            .nodes
            .get(parent)
            .ok_or(HtmlParseError::InvalidParserTree)?;
        let mut ordinal = 0_u32;
        if in_document {
            let mut child = parent_node.first_child.get();
            while let Some(child_id) = child {
                let child_node = self
                    .nodes
                    .get(child_id)
                    .ok_or(HtmlParseError::InvalidParserTree)?;
                if matches!(&child_node.kind, HtmlNodeKind::Element { .. }) {
                    ordinal = ordinal
                        .checked_add(1)
                        .ok_or(HtmlParseError::CoordinateOverflow)?;
                }
                child = child_node.next.get();
            }
        }
        let mut child = parent_node.last_child.get();
        while let Some(child_id) = child {
            let child_node = self
                .nodes
                .get(child_id)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            let child_is_element = matches!(&child_node.kind, HtmlNodeKind::Element { .. });
            let child_depth = if in_document && child_is_element {
                element_depth
                    .checked_add(1)
                    .ok_or(HtmlParseError::CoordinateOverflow)?
            } else {
                element_depth
            };
            pending.push(FinalizeItem {
                node: child_id,
                element_parent,
                element_depth: child_depth,
                element_ordinal: if child_is_element { ordinal } else { 0 },
                in_document,
            });
            if in_document && child_is_element {
                ordinal = ordinal
                    .checked_sub(1)
                    .ok_or(HtmlParseError::CoordinateOverflow)?;
            }
            child = child_node.previous.get();
        }
        if in_document && ordinal != 0 {
            return Err(HtmlParseError::InvalidParserTree);
        }
        Ok(())
    }

    fn build_element_children(&mut self) -> Result<(), HtmlParseError> {
        let mut counts = vec![0_usize; self.elements.len()];
        for index in 0..self.elements.len() {
            let Some(parent) = self.element(index).and_then(HtmlNode::element_parent) else {
                continue;
            };
            let count = counts
                .get_mut(parent)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            *count = count
                .checked_add(1)
                .ok_or(HtmlParseError::CoordinateOverflow)?;
        }

        self.element_child_ranges.clear();
        self.element_child_ranges.reserve(counts.len());
        let mut end = 0_usize;
        for count in &mut counts {
            let start = end;
            end = end
                .checked_add(*count)
                .ok_or(HtmlParseError::CoordinateOverflow)?;
            self.element_child_ranges.push(start..end);
            *count = start;
        }
        self.element_children.clear();
        self.element_children.resize(end, 0);
        for index in 0..self.elements.len() {
            let Some(parent) = self.element(index).and_then(HtmlNode::element_parent) else {
                continue;
            };
            let cursor = counts
                .get_mut(parent)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            let slot = self
                .element_children
                .get_mut(*cursor)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            *slot = index;
            *cursor = cursor
                .checked_add(1)
                .ok_or(HtmlParseError::CoordinateOverflow)?;
        }
        Ok(())
    }
}
