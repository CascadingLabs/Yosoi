//! Retain borrowed parser representations on their owning Rust thread.
//!
//! Python owns a channel, never an unsendable parser or a forged Rust lifetime.
//! Each explicit parse retains one representation until close or last-owner drop.

use std::{
    sync::{Mutex, mpsc},
    thread::{self, JoinHandle},
};

use pyo3::prelude::*;
use yosoi::{locators::Plan, policy::Policy};

use crate::{documents::NativeDocument, errors, locators::NativePlan};

#[derive(Debug)]
struct Locate {
    plan: Plan,
    reply: mpsc::SyncSender<PyResult<String>>,
}

#[derive(Debug)]
struct Worker {
    sender: mpsc::SyncSender<Locate>,
    thread: JoinHandle<()>,
}

#[pyclass(frozen, module = "yosoi._native", name = "ParsedDocument")]
#[derive(Debug)]
pub struct NativeParsedDocument {
    worker: Mutex<Option<Worker>>,
}

impl NativeParsedDocument {
    pub fn start(document: NativeDocument, policy: Policy) -> PyResult<Self> {
        // No sleeping/polling and no leaked 'static document allocation.
        let (sender, receiver) = mpsc::sync_channel::<Locate>(0);
        let (ready_sender, ready_receiver) = mpsc::sync_channel(1);
        let thread = thread::Builder::new()
            .name("yosoi-parsed-document".to_owned())
            .spawn(move || {
                let document_ref = match document.borrowed() {
                    Ok(document) => document,
                    Err(error) => {
                        let _ = ready_sender.send(Err(error));
                        return;
                    }
                };
                let bound = document_ref.bind(&policy);
                let parsed = match bound.parse() {
                    Ok(parsed) => parsed,
                    Err(error) => {
                        let _ = ready_sender
                            .send(Err(Python::attach(|py| errors::parse_error(py, &error))));
                        return;
                    }
                };
                if ready_sender.send(Ok(())).is_err() {
                    return;
                }
                while let Ok(request) = receiver.recv() {
                    let outcome = serde_json::to_string(&parsed.locate(&request.plan))
                        .map_err(|error| errors::LocatorError::new_err(error.to_string()));
                    let _ = request.reply.send(outcome);
                }
            })
            .map_err(|error| errors::ParseError::new_err(error.to_string()))?;
        match ready_receiver.recv() {
            Ok(Ok(())) => Ok(Self {
                worker: Mutex::new(Some(Worker { sender, thread })),
            }),
            Ok(Err(error)) => {
                let _ = thread.join();
                Err(error)
            }
            Err(error) => {
                let _ = thread.join();
                Err(errors::ParseError::new_err(error.to_string()))
            }
        }
    }

    fn stop(&self) -> PyResult<()> {
        let worker = self
            .worker
            .lock()
            .map_err(|_| errors::ClosedResourceError::new_err("parsed document lock poisoned"))?
            .take();
        if let Some(worker) = worker {
            drop(worker.sender);
            worker.thread.join().map_err(|_| {
                errors::ClosedResourceError::new_err("parsed document worker failed")
            })?;
        }
        Ok(())
    }
}

#[pymethods]
impl NativeParsedDocument {
    fn locate(&self, py: Python<'_>, plan: &NativePlan) -> PyResult<String> {
        let plan = plan.inner.clone();
        py.detach(|| {
            let sender = self
                .worker
                .lock()
                .map_err(|_| errors::ClosedResourceError::new_err("parsed document lock poisoned"))?
                .as_ref()
                .map(|worker| worker.sender.clone())
                .ok_or_else(|| errors::ClosedResourceError::new_err("parsed document is closed"))?;
            let (reply, receiver) = mpsc::sync_channel(1);
            sender
                .send(Locate { plan, reply })
                .map_err(|_| errors::ClosedResourceError::new_err("parsed document is closed"))?;
            receiver.recv().map_err(|_| {
                errors::ClosedResourceError::new_err("parsed document worker stopped")
            })?
        })
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.stop())
    }

    #[getter]
    fn closed(&self) -> PyResult<bool> {
        self.worker
            .lock()
            .map(|worker| worker.is_none())
            .map_err(|_| errors::ClosedResourceError::new_err("parsed document lock poisoned"))
    }
}

impl Drop for NativeParsedDocument {
    fn drop(&mut self) {
        if let Ok(worker) = self.worker.get_mut()
            && let Some(worker) = worker.take()
        {
            drop(worker.sender);
            let _ = worker.thread.join();
        }
    }
}
