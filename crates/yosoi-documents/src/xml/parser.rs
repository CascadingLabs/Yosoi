use std::str;

use crate::{Document, DocumentClass, ResourceBudget};

use super::{XML_NODE_LIMIT, XmlDocument, XmlError};

impl<'input> XmlDocument<'input> {
    /// Parses a source XML document under the caller's input and depth limits.
    pub fn parse(document: &'input Document, limits: ResourceBudget) -> Result<Self, XmlError> {
        if document.class() != DocumentClass::SourceXml {
            return Err(XmlError::WrongDocumentClass {
                actual: document.class(),
            });
        }
        if document.byte_len() > limits.max_input_bytes() {
            return Err(XmlError::InputLimitExceeded {
                maximum: limits.max_input_bytes(),
                observed: document.byte_len(),
            });
        }

        let source = str::from_utf8(document.bytes()).map_err(|_| XmlError::InvalidUtf8)?;
        let maximum_nodes = limits.max_nodes().min(u64::from(XML_NODE_LIMIT));
        let parser_node_limit =
            u32::try_from(maximum_nodes).map_err(|_| XmlError::NodeCountOverflow)?;
        let parser_options = roxmltree::ParsingOptions {
            allow_dtd: false,
            nodes_limit: parser_node_limit,
            entity_resolver: None,
        };
        let tree = match roxmltree::Document::parse_with_options(source, parser_options) {
            Ok(tree) => tree,
            Err(roxmltree::Error::DtdDetected) => return Err(XmlError::DtdProhibited),
            Err(roxmltree::Error::NodesLimitReached) => {
                let observed = maximum_nodes
                    .checked_add(1)
                    .ok_or(XmlError::NodeCountOverflow)?;
                return Err(XmlError::NodeLimitExceeded {
                    maximum: maximum_nodes,
                    observed,
                });
            }
            Err(_) => return Err(XmlError::MalformedXml),
        };
        let (node_count, depth) = measure_tree(&tree, limits.max_depth())?;
        if node_count > maximum_nodes {
            return Err(XmlError::NodeLimitExceeded {
                maximum: maximum_nodes,
                observed: node_count,
            });
        }
        Ok(Self {
            document,
            tree,
            node_count,
            depth,
        })
    }
}

fn measure_tree(
    tree: &roxmltree::Document<'_>,
    maximum_depth: u32,
) -> Result<(u64, u32), XmlError> {
    let mut pending = vec![(tree.root(), 0_u32)];
    let mut node_count = 0_u64;
    let mut observed_depth = 0_u32;
    while let Some((node, parent_element_depth)) = pending.pop() {
        node_count = node_count
            .checked_add(1)
            .ok_or(XmlError::NodeCountOverflow)?;

        let element_depth = if node.is_element() {
            let depth =
                parent_element_depth
                    .checked_add(1)
                    .ok_or(XmlError::DepthLimitExceeded {
                        maximum: maximum_depth,
                        observed: u32::MAX,
                    })?;
            observed_depth = observed_depth.max(depth);
            if depth > maximum_depth {
                return Err(XmlError::DepthLimitExceeded {
                    maximum: maximum_depth,
                    observed: observed_depth,
                });
            }
            depth
        } else {
            parent_element_depth
        };

        for child in node.children() {
            pending.push((child, element_depth));
        }
    }
    Ok((node_count, observed_depth))
}
