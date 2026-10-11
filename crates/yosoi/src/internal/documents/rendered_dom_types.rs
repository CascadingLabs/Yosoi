use crate::internal::documents::LocateFailure;
use crate::internal::documents::html::{
    ElementTree, HTML_NAMESPACE, SelectorElement, SelectorVisitBudget, TextSegment,
};
use crate::internal::documents::{DocumentEpoch, DocumentId, DomNodeId};

pub const RENDERED_DOM_SCHEMA_V1: &str = "yosoi.rendered-dom.v1";
/// One document's DOM light tree, without shadow or composed-tree expansion.
pub const RENDERED_DOM_TREE_MODEL: &str = "document_light_dom";

/// A validated immutable tree ready for synchronous selector evaluation.
///
/// The document epoch and every selected node ID travel together in native
/// coordinates. The tree contains no iframe subdocuments or pseudo-elements,
/// and descendant text does not imply layout visibility.
#[derive(Debug)]
pub struct RenderedDomDocument {
    pub(super) document_id: DocumentId,
    pub(super) document_epoch: DocumentEpoch,
    pub(super) input_bytes: u64,
    pub(super) node_count: u64,
    pub(super) elements: Vec<RenderedDomElement>,
    pub(super) normalized_text: String,
    pub(super) text_segments: Vec<TextSegment>,
    pub(super) max_depth: u32,
}

impl RenderedDomDocument {
    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }

    pub const fn document_epoch(&self) -> DocumentEpoch {
        self.document_epoch
    }

    pub const fn node_count(&self) -> u64 {
        self.node_count
    }
}

#[derive(Debug)]
pub(super) struct RenderedDomElement {
    pub(super) id: DomNodeId,
    pub(super) parent: Option<usize>,
    pub(super) children: Vec<usize>,
    pub(super) namespace_uri: String,
    pub(super) tag_name: String,
    pub(super) attributes: Vec<DomAttribute>,
    pub(super) text_range: Option<(usize, usize)>,
}

#[derive(Debug)]
pub(super) struct DomAttribute {
    pub(super) namespace_uri: String,
    pub(super) name: String,
    pub(super) value: String,
}

impl SelectorElement for RenderedDomElement {
    fn local_name(&self) -> Option<&str> {
        Some(&self.tag_name)
    }

    fn namespace_uri(&self) -> Option<&str> {
        Some(&self.namespace_uri)
    }

    fn attribute_value(
        &self,
        requested_name: &str,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Option<String>, LocateFailure> {
        let is_html_element = self.namespace_uri == HTML_NAMESPACE;
        for attribute in &self.attributes {
            budget.charge()?;
            if !attribute.namespace_uri.is_empty() {
                continue;
            }
            let matches = if is_html_element {
                attribute.name.eq_ignore_ascii_case(requested_name)
            } else {
                attribute.name == requested_name
            };
            if matches {
                return Ok(Some(attribute.value.clone()));
            }
        }
        Ok(None)
    }
}

impl ElementTree for [RenderedDomElement] {
    type Element = RenderedDomElement;

    fn element_count(&self) -> usize {
        self.len()
    }

    fn element(&self, index: usize) -> Option<&Self::Element> {
        self.get(index)
    }

    fn parent(&self, index: usize) -> Option<usize> {
        self.get(index).and_then(|element| element.parent)
    }

    fn children(&self, index: usize) -> Option<&[usize]> {
        self.get(index).map(|element| element.children.as_slice())
    }
}
