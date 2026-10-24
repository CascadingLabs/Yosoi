//! In-memory cursor and action-lease ownership, never restored from DTOs.

use super::{NativeSurface, decode, encode, failure};
use pyo3::prelude::*;
use std::sync::Mutex;
use yosoi::surface;

#[pyclass(frozen, module = "yosoi._native", name = "SurfaceSession")]
#[derive(Debug)]
pub struct NativeSession {
    inner: surface::Session,
}

#[pymethods]
impl NativeSession {
    #[new]
    fn new(index: &NativeSurface, policy: &str) -> PyResult<Self> {
        surface::Session::new(index.inner.clone(), decode(policy)?)
            .map(|inner| Self { inner })
            .map_err(failure)
    }
    fn cursor(&self) -> PyResult<NativeCursor> {
        self.inner
            .cursor()
            .map(|inner| NativeCursor { inner })
            .map_err(failure)
    }
    fn attach(&self) -> PyResult<()> {
        self.inner.attach().map_err(failure)
    }
    fn detach(&self) -> PyResult<()> {
        self.inner.detach().map_err(failure)
    }
    fn invalidate(&self, reason: &str) -> PyResult<()> {
        self.inner.invalidate(reason).map_err(failure)
    }
    fn current(&self) -> PyResult<NativeSurface> {
        self.inner
            .current()
            .map(|inner| NativeSurface { inner })
            .map_err(failure)
    }
    fn hot_owner(&self) -> PyResult<Option<u64>> {
        Ok(self
            .inner
            .hot_owner()
            .map_err(failure)?
            .map(surface::CursorId::get))
    }
    fn publish(&self, index: &NativeSurface) -> PyResult<()> {
        self.inner.publish(index.inner.clone()).map_err(failure)
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "SurfaceCursor")]
#[derive(Debug)]
pub struct NativeCursor {
    inner: surface::Cursor,
}

#[pymethods]
impl NativeCursor {
    const fn id(&self) -> u64 {
        self.inner.id().get()
    }
    fn position(&self) -> PyResult<String> {
        encode(&self.inner.position().map_err(failure)?)
    }
    fn status(&self) -> PyResult<String> {
        encode(&self.inner.status().map_err(failure)?)
    }
    fn events(&self) -> PyResult<String> {
        encode(&self.inner.events().map_err(failure)?)
    }
    fn focus(&self, reference: &str) -> PyResult<()> {
        self.inner.focus(&decode(reference)?).map_err(failure)
    }
    fn subscribe(&self, reference: &str) -> PyResult<u64> {
        Ok(self
            .inner
            .subscribe(&decode(reference)?)
            .map_err(failure)?
            .get())
    }
    fn unsubscribe(&self, watch: &str) -> PyResult<()> {
        self.inner.unsubscribe(decode(watch)?).map_err(failure)
    }
    fn reconcile(&self, watch: &str, reference: &str) -> PyResult<String> {
        encode(
            &self
                .inner
                .reconcile(decode(watch)?, &decode(reference)?)
                .map_err(failure)?,
        )
    }
    fn promote(&self) -> PyResult<()> {
        self.inner.promote().map_err(failure)
    }
    fn cool(&self) -> PyResult<()> {
        self.inner.cool().map_err(failure)
    }
    fn close(&self) -> PyResult<()> {
        self.inner.close().map_err(failure)
    }
    fn begin_action(&self) -> PyResult<NativeActionLease> {
        self.inner
            .begin_action()
            .map(|inner| NativeActionLease {
                inner: Mutex::new(Some(inner)),
            })
            .map_err(failure)
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
            _ => Err(failure(surface::SurfaceError::Invalid(
                "unsupported cursor operation".into(),
            ))),
        })
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "SurfaceActionLease")]
#[derive(Debug)]
pub struct NativeActionLease {
    inner: Mutex<Option<surface::ActionLease>>,
}

#[pymethods]
impl NativeActionLease {
    fn revalidate(&self) -> PyResult<String> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| failure(surface::SurfaceError::Poisoned))?;
        let lease = guard
            .as_ref()
            .ok_or_else(|| failure(surface::SurfaceError::Stale))?;
        let reference = lease.revalidate().map_err(failure)?.clone();
        drop(guard);
        encode(&reference)
    }
    fn mark_dispatched(&self) -> PyResult<()> {
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| failure(surface::SurfaceError::Poisoned))?;
        guard
            .as_mut()
            .ok_or_else(|| failure(surface::SurfaceError::Stale))?
            .mark_dispatched()
            .map_err(failure)
    }
    fn finish(&self, status: &str, note: &str) -> PyResult<String> {
        let status = decode(status)?;
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| failure(surface::SurfaceError::Poisoned))?;
        let lease = guard
            .take()
            .ok_or_else(|| failure(surface::SurfaceError::Stale))?;
        drop(guard);
        encode(&lease.finish(status, note).map_err(failure)?)
    }
    fn close(&self) -> PyResult<()> {
        self.inner
            .lock()
            .map_err(|_| failure(surface::SurfaceError::Poisoned))?
            .take();
        Ok(())
    }
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeSession>()?;
    module.add_class::<NativeCursor>()?;
    module.add_class::<NativeActionLease>()
}
