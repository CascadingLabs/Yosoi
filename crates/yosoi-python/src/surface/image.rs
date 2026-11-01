//! Checked image construction, resource helpers and the existing image connection.

use super::{NativePixelArtifact, NativeSurface, decode, encode, failure};
use crate::{async_runtime, media::NativeFileDocument};
use pyo3::prelude::*;
use std::{path::PathBuf, sync::Arc};
use tokio::sync::Mutex;
use yosoi::{
    documents::{FileDocument, ImageDocument},
    surface::{self, SurfaceConnection},
};

pub(super) fn document(value: &NativeFileDocument) -> PyResult<ImageDocument> {
    match value.inner.as_ref() {
        FileDocument::Image(document) => Ok(document.clone()),
        _ => Err(failure(surface::SurfaceError::Invalid(
            "image operation requires an ImageDocument".into(),
        ))),
    }
}

#[pyfunction]
fn surface_index_pixel_artifact(
    py: Python<'_>,
    artifact: &NativePixelArtifact,
    tile_side: u32,
    limits: &str,
    pixel_limits: &str,
) -> PyResult<NativeSurface> {
    let limits = decode(limits)?;
    let pixel_limits = decode(pixel_limits)?;
    py.detach(|| {
        surface::Surface::from_pixel_artifact_with_pixel_limits(
            &artifact.inner,
            tile_side,
            limits,
            pixel_limits,
        )
        .map(|inner| NativeSurface { inner })
        .map_err(failure)
    })
}

#[pyfunction]
fn surface_image_source_identity(value: &NativeFileDocument) -> PyResult<String> {
    surface::image_source_identity(&document(value)?).map_err(failure)
}

#[pyfunction]
fn surface_pixel_source_identity(source: &str) -> PyResult<String> {
    surface::pixel_source_identity(&decode(source)?).map_err(failure)
}

#[pyfunction]
fn surface_resize_transform(
    parent: &NativePixelArtifact,
    operation: &str,
    width: u32,
    height: u32,
) -> PyResult<String> {
    encode(
        &surface::pixels::resize_transform(&parent.inner, decode(operation)?, width, height)
            .map_err(failure)?,
    )
}

#[pyfunction]
fn surface_pixel_limits_validate(limits: &str) -> PyResult<String> {
    let limits: surface::PixelLimits = decode(limits)?;
    encode(&limits.validate().map_err(failure)?)
}

#[pyfunction]
fn surface_pixel_limits_check_pixels(limits: &str, width: u32, height: u32) -> PyResult<u64> {
    let limits: surface::PixelLimits = decode(limits)?;
    limits.check_pixels(width, height).map_err(failure)
}

#[pyfunction]
fn surface_pixel_limits_check_output(
    limits: &str,
    width: u32,
    height: u32,
    bytes: usize,
) -> PyResult<()> {
    let limits: surface::PixelLimits = decode(limits)?;
    limits.check_output(width, height, bytes).map_err(failure)
}

#[pyfunction]
#[pyo3(signature = (key, document, tile_side, surface=None))]
fn surface_source_image(
    key: &str,
    document: &NativeFileDocument,
    tile_side: u32,
    surface: Option<&NativeSurface>,
) -> PyResult<String> {
    encode(&surface::ArchivedSource::new_image(
        key,
        &self::document(document)?,
        tile_side,
        surface.map(|value| &value.inner),
    ))
}

#[pyclass(frozen, module = "yosoi._native", name = "ImageSession")]
#[derive(Debug)]
struct NativeImageSession {
    inner: Arc<Mutex<surface::ImageSession>>,
}

#[pymethods]
impl NativeImageSession {
    #[staticmethod]
    fn open<'py>(
        py: Python<'py>,
        path: PathBuf,
        policy: &str,
        tile_side: u32,
        limits: &str,
        pixel_limits: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = decode(policy)?;
        let limits = decode(limits)?;
        let pixel_limits = decode(pixel_limits)?;
        async_runtime::bridge(py, None, move |_| async move {
            surface::ImageSession::open(path, policy, tile_side, limits, pixel_limits)
                .await
                .map(|inner| Self {
                    inner: Arc::new(Mutex::new(inner)),
                })
                .map_err(super::connection::failure)
        })
    }

    #[staticmethod]
    fn open_pixel_artifact<'py>(
        py: Python<'py>,
        reference: &str,
        archive_root: PathBuf,
        policy: &str,
        tile_side: u32,
        limits: &str,
        pixel_limits: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let reference = decode(reference)?;
        let policy = decode(policy)?;
        let limits = decode(limits)?;
        let pixel_limits = decode(pixel_limits)?;
        async_runtime::bridge(py, None, move |_| async move {
            surface::ImageSession::open_pixel_artifact(
                &reference,
                archive_root,
                policy,
                tile_side,
                limits,
                pixel_limits,
            )
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

    fn execute<'py>(&self, py: Python<'py>, command: &str) -> PyResult<Bound<'py, PyAny>> {
        let command = decode(command)?;
        let inner = Arc::clone(&self.inner);
        async_runtime::bridge(py, None, move |_| async move {
            encode(
                &inner
                    .lock()
                    .await
                    .execute(command)
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

pub(super) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeImageSession>()?;
    module.add_function(wrap_pyfunction!(surface_index_pixel_artifact, module)?)?;
    module.add_function(wrap_pyfunction!(surface_image_source_identity, module)?)?;
    module.add_function(wrap_pyfunction!(surface_pixel_source_identity, module)?)?;
    module.add_function(wrap_pyfunction!(surface_resize_transform, module)?)?;
    module.add_function(wrap_pyfunction!(surface_pixel_limits_validate, module)?)?;
    module.add_function(wrap_pyfunction!(surface_pixel_limits_check_pixels, module)?)?;
    module.add_function(wrap_pyfunction!(surface_pixel_limits_check_output, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_image, module)?)?;
    Ok(())
}
