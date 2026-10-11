use crate::internal::policy::PolicyError;

use super::BrowserMode;

mod wire;

const MAX_ACQUISITIONS: usize = 3;
const MAX_DOCUMENTS_PER_ACQUISITION: usize = 4;

/// A public document view that an acquisition may request.
#[derive(Clone, Copy, Debug, serde::Deserialize, Eq, Hash, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentRequest {
    /// The response document view.
    ResponseDocument,
    /// The browser's rendered DOM.
    RenderedDom,
    /// The browser's accessibility tree.
    AccessibilityTree,
    /// The network tree view.
    NetworkTree,
}

/// The acquisition mechanism, independent of its document selection.
#[derive(Clone, Copy, Debug, serde::Deserialize, Eq, Hash, PartialEq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum AcquisitionKind {
    /// Use the standalone HTTP acquisition path.
    DirectHttp,
    /// Navigate with the selected browser windowing mode.
    Browser { mode: BrowserMode },
}

/// Whether the authored acquisition uses the current document default or an
/// explicit replacement set.
#[derive(Clone, Copy, Debug, serde::Deserialize, Eq, Hash, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentSelectionKind {
    /// Resolve to the current default document set when creating a snapshot.
    Current,
    /// Use the exact document set authored by the caller.
    Exact,
}

/// One ordered page acquisition declaration.
///
/// The bare `DirectHttp` and `Browser(mode)` variants use the current document
/// set. Calling [`Acquisition::documents`] creates an exact replacement set,
/// including when the iterator is empty.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Acquisition {
    /// Use Direct HTTP and the current document set.
    DirectHttp,
    /// Use a browser and the current document set.
    Browser(BrowserMode),
    /// Use an exact replacement document set for the selected acquisition.
    Exact {
        /// Acquisition mechanism whose documents are selected.
        acquisition: AcquisitionKind,
        /// Exact document requests, in canonical policy order.
        documents: Vec<DocumentRequest>,
    },
}

impl Acquisition {
    /// Replaces this acquisition's document selection with an exact set.
    ///
    /// Repeated calls replace the prior set. The policy is validated when it
    /// is snapshotted or serialized.
    pub fn documents(self, documents: impl IntoIterator<Item = DocumentRequest>) -> Self {
        let acquisition = self.kind();
        let mut exact_documents = Vec::with_capacity(MAX_DOCUMENTS_PER_ACQUISITION);
        for document in documents {
            exact_documents.push(document);
            if exact_documents.len() > MAX_DOCUMENTS_PER_ACQUISITION {
                break;
            }
        }
        exact_documents.sort_by_key(|document| document_order(*document));
        Self::Exact {
            acquisition,
            documents: exact_documents,
        }
    }

    /// Returns the acquisition mechanism represented by this declaration.
    pub const fn kind(&self) -> AcquisitionKind {
        match self {
            Self::DirectHttp => AcquisitionKind::DirectHttp,
            Self::Browser(mode) => AcquisitionKind::Browser { mode: *mode },
            Self::Exact { acquisition, .. } => *acquisition,
        }
    }

    /// Returns whether this declaration uses Current or Exact document
    /// selection.
    pub const fn selection_kind(&self) -> DocumentSelectionKind {
        match self {
            Self::DirectHttp | Self::Browser(_) => DocumentSelectionKind::Current,
            Self::Exact { .. } => DocumentSelectionKind::Exact,
        }
    }

    /// Returns the exact document list when this declaration replaces the
    /// current default.
    pub fn exact_documents(&self) -> Option<&[DocumentRequest]> {
        match self {
            Self::DirectHttp | Self::Browser(_) => None,
            Self::Exact { documents, .. } => Some(documents),
        }
    }

    pub(in crate::internal::policy) fn validate(&self) -> Result<(), PolicyError> {
        let Self::Exact {
            acquisition,
            documents,
        } = self
        else {
            return Ok(());
        };

        if documents.len() > MAX_DOCUMENTS_PER_ACQUISITION {
            return Err(PolicyError::TooManyDocuments);
        }

        let mut seen = Vec::with_capacity(MAX_DOCUMENTS_PER_ACQUISITION);
        let mut previous = None;
        for document in documents {
            if seen.contains(document) {
                return Err(PolicyError::DuplicateDocument(*document));
            }
            if previous.is_some_and(|prior| document_order(prior) > document_order(*document)) {
                return Err(PolicyError::NonCanonicalDocumentOrder);
            }
            seen.push(*document);
            previous = Some(*document);
        }

        if matches!(acquisition, AcquisitionKind::DirectHttp)
            && documents
                .iter()
                .any(|document| *document != DocumentRequest::ResponseDocument)
        {
            return Err(PolicyError::UnsupportedDirectHttpDocument);
        }
        Ok(())
    }
}

/// Ordered acquisitions and their document selections for one page policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Page {
    /// Acquisitions in authored order.
    pub acquisitions: Vec<Acquisition>,
}

impl Default for Page {
    fn default() -> Self {
        Self {
            acquisitions: vec![Acquisition::DirectHttp],
        }
    }
}

impl Page {
    /// Creates and validates an ordered page acquisition list.
    pub fn new(acquisitions: Vec<Acquisition>) -> Result<Self, PolicyError> {
        let page = Self { acquisitions };
        page.validate()?;
        Ok(page)
    }

    pub(in crate::internal::policy) fn validate(&self) -> Result<(), PolicyError> {
        if self.acquisitions.len() > MAX_ACQUISITIONS {
            return Err(PolicyError::TooManyAcquisitions);
        }

        let mut seen = Vec::with_capacity(MAX_ACQUISITIONS);
        for acquisition in &self.acquisitions {
            acquisition.validate()?;
            let kind = acquisition.kind();
            if seen.contains(&kind) {
                return Err(PolicyError::DuplicateAcquisition(kind));
            }
            seen.push(kind);
        }
        Ok(())
    }

    pub(in crate::internal::policy) fn effective(&self) -> EffectivePage {
        let acquisitions = self
            .acquisitions
            .iter()
            .map(|acquisition| {
                let mut documents = match acquisition {
                    Acquisition::DirectHttp | Acquisition::Browser(_) => {
                        vec![DocumentRequest::ResponseDocument]
                    }
                    Acquisition::Exact { documents, .. } => documents.clone(),
                };
                documents.sort_by_key(|document| document_order(*document));
                EffectiveAcquisition {
                    acquisition: acquisition.kind(),
                    authored_selection: acquisition.selection_kind(),
                    documents,
                }
            })
            .collect();
        EffectivePage { acquisitions }
    }
}

/// A resolved acquisition, retaining whether the caller authored Current or
/// Exact while exposing the exact document requests for this snapshot.
#[derive(Clone, Debug, serde::Deserialize, Eq, PartialEq, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectiveAcquisition {
    /// The mechanism used by this acquisition.
    pub acquisition: AcquisitionKind,
    /// The caller's Current or Exact selection.
    pub authored_selection: DocumentSelectionKind,
    /// Exact documents resolved for this snapshot, in canonical order.
    pub documents: Vec<DocumentRequest>,
}

/// Ordered acquisitions after resolving their Current document selections.
#[derive(Clone, Debug, Default, serde::Deserialize, Eq, PartialEq, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectivePage {
    /// Effective acquisitions in the authored order.
    pub acquisitions: Vec<EffectiveAcquisition>,
}

impl EffectivePage {
    pub(in crate::internal::policy) fn validate(&self) -> Result<(), PolicyError> {
        Page::new(
            self.acquisitions
                .iter()
                .map(|resolved| Acquisition::Exact {
                    acquisition: resolved.acquisition,
                    documents: resolved.documents.clone(),
                })
                .collect(),
        )?;
        Ok(())
    }
}

const fn document_order(document: DocumentRequest) -> u8 {
    match document {
        DocumentRequest::ResponseDocument => 0,
        DocumentRequest::RenderedDom => 1,
        DocumentRequest::AccessibilityTree => 2,
        DocumentRequest::NetworkTree => 3,
    }
}
