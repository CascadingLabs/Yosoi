//! Python storage and offline inspection use the existing public SDK boundaries.

use std::{error::Error, path::PathBuf, sync::Arc};

use pyo3::prelude::*;
use serde::{Serialize, de::DeserializeOwned};
use yosoi::{
    Archive,
    archive::{ArchiveError, DocumentArchiveRef, PlanArchiveRef},
    automation_record::{AutomationRecord, AutomationRecordRef, MAX_AUTOMATION_RECORD_BYTES},
    view::{View, ViewCursor},
};

use crate::{
    async_runtime,
    documents::{DocumentSource, NativeDocument},
    errors,
    locators::NativePlan,
};

fn failure<E: Error + 'static>(error: E, rust_type: &str, variant: Option<&str>) -> PyErr {
    let mut sources = Vec::new();
    let mut source = error.source();
    while let Some(value) = source {
        sources.push(value.to_string());
        source = value.source();
    }
    Python::attach(|py| {
        errors::with_metadata(
            py,
            errors::ArchiveError::new_err(error.to_string()),
            rust_type,
            variant,
            serde_json::json!({}),
            &sources,
        )
    })
}

fn archive_error(error: ArchiveError) -> PyErr {
    let (variant, details) = match &error {
        ArchiveError::UnsupportedPlatform { platform, .. } => (
            "UnsupportedPlatform",
            serde_json::json!({"platform": platform}),
        ),
        ArchiveError::EmptyRoot => ("EmptyRoot", serde_json::json!({})),
        ArchiveError::InvalidReference(_) => ("InvalidReference", serde_json::json!({})),
        ArchiveError::Io {
            operation, path, ..
        } => (
            "Io",
            serde_json::json!({"operation": operation, "path": path}),
        ),
        ArchiveError::FilesystemTask { operation, .. } => (
            "FilesystemTask",
            serde_json::json!({"operation": operation}),
        ),
        ArchiveError::UnsafeArchivePath { path, reason, .. } => (
            "UnsafeArchivePath",
            serde_json::json!({"path": path, "reason": reason}),
        ),
        ArchiveError::InsecurePermissions { path, mode, .. } => (
            "InsecurePermissions",
            serde_json::json!({"path": path, "mode": mode}),
        ),
        ArchiveError::RecordNotFound { kind, key, .. } => (
            "RecordNotFound",
            serde_json::json!({"kind": kind, "key": key}),
        ),
        ArchiveError::NotRegularFile { path, .. } => {
            ("NotRegularFile", serde_json::json!({"path": path}))
        }
        ArchiveError::RecordTooLarge {
            maximum, observed, ..
        } => (
            "RecordTooLarge",
            serde_json::json!({"maximum": maximum, "observed": observed}),
        ),
        ArchiveError::InvalidPolicy(_) => ("InvalidPolicy", serde_json::json!({})),
        ArchiveError::InvalidRequestRun(_) => ("InvalidRequestRun", serde_json::json!({})),
        ArchiveError::InvalidDocument(_) => ("InvalidDocument", serde_json::json!({})),
        ArchiveError::InvalidEvaluationRun(_) => ("InvalidEvaluationRun", serde_json::json!({})),
        ArchiveError::InvalidLocatorRun(_) => ("InvalidLocatorRun", serde_json::json!({})),
        ArchiveError::InvalidContractRun(_) => ("InvalidContractRun", serde_json::json!({})),
        ArchiveError::DocumentTooLarge {
            maximum, observed, ..
        } => (
            "DocumentTooLarge",
            serde_json::json!({"maximum": maximum, "observed": observed}),
        ),
        ArchiveError::DocumentPayloadMissing { key, .. } => {
            ("DocumentPayloadMissing", serde_json::json!({"key": key}))
        }
        ArchiveError::DocumentPayloadLengthMismatch {
            key,
            expected,
            observed,
            ..
        } => (
            "DocumentPayloadLengthMismatch",
            serde_json::json!({"key": key, "expected": expected, "observed": observed}),
        ),
        ArchiveError::DocumentPayloadDigestMismatch { key, .. } => (
            "DocumentPayloadDigestMismatch",
            serde_json::json!({"key": key}),
        ),
        ArchiveError::DocumentPayloadConflict { key, .. } => {
            ("DocumentPayloadConflict", serde_json::json!({"key": key}))
        }
        ArchiveError::DocumentPayloadCommitUncertain { key, .. } => (
            "DocumentPayloadCommitUncertain",
            serde_json::json!({"key": key}),
        ),
        ArchiveError::EvaluationSourcePayloadUnavailable { artifact, .. } => (
            "EvaluationSourcePayloadUnavailable",
            serde_json::json!({"artifact": artifact}),
        ),
        ArchiveError::InvalidWebCapture(_) => ("InvalidWebCapture", serde_json::json!({})),
        ArchiveError::InvalidCaptureBundle(_) => ("InvalidCaptureBundle", serde_json::json!({})),
        ArchiveError::CaptureRecordJson(_) => ("CaptureRecordJson", serde_json::json!({})),
        ArchiveError::CaptureIdentityMismatch {
            expected, found, ..
        } => (
            "CaptureIdentityMismatch",
            serde_json::json!({"expected": expected, "found": found}),
        ),
        ArchiveError::CapturePayloadCountExceeded {
            maximum, observed, ..
        } => (
            "CapturePayloadCountExceeded",
            serde_json::json!({"maximum": maximum, "observed": observed}),
        ),
        ArchiveError::CaptureMaterializationTooLarge {
            maximum, observed, ..
        } => (
            "CaptureMaterializationTooLarge",
            serde_json::json!({"maximum": maximum, "observed": observed}),
        ),
        ArchiveError::CapturePayloadMissing {
            capture_id,
            artifact_id,
            ..
        } => (
            "CapturePayloadMissing",
            serde_json::json!({"capture_id": capture_id, "artifact_id": artifact_id}),
        ),
        ArchiveError::CapturePayloadLengthMismatch {
            artifact,
            expected,
            observed,
            ..
        } => (
            "CapturePayloadLengthMismatch",
            serde_json::json!({"artifact": artifact, "expected": expected, "observed": observed}),
        ),
        ArchiveError::CapturePayloadDigestMismatch { artifact, .. } => (
            "CapturePayloadDigestMismatch",
            serde_json::json!({"artifact": artifact}),
        ),
        ArchiveError::CapturePayloadConflict {
            capture_id,
            artifact_id,
            ..
        } => (
            "CapturePayloadConflict",
            serde_json::json!({"capture_id": capture_id, "artifact_id": artifact_id}),
        ),
        ArchiveError::CapturePayloadCommitUncertain {
            capture_id,
            artifact_id,
            ..
        } => (
            "CapturePayloadCommitUncertain",
            serde_json::json!({"capture_id": capture_id, "artifact_id": artifact_id}),
        ),
        ArchiveError::EncodeRecord { kind, .. } => {
            ("EncodeRecord", serde_json::json!({"kind": kind}))
        }
        ArchiveError::MalformedEnvelope(_) => ("MalformedEnvelope", serde_json::json!({})),
        ArchiveError::InvalidRecordValue { kind, .. } => {
            ("InvalidRecordValue", serde_json::json!({"kind": kind}))
        }
        ArchiveError::InvalidLayout { reason, .. } => {
            ("InvalidLayout", serde_json::json!({"reason": reason}))
        }
        ArchiveError::UnsupportedFormat {
            found, supported, ..
        } => (
            "UnsupportedFormat",
            serde_json::json!({"found": found, "supported": supported}),
        ),
        ArchiveError::MigrationRequired {
            kind,
            found_schema,
            supported_schema,
            writer_package,
            writer_version,
            ..
        } => (
            "MigrationRequired",
            serde_json::json!({"kind": kind, "found_schema": found_schema, "supported_schema": supported_schema, "writer_package": writer_package, "writer_version": writer_version}),
        ),
        ArchiveError::WrongRecordKind {
            found, expected, ..
        } => (
            "WrongRecordKind",
            serde_json::json!({"found": found, "expected": expected}),
        ),
        ArchiveError::WrongRecordKey {
            found, expected, ..
        } => (
            "WrongRecordKey",
            serde_json::json!({"found": found, "expected": expected}),
        ),
        ArchiveError::IdentityConflict { kind, key, .. } => (
            "IdentityConflict",
            serde_json::json!({"kind": kind, "key": key}),
        ),
        ArchiveError::CommitUncertain { kind, key, .. } => (
            "CommitUncertain",
            serde_json::json!({"kind": kind, "key": key}),
        ),
    };
    let exception = failure(error, "yosoi::archive::ArchiveError", Some(variant));
    Python::attach(|py| {
        let value = exception.value(py);
        let sources: Vec<String> = value
            .getattr("source_chain")
            .and_then(|value| value.extract())
            .unwrap_or_default();
        errors::with_metadata(
            py,
            exception,
            "yosoi::archive::ArchiveError",
            Some(variant),
            details,
            &sources,
        )
    })
}

fn decode<T: DeserializeOwned>(value: &str) -> PyResult<T> {
    if u64::try_from(value.len()).unwrap_or(u64::MAX) > MAX_AUTOMATION_RECORD_BYTES {
        return Err(errors::ArchiveError::new_err(
            "Archive input exceeds 64 MiB",
        ));
    }
    serde_json::from_str(value).map_err(|error| failure(error, "serde_json::Error", Some("Decode")))
}

fn encode<T: Serialize>(value: &T) -> PyResult<String> {
    serde_json::to_string(value)
        .map_err(|error| failure(error, "serde_json::Error", Some("Serialize")))
}

fn record(value: &str) -> PyResult<AutomationRecord> {
    let value: AutomationRecord = decode(value)?;
    if value.version() != yosoi::automation_record::AUTOMATION_RECORD_VERSION {
        return Err(errors::ArchiveError::new_err(
            "unsupported automation record version",
        ));
    }
    let mut validated = AutomationRecord::new(
        value.id(),
        value.observations().to_vec(),
        value.operations().to_vec(),
    )
    .map_err(|error| {
        failure(
            error,
            "yosoi::automation_record::AutomationRecordError",
            None,
        )
    })?;
    if let Some(outcome) = value.flow_outcome() {
        validated = validated
            .with_flow_outcome(outcome.clone())
            .map_err(|error| {
                failure(
                    error,
                    "yosoi::automation_record::AutomationRecordError",
                    None,
                )
            })?;
    }
    if let Some(context) = value.context() {
        validated = validated.with_context(context.clone()).map_err(|error| {
            failure(
                error,
                "yosoi::automation_record::AutomationRecordError",
                None,
            )
        })?;
    }
    Ok(validated)
}

#[pyfunction]
fn validate_archive_ref(kind: &str, value: &str) -> PyResult<String> {
    match kind {
        "document" => value
            .parse::<DocumentArchiveRef>()
            .map(|reference| reference.to_string()),
        "plan" => value
            .parse::<PlanArchiveRef>()
            .map(|reference| reference.to_string()),
        _ => {
            return Err(errors::ArchiveError::new_err(
                "unsupported Archive reference kind",
            ));
        }
    }
    .map_err(|error| failure(error, "yosoi::archive::ArchiveRefError", None))
}

#[pyfunction]
fn validate_automation_record(py: Python<'_>, value: &str) -> PyResult<String> {
    py.detach(|| encode(&record(value)?))
}

#[pyfunction]
fn automation_record_from_flow(py: Python<'_>, id: &str, outcome: &str) -> PyResult<String> {
    py.detach(|| {
        let record = AutomationRecord::from_flow(id, decode(outcome)?).map_err(|error| {
            failure(
                error,
                "yosoi::automation_record::AutomationRecordError",
                None,
            )
        })?;
        encode(&record)
    })
}

#[pyfunction]
#[pyo3(signature = (observation, page_size=20, cursor=None))]
fn observation_view(
    py: Python<'_>,
    observation: &str,
    page_size: usize,
    cursor: Option<&str>,
) -> PyResult<String> {
    py.detach(|| {
        let observation = decode(observation)?;
        let view = if let Some(cursor) = cursor {
            let cursor: ViewCursor = decode(cursor)?;
            View::continue_from(&observation, &cursor)
        } else {
            View::from_observation(&observation, page_size)
        }
        .map_err(|error| failure(error, "yosoi::view::ViewError", None))?;
        encode(&view)
    })
}

#[pyclass(
    frozen,
    skip_from_py_object,
    module = "yosoi._native",
    name = "Archive"
)]
#[derive(Clone, Debug)]
pub struct NativeArchive {
    inner: Archive,
}

#[pymethods]
impl NativeArchive {
    #[staticmethod]
    fn open(py: Python<'_>, root: PathBuf) -> PyResult<Bound<'_, PyAny>> {
        async_runtime::bridge(py, None, move |_| async move {
            Archive::open(root)
                .await
                .map(|inner| Self { inner })
                .map_err(archive_error)
        })
    }

    #[getter]
    fn root(&self) -> PathBuf {
        self.inner.root().to_path_buf()
    }

    fn write_document<'py>(
        &self,
        py: Python<'py>,
        document: &NativeDocument,
    ) -> PyResult<Bound<'py, PyAny>> {
        let archive = self.inner.clone();
        let document = document.borrowed()?.to_owned();
        async_runtime::bridge(py, None, move |_| async move {
            archive
                .write_document(&document)
                .await
                .map(|reference| reference.to_string())
                .map_err(archive_error)
        })
    }

    fn read_document<'py>(&self, py: Python<'py>, reference: &str) -> PyResult<Bound<'py, PyAny>> {
        let reference: DocumentArchiveRef = reference
            .parse()
            .map_err(|error| failure(error, "yosoi::archive::ArchiveRefError", None))?;
        let archive = self.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            let document = archive
                .read_document(&reference)
                .await
                .map_err(archive_error)?;
            Ok(NativeDocument {
                source: DocumentSource::Owned(Arc::new(document)),
            })
        })
    }

    fn write_plan<'py>(&self, py: Python<'py>, plan: &NativePlan) -> PyResult<Bound<'py, PyAny>> {
        let archive = self.inner.clone();
        let plan = plan.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            archive
                .write(&plan)
                .await
                .map(|reference| reference.to_string())
                .map_err(archive_error)
        })
    }

    fn read_plan<'py>(&self, py: Python<'py>, reference: &str) -> PyResult<Bound<'py, PyAny>> {
        let reference: PlanArchiveRef = reference
            .parse()
            .map_err(|error| failure(error, "yosoi::archive::ArchiveRefError", None))?;
        let archive = self.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            let plan = archive.read(&reference).await.map_err(archive_error)?;
            encode(&plan)
        })
    }

    fn write_record<'py>(&self, py: Python<'py>, value: &str) -> PyResult<Bound<'py, PyAny>> {
        let record = py.detach(|| record(value))?;
        let archive = self.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            let reference = record.write_to(&archive).await.map_err(|error| {
                failure(
                    error,
                    "yosoi::automation_record::AutomationRecordError",
                    None,
                )
            })?;
            encode(&reference)
        })
    }

    fn read_record<'py>(&self, py: Python<'py>, reference: &str) -> PyResult<Bound<'py, PyAny>> {
        let reference: AutomationRecordRef = decode(reference)?;
        let archive = self.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            let record = AutomationRecord::read_from(&archive, &reference)
                .await
                .map_err(|error| {
                    failure(
                        error,
                        "yosoi::automation_record::AutomationRecordError",
                        None,
                    )
                })?;
            encode(&record)
        })
    }
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeArchive>()?;
    module.add_function(wrap_pyfunction!(validate_archive_ref, module)?)?;
    module.add_function(wrap_pyfunction!(validate_automation_record, module)?)?;
    module.add_function(wrap_pyfunction!(automation_record_from_flow, module)?)?;
    module.add_function(wrap_pyfunction!(observation_view, module)?)
}
