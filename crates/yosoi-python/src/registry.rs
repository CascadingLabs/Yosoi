//! Registry bindings preserve native atomicity and release Python while doing I/O.

use pyo3::{prelude::*, types::PyType};
use yosoi::registry::{
    Change, Coordination, Registry, RegistryError, Revision, TransactionContext,
};

use crate::errors;

fn failure(error: RegistryError) -> PyErr {
    use std::error::Error;

    let variant = match &error {
        RegistryError::Conflict => "Conflict",
        RegistryError::Busy => "Busy",
        RegistryError::InvalidKey => "InvalidKey",
        RegistryError::InvalidState => "InvalidState",
        RegistryError::CapacityExceeded => "CapacityExceeded",
        RegistryError::NoGlobalLocation => "NoGlobalLocation",
        RegistryError::Io(_) => "Io",
        RegistryError::Json(_) => "Json",
    };
    let mut sources = Vec::new();
    let mut source = error.source();
    while let Some(cause) = source {
        sources.push(cause.to_string());
        source = cause.source();
    }
    let message = error.to_string();
    drop(error);
    Python::attach(|py| {
        errors::with_metadata(
            py,
            errors::RegistryError::new_err(message),
            "yosoi::registry::RegistryError",
            Some(variant),
            serde_json::json!({}),
            &sources,
        )
    })
}

#[pyclass(frozen)]
#[derive(Debug)]
pub struct NativeRegistry {
    registry: Registry,
}

#[pymethods]
impl NativeRegistry {
    #[new]
    #[pyo3(signature = (path=None))]
    fn new(py: Python<'_>, path: Option<String>) -> PyResult<Self> {
        let registry = py
            .detach(|| match path {
                Some(path) => Registry::jsonl(path),
                None => Registry::new(),
            })
            .map_err(failure)?;
        Ok(Self { registry })
    }

    #[classmethod]
    fn jsonl(_class: &Bound<'_, PyType>, py: Python<'_>, path: String) -> PyResult<Self> {
        let registry = py.detach(|| Registry::jsonl(path)).map_err(failure)?;
        Ok(Self { registry })
    }

    fn clone_handle(&self) -> Self {
        Self {
            registry: self.registry.clone(),
        }
    }

    fn coordination(&self) -> &'static str {
        match self.registry.coordination() {
            Coordination::LocalProcesses => "local_processes",
        }
    }

    fn caller_json(&self) -> PyResult<String> {
        serde_json::to_string(self.registry.caller()).map_err(|error| failure(error.into()))
    }

    fn path(&self) -> String {
        self.registry.path().to_string_lossy().into_owned()
    }

    fn snapshot_json(&self, py: Python<'_>) -> PyResult<String> {
        let snapshot = py.detach(|| self.registry.snapshot()).map_err(failure)?;
        serde_json::to_string(&snapshot).map_err(|error| failure(error.into()))
    }

    fn commit_json(
        &self,
        py: Python<'_>,
        expected: &str,
        changes: &str,
        context: &str,
    ) -> PyResult<String> {
        let expected: Revision =
            serde_json::from_str(expected).map_err(|error| failure(error.into()))?;
        let changes: Vec<Change> =
            serde_json::from_str(changes).map_err(|error| failure(error.into()))?;
        let context: TransactionContext =
            serde_json::from_str(context).map_err(|error| failure(error.into()))?;
        let snapshot = py
            .detach(|| {
                self.registry
                    .commit_with_context(&expected, &changes, &context)
            })
            .map_err(failure)?;
        serde_json::to_string(&snapshot).map_err(|error| failure(error.into()))
    }

    fn compact(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.registry.compact()).map_err(failure)
    }
}
