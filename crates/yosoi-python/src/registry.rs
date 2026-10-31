//! Registry bindings preserve native atomicity and release Python while doing I/O.

use pyo3::{prelude::*, types::PyType};
use yosoi::registry::{Change, Coordination, Registry, RegistryError, Revision};

use crate::errors;

fn failure(error: RegistryError) -> PyErr {
    use std::error::Error;

    let variant = match &error {
        RegistryError::Conflict => "Conflict",
        RegistryError::Busy => "Busy",
        RegistryError::Poisoned => "Poisoned",
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
    fn new() -> Self {
        Self {
            registry: Registry::default(),
        }
    }

    #[classmethod]
    fn jsonl(_class: &Bound<'_, PyType>, py: Python<'_>, path: String) -> PyResult<Self> {
        let registry = py.detach(|| Registry::jsonl(path)).map_err(failure)?;
        Ok(Self { registry })
    }

    #[classmethod]
    fn global_jsonl(_class: &Bound<'_, PyType>, py: Python<'_>) -> PyResult<Self> {
        let registry = py.detach(Registry::global_jsonl).map_err(failure)?;
        Ok(Self { registry })
    }

    fn clone_handle(&self) -> Self {
        Self {
            registry: self.registry.clone(),
        }
    }

    fn coordination(&self) -> &'static str {
        match self.registry.coordination() {
            Coordination::Instance => "instance",
            Coordination::LocalProcesses => "local_processes",
            Coordination::Distributed => "distributed",
        }
    }

    fn snapshot_json(&self, py: Python<'_>) -> PyResult<String> {
        let snapshot = py.detach(|| self.registry.snapshot()).map_err(failure)?;
        serde_json::to_string(&snapshot).map_err(|error| failure(error.into()))
    }

    fn commit_json(&self, py: Python<'_>, expected: &str, changes: &str) -> PyResult<String> {
        let expected: Revision =
            serde_json::from_str(expected).map_err(|error| failure(error.into()))?;
        let changes: Vec<Change> =
            serde_json::from_str(changes).map_err(|error| failure(error.into()))?;
        let snapshot = py
            .detach(|| self.registry.commit(&expected, &changes))
            .map_err(failure)?;
        serde_json::to_string(&snapshot).map_err(|error| failure(error.into()))
    }

    fn compact(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.registry.compact()).map_err(failure)
    }
}
