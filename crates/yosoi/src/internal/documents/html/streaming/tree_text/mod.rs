use crate::internal::documents as yosoi_documents;

use super::names::{BUTTON, DD, DT, FORM, LI, NameKey, P};
use super::support::{ElementTree, Range, SelectorElement, SelectorVisitBudget, TextSegment};
use super::tag_rules::{closes_paragraph, is_heading};

mod evaluate;
mod selection;

pub(super) use evaluate::try_tree_text;

pub(super) struct TreeTextNode {
    pub(super) parent: u32,
    pub(super) ordinal: u32,
    pub(super) depth: u32,
}

pub(super) struct TreeTextOpenElement {
    pub(super) id: usize,
    pub(super) name: NameKey,
    pub(super) child_count: u32,
}

#[derive(Clone, Copy)]
pub(super) struct CompactTextSegment {
    pub(super) start: u32,
    pub(super) end: u32,
    pub(super) owner: u32,
}

#[derive(Default)]
pub(super) struct TreeTextRepairState {
    pub(super) open: u8,
}

impl TreeTextRepairState {
    const P: u8 = 1;
    const LI: u8 = 2;
    const DEFINITION_ITEM: u8 = 4;
    const HEADING: u8 = 8;

    pub(super) fn requires_repair(&self, tag: NameKey) -> bool {
        if matches!(tag, BUTTON | FORM) {
            return true;
        }
        if self.open == 0 {
            return false;
        }
        (self.open & Self::P != 0 && closes_paragraph(tag))
            || (self.open & Self::LI != 0 && tag == LI)
            || (self.open & Self::DEFINITION_ITEM != 0 && matches!(tag, DD | DT))
            || (self.open & Self::HEADING != 0 && is_heading(tag))
    }

    const fn opened(&mut self, tag: NameKey) {
        self.open |= match tag {
            P => Self::P,
            LI => Self::LI,
            DD | DT => Self::DEFINITION_ITEM,
            tag if is_heading(tag) => Self::HEADING,
            _ => 0,
        };
    }

    const fn closed(&mut self, tag: NameKey) {
        let closed = match tag {
            P => Self::P,
            LI => Self::LI,
            DD | DT => Self::DEFINITION_ITEM,
            tag if is_heading(tag) => Self::HEADING,
            _ => 0,
        };
        self.open &= !closed;
    }
}

impl CompactTextSegment {
    pub(super) fn expanded(self) -> Option<TextSegment> {
        Some(TextSegment {
            start: usize::try_from(self.start).ok()?,
            end: usize::try_from(self.end).ok()?,
            owner: usize::try_from(self.owner).ok()?,
        })
    }
}

impl TreeTextNode {
    pub(super) fn parent(&self) -> Option<usize> {
        if self.parent == u32::MAX {
            None
        } else {
            usize::try_from(self.parent).ok()
        }
    }
}

pub(super) struct TreeTextTree {
    pub(super) nodes: Vec<TreeTextNode>,
    pub(super) children: Vec<usize>,
    pub(super) child_ranges: Vec<Range<usize>>,
}

impl TreeTextTree {
    pub(super) fn finish_children(&mut self) -> Option<()> {
        let mut offsets = Vec::with_capacity(self.nodes.len().checked_add(1)?);
        let mut counts = vec![0_usize; self.nodes.len()];
        for node in &self.nodes {
            if let Some(parent) = node.parent() {
                let count = counts.get(parent)?.checked_add(1)?;
                *counts.get_mut(parent)? = count;
            }
        }
        offsets.push(0_usize);
        for count in counts {
            offsets.push(offsets.last()?.checked_add(count)?);
        }
        let total = offsets.last().copied()?;
        let mut positions = offsets.get(..self.nodes.len())?.to_vec();
        let mut children = vec![0_usize; total];
        for (child, node) in self.nodes.iter().enumerate() {
            let Some(parent) = node.parent() else {
                continue;
            };
            let position = *positions.get(parent)?;
            *children.get_mut(position)? = child;
            *positions.get_mut(parent)? = position.checked_add(1)?;
        }
        let mut child_ranges = Vec::with_capacity(self.nodes.len());
        for pair in offsets.windows(2) {
            child_ranges.push(*pair.first()?..*pair.get(1)?);
        }
        self.child_ranges = child_ranges;
        self.children = children;
        Some(())
    }
}

impl SelectorElement for TreeTextNode {
    fn local_name(&self) -> Option<&str> {
        None
    }

    fn namespace_uri(&self) -> Option<&str> {
        None
    }

    fn attribute_value(
        &self,
        _requested_name: &str,
        _budget: &mut SelectorVisitBudget,
    ) -> Result<Option<String>, yosoi_documents::LocateFailure> {
        Ok(None)
    }
}

impl ElementTree for TreeTextTree {
    type Element = TreeTextNode;

    fn element_count(&self) -> usize {
        self.nodes.len()
    }

    fn element(&self, index: usize) -> Option<&Self::Element> {
        self.nodes.get(index)
    }

    fn parent(&self, index: usize) -> Option<usize> {
        self.nodes.get(index).and_then(TreeTextNode::parent)
    }

    fn children(&self, index: usize) -> Option<&[usize]> {
        self.children.get(self.child_ranges.get(index)?.clone())
    }
}
