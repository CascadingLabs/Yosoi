//! Bridge Python cancellation to SDK cancellation while Rust cleanup finishes.

use std::{
    future::Future,
    sync::{
        OnceLock,
        atomic::{AtomicUsize, Ordering},
    },
};

use pyo3::{exceptions::PyRuntimeError, prelude::*};
use tokio::{runtime::Runtime, sync::Notify};
use yosoi::request::CancellationToken;

static RUNTIME: OnceLock<Result<Runtime, String>> = OnceLock::new();
static REGISTERED: OnceLock<Result<(), ()>> = OnceLock::new();
static ACTIVE: AtomicUsize = AtomicUsize::new(0);
static IDLE: Notify = Notify::const_new();

pub fn initialize() -> PyResult<()> {
    let runtime = RUNTIME
        .get_or_init(|| {
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(1)
                .enable_all()
                .build()
                .map_err(|error| error.to_string())
        })
        .as_ref()
        .map_err(|error| PyRuntimeError::new_err(error.clone()))?;
    REGISTERED
        .get_or_init(|| pyo3_async_runtimes::tokio::init_with_runtime(runtime))
        .as_ref()
        .map(|()| ())
        .map_err(|()| PyRuntimeError::new_err("Python async runtime already initialized"))
}

#[pyclass(frozen, module = "yosoi._native", name = "CancellationToken")]
#[derive(Debug)]
pub struct NativeCancellation {
    pub inner: CancellationToken,
}

#[pymethods]
impl NativeCancellation {
    #[new]
    fn new() -> Self {
        Self {
            inner: CancellationToken::new(),
        }
    }

    fn cancel(&self) {
        self.inner.cancel();
    }

    #[getter]
    fn cancelled(&self) -> bool {
        self.inner.is_cancelled()
    }
}

struct ActiveOperation;
impl ActiveOperation {
    fn start() -> PyResult<Self> {
        ACTIVE
            .try_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map(|_| Self)
            .map_err(|_| PyRuntimeError::new_err("operation count overflow"))
    }
}
impl Drop for ActiveOperation {
    fn drop(&mut self) {
        let _ = ACTIVE.try_update(Ordering::AcqRel, Ordering::Acquire, |value| {
            value.checked_sub(1)
        });
        IDLE.notify_waiters();
    }
}

struct CancelOnDrop {
    token: CancellationToken,
    armed: bool,
}
impl CancelOnDrop {
    fn disarm(&mut self) {
        self.armed = false;
    }
}
impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        if self.armed {
            self.token.cancel();
        }
    }
}

pub fn bridge<'py, F, T>(
    py: Python<'py>,
    cancellation: Option<&NativeCancellation>,
    operation: impl FnOnce(CancellationToken) -> F,
) -> PyResult<Bound<'py, PyAny>>
where
    F: Future<Output = PyResult<T>> + Send + 'static,
    T: for<'object> IntoPyObject<'object> + Send + 'static,
{
    initialize()?;
    // A child token keeps task cancellation from cancelling sibling operations.
    let token = cancellation.map_or_else(CancellationToken::new, |value| value.inner.child_token());
    let mut guard = CancelOnDrop {
        token: token.clone(),
        armed: true,
    };
    let ticket = ActiveOperation::start()?;
    let future = operation(token);
    let task = pyo3_async_runtimes::tokio::get_runtime().spawn(async move {
        let _ticket = ticket;
        future.await
    });
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let result = task
            .await
            .map_err(|_| PyRuntimeError::new_err("Rust SDK operation task failed"))?;
        guard.disarm();
        result
    })
}

// Private lifecycle evidence for cancellation tests; not an application SDK API.
#[pyfunction]
pub fn wait_for_idle(py: Python<'_>) -> PyResult<Bound<'_, PyAny>> {
    initialize()?;
    pyo3_async_runtimes::tokio::future_into_py(py, async {
        loop {
            let notified = IDLE.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if ACTIVE.load(Ordering::Acquire) == 0 {
                return Ok(());
            }
            notified.await;
        }
    })
}
