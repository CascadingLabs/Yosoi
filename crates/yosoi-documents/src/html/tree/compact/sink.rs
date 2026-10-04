use std::{borrow::Cow, cell::Ref, collections::HashSet};

use html5ever::{
    Attribute, QualName,
    tendril::StrTendril,
    tree_builder::{ElementFlags, NodeOrText, QuirksMode, TreeSink},
};

use super::super::{
    HtmlNode,
    node::{HtmlNodeKind, NodeLink},
};
use super::{ArenaName, CompactHtmlSink};

impl TreeSink for CompactHtmlSink {
    type Output = Self;
    type Handle = usize;
    type ElemName<'a>
        = ArenaName<'a>
    where
        Self: 'a;
    fn finish(self) -> Self::Output {
        self
    }
    fn parse_error(&self, _message: Cow<'static, str>) {}
    fn get_document(&self) -> usize {
        0
    }
    fn elem_name<'a>(&'a self, target: &'a usize) -> ArenaName<'a> {
        Ref::filter_map(self.nodes.borrow(), |nodes| {
            nodes.get(*target).and_then(|node| match &node.kind {
                HtmlNodeKind::Element { name, .. } => Some(name),
                _ => None,
            })
        })
        .map_or_else(
            |_| {
                self.fail();
                ArenaName::Fallback(&self.fallback_name)
            },
            ArenaName::Valid,
        )
    }
    fn create_element(
        &self,
        name: QualName,
        attributes: Vec<Attribute>,
        flags: ElementFlags,
    ) -> usize {
        let template = flags
            .template
            .then(|| self.allocate(HtmlNodeKind::Document));
        self.allocate(HtmlNodeKind::Element {
            name,
            attributes,
            template,
            mathml_integration: flags.mathml_annotation_xml_integration_point,
        })
    }
    fn create_comment(&self, _text: StrTendril) -> usize {
        self.allocate(HtmlNodeKind::Other)
    }
    fn create_pi(&self, _target: StrTendril, _data: StrTendril) -> usize {
        self.allocate(HtmlNodeKind::Other)
    }
    fn append(&self, parent: &usize, child: NodeOrText<usize>) {
        match child {
            NodeOrText::AppendText(text) => self.append_text(*parent, text),
            NodeOrText::AppendNode(node) => self.append_node(*parent, node),
        }
    }
    fn append_based_on_parent_node(
        &self,
        element: &usize,
        previous: &usize,
        child: NodeOrText<usize>,
    ) {
        if self
            .nodes
            .borrow()
            .get(*element)
            .is_some_and(|node| !node.parent.is_absent())
        {
            self.append_before_sibling(element, child);
        } else {
            self.append(previous, child);
        }
    }
    fn append_doctype_to_document(
        &self,
        _name: StrTendril,
        _public: StrTendril,
        _system: StrTendril,
    ) {
        let node = self.allocate(HtmlNodeKind::Other);
        self.append_node(0, node);
    }
    fn get_template_contents(&self, target: &usize) -> usize {
        let nodes = self.nodes.borrow();
        let Some(HtmlNodeKind::Element {
            template: Some(id), ..
        }) = nodes.get(*target).map(|node| &node.kind)
        else {
            self.fail();
            return 0;
        };
        *id
    }
    fn same_node(&self, left: &usize, right: &usize) -> bool {
        left == right
    }
    fn set_quirks_mode(&self, mode: QuirksMode) {
        self.quirks.set(mode);
    }
    fn append_before_sibling(&self, sibling: &usize, child: NodeOrText<usize>) {
        let mut nodes = self.nodes.borrow_mut();
        let Some(sibling_node) = nodes.get(*sibling) else {
            self.fail();
            return;
        };
        let parent_link = sibling_node.parent;
        let Some(parent) = parent_link.get() else {
            self.fail();
            return;
        };
        let previous = sibling_node.previous;
        let Some(sibling_link) = NodeLink::from_index(*sibling) else {
            self.fail();
            return;
        };
        if let NodeOrText::AppendText(text) = child {
            if let Some(previous) = previous.get()
                && let Some(HtmlNode {
                    kind: HtmlNodeKind::Text(existing),
                    ..
                }) = nodes.get_mut(previous)
            {
                existing.push_tendril(&text);
                return;
            }
            let id = nodes.len();
            let Some(id_link) = NodeLink::from_index(id) else {
                self.fail();
                return;
            };
            let mut node = HtmlNode::new(HtmlNodeKind::Text(text));
            node.parent = parent_link;
            node.previous = previous;
            node.next = sibling_link;
            nodes.push(node);
            if let Some(node) = nodes.get_mut(*sibling) {
                node.previous = id_link;
            }
            if let Some(previous) = previous.get() {
                if let Some(node) = nodes.get_mut(previous) {
                    node.next = id_link;
                }
            } else if let Some(node) = nodes.get_mut(parent) {
                node.first_child = id_link;
            }
            return;
        }
        let NodeOrText::AppendNode(id) = child else {
            return;
        };
        if nodes.get(id).is_none() || !Self::detach(&mut nodes, id) {
            self.fail();
            return;
        }
        let Some(id_link) = NodeLink::from_index(id) else {
            self.fail();
            return;
        };
        if let Some(node) = nodes.get_mut(id) {
            node.parent = parent_link;
            node.previous = previous;
            node.next = sibling_link;
        }
        if let Some(node) = nodes.get_mut(*sibling) {
            node.previous = id_link;
        }
        if let Some(previous) = previous.get() {
            if let Some(node) = nodes.get_mut(previous) {
                node.next = id_link;
            }
        } else if let Some(node) = nodes.get_mut(parent) {
            node.first_child = id_link;
        }
    }
    fn add_attrs_if_missing(&self, target: &usize, attributes: Vec<Attribute>) {
        let mut nodes = self.nodes.borrow_mut();
        let Some(HtmlNode {
            kind:
                HtmlNodeKind::Element {
                    attributes: existing,
                    ..
                },
            ..
        }) = nodes.get_mut(*target)
        else {
            self.fail();
            return;
        };
        let names = existing
            .iter()
            .map(|attribute| attribute.name.clone())
            .collect::<HashSet<_>>();
        existing.extend(
            attributes
                .into_iter()
                .filter(|attribute| !names.contains(&attribute.name)),
        );
    }
    fn remove_from_parent(&self, target: &usize) {
        if !Self::detach(&mut self.nodes.borrow_mut(), *target) {
            self.fail();
        }
    }
    fn reparent_children(&self, source: &usize, new_parent: &usize) {
        let mut nodes = self.nodes.borrow_mut();
        let Some(source_node) = nodes.get(*source) else {
            self.fail();
            return;
        };
        let first_link = source_node.first_child;
        let Some(first) = first_link.get() else {
            return;
        };
        let last_link = source_node.last_child;
        let Some(last) = last_link.get() else {
            self.fail();
            return;
        };
        if nodes.get(last).is_none() {
            self.fail();
            return;
        }
        let Some(parent_node) = nodes.get(*new_parent) else {
            self.fail();
            return;
        };
        let Some(new_parent_link) = NodeLink::from_index(*new_parent) else {
            self.fail();
            return;
        };
        let previous = parent_node.last_child;
        if let Some(previous_index) = previous.get() {
            let Some(node) = nodes.get_mut(previous_index) else {
                self.fail();
                return;
            };
            node.next = first_link;
            if let Some(node) = nodes.get_mut(first) {
                node.previous = previous;
            } else {
                self.fail();
                return;
            }
        } else {
            if let Some(node) = nodes.get_mut(*new_parent) {
                node.first_child = first_link;
            } else {
                self.fail();
                return;
            }
            if let Some(node) = nodes.get_mut(first) {
                node.previous = NodeLink::absent();
            } else {
                self.fail();
                return;
            }
        }
        if let Some(node) = nodes.get_mut(*new_parent) {
            node.last_child = last_link;
        } else {
            self.fail();
            return;
        }
        if let Some(node) = nodes.get_mut(*source) {
            node.first_child = NodeLink::absent();
            node.last_child = NodeLink::absent();
        } else {
            self.fail();
            return;
        }
        let mut current = Some(first);
        while let Some(id) = current {
            let Some(node) = nodes.get_mut(id) else {
                self.fail();
                return;
            };
            node.parent = new_parent_link;
            current = node.next.get();
        }
    }
    fn is_mathml_annotation_xml_integration_point(&self, target: &usize) -> bool {
        self.nodes
            .borrow()
            .get(*target)
            .and_then(|node| match &node.kind {
                HtmlNodeKind::Element {
                    mathml_integration, ..
                } => Some(*mathml_integration),
                _ => None,
            })
            .unwrap_or(false)
    }

    fn maybe_clone_an_option_into_selectedcontent(&self, option: &usize) {
        let mut nodes = self.nodes.borrow_mut();
        if Self::element_name(&nodes, *option) != Some("option") {
            self.fail();
            return;
        }
        if !Self::has_attribute(&nodes, *option, "selected") {
            return;
        }
        let Some(select) = Self::nearest_ancestor_select(&nodes, *option) else {
            return;
        };
        let Some(selectedcontent) = Self::selectedcontent(&nodes, select) else {
            return;
        };
        if !Self::replace_children_with_clones(&mut nodes, *option, selectedcontent) {
            self.fail();
        }
    }
}
