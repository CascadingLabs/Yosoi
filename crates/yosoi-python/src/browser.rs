//! Python access to the SDK's shared browser Action, Session, and Work APIs.

use std::{
    collections::{BTreeMap, HashMap},
    io::{self, Write},
    iter::once,
    path::Path,
    sync::Arc,
};

use pyo3::{create_exception, prelude::*, types::PyDict};
use tokio::sync::Mutex;
use yosoi::{
    action,
    assertions::{AssertionError, AssertionReport, LocalAssertion, MAX_CHECK_ERROR_BYTES},
    expect::Expectation,
    flow::{Flow, FlowInvokeError, FlowOutcome, Step},
    locators::Plan,
    policy::Policy,
    session::{self, Session, SessionError, SessionPolicy, SessionRequestError, Work},
};

use crate::{
    async_runtime::{self, NativeCancellation},
    errors::{self, YosoiError},
    policy,
    requests::NativeRequest,
    responses::{NativeResponse, ResponseSource},
};

const MAX_FLOW_JSON_BYTES: usize = 16 * 1024 * 1024;
const MAX_FLOW_OUTCOME_JSON_BYTES: usize = 32 * 1024 * 1024;
const MAX_SESSION_POLICY_JSON_BYTES: usize = 64 * 1024;
const MAX_ASSERTION_CALLBACK_JSON_BYTES: usize = 1024 * 1024;

create_exception!(_native, BrowserError, YosoiError);

type SessionState = Arc<Mutex<Option<Session>>>;
type WorkState = Arc<Mutex<Option<NativeLease>>>;
type AssertionCallbacks = HashMap<String, Py<PyAny>>;

#[derive(Debug)]
struct NativeLease {
    work: Work,
    policy: Policy,
}

#[pyclass(frozen, module = "yosoi._native", name = "BrowserSession")]
#[derive(Debug)]
pub struct NativeSession {
    state: SessionState,
}

#[pymethods]
impl NativeSession {
    #[pyo3(signature = (request, policy_json=None, cancellation=None))]
    fn send_request<'py>(
        &self,
        py: Python<'py>,
        request: &NativeRequest,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let request = request.clone_request();
        let policy = policy_json
            .map(|value| policy::parse(Some(value)))
            .transpose()?;
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, cancellation, move |token| async move {
            let guard = state.lock().await;
            let session = guard
                .as_ref()
                .ok_or_else(|| BrowserError::new_err("browser Session is closed"))?
                .clone();
            drop(guard);
            let mut request = request.in_session(&session);
            if let Some(policy) = policy.as_ref() {
                request = request.bind(policy);
            }
            let response = Box::pin(request.send_cancellable(&token))
                .await
                .map_err(session_request_error)?;
            drop(request);
            Ok(NativeResponse {
                source: ResponseSource::Request(Arc::new(response)),
            })
        })
    }

    #[pyo3(signature = (cancellation=None))]
    fn work<'py>(
        &self,
        py: Python<'py>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, cancellation, move |token| async move {
            if token.is_cancelled() {
                return Err(BrowserError::new_err("Work acquisition was cancelled"));
            }
            let guard = state.lock().await;
            let session = guard
                .as_ref()
                .ok_or_else(|| BrowserError::new_err("browser Session is closed"))?
                .clone();
            let policy = session.policy().clone();
            drop(guard);
            let work = session
                .work()
                .await
                .map_err(|error| BrowserError::new_err(error.to_string()))?;
            if token.is_cancelled() {
                work.release()
                    .await
                    .map_err(|error| BrowserError::new_err(error.to_string()))?;
                return Err(BrowserError::new_err("Work acquisition was cancelled"));
            }
            Ok(NativeWork {
                state: Arc::new(Mutex::new(Some(NativeLease { work, policy }))),
            })
        })
    }

    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, None, move |_token| async move {
            let mut guard = state.lock().await;
            let Some(session) = guard.as_ref() else {
                return Ok(());
            };
            session
                .close()
                .await
                .map_err(|error| BrowserError::new_err(error.to_string()))?;
            let _ = guard.take();
            Ok(())
        })
    }

    #[getter]
    fn closed(&self) -> bool {
        self.state.try_lock().is_ok_and(|guard| guard.is_none())
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "BrowserWork")]
#[derive(Debug)]
pub struct NativeWork {
    state: WorkState,
}

#[pymethods]
impl NativeWork {
    #[pyo3(signature = (request, policy_json=None, cancellation=None))]
    fn send_request<'py>(
        &self,
        py: Python<'py>,
        request: &NativeRequest,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let request = request.clone_request();
        let policy = policy_json
            .map(|value| policy::parse(Some(value)))
            .transpose()?;
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, cancellation, move |token| async move {
            let guard = state.try_lock().map_err(|_| {
                BrowserError::new_err("browser Work is already executing an operation")
            })?;
            let lease = guard
                .as_ref()
                .ok_or_else(|| BrowserError::new_err("browser Work lease is released"))?;
            let mut request = request.with_work(&lease.work);
            if let Some(policy) = policy.as_ref() {
                request = request.bind(policy);
            }
            let response = Box::pin(request.send_cancellable(&token))
                .await
                .map_err(session_request_error)?;
            drop(request);
            drop(guard);
            Ok(NativeResponse {
                source: ResponseSource::Request(Arc::new(response)),
            })
        })
    }

    #[pyo3(signature = (flow_json, policy_json=None, cancellation=None))]
    fn run_flow<'py>(
        &self,
        py: Python<'py>,
        flow_json: &str,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let flow = parse_flow(flow_json)?;
        let policy = policy::parse(policy_json)?;
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, cancellation, move |token| async move {
            if token.is_cancelled() {
                return Err(BrowserError::new_err(
                    "Flow execution was cancelled before dispatch",
                ));
            }
            let guard = state
                .try_lock()
                .map_err(|_| BrowserError::new_err("browser Work is already executing a Flow"))?;
            let lease = guard
                .as_ref()
                .ok_or_else(|| BrowserError::new_err("browser Work lease is released"))?;
            let outcome = flow
                .bind(&policy)
                .with_lease(&lease.work)
                .with_cancellation(&token)
                .invoke()
                .await
                .map_err(|error| flow_invoke_error(&error))?;
            drop(guard);
            serialize_flow_outcome(&outcome)
        })
    }

    #[pyo3(signature = (flow_json, policy_json=None, cancellation=None, assertions=None))]
    #[allow(
        clippy::significant_drop_tightening,
        reason = "the borrowed lease and its policy must remain protected by the native mutex through invocation"
    )]
    fn invoke_flow<'py>(
        &self,
        py: Python<'py>,
        flow_json: &str,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
        assertions: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut flow = parse_flow(flow_json)?;
        let callbacks = parse_assertion_callbacks(py, assertions, &flow)?;
        bind_assertion_callbacks(py, &mut flow, &callbacks)?;
        let selected_policy = policy_json
            .map(|value| policy::parse(Some(value)))
            .transpose()?;
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, cancellation, move |token| async move {
            if token.is_cancelled() {
                return Err(BrowserError::new_err(
                    "Flow execution was cancelled before dispatch",
                ));
            }
            let outcome = {
                let guard = state.try_lock().map_err(|_| {
                    BrowserError::new_err("browser Work is already executing a Flow")
                })?;
                let lease = guard
                    .as_ref()
                    .ok_or_else(|| BrowserError::new_err("browser Work lease is released"))?;
                let selected_policy = selected_policy.as_ref().unwrap_or(&lease.policy);
                flow.bind(selected_policy)
                    .with_lease(&lease.work)
                    .with_cancellation(&token)
                    .invoke()
                    .await
                    .map_err(|error| flow_invoke_error(&error))?
            };
            serialize_flow_outcome(&outcome)
        })
    }

    fn release<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let state = Arc::clone(&self.state);
        async_runtime::bridge(py, None, move |_token| async move {
            let mut guard = state.lock().await;
            let Some(lease) = guard.take() else {
                return Ok(());
            };
            lease
                .work
                .release()
                .await
                .map_err(|error| BrowserError::new_err(error.to_string()))
        })
    }

    #[getter]
    fn released(&self) -> bool {
        self.state.try_lock().is_ok_and(|guard| guard.is_none())
    }
}

#[pyfunction]
#[pyo3(signature = (flow_json, policy_json=None, cancellation=None, allow_javascript=false, assertions=None))]
fn invoke_flow<'py>(
    py: Python<'py>,
    flow_json: &str,
    policy_json: Option<&str>,
    cancellation: Option<&NativeCancellation>,
    allow_javascript: bool,
    assertions: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let mut flow = parse_flow(flow_json)?;
    let callbacks = parse_assertion_callbacks(py, assertions, &flow)?;
    bind_assertion_callbacks(py, &mut flow, &callbacks)?;
    let policy = policy::parse(policy_json)?;
    async_runtime::bridge(py, cancellation, move |token| async move {
        if token.is_cancelled() {
            return Err(BrowserError::new_err(
                "Flow execution was cancelled before Session acquisition",
            ));
        }
        let bound = flow.bind(&policy).with_cancellation(&token);
        let outcome = if allow_javascript {
            bound.allow_javascript().invoke().await
        } else {
            bound.invoke().await
        }
        .map_err(|error| flow_invoke_error(&error))?;
        serialize_flow_outcome(&outcome)
    })
}

#[pyfunction]
fn snapshot_evaluate_file(path: &str) -> PyResult<String> {
    let step = action::evaluate_file(Path::new(path))
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    serialize_step(&step)
}

#[pyfunction]
#[pyo3(signature = (path, export_name=None))]
fn snapshot_module(path: &str, export_name: Option<&str>) -> PyResult<String> {
    let step = export_name
        .map_or_else(
            || action::run_module(Path::new(path)),
            |name| action::run_module_with_export(Path::new(path), name),
        )
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    serialize_step(&step)
}

#[pyfunction]
fn create_assertion(
    contract_type: &str,
    plan_json: &str,
    names: Vec<Option<String>>,
) -> PyResult<String> {
    if plan_json.len() > 65_536 {
        return Err(BrowserError::new_err(
            "assertion Plan JSON exceeds the 64 KiB input limit",
        ));
    }
    let plan: Plan = serde_json::from_str(plan_json)
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    let assertion = LocalAssertion::new_external_descriptor(contract_type.to_owned(), plan, names)
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    serialize_step(&Step::AssertAll { assertion })
}

#[pyfunction]
#[pyo3(signature = (url, flow_json, policy_json=None, cancellation=None))]
fn browser_action<'py>(
    py: Python<'py>,
    url: String,
    flow_json: &str,
    policy_json: Option<&str>,
    cancellation: Option<&NativeCancellation>,
) -> PyResult<Bound<'py, PyAny>> {
    let flow = parse_flow(flow_json)?;
    let policy = policy::parse(policy_json)?;
    async_runtime::bridge(py, cancellation, move |token| async move {
        if token.is_cancelled() {
            return Err(BrowserError::new_err(
                "Action was cancelled before dispatch",
            ));
        }
        let recipe = Flow::new(once(action::navigate(url)).chain(flow.steps().iter().cloned()))
            .with_failure_capture(flow.failure_capture_policy());
        let outcome = recipe
            .bind(&policy)
            .with_cancellation(&token)
            .invoke()
            .await
            .map_err(|error| BrowserError::new_err(error.to_string()))?;
        serialize_flow_outcome(&outcome)
    })
}

#[pyfunction]
#[pyo3(signature = (policy_json=None, session_policy_json=None, cancellation=None))]
fn acquire_browser_session<'py>(
    py: Python<'py>,
    policy_json: Option<&str>,
    session_policy_json: Option<&str>,
    cancellation: Option<&NativeCancellation>,
) -> PyResult<Bound<'py, PyAny>> {
    let policy = policy::parse(policy_json)?;
    let settings = parse_session_policy(session_policy_json)?;
    async_runtime::bridge(py, cancellation, move |token| async move {
        let session = session::new()
            .bind(&policy)
            .configure(settings)
            .acquire_cancellable(&token)
            .await
            .map_err(|error| BrowserError::new_err(error.to_string()))?;
        if token.is_cancelled() {
            session
                .close()
                .await
                .map_err(|error| BrowserError::new_err(error.to_string()))?;
            return Err(BrowserError::new_err("Session acquisition was cancelled"));
        }
        Ok(NativeSession {
            state: Arc::new(Mutex::new(Some(session))),
        })
    })
}

#[pyfunction]
fn default_session_policy() -> PyResult<String> {
    serde_json::to_string(&SessionPolicy::default())
        .map_err(|error| BrowserError::new_err(error.to_string()))
}

#[pyfunction]
fn validate_session_policy(value: &str) -> PyResult<String> {
    let settings = parse_session_policy(Some(value))?;
    serde_json::to_string(&settings).map_err(|error| BrowserError::new_err(error.to_string()))
}

#[pyfunction]
fn validate_flow(value: &str) -> PyResult<String> {
    let flow = parse_flow(value)?;
    serde_json::to_string(&flow).map_err(|error| BrowserError::new_err(error.to_string()))
}

fn serialize_step(step: &Step) -> PyResult<String> {
    serde_json::to_string(step).map_err(|error| BrowserError::new_err(error.to_string()))
}

fn session_request_error(error: SessionRequestError) -> PyErr {
    match error {
        SessionRequestError::Session(error) => Python::attach(|py| {
            let variant = match &error {
                SessionError::ExecutionCapacity(_) => "ExecutionCapacity",
                SessionError::BrowserFeatureDisabled => "BrowserFeatureDisabled",
                SessionError::InvalidPolicy => "InvalidPolicy",
                SessionError::InvalidInput => "InvalidInput",
                SessionError::InputTargetLost => "InputTargetLost",
                SessionError::Closed => "Closed",
                SessionError::Denied => "Denied",
                SessionError::Cancelled => "Cancelled",
                SessionError::Admission => "Admission",
                SessionError::AcquisitionDeadline => "AcquisitionDeadline",
                SessionError::Deadline => "Deadline",
                SessionError::TimeoutAfterDispatch => "TimeoutAfterDispatch",
                SessionError::Unknown => "Unknown",
                SessionError::Execution(_) => "Execution",
                SessionError::ResultLimit { .. } => "ResultLimit",
                SessionError::EvidenceUnavailable => "EvidenceUnavailable",
                SessionError::AssertionEvaluation(_) => "AssertionEvaluation",
                SessionError::Cleanup => "Cleanup",
                SessionError::WatchLagged(_) => "WatchLagged",
                SessionError::WatchDeadline => "WatchDeadline",
                SessionError::Unsupported(_) => "Unsupported",
            };
            errors::with_metadata(
                py,
                errors::RequestError::new_err(error.to_string()),
                "yosoi::session::SessionError",
                Some(variant),
                serde_json::json!({
                    "message": bounded_error(&error.to_string()),
                    "is_cancelled": error.is_cancelled(),
                    "is_unknown": error.is_unknown(),
                }),
                &[],
            )
        }),
        SessionRequestError::Request(error) => {
            Python::attach(|py| errors::request_send_error(py, &error))
        }
    }
}

fn flow_invoke_error(error: &FlowInvokeError) -> PyErr {
    let message = bounded_error(&error.to_string());
    let variant = match &error {
        FlowInvokeError::InvalidFlow(_) => "invalid_flow",
        FlowInvokeError::Policy(_) => "policy",
        FlowInvokeError::Session { .. } => "session",
    };
    let mut outcome_encoding_error = None;
    let outcome = error
        .partial_outcome()
        .and_then(|value| match serialize_flow_outcome(value) {
            Ok(value) => Some(value),
            Err(error) => {
                outcome_encoding_error = Some(bounded_error(&error.to_string()));
                None
            }
        });
    let cleanup_error = error
        .cleanup_error()
        .map(ToString::to_string)
        .as_deref()
        .map(bounded_error);
    let exception = Python::attach(|py| -> PyResult<PyErr> {
        let exception = BrowserError::new_err(message);
        let value = exception.value(py);
        value.setattr("rust_variant", variant)?;
        if let Some(outcome) = outcome {
            value.setattr("outcome_json", outcome)?;
        }
        if let Some(outcome_encoding_error) = outcome_encoding_error {
            value.setattr("outcome_encoding_error", outcome_encoding_error)?;
        }
        if let Some(cleanup_error) = cleanup_error {
            value.setattr("cleanup_error", cleanup_error)?;
        }
        Ok(exception)
    });
    exception.unwrap_or_else(|error| {
        BrowserError::new_err(bounded_error(&format!(
            "FlowInvokeError details could not be attached: {error}"
        )))
    })
}

fn parse_assertion_callbacks(
    py: Python<'_>,
    bindings: Option<&Bound<'_, PyDict>>,
    flow: &Flow,
) -> PyResult<AssertionCallbacks> {
    let descriptors = assertion_descriptors(flow)?;
    let mut callbacks = AssertionCallbacks::new();
    if let Some(bindings) = bindings {
        for (key, callback) in bindings.iter() {
            let id = key.extract::<String>().map_err(|_| {
                BrowserError::new_err("assertion callback keys must be descriptor ID strings")
            })?;
            if !descriptors.contains_key(&id) {
                return Err(BrowserError::new_err(format!(
                    "no assertion descriptor has ID {id}"
                )));
            }
            if !callback.is_callable() {
                return Err(BrowserError::new_err(format!(
                    "assertion callback {id} must be callable"
                )));
            }
            callbacks.insert(id, callback.clone().unbind());
        }
    }
    if callbacks.len() != descriptors.len() {
        let unbound = descriptors
            .keys()
            .find(|id| !callbacks.contains_key(*id))
            .map_or("unknown", String::as_str);
        return Err(BrowserError::new_err(format!(
            "assertion descriptor {unbound} has no Python evaluator"
        )));
    }
    let _ = py;
    Ok(callbacks)
}

fn bind_assertion_callbacks(
    py: Python<'_>,
    flow: &mut Flow,
    callbacks: &AssertionCallbacks,
) -> PyResult<()> {
    for step in &mut flow.steps {
        bind_step_assertions(py, step, callbacks)?;
    }
    Ok(())
}

fn bind_step_assertions(
    py: Python<'_>,
    step: &mut Step,
    callbacks: &AssertionCallbacks,
) -> PyResult<()> {
    match step {
        Step::AssertAll { assertion } => bind_assertion(py, assertion, callbacks),
        Step::Until {
            trigger,
            expectation,
        } => {
            if let Some(trigger) = trigger {
                bind_step_assertions(py, trigger, callbacks)?;
            }
            bind_expectation_assertions(py, expectation, callbacks)
        }
        Step::Timed { action, .. } | Step::Configured { action, .. } => {
            bind_step_assertions(py, action, callbacks)
        }
        Step::NestedFlow { flow } => bind_assertion_callbacks(py, flow, callbacks),
        _ => Ok(()),
    }
}

fn bind_expectation_assertions(
    py: Python<'_>,
    expectation: &mut Expectation,
    callbacks: &AssertionCallbacks,
) -> PyResult<()> {
    match expectation {
        Expectation::Contract { assertion } => bind_assertion(py, assertion, callbacks),
        Expectation::All { expectations } => {
            for expectation in expectations {
                bind_expectation_assertions(py, expectation, callbacks)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn bind_assertion(
    py: Python<'_>,
    assertion: &mut LocalAssertion,
    callbacks: &AssertionCallbacks,
) -> PyResult<()> {
    let callback = callbacks
        .get(assertion.descriptor_id())
        .ok_or_else(|| BrowserError::new_err("assertion callback binding is missing"))?
        .clone_ref(py);
    assertion.rebind_external(move |located_json, policy_json| {
        let callback_json = Python::attach(|py| -> PyResult<String> {
            callback
                .bind(py)
                .call1((located_json, policy_json))?
                .extract::<String>()
        })
        .map_err(|error| AssertionError::ExternalEvaluator(bounded_error(&error.to_string())))?;
        if callback_json.len() > MAX_ASSERTION_CALLBACK_JSON_BYTES {
            return Err(AssertionError::ExternalEvaluator(
                "callback report exceeds the 1 MiB output limit".into(),
            ));
        }
        serde_json::from_str::<AssertionReport>(&callback_json).map_err(|error| {
            AssertionError::ExternalEvaluator(format!(
                "callback returned an invalid AssertionReport: {error}"
            ))
        })
    });
    Ok(())
}

fn bounded_error(message: &str) -> String {
    if message.len() <= MAX_CHECK_ERROR_BYTES {
        return message.to_owned();
    }
    let maximum = MAX_CHECK_ERROR_BYTES.saturating_sub(3);
    let mut end = maximum.min(message.len());
    while !message.is_char_boundary(end) {
        end = end.saturating_sub(1);
    }
    let prefix = message.get(..end).unwrap_or_default();
    format!("{prefix}...")
}

fn assertion_descriptors(flow: &Flow) -> PyResult<BTreeMap<String, serde_json::Value>> {
    let mut descriptors = BTreeMap::new();
    for step in &flow.steps {
        collect_step_descriptors(step, &mut descriptors)?;
    }
    Ok(descriptors)
}

fn collect_step_descriptors(
    step: &Step,
    descriptors: &mut BTreeMap<String, serde_json::Value>,
) -> PyResult<()> {
    match step {
        Step::AssertAll { assertion } => insert_assertion_descriptor(assertion, descriptors),
        Step::Until {
            trigger,
            expectation,
        } => {
            if let Some(trigger) = trigger {
                collect_step_descriptors(trigger, descriptors)?;
            }
            collect_expectation_descriptors(expectation, descriptors)
        }
        Step::Timed { action, .. } | Step::Configured { action, .. } => {
            collect_step_descriptors(action, descriptors)
        }
        Step::NestedFlow { flow } => {
            for step in &flow.steps {
                collect_step_descriptors(step, descriptors)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn collect_expectation_descriptors(
    expectation: &Expectation,
    descriptors: &mut BTreeMap<String, serde_json::Value>,
) -> PyResult<()> {
    match expectation {
        Expectation::Contract { assertion } => insert_assertion_descriptor(assertion, descriptors),
        Expectation::All { expectations } => {
            for expectation in expectations {
                collect_expectation_descriptors(expectation, descriptors)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn insert_assertion_descriptor(
    assertion: &LocalAssertion,
    descriptors: &mut BTreeMap<String, serde_json::Value>,
) -> PyResult<()> {
    let descriptor = serde_json::to_value(assertion)
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    let id = assertion.descriptor_id().to_owned();
    if let Some(previous) = descriptors.get(&id) {
        if previous != &descriptor {
            return Err(BrowserError::new_err(format!(
                "assertion descriptor ID {id} is reused with conflicting contents"
            )));
        }
    } else {
        descriptors.insert(id, descriptor);
    }
    Ok(())
}

fn parse_flow(value: &str) -> PyResult<Flow> {
    if value.len() > MAX_FLOW_JSON_BYTES {
        return Err(BrowserError::new_err(
            "Flow JSON exceeds the 16 MiB input limit",
        ));
    }
    let flow: Flow =
        serde_json::from_str(value).map_err(|error| BrowserError::new_err(error.to_string()))?;
    flow.validate()
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    Ok(flow)
}

fn parse_session_policy(value: Option<&str>) -> PyResult<SessionPolicy> {
    let settings = match value {
        Some(value) => {
            if value.len() > MAX_SESSION_POLICY_JSON_BYTES {
                return Err(BrowserError::new_err(
                    "SessionPolicy JSON exceeds the 64 KiB input limit",
                ));
            }
            serde_json::from_str::<SessionPolicy>(value)
                .map_err(|error| BrowserError::new_err(error.to_string()))?
        }
        None => SessionPolicy::default(),
    };
    settings
        .validate()
        .map_err(|error| BrowserError::new_err(error.to_string()))?;
    Ok(settings)
}

fn serialize_flow_outcome(outcome: &FlowOutcome) -> PyResult<String> {
    let mut writer = BoundedJsonWriter::default();
    if let Err(error) = serde_json::to_writer(&mut writer, outcome) {
        if writer.exceeded {
            return Err(BrowserError::new_err(
                "FlowOutcome JSON exceeds the 32 MiB transfer limit",
            ));
        }
        return Err(BrowserError::new_err(error.to_string()));
    }
    String::from_utf8(writer.bytes).map_err(|error| BrowserError::new_err(error.to_string()))
}

#[derive(Default)]
struct BoundedJsonWriter {
    bytes: Vec<u8>,
    exceeded: bool,
}

impl Write for BoundedJsonWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let Some(next_len) = self.bytes.len().checked_add(buffer.len()) else {
            self.exceeded = true;
            return Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "FlowOutcome JSON exceeds its transfer limit",
            ));
        };
        if next_len > MAX_FLOW_OUTCOME_JSON_BYTES {
            self.exceeded = true;
            return Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "FlowOutcome JSON exceeds its transfer limit",
            ));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// Registers this module's browser-only Python bridge surface.
pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("BrowserError", module.py().get_type::<BrowserError>())?;
    module.add_class::<NativeSession>()?;
    module.add_class::<NativeWork>()?;
    module.add_function(wrap_pyfunction!(invoke_flow, module)?)?;
    module.add_function(wrap_pyfunction!(snapshot_evaluate_file, module)?)?;
    module.add_function(wrap_pyfunction!(snapshot_module, module)?)?;
    module.add_function(wrap_pyfunction!(create_assertion, module)?)?;
    module.add_function(wrap_pyfunction!(browser_action, module)?)?;
    module.add_function(wrap_pyfunction!(acquire_browser_session, module)?)?;
    module.add_function(wrap_pyfunction!(default_session_policy, module)?)?;
    module.add_function(wrap_pyfunction!(validate_session_policy, module)?)?;
    module.add_function(wrap_pyfunction!(validate_flow, module)?)
}
