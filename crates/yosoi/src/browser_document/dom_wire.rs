use std::io::{self, Write};

use serde::Serialize;
use yosoi_documents::{DocumentEpoch, DomNodeId, ResourceBudget};

use super::RenderedDomNormalizationError;

pub(super) const RENDERED_DOM_SCHEMA_V1: &str = "yosoi.rendered-dom.v1";
pub(super) const RENDERED_DOM_TREE_MODEL: &str = "document_light_dom";

#[derive(Serialize)]
pub(super) struct RenderedDomWire {
    pub(super) schema: &'static str,
    pub(super) document_epoch: DocumentEpoch,
    pub(super) tree_model: &'static str,
    pub(super) root: DomNodeId,
    pub(super) nodes: Vec<WireNode>,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub(super) enum WireNode {
    Document {
        id: DomNodeId,
        parent: Option<DomNodeId>,
        children: Vec<DomNodeId>,
    },
    Element {
        id: DomNodeId,
        parent: Option<DomNodeId>,
        children: Vec<DomNodeId>,
        namespace_uri: String,
        tag_name: String,
        attributes: Vec<WireAttribute>,
    },
    Text {
        id: DomNodeId,
        parent: Option<DomNodeId>,
        children: Vec<DomNodeId>,
        value: String,
    },
}

#[derive(Serialize)]
pub(super) struct WireAttribute {
    pub(super) namespace_uri: String,
    pub(super) name: String,
    pub(super) value: String,
}

struct BoundedOutput {
    bytes: Vec<u8>,
    maximum: usize,
    limit_exceeded: bool,
    allocation_failed: bool,
}

impl BoundedOutput {
    const fn new(maximum: usize) -> Self {
        Self {
            bytes: Vec::new(),
            maximum,
            limit_exceeded: false,
            allocation_failed: false,
        }
    }
}

impl Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let Some(observed) = self.bytes.len().checked_add(bytes.len()) else {
            self.limit_exceeded = true;
            return Err(io::Error::other("rendered DOM output size overflow"));
        };
        if observed > self.maximum {
            self.limit_exceeded = true;
            return Err(io::Error::other("rendered DOM output limit exceeded"));
        }
        if self.bytes.try_reserve(bytes.len()).is_err() {
            self.allocation_failed = true;
            return Err(io::Error::other("rendered DOM output allocation failed"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub(super) fn serialize_bounded(
    wire: &RenderedDomWire,
    budget: ResourceBudget,
) -> Result<Vec<u8>, RenderedDomNormalizationError> {
    let maximum = budget.max_output_bytes().min(budget.max_input_bytes());
    let maximum_usize = usize::try_from(maximum)
        .map_err(|_| RenderedDomNormalizationError::OutputLimitNotAddressable)?;
    let mut output = BoundedOutput::new(maximum_usize);
    let serialized = serde_json::to_writer(&mut output, wire);
    if let Err(error) = serialized {
        if output.limit_exceeded {
            return Err(RenderedDomNormalizationError::OutputLimitExceeded { maximum });
        }
        if output.allocation_failed {
            return Err(RenderedDomNormalizationError::AllocationFailed);
        }
        return Err(RenderedDomNormalizationError::Serialization(error));
    }
    Ok(output.bytes)
}
