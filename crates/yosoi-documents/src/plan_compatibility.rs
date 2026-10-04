use crate::html::{parse_css, parse_xpath};
use crate::query::{Projection, ProjectionKind, QueryAtom, QueryResultShape, QuerySpec};
use crate::{DocumentClass, xml};

use super::model::LocatorCapability;

const TREE_DOCUMENTS: &[DocumentClass] = &[
    DocumentClass::SourceHtml,
    DocumentClass::SourceXml,
    DocumentClass::RenderedDom,
];
const JSON_DOCUMENTS: &[DocumentClass] = &[DocumentClass::SourceJson];
const AX_DOCUMENTS: &[DocumentClass] = &[DocumentClass::AccessibilityTree];
const TEXT_DOCUMENTS: &[DocumentClass] = &[DocumentClass::SourceText];

pub(super) struct Compatibility {
    pub(super) documents: Vec<DocumentClass>,
    pub(super) capability: LocatorCapability,
}

pub(super) fn region_compatibility(query: &QuerySpec) -> Option<Compatibility> {
    match (query.atom(), query.result_shape()) {
        (QueryAtom::Css(_), QueryResultShape::TreeNodes) => Some(Compatibility {
            documents: tree_query_documents(query),
            capability: LocatorCapability::Css,
        }),
        (QueryAtom::XPath(_), QueryResultShape::TreeNodes) => Some(Compatibility {
            documents: tree_query_documents(query),
            capability: LocatorCapability::XPath,
        }),
        (QueryAtom::TreeTextContains(_), QueryResultShape::TreeNodes) => Some(Compatibility {
            documents: TREE_DOCUMENTS.to_vec(),
            capability: LocatorCapability::TreeTextContains,
        }),
        _ => None,
    }
}

pub(super) fn output_compatibility(
    query: &QuerySpec,
    projection: &Projection,
) -> Option<Compatibility> {
    match (query.atom(), query.result_shape(), projection) {
        (
            QueryAtom::Css(_),
            QueryResultShape::TreeNodes,
            Projection::DescendantText | Projection::Attribute(_) | Projection::NodeReference,
        ) => Some(Compatibility {
            documents: tree_query_documents(query),
            capability: LocatorCapability::Css,
        }),
        (
            QueryAtom::XPath(_),
            QueryResultShape::TreeNodes,
            Projection::DescendantText | Projection::Attribute(_) | Projection::NodeReference,
        ) => Some(Compatibility {
            documents: tree_query_documents(query),
            capability: LocatorCapability::XPath,
        }),
        (
            QueryAtom::TreeTextContains(_),
            QueryResultShape::TreeNodes,
            Projection::DescendantText | Projection::NodeReference,
        ) => Some(Compatibility {
            documents: TREE_DOCUMENTS.to_vec(),
            capability: LocatorCapability::TreeTextContains,
        }),
        (QueryAtom::JsonPointer(_), QueryResultShape::JsonValues, Projection::JsonValue) => {
            Some(Compatibility {
                documents: JSON_DOCUMENTS.to_vec(),
                capability: LocatorCapability::JsonPointer,
            })
        }
        (QueryAtom::JsonPath(_), QueryResultShape::JsonValues, Projection::JsonValue) => {
            Some(Compatibility {
                documents: JSON_DOCUMENTS.to_vec(),
                capability: LocatorCapability::JsonPath,
            })
        }
        (
            QueryAtom::AccessibilityRole(_),
            QueryResultShape::AccessibilityNodes,
            Projection::NodeReference | Projection::AccessibleName,
        ) => Some(Compatibility {
            documents: AX_DOCUMENTS.to_vec(),
            capability: LocatorCapability::AccessibilityRole,
        }),
        (
            QueryAtom::AccessibleName(_),
            QueryResultShape::AccessibilityNodes,
            Projection::NodeReference | Projection::AccessibleName,
        ) => Some(Compatibility {
            documents: AX_DOCUMENTS.to_vec(),
            capability: LocatorCapability::AccessibleNameQuery,
        }),
        (
            QueryAtom::AccessibilityText(_),
            QueryResultShape::AccessibilityNodes,
            Projection::NodeReference | Projection::AccessibilityText,
        ) => Some(Compatibility {
            documents: AX_DOCUMENTS.to_vec(),
            capability: LocatorCapability::AccessibilityTextQuery,
        }),
        (
            QueryAtom::AccessibilityState { .. },
            QueryResultShape::AccessibilityNodes,
            Projection::NodeReference,
        ) => Some(Compatibility {
            documents: AX_DOCUMENTS.to_vec(),
            capability: LocatorCapability::AccessibilityStateQuery,
        }),
        (QueryAtom::TextLiteral(_), QueryResultShape::TextRanges, Projection::MatchedText) => {
            Some(Compatibility {
                documents: TEXT_DOCUMENTS.to_vec(),
                capability: LocatorCapability::TextLiteral,
            })
        }
        (QueryAtom::TextRegex(_), QueryResultShape::TextRanges, Projection::MatchedText) => {
            Some(Compatibility {
                documents: TEXT_DOCUMENTS.to_vec(),
                capability: LocatorCapability::TextRegex,
            })
        }
        (
            QueryAtom::TextRegex(_),
            QueryResultShape::TextRanges,
            Projection::MatchedTextWithCaptures { .. },
        ) => Some(Compatibility {
            documents: TEXT_DOCUMENTS.to_vec(),
            capability: LocatorCapability::TextRegex,
        }),
        _ => None,
    }
}

fn tree_query_documents(query: &QuerySpec) -> Vec<DocumentClass> {
    let html_syntax = if query.requires_xml_namespace_semantics() {
        false
    } else {
        match query.atom() {
            QueryAtom::Css(expression) => parse_css(expression).is_ok(),
            QueryAtom::XPath(expression) => parse_xpath(expression).is_ok(),
            _ => false,
        }
    };
    let xml_syntax = xml::supports_query_syntax(query);
    let mut documents = Vec::new();
    if html_syntax {
        documents.push(DocumentClass::SourceHtml);
    }
    if xml_syntax {
        documents.push(DocumentClass::SourceXml);
    }
    if html_syntax {
        documents.push(DocumentClass::RenderedDom);
    }
    documents
}

pub(super) const fn projection_capability(kind: ProjectionKind) -> LocatorCapability {
    match kind {
        ProjectionKind::DescendantText => LocatorCapability::DescendantTextProjection,
        ProjectionKind::Attribute => LocatorCapability::AttributeProjection,
        ProjectionKind::JsonValue => LocatorCapability::JsonValueProjection,
        ProjectionKind::NodeReference => LocatorCapability::NodeReferenceProjection,
        ProjectionKind::AccessibleName => LocatorCapability::AccessibleNameProjection,
        ProjectionKind::AccessibilityText => LocatorCapability::AccessibilityTextProjection,
        ProjectionKind::MatchedText => LocatorCapability::MatchedTextProjection,
        ProjectionKind::MatchedTextWithCaptures => {
            LocatorCapability::MatchedTextWithCapturesProjection
        }
    }
}
