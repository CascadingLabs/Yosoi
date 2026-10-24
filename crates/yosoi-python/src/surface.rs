//! Thin ownership and JSON conversion boundary over the Rust Surface SDK.

#[cfg(any(feature = "browser", feature = "surface-video"))]
use pyo3::types::PyBytes;
use pyo3::{create_exception, prelude::*};
use serde::{Serialize, de::DeserializeOwned};
use yosoi::surface::{self, model::SurfaceRead};

use crate::{documents::NativeDocument, errors};

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

    fn web(&self, source: &str) -> PyResult<NativeWebSurface> {
        let source = surface::model::SourceId::new(source).map_err(failure)?;
        surface::web::WebSurface::new(self.inner.clone(), source)
            .map(|inner| NativeWebSurface { inner })
            .map_err(failure)
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
    fn crop<'py>(
        &self,
        py: Python<'py>,
        reference: &str,
        max_png_bytes: usize,
    ) -> PyResult<(String, Bound<'py, PyBytes>)> {
        let reference = decode(reference)?;
        let crop = py.detach(|| self.inner.crop(&reference, max_png_bytes).map_err(failure))?;
        let info = encode(&serde_json::json!({"reference":crop.reference,"rect":crop.rect}))?;
        Ok((info, PyBytes::new(py, &crop.png)))
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "WebSurface")]
#[derive(Debug)]
pub struct NativeWebSurface {
    inner: surface::web::WebSurface,
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

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("SurfaceError", module.py().get_type::<SurfaceError>())?;
    module.add_class::<NativeSurface>()?;
    module.add_class::<NativeWebSurface>()?;
    module.add("surface_video_enabled", cfg!(feature = "surface-video"))?;
    session::register(module)?;
    #[cfg(feature = "surface-video")]
    video::register(module)?;
    Ok(())
}
