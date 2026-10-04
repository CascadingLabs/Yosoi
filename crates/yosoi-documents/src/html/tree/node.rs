use html5ever::{Attribute, QualName, tendril::StrTendril};

use super::super::{HTML_NAMESPACE, HtmlParseError, SelectorElement, SelectorVisitBudget};

/// A one-word link to a node in the parser arena.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct NodeLink(usize);

impl NodeLink {
    const ABSENT: Self = Self(usize::MAX);

    pub(super) const fn absent() -> Self {
        Self::ABSENT
    }

    pub(super) const fn from_index(index: usize) -> Option<Self> {
        if index == usize::MAX {
            None
        } else {
            Some(Self(index))
        }
    }

    pub(super) const fn get(self) -> Option<usize> {
        if self.0 == usize::MAX {
            None
        } else {
            Some(self.0)
        }
    }

    pub(super) const fn is_absent(self) -> bool {
        self.0 == usize::MAX
    }
}

/// An optional index into the finalized element list. Keeping the absence
/// marker in one word avoids reserving two words per HTML node for `Option<usize>`.
#[derive(Clone, Copy, Debug)]
pub(super) struct ElementIndex(usize);

impl ElementIndex {
    pub(super) const fn absent() -> Self {
        Self(usize::MAX)
    }

    pub(super) const fn from_option(index: Option<usize>) -> Result<Self, HtmlParseError> {
        match index {
            Some(index) if index == usize::MAX => Err(HtmlParseError::NodeCountOverflow),
            Some(index) => Ok(Self(index)),
            None => Ok(Self::absent()),
        }
    }

    pub(super) const fn get(self) -> Option<usize> {
        if self.0 == usize::MAX {
            None
        } else {
            Some(self.0)
        }
    }
}

#[derive(Debug)]
pub(super) enum HtmlNodeKind {
    Document,
    Element {
        name: QualName,
        attributes: Vec<Attribute>,
        template: Option<usize>,
        mathml_integration: bool,
    },
    Text(StrTendril),
    Other,
}

#[derive(Debug)]
pub(in crate::html) struct HtmlNode {
    pub(super) parent: NodeLink,
    pub(super) first_child: NodeLink,
    pub(super) last_child: NodeLink,
    pub(super) previous: NodeLink,
    pub(super) next: NodeLink,
    pub(super) element_parent: ElementIndex,
    pub(super) element_index: ElementIndex,
    pub(super) ordinal: Option<u32>,
    pub(super) in_document: bool,
    pub(super) kind: HtmlNodeKind,
}

impl HtmlNode {
    pub(super) const fn new(kind: HtmlNodeKind) -> Self {
        Self {
            parent: NodeLink::absent(),
            first_child: NodeLink::absent(),
            last_child: NodeLink::absent(),
            previous: NodeLink::absent(),
            next: NodeLink::absent(),
            element_parent: ElementIndex::absent(),
            element_index: ElementIndex::absent(),
            ordinal: None,
            in_document: false,
            kind,
        }
    }
    pub(in crate::html) const fn element_parent(&self) -> Option<usize> {
        self.element_parent.get()
    }
    pub(in crate::html) const fn element_sibling_ordinal(&self) -> Option<u32> {
        self.ordinal
    }
}

impl SelectorElement for HtmlNode {
    fn local_name(&self) -> Option<&str> {
        match &self.kind {
            HtmlNodeKind::Element { name, .. } if self.in_document => Some(name.local.as_ref()),
            _ => None,
        }
    }
    fn namespace_uri(&self) -> Option<&str> {
        match &self.kind {
            HtmlNodeKind::Element { name, .. } if self.in_document => Some(name.ns.as_ref()),
            _ => None,
        }
    }
    fn attribute_value(
        &self,
        requested: &str,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Option<String>, crate::LocateFailure> {
        let HtmlNodeKind::Element {
            name, attributes, ..
        } = &self.kind
        else {
            return Ok(None);
        };
        if !self.in_document {
            return Ok(None);
        }
        let html = name.ns.as_ref() == HTML_NAMESPACE;
        for attribute in attributes {
            budget.charge()?;
            if !attribute.name.ns.as_ref().is_empty() {
                continue;
            }
            let candidate = attribute.name.local.as_ref();
            if (html && candidate.eq_ignore_ascii_case(requested))
                || (!html && candidate == requested)
            {
                return Ok(Some(attribute.value.to_string()));
            }
        }
        Ok(None)
    }
}

#[cfg(test)]
mod tests {
    use std::mem::size_of;

    use super::NodeLink;

    #[test]
    fn node_link_is_one_word_and_rejects_the_absence_sentinel() {
        assert_eq!(size_of::<NodeLink>(), size_of::<usize>());
        assert_eq!(NodeLink::absent().get(), None);
        assert_eq!(NodeLink::from_index(0).and_then(NodeLink::get), Some(0));
        assert_eq!(NodeLink::from_index(usize::MAX), None);
    }
}
