//! Owned video snapshots and PNG artifacts; decoding stays in the Rust provider.

use std::error::Error;
use std::{path::PathBuf, sync::Arc};

use pyo3::{create_exception, exceptions::PyTypeError, prelude::*, types::PyBytes};
use tokio::sync::Mutex;
use yosoi::documents::FileDocument;
use yosoi::surface::{SurfaceConnection, model::SurfaceRead, video};

use super::{decode, encode};
use crate::{archive::NativeArchive, async_runtime, errors, media::NativeFileDocument};

create_exception!(_native, VideoError, super::SurfaceError);

fn failure(error: video::VideoError) -> PyErr {
    let (variant, details) = match &error {
        video::VideoError::Io(error) => (
            "Io",
            serde_json::json!({"message":error.to_string(),"kind":format!("{:?}",error.kind()),"raw_os_error":error.raw_os_error()}),
        ),
        video::VideoError::Invalid(message) => ("Invalid", serde_json::json!({"message":message})),
        video::VideoError::Limit(limit) => ("Limit", serde_json::json!({"limit":limit})),
        video::VideoError::Tool(message) => ("Tool", serde_json::json!({"message":message})),
        video::VideoError::Cancelled => ("Cancelled", serde_json::json!({})),
        video::VideoError::Timeout => ("Timeout", serde_json::json!({})),
        video::VideoError::NoFrameAtOrAfter { requested_us } => (
            "NoFrameAtOrAfter",
            serde_json::json!({"requested_us": requested_us}),
        ),
        video::VideoError::Surface(error) => {
            let (variant, details) = super::details(error);
            (
                "Surface",
                serde_json::json!({"surface":{"variant":variant,"details":details}}),
            )
        }
    };
    let mut source_chain = Vec::new();
    let mut source = error.source();
    while let Some(value) = source {
        source_chain.push(value.to_string());
        source = value.source();
    }
    let message = error.to_string();
    drop(error);
    Python::attach(|py| {
        errors::with_metadata(
            py,
            VideoError::new_err(message),
            "yosoi::surface::video::VideoError",
            Some(variant),
            details,
            &source_chain,
        )
    })
}

#[pyclass(frozen, module = "yosoi._native", name = "VideoSurface")]
#[derive(Debug)]
pub struct NativeVideoSurface {
    inner: video::VideoSurface,
}

#[pymethods]
impl NativeVideoSurface {
    #[staticmethod]
    #[pyo3(signature = (document, policy, cancellation=None))]
    fn from_document<'py>(
        py: Python<'py>,
        document: &NativeFileDocument,
        policy: &str,
        cancellation: Option<&async_runtime::NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let FileDocument::Video(document) = document.inner.as_ref() else {
            return Err(PyTypeError::new_err("expected VideoDocument"));
        };
        let document = document.clone();
        let policy = decode(policy)?;
        async_runtime::bridge(py, cancellation, move |token| async move {
            video::VideoSurface::from_document_cancellable(&document, policy, &token)
                .await
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }
    #[staticmethod]
    #[pyo3(signature = (path, policy, cancellation=None))]
    fn open<'py>(
        py: Python<'py>,
        path: PathBuf,
        policy: &str,
        cancellation: Option<&async_runtime::NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = decode(policy)?;
        async_runtime::bridge(py, cancellation, move |token| async move {
            video::VideoSurface::open_cancellable(path, policy, &token)
                .await
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }
    fn descriptor(&self) -> PyResult<String> {
        encode(self.inner.descriptor())
    }
    fn source_document(&self) -> Option<NativeFileDocument> {
        self.inner
            .source_document()
            .map(|document| NativeFileDocument::new(FileDocument::Video(document.clone())))
    }
    fn observation(&self) -> PyResult<String> {
        encode(self.inner.observation())
    }
    fn root_reference(&self) -> PyResult<String> {
        encode(&self.inner.root_reference())
    }
    fn metadata(&self) -> PyResult<String> {
        encode(self.inner.metadata())
    }
    fn policy(&self) -> PyResult<String> {
        encode(self.inner.policy())
    }
    fn at(&self, position_us: u64) -> PyResult<String> {
        encode(&self.inner.at(position_us).map_err(failure)?)
    }
    fn read(&self, py: Python<'_>, request: &str) -> PyResult<String> {
        let request = decode(request)?;
        py.detach(|| encode(&self.inner.read(&request).map_err(super::failure)?))
    }
    #[pyo3(signature = (reference, cancellation=None))]
    fn frame<'py>(
        &self,
        py: Python<'py>,
        reference: &str,
        cancellation: Option<&async_runtime::NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let reference = decode(reference)?;
        let inner = self.inner.clone();
        async_runtime::bridge(py, cancellation, move |token| async move {
            inner
                .frame_cancellable(&reference, &token)
                .await
                .map(|inner| NativeDecodedFrame { inner })
                .map_err(failure)
        })
    }
    #[pyo3(signature = (reference, rect, cancellation=None))]
    fn crop<'py>(
        &self,
        py: Python<'py>,
        reference: &str,
        rect: &str,
        cancellation: Option<&async_runtime::NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let reference = decode(reference)?;
        let rect = decode(rect)?;
        let inner = self.inner.clone();
        async_runtime::bridge(py, cancellation, move |token| async move {
            inner
                .crop_cancellable(&reference, rect, &token)
                .await
                .map(|inner| NativeDecodedFrame { inner })
                .map_err(failure)
        })
    }
    fn write_to<'py>(
        &self,
        py: Python<'py>,
        archive: &NativeArchive,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        let archive = archive.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            encode(&inner.write_to(&archive).await.map_err(failure)?)
        })
    }
    #[staticmethod]
    fn read_from<'py>(
        py: Python<'py>,
        archive: &NativeArchive,
        reference: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let reference = decode(reference)?;
        let archive = archive.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            video::VideoSurface::read_from(&archive, &reference)
                .await
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "DecodedFrame")]
#[derive(Debug)]
pub struct NativeDecodedFrame {
    inner: video::DecodedFrame,
}

#[pymethods]
impl NativeDecodedFrame {
    fn pixel_artifact(&self) -> PyResult<Option<super::NativePixelArtifact>> {
        self.inner
            .pixel_artifact()
            .map(|value| value.map(|inner| super::NativePixelArtifact { inner }))
            .map_err(failure)
    }
    fn info(&self) -> PyResult<String> {
        encode(&self.inner.info)
    }
    fn png<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.png)
    }
    fn write_to<'py>(
        &self,
        py: Python<'py>,
        archive: &NativeArchive,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        let archive = archive.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            encode(&inner.write_to(&archive).await.map_err(failure)?)
        })
    }
    #[staticmethod]
    fn read_from<'py>(
        py: Python<'py>,
        archive: &NativeArchive,
        reference: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let reference = decode(reference)?;
        let archive = archive.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            video::DecodedFrame::read_from(&archive, &reference)
                .await
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeVideoSession>()?;
    module.add("VideoError", module.py().get_type::<VideoError>())?;
    module.add_class::<NativeVideoSurface>()?;
    module.add_class::<NativeDecodedFrame>()
}

#[pyclass(frozen, module = "yosoi._native", name = "VideoSession")]
#[derive(Debug)]
pub struct NativeVideoSession {
    inner: Arc<Mutex<video::VideoSession>>,
}

#[pymethods]
impl NativeVideoSession {
    #[staticmethod]
    #[pyo3(signature = (path, policy, max_side, cancellation=None))]
    fn open<'py>(
        py: Python<'py>,
        path: PathBuf,
        policy: &str,
        max_side: u32,
        cancellation: Option<&async_runtime::NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = decode(policy)?;
        async_runtime::bridge(py, cancellation, move |token| async move {
            video::VideoSession::open_cancellable(path, policy, max_side, &token)
                .await
                .map(|inner| Self {
                    inner: Arc::new(Mutex::new(inner)),
                })
                .map_err(super::connection::failure)
        })
    }

    fn ready<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        async_runtime::bridge(py, None, move |_| async move {
            encode(
                &inner
                    .lock()
                    .await
                    .ready()
                    .map_err(super::connection::failure)?,
            )
        })
    }

    #[pyo3(signature = (command, cancellation=None))]
    fn execute<'py>(
        &self,
        py: Python<'py>,
        command: &str,
        cancellation: Option<&async_runtime::NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let command = decode(command)?;
        let inner = Arc::clone(&self.inner);
        async_runtime::bridge(py, cancellation, move |token| async move {
            encode(
                &inner
                    .lock()
                    .await
                    .execute_cancellable(command, &token)
                    .await
                    .map_err(super::connection::failure)?,
            )
        })
    }

    fn outcome<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        async_runtime::bridge(py, None, move |_| async move {
            encode(&inner.lock().await.outcome())
        })
    }

    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = Arc::clone(&self.inner);
        async_runtime::bridge(py, None, move |_| async move {
            encode(
                &inner
                    .lock()
                    .await
                    .close()
                    .await
                    .map_err(super::connection::failure)?,
            )
        })
    }
}
