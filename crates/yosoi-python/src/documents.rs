//! Immutable document handles delegate parsing and location to the Rust SDK.

use std::sync::Arc;

use pyo3::prelude::*;
use yosoi::documents::{Document, DocumentId, DocumentProfile, DocumentRef};

use crate::{
    errors, locators::NativePlan, parsed::NativeParsedDocument, policy, responses::ResponseSource,
};

#[pyfunction]
pub fn validate_profile(profile_json: &str) -> PyResult<String> {
    let profile: DocumentProfile = serde_json::from_str(profile_json)
        .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
    serde_json::to_string(&profile)
        .map_err(|error| errors::DocumentError::new_err(error.to_string()))
}

#[pyfunction]
pub fn profile_class(profile_json: &str) -> PyResult<String> {
    let profile: DocumentProfile = serde_json::from_str(profile_json)
        .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
    let class = profile
        .class()
        .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
    serde_json::to_string(&class).map_err(|error| errors::DocumentError::new_err(error.to_string()))
}

#[derive(Clone, Debug)]
pub enum DocumentSource {
    Owned(Arc<Document>),
    Response {
        response: ResponseSource,
        attempt: usize,
        document: usize,
    },
}

#[pyclass(
    frozen,
    skip_from_py_object,
    module = "yosoi._native",
    name = "Document"
)]
#[derive(Clone, Debug)]
pub struct NativeDocument {
    pub source: DocumentSource,
}

impl NativeDocument {
    pub fn borrowed(&self) -> PyResult<DocumentRef<'_>> {
        match &self.source {
            DocumentSource::Owned(document) => Ok(document.as_ref().as_ref()),
            DocumentSource::Response {
                response,
                attempt,
                document,
            } => response
                .borrowed()?
                .attempts()
                .nth(*attempt)
                .and_then(|item| item.documents().nth(*document))
                .and_then(|item| item.outcome().document())
                .ok_or_else(|| {
                    errors::DocumentError::new_err("document is unavailable or out of range")
                }),
        }
    }
}

#[pymethods]
impl NativeDocument {
    #[new]
    fn new(id: &str, content: Vec<u8>, profile_json: &str) -> PyResult<Self> {
        let profile: DocumentProfile = serde_json::from_str(profile_json)
            .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
        let id = DocumentId::try_new(id)
            .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
        let inner = Document::from_profile(id, profile, content)
            .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
        Ok(Self {
            source: DocumentSource::Owned(Arc::new(inner)),
        })
    }

    #[getter]
    fn id(&self) -> PyResult<&str> {
        Ok(self.borrowed()?.id().as_str())
    }

    fn profile(&self) -> PyResult<String> {
        serde_json::to_string(&self.borrowed()?.profile())
            .map_err(|error| errors::DocumentError::new_err(error.to_string()))
    }

    fn document_class(&self) -> PyResult<String> {
        serde_json::to_string(&self.borrowed()?.class())
            .map_err(|error| errors::DocumentError::new_err(error.to_string()))
    }

    fn bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyBytes>> {
        Ok(pyo3::types::PyBytes::new(py, self.borrowed()?.bytes()))
    }

    #[getter]
    fn byte_len(&self) -> PyResult<u64> {
        Ok(self.borrowed()?.byte_len())
    }

    #[pyo3(signature = (plan, policy_json=None))]
    fn locate(
        &self,
        py: Python<'_>,
        plan: &NativePlan,
        policy_json: Option<&str>,
    ) -> PyResult<String> {
        let policy = policy::parse(policy_json)?;
        let document = self.borrowed()?;
        py.detach(|| {
            serde_json::to_string(&document.bind(&policy).locate(&plan.inner))
                .map_err(|error| errors::LocatorError::new_err(error.to_string()))
        })
    }

    #[pyo3(signature = (policy_json=None))]
    fn parse(&self, py: Python<'_>, policy_json: Option<&str>) -> PyResult<NativeParsedDocument> {
        let policy = policy::parse(policy_json)?;
        let document = self.clone();
        py.detach(|| NativeParsedDocument::start(document, policy))
    }

    fn validate_input(&self, id: &str, content: &[u8], profile_json: &str) -> PyResult<()> {
        let profile: DocumentProfile = serde_json::from_str(profile_json)
            .map_err(|error| errors::DocumentError::new_err(error.to_string()))?;
        let document = self.borrowed()?;
        if document.id().as_str() != id
            || document.profile() != profile
            || document.bytes() != content
        {
            return Err(errors::DocumentError::new_err(
                "document values do not match the native source",
            ));
        }
        Ok(())
    }
}
