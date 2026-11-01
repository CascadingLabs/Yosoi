//! Thin ownership and JSON conversion boundary over the Rust Surface SDK.

#[cfg(any(feature = "browser", feature = "surface-video"))]
use pyo3::types::PyBytes;
use pyo3::{create_exception, prelude::*};
use serde::{Serialize, de::DeserializeOwned};
use yosoi::{
    documents::FileDocument,
    surface::{self, model::SurfaceRead},
};

use crate::media::NativeFileDocument;
#[cfg(any(feature = "browser", feature = "surface-video"))]
use crate::{
    archive::{NativeArchive, archive_error},
    async_runtime,
};
use crate::{
    documents::{DocumentSource, NativeDocument},
    errors,
};
use std::sync::Arc;

#[cfg(feature = "browser")]
mod browser;
#[cfg(any(feature = "browser", feature = "surface-video"))]
mod connection;
#[cfg(any(feature = "browser", feature = "surface-video"))]
mod image;
mod session;
#[cfg(feature = "surface-video")]
mod video;

create_exception!(_native, SurfaceError, errors::YosoiError);

fn details(error: &surface::SurfaceError) -> (&'static str, serde_json::Value) {
    match error {
        surface::SurfaceError::Invalid(message) => {
            ("Invalid", serde_json::json!({"message":message}))
        }
        surface::SurfaceError::Parse(message) => ("Parse", serde_json::json!({"message":message})),
        surface::SurfaceError::Limit(limit) => ("Limit", serde_json::json!({"limit":limit})),
        surface::SurfaceError::WrongCapture => ("WrongCapture", serde_json::json!({})),
        surface::SurfaceError::Unknown => ("Unknown", serde_json::json!({})),
        surface::SurfaceError::BudgetTooSmall => ("BudgetTooSmall", serde_json::json!({})),
        surface::SurfaceError::Detached => ("Detached", serde_json::json!({})),
        surface::SurfaceError::HotOwned => ("HotOwned", serde_json::json!({})),
        surface::SurfaceError::ReaderOnly => ("ReaderOnly", serde_json::json!({})),
        surface::SurfaceError::ActionInFlight => ("ActionInFlight", serde_json::json!({})),
        surface::SurfaceError::Stale => ("Stale", serde_json::json!({})),
        surface::SurfaceError::Uncertain => ("Uncertain", serde_json::json!({})),
        surface::SurfaceError::Poisoned => ("Poisoned", serde_json::json!({})),
    }
}

fn failure(error: surface::SurfaceError) -> PyErr {
    let (variant, details) = details(&error);
    let message = error.to_string();
    drop(error);
    Python::attach(|py| {
        errors::with_metadata(
            py,
            SurfaceError::new_err(message),
            "yosoi::surface::SurfaceError",
            Some(variant),
            details,
            &[],
        )
    })
}

fn decode<T: DeserializeOwned>(value: &str) -> PyResult<T> {
    serde_json::from_str(value)
        .map_err(|error| failure(surface::SurfaceError::Invalid(error.to_string())))
}

pub fn validate_identity<T>(value: &str) -> PyResult<String>
where
    T: TryFrom<String, Error = surface::SurfaceError> + Serialize,
{
    encode(&T::try_from(decode::<String>(value)?).map_err(failure)?)
}

fn encode<T: Serialize>(value: &T) -> PyResult<String> {
    serde_json::to_string(value)
        .map_err(|error| failure(surface::SurfaceError::Parse(error.to_string())))
}

#[pyclass(
    frozen,
    module = "yosoi._native",
    name = "Surface",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct NativeSurface {
    pub(crate) inner: surface::Surface,
}

#[pymethods]
impl NativeSurface {
    #[new]
    fn new(py: Python<'_>, document: &NativeDocument, limits: &str) -> PyResult<Self> {
        let limits = decode(limits)?;
        let document = document.borrowed()?.to_owned();
        py.detach(|| {
            surface::Surface::with_limits(&document, limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    fn metadata(&self) -> PyResult<String> {
        encode(
            &serde_json::json!({"identity": self.inner.identity(), "representation": self.inner.representation(),
            "source_bytes": self.inner.source_bytes(), "node_count": self.inner.node_count(),
            "coverage": self.inner.coverage(), "root": self.inner.root()}),
        )
    }

    #[pyo3(signature = (operation, reference, query, continuation, budget))]
    fn read(
        &self,
        py: Python<'_>,
        operation: &str,
        reference: Option<&str>,
        query: &str,
        continuation: Option<&str>,
        budget: &str,
    ) -> PyResult<String> {
        let reference: Option<surface::Reference> = reference.map(decode).transpose()?;
        let continuation: Option<surface::Continuation> = continuation.map(decode).transpose()?;
        let budget = decode(budget)?;
        let target = || {
            reference.as_ref().ok_or_else(|| {
                failure(surface::SurfaceError::Invalid(
                    "reference is required".into(),
                ))
            })
        };
        py.detach(|| match operation {
            "overview" => encode(
                &self
                    .inner
                    .overview(continuation.as_ref(), budget)
                    .map_err(failure)?,
            ),
            "find" => encode(
                &self
                    .inner
                    .find(query, continuation.as_ref(), budget)
                    .map_err(failure)?,
            ),
            "expand" => encode(
                &self
                    .inner
                    .expand(target()?, continuation.as_ref(), budget)
                    .map_err(failure)?,
            ),
            "inspect" => encode(
                &self
                    .inner
                    .inspect(target()?, continuation.as_ref(), budget)
                    .map_err(failure)?,
            ),
            "parent" => encode(&self.inner.parent(target()?).map_err(failure)?),
            "coordinate" => encode(&self.inner.coordinate(target()?).map_err(failure)?),
            "source_reference" => encode(&self.inner.source_reference(target()?).map_err(failure)?),
            "validate" => self
                .inner
                .validate(target()?)
                .map_err(failure)
                .and_then(|()| encode(&())),
            _ => Err(failure(surface::SurfaceError::Invalid(
                "unsupported index operation".into(),
            ))),
        })
    }

    #[pyo3(signature = (source, policy=None))]
    fn web(&self, source: &str, policy: Option<&str>) -> PyResult<NativeWebSurface> {
        let source = surface::model::SourceId::new(source).map_err(failure)?;
        let policy = policy.map(decode).transpose()?.unwrap_or_default();
        surface::browser::WebSurface::with_policy(self.inner.clone(), source, policy)
            .map(|inner| NativeWebSurface { inner })
            .map_err(failure)
    }
    #[staticmethod]
    fn with_policy(py: Python<'_>, document: &NativeDocument, policies: &str) -> PyResult<Self> {
        let policies = decode(policies)?;
        let document = document.borrowed()?.to_owned();
        py.detach(|| {
            surface::Surface::with_policy(&document, &policies)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[staticmethod]
    fn combine(
        py: Python<'_>,
        scope: &str,
        views: Vec<(String, PyRef<'_, Self>)>,
        limits: &str,
    ) -> PyResult<Self> {
        let limits = decode(limits)?;
        let views = views
            .into_iter()
            .map(|(name, value)| (name, value.inner.clone()))
            .collect();
        py.detach(|| {
            surface::Surface::combine(scope, views, limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    fn view(&self, name: &str) -> Option<Self> {
        self.inner.view(name).map(|inner| Self { inner })
    }

    fn project(&self, name: &str, reference: &str) -> PyResult<String> {
        encode(
            &self
                .inner
                .project(name, &decode(reference)?)
                .map_err(failure)?,
        )
    }
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    #[staticmethod]
    fn from_image(py: Python<'_>, bytes: &[u8], tile_side: u32, limits: &str) -> PyResult<Self> {
        let limits = decode(limits)?;
        py.detach(|| {
            surface::Surface::from_image(bytes, tile_side, limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    #[staticmethod]
    fn from_image_with_pixel_limits(
        py: Python<'_>,
        bytes: &[u8],
        tile_side: u32,
        limits: &str,
        pixel_limits: &str,
    ) -> PyResult<Self> {
        let limits = decode(limits)?;
        let pixel_limits = decode(pixel_limits)?;
        py.detach(|| {
            surface::Surface::from_image_with_pixel_limits(bytes, tile_side, limits, pixel_limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    #[staticmethod]
    #[pyo3(signature = (document, tile_side, limits, pixel_limits))]
    fn from_image_document(
        py: Python<'_>,
        document: &NativeFileDocument,
        tile_side: u32,
        limits: &str,
        pixel_limits: &str,
    ) -> PyResult<Self> {
        let document = match document.inner.as_ref() {
            FileDocument::Image(image) => image.clone(),
            _ => {
                return Err(failure(surface::SurfaceError::Invalid(
                    "from_image_document requires an ImageDocument".into(),
                )));
            }
        };
        let limits = decode(limits)?;
        let pixel_limits = decode(pixel_limits)?;
        py.detach(|| {
            surface::Surface::from_image_document_with_pixel_limits(
                &document,
                tile_side,
                limits,
                pixel_limits,
            )
            .map(|inner| Self { inner })
            .map_err(failure)
        })
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    fn direct_image(&self) -> PyResult<NativePixelArtifact> {
        self.inner
            .direct_image()
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    fn overview_image(&self, max_side: u32) -> PyResult<NativePixelArtifact> {
        self.inner
            .overview_image(max_side)
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    fn resize_image(&self, width: u32, height: u32) -> PyResult<NativePixelArtifact> {
        self.inner
            .resize_image(width, height)
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    fn crop(
        &self,
        py: Python<'_>,
        reference: &str,
        max_png_bytes: usize,
    ) -> PyResult<(String, NativePixelArtifact)> {
        let reference = decode(reference)?;
        let crop = py.detach(|| self.inner.crop(&reference, max_png_bytes).map_err(failure))?;
        let info = encode(&serde_json::json!({
            "reference": crop.reference,
            "rect": crop.rect,
        }))?;
        Ok((
            info,
            NativePixelArtifact {
                inner: crop.artifact,
            },
        ))
    }

    #[cfg(any(feature = "browser", feature = "surface-video"))]
    fn crop_rect(
        &self,
        py: Python<'_>,
        rect: &str,
        max_png_bytes: usize,
    ) -> PyResult<(String, NativePixelArtifact)> {
        let rect = decode(rect)?;
        let crop = py.detach(|| self.inner.crop_image(rect, max_png_bytes).map_err(failure))?;
        let info = encode(&serde_json::json!({
            "reference": crop.reference,
            "rect": crop.rect,
        }))?;
        Ok((
            info,
            NativePixelArtifact {
                inner: crop.artifact,
            },
        ))
    }
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pyclass(
    frozen,
    module = "yosoi._native",
    name = "PixelArtifact",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct NativePixelArtifact {
    inner: surface::PixelArtifact,
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pymethods]
impl NativePixelArtifact {
    #[staticmethod]
    fn from_image_document_with_dimensions(
        py: Python<'_>,
        document: &NativeFileDocument,
        width: u32,
        height: u32,
        orientation: &str,
    ) -> PyResult<Self> {
        let document = image::document(document)?;
        let orientation = decode(orientation)?;
        py.detach(move || {
            surface::PixelArtifact::from_image_document(document, width, height, orientation)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[staticmethod]
    fn from_raster_document(
        py: Python<'_>,
        document: &NativeFileDocument,
        source: &str,
        coordinate_space: &str,
    ) -> PyResult<Self> {
        let document = image::document(document)?;
        let source = decode(source)?;
        let coordinate_space = decode(coordinate_space)?;
        py.detach(move || {
            surface::PixelArtifact::from_raster_document(document, source, coordinate_space)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[staticmethod]
    fn crop_from(
        py: Python<'_>,
        parent: &Self,
        document: &NativeFileDocument,
        rect: &str,
    ) -> PyResult<Self> {
        let document = image::document(document)?;
        let rect = decode(rect)?;
        py.detach(|| {
            surface::PixelArtifact::crop_from(&parent.inner, document, rect)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[staticmethod]
    fn resize_from(
        py: Python<'_>,
        parent: &Self,
        document: &NativeFileDocument,
        operation: &str,
        width: u32,
        height: u32,
    ) -> PyResult<Self> {
        let document = image::document(document)?;
        let operation = decode(operation)?;
        py.detach(|| {
            surface::PixelArtifact::resize_from(&parent.inner, document, operation, width, height)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    fn source_identity(&self) -> PyResult<String> {
        self.inner.source_identity().map_err(failure)
    }

    fn validate(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.inner.validate().map_err(failure))
    }

    #[staticmethod]
    fn from_image_document(
        py: Python<'_>,
        document: &NativeFileDocument,
        limits: &str,
    ) -> PyResult<Self> {
        let document = match document.inner.as_ref() {
            FileDocument::Image(image) => image.clone(),
            _ => {
                return Err(failure(surface::SurfaceError::Invalid(
                    "PixelArtifact requires an ImageDocument".into(),
                )));
            }
        };
        let limits = decode(limits)?;
        py.detach(|| {
            surface::PixelArtifact::decode_image_document(document, limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    fn info(&self) -> PyResult<String> {
        encode(self.inner.info())
    }

    fn bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.bytes())
    }

    fn matches(&self, info: &str, bytes: &[u8]) -> PyResult<bool> {
        let info: surface::PixelArtifactInfo = decode(info)?;
        Ok(self.inner.info() == &info && self.inner.bytes() == bytes)
    }

    fn document(&self) -> NativeFileDocument {
        NativeFileDocument::new(FileDocument::Image(self.inner.document().clone()))
    }

    fn map_rect_to_source(&self, rect: &str) -> PyResult<String> {
        encode(
            &self
                .inner
                .map_rect_to_source(decode(rect)?)
                .map_err(failure)?,
        )
    }

    fn write_to<'py>(
        &self,
        py: Python<'py>,
        archive: &NativeArchive,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        let archive = archive.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            encode(&inner.write_to(&archive).await.map_err(archive_error)?)
        })
    }

    #[staticmethod]
    fn read_from<'py>(
        py: Python<'py>,
        archive: &NativeArchive,
        reference: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let reference: surface::pixels::PixelArtifactArchiveRef = decode(reference)?;
        let archive = archive.inner.clone();
        async_runtime::bridge(py, None, move |_| async move {
            surface::PixelArtifact::read_from(&archive, &reference)
                .await
                .map(|inner| Self { inner })
                .map_err(archive_error)
        })
    }
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pyclass(
    frozen,
    module = "yosoi._native",
    name = "ImageSurface",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct NativeImageSurface {
    inner: surface::ImageSurface,
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pymethods]
impl NativeImageSurface {
    fn index(&self) -> NativeSurface {
        NativeSurface {
            inner: self.inner.index().clone(),
        }
    }

    fn source_document(&self) -> NativeFileDocument {
        NativeFileDocument::new(FileDocument::Image(self.inner.source_document().clone()))
    }

    #[staticmethod]
    fn from_image_document(
        py: Python<'_>,
        document: &NativeFileDocument,
        tile_side: u32,
        limits: &str,
        pixel_limits: &str,
    ) -> PyResult<Self> {
        let document = match document.inner.as_ref() {
            FileDocument::Image(image) => image.clone(),
            _ => {
                return Err(failure(surface::SurfaceError::Invalid(
                    "ImageSurface requires an ImageDocument".into(),
                )));
            }
        };
        let limits = decode(limits)?;
        let pixel_limits = decode(pixel_limits)?;
        py.detach(|| {
            surface::ImageSurface::from_image_document(&document, tile_side, limits, pixel_limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    #[staticmethod]
    fn from_pixel_artifact(
        py: Python<'_>,
        artifact: &NativePixelArtifact,
        tile_side: u32,
        limits: &str,
        pixel_limits: &str,
    ) -> PyResult<Self> {
        let artifact = artifact.inner.clone();
        let limits = decode(limits)?;
        let pixel_limits = decode(pixel_limits)?;
        py.detach(move || {
            surface::ImageSurface::from_pixel_artifact(&artifact, tile_side, limits, pixel_limits)
                .map(|inner| Self { inner })
                .map_err(failure)
        })
    }

    fn descriptor(&self) -> PyResult<String> {
        encode(self.inner.descriptor())
    }

    fn observation(&self) -> PyResult<String> {
        encode(self.inner.observation())
    }

    fn root_reference(&self) -> PyResult<String> {
        encode(&self.inner.root_reference())
    }

    fn read(&self, py: Python<'_>, request: &str) -> PyResult<String> {
        let request = decode(request)?;
        py.detach(|| encode(&self.inner.read(&request).map_err(failure)?))
    }

    fn reference(&self, reference: &str) -> PyResult<String> {
        encode(&self.inner.reference(&decode(reference)?).map_err(failure)?)
    }

    fn native_reference(&self, reference: &str) -> PyResult<String> {
        encode(
            &self
                .inner
                .native_reference(&decode(reference)?)
                .map_err(failure)?,
        )
    }

    fn source_artifact(&self) -> NativePixelArtifact {
        NativePixelArtifact {
            inner: self.inner.source_artifact().clone(),
        }
    }

    fn direct_image(&self) -> PyResult<NativePixelArtifact> {
        self.inner
            .direct_image()
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    }

    fn overview_image(&self, max_side: u32) -> PyResult<NativePixelArtifact> {
        self.inner
            .overview_image(max_side)
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    }

    fn resize_image(&self, width: u32, height: u32) -> PyResult<NativePixelArtifact> {
        self.inner
            .resize_image(width, height)
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    }

    fn crop(
        &self,
        py: Python<'_>,
        reference: &str,
        max_png_bytes: usize,
    ) -> PyResult<(String, NativePixelArtifact)> {
        let reference = decode(reference)?;
        let crop = py.detach(|| self.inner.crop(&reference, max_png_bytes).map_err(failure))?;
        let info = encode(&serde_json::json!({
            "reference": crop.reference,
            "rect": crop.rect,
        }))?;
        Ok((
            info,
            NativePixelArtifact {
                inner: crop.artifact,
            },
        ))
    }

    fn crop_rect(
        &self,
        py: Python<'_>,
        rect: &str,
        max_png_bytes: usize,
    ) -> PyResult<(String, NativePixelArtifact)> {
        let rect = decode(rect)?;
        let crop = py.detach(|| self.inner.crop_rect(rect, max_png_bytes).map_err(failure))?;
        let info = encode(&serde_json::json!({
            "reference": crop.reference,
            "rect": crop.rect,
        }))?;
        Ok((
            info,
            NativePixelArtifact {
                inner: crop.artifact,
            },
        ))
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "WebSurface")]
#[derive(Debug)]
pub struct NativeWebSurface {
    inner: surface::browser::WebSurface,
}

#[pymethods]
impl NativeWebSurface {
    fn descriptor(&self) -> PyResult<String> {
        encode(self.inner.descriptor())
    }
    fn observation(&self) -> PyResult<String> {
        encode(self.inner.observation())
    }
    fn root_reference(&self) -> PyResult<String> {
        encode(&self.inner.root_reference())
    }
    fn read(&self, py: Python<'_>, request: &str) -> PyResult<String> {
        let request = decode(request)?;
        py.detach(|| encode(&self.inner.read(&request).map_err(failure)?))
    }
    fn reference(&self, reference: &str) -> PyResult<String> {
        encode(&self.inner.reference(&decode(reference)?).map_err(failure)?)
    }
    fn native_reference(&self, reference: &str) -> PyResult<String> {
        encode(
            &self
                .inner
                .native_reference(&decode(reference)?)
                .map_err(failure)?,
        )
    }
}

#[pyfunction]
fn surface_network_policy_validate(value: &str) -> PyResult<()> {
    let policy: surface::NetworkObservationPolicy = decode(value)?;
    policy.validate().map_err(failure)
}

#[pyfunction]
fn surface_network_policy_retention(value: &str) -> PyResult<String> {
    let policy: surface::NetworkObservationPolicy = decode(value)?;
    encode(&policy.retention())
}

#[pyfunction]
fn surface_network_window_validate(value: &str) -> PyResult<()> {
    let window: surface::NetworkWindow = decode(value)?;
    window.validate().map_err(failure)
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(surface_network_policy_validate, module)?)?;
    module.add_function(wrap_pyfunction!(surface_network_policy_retention, module)?)?;
    module.add_function(wrap_pyfunction!(surface_network_window_validate, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_new, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_file_document, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_capture, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_restore, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_restore_image, module)?)?;
    module.add_function(wrap_pyfunction!(
        surface_source_restore_file_document,
        module
    )?)?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    module.add_function(wrap_pyfunction!(
        surface_source_restore_pixel_artifact,
        module
    )?)?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    module.add_function(wrap_pyfunction!(surface_source_pixel_artifact, module)?)?;
    module.add_function(wrap_pyfunction!(surface_source_restore_surface, module)?)?;
    module.add_function(wrap_pyfunction!(surface_outcome_new, module)?)?;
    module.add_function(wrap_pyfunction!(surface_outcome_with_source, module)?)?;
    module.add_function(wrap_pyfunction!(surface_outcome_validate, module)?)?;
    module.add_function(wrap_pyfunction!(surface_outcome_restore, module)?)?;
    module.add_function(wrap_pyfunction!(surface_outcome_source_document, module)?)?;
    module.add_function(wrap_pyfunction!(
        surface_outcome_source_file_document,
        module
    )?)?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    module.add_function(wrap_pyfunction!(
        surface_outcome_source_pixel_artifact,
        module
    )?)?;
    module.add("SurfaceError", module.py().get_type::<SurfaceError>())?;
    module.add_class::<NativeSurface>()?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    module.add_class::<NativePixelArtifact>()?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    module.add_class::<NativeImageSurface>()?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    image::register(module)?;
    module.add_class::<NativeWebSurface>()?;
    module.add("surface_video_enabled", cfg!(feature = "surface-video"))?;
    module.add("surface_browser_enabled", cfg!(feature = "browser"))?;
    module.add(
        "surface_archive_enabled",
        cfg!(any(feature = "browser", feature = "surface-video")),
    )?;
    #[cfg(feature = "browser")]
    browser::register(module)?;
    #[cfg(any(feature = "browser", feature = "surface-video"))]
    connection::register(module)?;
    session::register(module)?;
    #[cfg(feature = "surface-video")]
    video::register(module)?;
    Ok(())
}

#[pyfunction]
fn surface_outcome_validate(py: Python<'_>, value: &str) -> PyResult<()> {
    py.detach(|| {
        decode::<surface::Outcome>(value)?
            .validate()
            .map_err(failure)
    })
}

#[pyfunction]
fn surface_outcome_restore(
    py: Python<'_>,
    value: &str,
    key: &str,
    limits: &str,
) -> PyResult<NativeSurface> {
    py.detach(|| {
        let outcome: surface::Outcome = decode(value)?;
        outcome.validate().map_err(failure)?;
        outcome
            .surface(key, decode(limits)?)
            .map(|inner| NativeSurface { inner })
            .map_err(failure)
    })
}

#[pyfunction]
fn surface_outcome_source_document(
    py: Python<'_>,
    value: &str,
    key: &str,
    maximum: u64,
) -> PyResult<NativeDocument> {
    py.detach(|| {
        let outcome: surface::Outcome = decode(value)?;
        let document = outcome.source_document(key, maximum).map_err(failure)?;
        Ok(NativeDocument {
            source: DocumentSource::Owned(Arc::new(document)),
        })
    })
}

#[pyfunction]
fn surface_outcome_source_file_document(
    py: Python<'_>,
    value: &str,
    key: &str,
    maximum: u64,
) -> PyResult<NativeFileDocument> {
    py.detach(|| {
        let outcome: surface::Outcome = decode(value)?;
        outcome
            .source_file_document(key, maximum)
            .map(NativeFileDocument::new)
            .map_err(failure)
    })
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pyfunction]
fn surface_outcome_source_pixel_artifact(
    py: Python<'_>,
    value: &str,
    key: &str,
    maximum: u64,
) -> PyResult<NativePixelArtifact> {
    py.detach(|| {
        let outcome: surface::Outcome = decode(value)?;
        outcome
            .source_pixel_artifact(key, maximum)
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    })
}

#[pyfunction]
#[pyo3(signature=(key, document, index=None))]
fn surface_source_new(
    py: Python<'_>,
    key: &str,
    document: &NativeDocument,
    index: Option<&NativeSurface>,
) -> PyResult<String> {
    let document = document.borrowed()?.to_owned();
    py.detach(|| {
        encode(&surface::ArchivedSource::new(
            key,
            &document,
            index.map(|value| &value.inner),
        ))
    })
}

#[pyfunction]
#[pyo3(signature=(key, document, index=None))]
fn surface_source_file_document(
    py: Python<'_>,
    key: &str,
    document: &NativeFileDocument,
    index: Option<&NativeSurface>,
) -> PyResult<String> {
    let document = document.inner.as_ref().clone();
    py.detach(|| {
        encode(&surface::ArchivedSource::new_file_document(
            key,
            &document,
            index.map(|value| &value.inner),
        ))
    })
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pyfunction]
#[pyo3(signature=(key, artifact, tile_side, surface=None))]
fn surface_source_pixel_artifact(
    py: Python<'_>,
    key: &str,
    artifact: &NativePixelArtifact,
    tile_side: u32,
    surface: Option<&NativeImageSurface>,
) -> PyResult<String> {
    let artifact = artifact.inner.clone();
    py.detach(|| {
        encode(&surface::ArchivedSource::new_pixel_artifact(
            key,
            &artifact,
            tile_side,
            surface.map(|value| value.inner.index()),
        ))
    })
}

#[pyfunction]
fn surface_source_capture(py: Python<'_>, key: &str, index: &NativeSurface) -> PyResult<String> {
    py.detach(|| encode(&surface::ArchivedSource::capture(key, &index.inner).map_err(failure)?))
}
#[pyfunction]
fn surface_source_restore(py: Python<'_>, value: &str, maximum: u64) -> PyResult<NativeDocument> {
    py.detach(|| {
        let source: surface::ArchivedSource = decode(value)?;
        let document = source.restore(maximum).map_err(failure)?;
        Ok(NativeDocument {
            source: DocumentSource::Owned(Arc::new(document)),
        })
    })
}

#[pyfunction]
fn surface_source_restore_image(
    py: Python<'_>,
    value: &str,
    maximum: u64,
) -> PyResult<NativeFileDocument> {
    py.detach(|| {
        let source: surface::ArchivedSource = decode(value)?;
        source
            .restore_image(maximum)
            .map(|inner| NativeFileDocument::new(FileDocument::Image(inner)))
            .map_err(failure)
    })
}

#[pyfunction]
fn surface_source_restore_file_document(
    py: Python<'_>,
    value: &str,
    maximum: u64,
) -> PyResult<NativeFileDocument> {
    py.detach(|| {
        let source: surface::ArchivedSource = decode(value)?;
        source
            .restore_file_document(maximum)
            .map(NativeFileDocument::new)
            .map_err(failure)
    })
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[pyfunction]
fn surface_source_restore_pixel_artifact(
    py: Python<'_>,
    value: &str,
    maximum: u64,
) -> PyResult<NativePixelArtifact> {
    py.detach(|| {
        let source: surface::ArchivedSource = decode(value)?;
        source
            .restore_pixel_artifact(maximum)
            .map(|inner| NativePixelArtifact { inner })
            .map_err(failure)
    })
}
#[pyfunction]
fn surface_source_restore_surface(
    py: Python<'_>,
    value: &str,
    limits: &str,
) -> PyResult<NativeSurface> {
    py.detach(|| {
        let source: surface::ArchivedSource = decode(value)?;
        source
            .restore_surface(decode(limits)?)
            .map(|inner| NativeSurface { inner })
            .map_err(failure)
    })
}
#[pyfunction]
fn surface_outcome_new(py: Python<'_>, id: &str, limits: &str) -> PyResult<String> {
    py.detach(|| encode(&surface::Outcome::new(id, decode(limits)?).map_err(failure)?))
}
#[pyfunction]
fn surface_outcome_with_source(py: Python<'_>, value: &str, source: &str) -> PyResult<String> {
    py.detach(|| {
        let outcome: surface::Outcome = decode(value)?;
        encode(&outcome.with_source(decode(source)?).map_err(failure)?)
    })
}
