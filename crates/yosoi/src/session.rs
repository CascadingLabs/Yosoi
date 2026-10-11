//! Explicit browser authority; the managed APIs compose this same substrate.
use crate::assertions;
use crate::automation_record;
#[cfg(feature = "browser")]
use crate::documents;
use crate::internal::engine as internal_engine;
#[cfg(feature = "browser")]
use crate::internal::engine::execution as internal_engine_execution;
#[cfg(feature = "browser")]
use crate::internal::engine::session as internal_engine_session;
use crate::internal::policy::policy as internal_policy_policy;
#[cfg(feature = "browser")]
use crate::internal::web_capture as internal_web_capture;
use crate::request;
use std::fmt as std_fmt;
use std::future as std_future;
use tokio::sync as tokio_sync;
#[cfg(feature = "browser")]
use tokio::time as tokio_time;
mod evaluation;
mod javascript;
mod until;

pub use until::{
    MAX_UNTIL_REPORT_BYTES, UntilCheck, UntilCheckState, UntilReport, UntilReportError, UntilScope,
    UntilTermination,
};

pub use crate::internal::engine::execution::{
    ExecutionPool, ExecutionPoolError, ExecutionSnapshot,
};
pub use crate::internal::policy::policy::BrowserMode;
#[cfg(feature = "browser")]
use crate::{
    assertions::{AssertionReport, LocalAssertion},
    documents::Document,
};
use crate::{
    automation_record::{Observation, OperationReceipt, OperationStatus},
    flow::Condition,
    policy::Policy,
    timing,
};
use serde::{Deserialize, Serialize};
use std::{sync::Arc, time::Duration};
use thiserror::Error;
use tokio::sync::broadcast;
#[cfg(feature = "browser")]
use tokio::time::{Instant, sleep_until};
use tokio_util::sync::CancellationToken;
tokio::task_local! { static SCOPED_POLICY: Policy; }
tokio::task_local! { static SCOPED_CANCELLATION: CancellationToken; }
pub(crate) async fn with_cancellation<T>(
    cancellation: &CancellationToken,
    future: impl std_future::Future<Output = T>,
) -> T {
    SCOPED_CANCELLATION
        .scope(cancellation.clone(), future)
        .await
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ActionKind {
    Navigate,
    Click,
    EnterText,
    Screenshot,
    Wait,
    Assert,
    Evaluate,
}

/// Frame selection is resolved uniquely immediately before script dispatch.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub enum JsFrame {
    #[default]
    Main,
    UrlContains(String),
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub enum JsWorld {
    #[default]
    Main,
    Isolated,
}
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct JsTarget {
    pub frame: JsFrame,
    pub world: JsWorld,
    pub expected_document_epoch: Option<u64>,
}

/// Execution bounds, separate from Request's existing acquisition/output policy.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionPolicy {
    /// Concurrent controller operations, independent of the number of tabs.
    #[serde(default = "default_execution_concurrency")]
    pub execution_concurrency: u32,
    #[serde(default = "default_execution_queue")]
    pub maximum_queued_operations: u32,
    /// Keep tab ownership but park event-driven condition waits outside worker capacity.
    #[serde(default = "default_yield_on_wait")]
    pub yield_on_wait: bool,
    pub mode: BrowserMode,
    pub maximum_tabs: u32,
    pub dom: bool,
    pub allow_arbitrary_js: bool,
    pub allowed_actions: Vec<ActionKind>,
    pub operation_timeout_ms: u64,
    pub maximum_input_bytes: usize,
    pub maximum_result_bytes: usize,
    pub maximum_observation_bytes: usize,
    pub watch_capacity: usize,
    pub remote_endpoint: Option<String>,
}
impl Default for SessionPolicy {
    fn default() -> Self {
        Self {
            execution_concurrency: default_execution_concurrency(),
            maximum_queued_operations: default_execution_queue(),
            yield_on_wait: default_yield_on_wait(),
            mode: BrowserMode::Headless,
            maximum_tabs: 1,
            dom: true,
            allow_arbitrary_js: false,
            allowed_actions: vec![
                ActionKind::Navigate,
                ActionKind::Click,
                ActionKind::EnterText,
                ActionKind::Screenshot,
                ActionKind::Wait,
                ActionKind::Assert,
            ],
            operation_timeout_ms: 10_000,
            maximum_input_bytes: 65_536,
            maximum_result_bytes: 65_536,
            maximum_observation_bytes: 262_144,
            watch_capacity: 16,
            remote_endpoint: None,
        }
    }
}
impl SessionPolicy {
    pub fn validate(&self) -> Result<(), SessionError> {
        if !(1..=32).contains(&self.execution_concurrency)
            || !(1..=1024).contains(&self.maximum_queued_operations)
            || self.maximum_tabs == 0
            || self.maximum_tabs > 32
            || self.operation_timeout_ms == 0
            || self.operation_timeout_ms > 60_000
            || self.watch_capacity == 0
            || self.watch_capacity > 1024
            || self.maximum_input_bytes == 0
            || self.maximum_result_bytes == 0
            || self.maximum_observation_bytes == 0
            || self.maximum_input_bytes > 1024 * 1024
            || self.maximum_result_bytes > 1024 * 1024
            || self.maximum_observation_bytes > automation_record::MAX_OBSERVATION_HTML_BYTES
            || self.allowed_actions.len() > 7
        {
            return Err(SessionError::InvalidPolicy);
        }
        if self.remote_endpoint.is_some() {
            return Err(SessionError::Unsupported("remote endpoint"));
        }
        Ok(())
    }
}

const fn default_execution_concurrency() -> u32 {
    2
}
const fn default_execution_queue() -> u32 {
    64
}
const fn default_yield_on_wait() -> bool {
    true
}

#[derive(Debug, Error)]
pub enum SessionError {
    #[error(transparent)]
    ExecutionCapacity(#[from] ExecutionPoolError),
    #[error("browser feature is disabled")]
    BrowserFeatureDisabled,
    #[error("invalid bounded Session policy")]
    InvalidPolicy,
    #[error("invalid browser input")]
    InvalidInput,
    #[error("native typing target changed before keyboard dispatch")]
    InputTargetLost,
    #[error("Session is closed")]
    Closed,
    #[error("operation is not permitted by Session policy")]
    Denied,
    #[error("operation cancelled before dispatch")]
    Cancelled,
    #[error("browser capacity/control could not be acquired")]
    Admission,
    #[error("Session acquisition deadline elapsed")]
    AcquisitionDeadline,
    #[error("execution deadline elapsed before dispatch")]
    Deadline,
    #[error("execution deadline elapsed after possible dispatch; outcome is unknown")]
    TimeoutAfterDispatch,
    #[error("browser outcome is unknown after possible dispatch")]
    Unknown,
    #[error("browser execution failed after possible dispatch: {0}")]
    Execution(String),
    #[error("JavaScript result exceeded the configured byte limit of {maximum} after dispatch")]
    ResultLimit { maximum: usize },
    #[error("browser evidence unavailable or incomplete")]
    EvidenceUnavailable,
    #[error("assertion evaluation failed: {0}")]
    AssertionEvaluation(String),
    #[error("browser cleanup incomplete")]
    Cleanup,
    #[error("watcher lagged by {0} items")]
    WatchLagged(u64),
    #[error("watcher deadline elapsed")]
    WatchDeadline,
    #[error("unsupported Session capability: {0}")]
    Unsupported(&'static str),
}
impl SessionError {
    pub const fn is_cancelled(&self) -> bool {
        matches!(self, Self::Cancelled | Self::Closed)
    }
    pub const fn is_unknown(&self) -> bool {
        matches!(
            self,
            Self::Unknown
                | Self::TimeoutAfterDispatch
                | Self::Execution(_)
                | Self::ResultLimit { .. }
        )
    }
}

pub fn new_operation_id() -> String {
    internal_engine::ActivityId::random().to_string()
}
pub fn new() -> SessionBuilder {
    SessionBuilder {
        policy: Policy::default(),
        settings: SessionPolicy::default(),
        configured: false,
        execution_pool: None,
    }
}

#[derive(Debug, Error)]
pub enum SessionRequestError {
    #[error(transparent)]
    Session(#[from] SessionError),
    #[error(transparent)]
    Request(#[from] request::RequestSendError),
}

enum RequestAuthority<'scope> {
    Session(&'scope Session),
    Work(&'scope Work),
}
pub struct SessionRequest<'scope> {
    request: request::PageRequest,
    policy: Policy,
    authority: RequestAuthority<'scope>,
}
impl std_fmt::Debug for SessionRequest<'_> {
    fn fmt(&self, formatter: &mut std_fmt::Formatter<'_>) -> std_fmt::Result {
        formatter
            .debug_struct("SessionRequest")
            .finish_non_exhaustive()
    }
}
impl<'scope> SessionRequest<'scope> {
    pub(crate) fn new(request: request::PageRequest, session: &'scope Session) -> Self {
        Self {
            request,
            policy: session.request_policy(),
            authority: RequestAuthority::Session(session),
        }
    }
    pub(crate) fn on_work(request: request::PageRequest, work: &'scope Work) -> Self {
        Self {
            request,
            policy: work.session.request_policy(),
            authority: RequestAuthority::Work(work),
        }
    }
    pub fn bind(mut self, policy: &Policy) -> Self {
        self.policy = policy.clone();
        self
    }
    pub async fn send(&self) -> Result<request::Response, SessionRequestError> {
        let cancellation = SCOPED_CANCELLATION
            .try_with(Clone::clone)
            .unwrap_or_default();
        Box::pin(self.send_cancellable(&cancellation)).await
    }
    /// Executes while honoring caller cancellation through acquisition and request settlement.
    #[expect(
        clippy::significant_drop_tightening,
        reason = "Ownership is moved into a task or consumed by async release; the nursery follows Drop fields after that move."
    )]
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<request::Response, SessionRequestError> {
        let scoped = SCOPED_CANCELLATION
            .try_with(Clone::clone)
            .unwrap_or_default();
        match self.authority {
            RequestAuthority::Session(session) => {
                // Dropping this acquisition future releases any partial control guard; no request
                // has been dispatched until `work()` returns successfully.
                let acquiring = session.work();
                tokio::pin!(acquiring);

                let work = tokio::select! {
                    biased;
                    () = cancellation.cancelled() => return Err(SessionError::Cancelled.into()),
                    () = scoped.cancelled() => return Err(SessionError::Cancelled.into()),
                    result = &mut acquiring => result?,
                };
                let response = Box::pin(self.send_on_cancellable(&work, cancellation)).await;
                let release = work.release().await;
                let response = response?;
                release?;
                Ok(response)
            }
            RequestAuthority::Work(work) => {
                Box::pin(self.send_on_cancellable(work, cancellation)).await
            }
        }
    }
    async fn send_on_cancellable(
        &self,
        work: &Work,
        cancellation: &CancellationToken,
    ) -> Result<request::Response, SessionRequestError> {
        #[cfg(feature = "browser")]
        {
            let scoped = SCOPED_CANCELLATION
                .try_with(Clone::clone)
                .unwrap_or_default();
            let session = work.session.inner.backend.cancellation();
            let operation = cancellation.child_token();
            let sending = with_cancellation(&operation, self.send_on(work, &operation));
            tokio::pin!(sending);
            tokio::select! {
                biased;
                () = cancellation.cancelled() => {
                    operation.cancel();
                    sending.await
                }
                () = scoped.cancelled() => {
                    operation.cancel();
                    sending.await
                }
                () = session.cancelled() => {
                    operation.cancel();
                    sending.await
                }
                result = &mut sending => result,
            }
        }
        #[cfg(not(feature = "browser"))]
        {
            self.send_on(work, cancellation).await
        }
    }
    async fn send_on(
        &self,
        work: &Work,
        cancellation: &CancellationToken,
    ) -> Result<request::Response, SessionRequestError> {
        let _operation = work.operation()?;
        work.authorize(ActionKind::Navigate, self.request.target().as_str())?;
        self.policy
            .validate()
            .map_err(|_| SessionError::InvalidPolicy)?;
        if self.policy.page.acquisitions.is_empty() {
            return Err(SessionError::InvalidPolicy.into());
        }
        for acquisition in &self.policy.page.acquisitions {
            use crate::internal::policy::policy::{AcquisitionKind, DocumentRequest};
            if acquisition.kind()
                != (AcquisitionKind::Browser {
                    mode: work.session.settings().mode,
                })
            {
                return Err(
                    SessionError::Unsupported("acquisition incompatible with Session").into(),
                );
            }
            if let Some(documents) = acquisition.exact_documents() {
                if !work.session.settings().dom && documents.contains(&DocumentRequest::RenderedDom)
                {
                    return Err(SessionError::Denied.into());
                }
                if documents.iter().any(|kind| {
                    matches!(
                        kind,
                        DocumentRequest::AccessibilityTree | DocumentRequest::NetworkTree
                    )
                }) {
                    return Err(
                        SessionError::Unsupported("explicit Session AX/network Documents").into(),
                    );
                }
            }
        }
        #[cfg(feature = "browser")]
        {
            use crate::internal::policy::policy::{AddressableByteLimit, MaximumElapsed};
            let mut policy = self.policy.clone();
            let maximum = u64::try_from(work.timeout().as_micros())
                .map_err(|_| SessionError::InvalidPolicy)?;
            policy.request.maximum_elapsed = MaximumElapsed::try_from(
                policy
                    .request
                    .maximum_elapsed
                    .as_microseconds()
                    .min(maximum),
            )
            .map_err(|_| SessionError::InvalidPolicy)?;
            let bytes =
                u64::try_from(work.observation_limit()).map_err(|_| SessionError::InvalidPolicy)?;
            policy.request.browser.dom_utf8_bytes = AddressableByteLimit::try_from(
                policy.request.browser.dom_utf8_bytes.get().min(bytes),
            )
            .map_err(|_| SessionError::InvalidPolicy)?;
            let deadline = timing::deadline()
                .or_else(|| {
                    timing::checked_deadline(Duration::from_micros(
                        policy.request.maximum_elapsed.as_microseconds(),
                    ))
                })
                .ok_or(SessionError::InvalidPolicy)?;
            let execution = work.execution_permit(deadline).await?;
            work.control
                .check_authority()
                .map_err(|_| SessionError::Closed)?;
            let remaining = u64::try_from(
                deadline
                    .saturating_duration_since(tokio_time::Instant::now())
                    .as_micros(),
            )
            .map_err(|_| SessionError::InvalidPolicy)?;
            if remaining == 0 {
                return Err(SessionError::Deadline.into());
            }
            policy.request.maximum_elapsed = MaximumElapsed::try_from(
                policy
                    .request
                    .maximum_elapsed
                    .as_microseconds()
                    .min(remaining),
            )
            .map_err(|_| SessionError::InvalidPolicy)?;

            let mut dispatch = DispatchFence {
                control: &work.control,
                unresolved: true,
            };
            let sent = self
                .request
                .send_on_browser_control(&policy, &work.control, cancellation)
                .await;
            let response = match sent {
                Ok(response) => response,
                Err(error) => {
                    // RequestSendError contains preparation/setup failures before execution.
                    dispatch.unresolved = false;
                    return Err(error.into());
                }
            };
            // A returned Response has authoritative per-attempt finalization.
            // Dropping the future before this point leaves the tab fenced.
            let settled = response.attempts().all(|attempt| {
                attempt.inner.result().is_some_and(|result| {
                    matches!(
                        result.transport(),
                        internal_engine::AttemptTransportOutcome::Browser {
                            cleanup: internal_web_capture::CleanupState::Complete,
                            ..
                        }
                    ) && matches!(
                        result.capture_facts().observation().termination(),
                        internal_web_capture::CaptureTermination::Settled(_)
                            | internal_web_capture::CaptureTermination::ControllerStopped(_)
                    )
                })
            });
            dispatch.unresolved = !settled;
            drop(execution);
            let states = response
                .attempts()
                .map(request::Attempt::state)
                .collect::<Vec<_>>();
            let documents = response
                .attempts()
                .flat_map(request::Attempt::documents)
                .collect::<Vec<_>>();
            let produced = documents
                .iter()
                .filter(|document| {
                    matches!(document.outcome(), request::DocumentOutcome::Produced(_))
                })
                .count();
            let succeeded = settled
                && states
                    .iter()
                    .all(|state| *state == request::AttemptState::Completed)
                && produced == documents.len();
            let completed = states
                .iter()
                .filter(|state| **state == request::AttemptState::Completed)
                .count();
            let capture_ids = response
                .attempts()
                .map(|attempt| attempt.capture_id().to_string())
                .collect::<Vec<_>>();
            let receipt = OperationReceipt {
                id: new_operation_id(),
                kind: "request".into(),
                status: if succeeded {
                    OperationStatus::Observed
                } else {
                    OperationStatus::Unknown
                },
                result: Some(
                    serde_json::json!({"request_id":response.request_id().to_string(),"capture_ids":capture_ids,"attempts":states.len(),"completed":completed,"documents":documents.len(),"produced":produced,"all_completed":succeeded}),
                ),
                observation: work.observe_inner().await.ok(),
                error: if succeeded {
                    None
                } else {
                    Some("browser acquisition failed or was interrupted".into())
                },
            };
            drop(dispatch);
            work.session.publish(&receipt);
            Ok(response)
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = cancellation;
            Err(SessionError::BrowserFeatureDisabled.into())
        }
    }
}

#[derive(Clone, Debug)]
pub struct SessionBuilder {
    policy: Policy,
    settings: SessionPolicy,
    configured: bool,
    execution_pool: Option<ExecutionPool>,
}
impl SessionBuilder {
    /// Explicitly permits arbitrary JavaScript through Work evaluation methods.
    /// Browser acquisition mode remains selected by the bound Policy.
    pub fn allow_javascript(mut self) -> Self {
        self.settings.allow_arbitrary_js = true;
        if !self
            .settings
            .allowed_actions
            .contains(&ActionKind::Evaluate)
        {
            self.settings.allowed_actions.push(ActionKind::Evaluate);
        }
        self
    }
    /// Shares controller capacity across Sessions/browser processes. Without this,
    /// the Session creates its own pool using its execution policy limits.
    pub fn execution_pool(mut self, pool: &ExecutionPool) -> Self {
        self.execution_pool = Some(pool.clone());
        self
    }
    pub fn bind(mut self, policy: &Policy) -> Self {
        self.policy = policy.clone();
        if !self.configured
            && let Some(mode) =
                policy
                    .page
                    .acquisitions
                    .iter()
                    .find_map(|acquisition| match acquisition.kind() {
                        internal_policy_policy::AcquisitionKind::Browser { mode } => Some(mode),
                        internal_policy_policy::AcquisitionKind::DirectHttp => None,
                    })
        {
            self.settings.mode = mode;
        }
        self
    }
    pub fn configure(mut self, settings: SessionPolicy) -> Self {
        self.settings = settings;
        self.configured = true;
        self
    }
    pub async fn acquire(self) -> Result<Session, SessionError> {
        self.acquire_cancellable(&CancellationToken::new()).await
    }
    pub async fn acquire_cancellable(
        self,
        cancellation: &CancellationToken,
    ) -> Result<Session, SessionError> {
        self.settings.validate()?;
        let execution = match self.execution_pool {
            Some(pool) => pool,
            None => ExecutionPool::new(
                self.settings.execution_concurrency,
                self.settings.maximum_queued_operations,
            )?,
        };
        if self
            .policy
            .page
            .acquisitions
            .iter()
            .any(|acquisition| match acquisition.kind() {
                internal_policy_policy::AcquisitionKind::Browser { mode } => {
                    mode != self.settings.mode
                }
                internal_policy_policy::AcquisitionKind::DirectHttp => false,
            })
        {
            return Err(SessionError::InvalidPolicy);
        }
        self.policy
            .validate()
            .map_err(|_| SessionError::InvalidPolicy)?;
        #[cfg(feature = "browser")]
        {
            let acquiring = cancellation.child_token();
            let _acquisition_guard = acquiring.clone().drop_guard();
            // Startup uses the acquisition Policy budget, not a tiny per-Work IO bound.
            let maximum =
                Duration::from_micros(self.policy.request.maximum_elapsed.as_microseconds());
            let backend = tokio_time::timeout(
                maximum,
                internal_engine_session::BrowserSession::acquire(
                    self.settings.mode,
                    self.settings.maximum_tabs,
                    false,
                    &acquiring,
                ),
            )
            .await
            .map_err(|_| SessionError::AcquisitionDeadline)?
            .map_err(|_| {
                if cancellation.is_cancelled() {
                    SessionError::Cancelled
                } else {
                    SessionError::Admission
                }
            })?;
            let (events, _) = broadcast::channel(self.settings.watch_capacity);
            Ok(Session {
                inner: Arc::new(SessionInner {
                    policy: self.policy,
                    settings: self.settings,
                    backend,
                    events,
                    execution,
                }),
            })
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = cancellation;
            let _ = execution;
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
}

struct SessionInner {
    execution: ExecutionPool,
    policy: Policy,
    settings: SessionPolicy,
    #[cfg(feature = "browser")]
    backend: internal_engine_session::BrowserSession,
    events: broadcast::Sender<Arc<OperationReceipt>>,
}
#[derive(Clone)]
pub struct Session {
    inner: Arc<SessionInner>,
}
impl std_fmt::Debug for Session {
    fn fmt(&self, f: &mut std_fmt::Formatter<'_>) -> std_fmt::Result {
        f.debug_struct("Session")
            .field("settings", &self.inner.settings)
            .finish_non_exhaustive()
    }
}
impl Session {
    /// Independent active/queued/parked counts. A shared pool aggregates Sessions.
    pub fn execution_snapshot(&self) -> ExecutionSnapshot {
        self.inner.execution.snapshot()
    }
    fn request_policy(&self) -> Policy {
        use crate::internal::policy::policy::{Acquisition, DocumentRequest};
        let mut policy = self.inner.policy.clone();
        let documents = if self.settings().dom {
            vec![DocumentRequest::RenderedDom]
        } else {
            Vec::new()
        };
        policy.page.acquisitions =
            vec![Acquisition::Browser(self.settings().mode).documents(documents)];
        policy
    }
    pub fn policy(&self) -> &Policy {
        &self.inner.policy
    }
    pub fn settings(&self) -> &SessionPolicy {
        &self.inner.settings
    }
    pub async fn work(&self) -> Result<Work, SessionError> {
        #[cfg(feature = "browser")]
        {
            self.work_on(self.inner.backend.initial_tab()).await
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    #[cfg(feature = "browser")]
    async fn work_on(
        &self,
        tab: internal_web_capture::RuntimeBrowserTabLease,
    ) -> Result<Work, SessionError> {
        let control = self
            .inner
            .backend
            .control(&tab, self.timeout())
            .await
            .map_err(|_| SessionError::Admission)?;
        Ok(Work {
            session: self.clone(),
            tab_id: tab.id().to_string(),
            control,
            operations: tokio_sync::Mutex::new(()),
        })
    }
    pub async fn new_tab(&self) -> Result<Tab, SessionError> {
        #[cfg(feature = "browser")]
        {
            let lease = self
                .inner
                .backend
                .new_tab()
                .await
                .map_err(|_| SessionError::Admission)?;
            Ok(Tab {
                session: self.clone(),
                lease,
            })
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    pub fn watch(&self) -> Watcher {
        Watcher {
            session: self.clone(),
            receiver: self.inner.events.subscribe(),
        }
    }
    pub fn cancel(&self) {
        #[cfg(feature = "browser")]
        self.inner.backend.cancellation().cancel();
    }
    pub async fn close(&self) -> Result<(), SessionError> {
        #[cfg(feature = "browser")]
        {
            self.inner
                .backend
                .close()
                .await
                .map_err(|_| SessionError::Cleanup)
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    fn timeout(&self) -> Duration {
        Duration::from_millis(self.inner.settings.operation_timeout_ms).min(Duration::from_micros(
            self.inner.policy.request.maximum_elapsed.as_microseconds(),
        ))
    }
    fn publish(&self, receipt: &OperationReceipt) {
        let _ = self.inner.events.send(Arc::new(receipt.clone()));
    }
}

pub struct Tab {
    session: Session,
    #[cfg(feature = "browser")]
    lease: internal_web_capture::RuntimeBrowserTabLease,
}
impl std_fmt::Debug for Tab {
    fn fmt(&self, formatter: &mut std_fmt::Formatter<'_>) -> std_fmt::Result {
        formatter.debug_struct("Tab").finish_non_exhaustive()
    }
}
impl Tab {
    /// Closes only this tab and revokes any held control; other tabs remain usable.
    pub async fn close(&self) -> Result<(), SessionError> {
        #[cfg(feature = "browser")]
        {
            self.lease.close().await.map_err(|_| SessionError::Cleanup)
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    pub async fn work(&self) -> Result<Work, SessionError> {
        #[cfg(feature = "browser")]
        {
            self.session.work_on(self.lease.clone()).await
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
}

pub struct Watcher {
    session: Session,
    receiver: broadcast::Receiver<Arc<OperationReceipt>>,
}
impl std_fmt::Debug for Watcher {
    fn fmt(&self, formatter: &mut std_fmt::Formatter<'_>) -> std_fmt::Result {
        formatter.debug_struct("Watcher").finish_non_exhaustive()
    }
}
impl Watcher {
    /// Bounded evidence delivery; no mutation/control handles are exposed.
    pub async fn next(&mut self) -> Result<Arc<OperationReceipt>, SessionError> {
        #[cfg(feature = "browser")]
        let cancellation = self.session.inner.backend.cancellation();
        #[cfg(feature = "browser")]
        let received = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(SessionError::Cancelled),
            value = tokio_time::timeout(self.session.timeout(), self.receiver.recv()) => value,
        };
        #[cfg(not(feature = "browser"))]
        let received = tokio::time::timeout(self.session.timeout(), self.receiver.recv()).await;
        match received {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(broadcast::error::RecvError::Lagged(count))) => {
                Err(SessionError::WatchLagged(count))
            }
            Ok(Err(broadcast::error::RecvError::Closed)) => Err(SessionError::Closed),
            Err(_) => Err(SessionError::WatchDeadline),
        }
    }
    pub fn close(self) {
        drop(self);
    }
}

pub struct Work {
    session: Session,
    tab_id: String,
    operations: tokio_sync::Mutex<()>,
    #[cfg(feature = "browser")]
    pub(crate) control: internal_web_capture::RuntimeBrowserControl,
}

#[cfg(feature = "browser")]
struct DispatchFence<'a> {
    control: &'a internal_web_capture::RuntimeBrowserControl,
    unresolved: bool,
}
#[cfg(feature = "browser")]
impl Drop for DispatchFence<'_> {
    fn drop(&mut self) {
        if self.unresolved {
            self.control.fence();
        }
    }
}
impl std_fmt::Debug for Work {
    fn fmt(&self, f: &mut std_fmt::Formatter<'_>) -> std_fmt::Result {
        f.debug_struct("Work")
            .field("tab_id", &self.tab_id)
            .finish_non_exhaustive()
    }
}
impl Work {
    pub(crate) fn session_cancelled(&self) -> bool {
        #[cfg(feature = "browser")]
        {
            self.session.inner.backend.cancellation().is_cancelled()
        }
        #[cfg(not(feature = "browser"))]
        {
            false
        }
    }

    pub(crate) async fn scoped<T>(
        &self,
        policy: &Policy,
        future: impl std_future::Future<Output = T>,
    ) -> Result<T, SessionError> {
        policy.validate().map_err(|_| SessionError::InvalidPolicy)?;
        if policy
            .page
            .acquisitions
            .iter()
            .any(|acquisition| match acquisition.kind() {
                internal_policy_policy::AcquisitionKind::Browser { mode } => {
                    mode != self.session.settings().mode
                }
                internal_policy_policy::AcquisitionKind::DirectHttp => false,
            })
        {
            return Err(SessionError::InvalidPolicy);
        }
        Ok(SCOPED_POLICY.scope(policy.clone(), future).await)
    }
    fn timeout(&self) -> Duration {
        if let Some(remaining) = timing::remaining() {
            return remaining;
        }
        SCOPED_POLICY
            .try_with(|policy| {
                Duration::from_micros(policy.request.maximum_elapsed.as_microseconds())
            })
            .map_or_else(
                |_| self.session.timeout(),
                |scope| self.session.timeout().min(scope),
            )
    }
    /// Default used by a Flow that borrows this Work without a bound Policy.
    /// A Policy explicitly bound to the Flow selects its own root fallback.
    pub(crate) fn default_action_timeout(&self) -> Duration {
        Duration::from_millis(self.session.policy().default_action_timeout_ms)
    }
    pub(crate) fn flow_policy(&self) -> &internal_policy_policy::FlowPolicy {
        &self.session.policy().flow
    }
    fn observation_limit(&self) -> usize {
        let base = self.session.settings().maximum_observation_bytes.min(
            self.session
                .policy()
                .request
                .browser
                .dom_utf8_bytes
                .as_usize()
                .unwrap_or(0),
        );
        SCOPED_POLICY
            .try_with(|policy| {
                policy
                    .request
                    .browser
                    .dom_utf8_bytes
                    .as_usize()
                    .unwrap_or(0)
            })
            .map_or(base, |scope| base.min(scope))
    }
    fn operation(&self) -> Result<tokio_sync::MutexGuard<'_, ()>, SessionError> {
        // A held Work is an ordered controller, not an additional unbounded queue.
        self.operations
            .try_lock()
            .map_err(|_| SessionError::Admission)
    }
    fn authorize(&self, kind: ActionKind, input: &str) -> Result<(), SessionError> {
        if timing::remaining().is_some_and(|remaining| remaining.is_zero()) {
            return Err(SessionError::Deadline);
        }
        if SCOPED_CANCELLATION
            .try_with(CancellationToken::is_cancelled)
            .unwrap_or(false)
        {
            return Err(SessionError::Cancelled);
        }
        #[cfg(feature = "browser")]
        if self.session.inner.backend.cancellation().is_cancelled() {
            return Err(SessionError::Cancelled);
        }
        #[cfg(feature = "browser")]
        self.control
            .check_authority()
            .map_err(|_| SessionError::Closed)?;
        if input.len() > self.session.settings().maximum_input_bytes {
            return Err(SessionError::InvalidInput);
        }
        if !self.session.settings().allowed_actions.contains(&kind)
            || (kind == ActionKind::Evaluate && !self.session.settings().allow_arbitrary_js)
        {
            return Err(SessionError::Denied);
        }
        Ok(())
    }
    #[cfg(feature = "browser")]
    async fn call<T>(
        &self,
        future: impl std_future::Future<Output = Result<T, internal_web_capture::BrowserControlError>>,
    ) -> Result<T, SessionError> {
        self.call_with_capacity(future, true).await
    }
    #[cfg(feature = "browser")]
    async fn execution_permit(
        &self,
        deadline: tokio_time::Instant,
    ) -> Result<internal_engine_execution::ExecutionPermit, SessionError> {
        let cancel = self.session.inner.backend.cancellation();
        let closing = self.control.closing();
        let scoped = SCOPED_CANCELLATION
            .try_with(Clone::clone)
            .unwrap_or_default();
        tokio::select! {
            biased;
            () = scoped.cancelled() => Err(SessionError::Cancelled),
            () = cancel.cancelled() => Err(SessionError::Cancelled),
            () = closing.cancelled() => Err(SessionError::Closed),
            result = tokio_time::timeout_at(deadline, self.session.inner.execution.acquire()) =>
                result.map_err(|_| SessionError::Deadline)?.map_err(SessionError::from),
        }
    }
    #[cfg(feature = "browser")]
    async fn call_with_capacity<T>(
        &self,
        future: impl std_future::Future<Output = Result<T, internal_web_capture::BrowserControlError>>,
        active: bool,
    ) -> Result<T, SessionError> {
        if self.timeout().is_zero() {
            return Err(SessionError::Deadline);
        }
        let deadline = timing::deadline()
            .or_else(|| timing::checked_deadline(self.timeout()))
            .ok_or(SessionError::InvalidInput)?;
        let _permit = if active {
            Some(self.execution_permit(deadline).await?)
        } else {
            None
        };
        self.control
            .check_authority()
            .map_err(|_| SessionError::Closed)?;
        let cancel = self.session.inner.backend.cancellation();
        let closing = self.control.closing();
        let scoped = SCOPED_CANCELLATION
            .try_with(Clone::clone)
            .unwrap_or_default();
        // Dropping/timing out a dispatched future cannot hand an uncertain tab
        // to another controller. The caller must close that tab/session.

        let mut dispatch = DispatchFence {
            control: &self.control,
            unresolved: true,
        };
        tokio::select! {
            biased;
            () = scoped.cancelled() => Err(SessionError::Unknown),
            () = cancel.cancelled() => Err(SessionError::Unknown),
            () = closing.cancelled() => Err(SessionError::Unknown),
            result = tokio_time::timeout_at(deadline, future) => result.map_or_else(
                |_| Err(SessionError::TimeoutAfterDispatch),
                |result| {
                    dispatch.unresolved = result.as_ref().err().is_some_and(internal_web_capture::BrowserControlError::requires_fence);
                    result.map_err(|error| match error {
                        internal_web_capture::BrowserControlError::InputTargetLost => SessionError::InputTargetLost,
                        error => SessionError::Execution(error.execution_message()),
                    })
                }),
        }
    }
    pub async fn observe(&self) -> Result<Observation, SessionError> {
        let _operation = self.operation()?;
        self.observe_inner().await
    }
    async fn observe_inner(&self) -> Result<Observation, SessionError> {
        #[cfg(feature = "browser")]
        {
            if self.session.inner.backend.cancellation().is_cancelled() {
                return Err(SessionError::Cancelled);
            }
            self.control
                .check_authority()
                .map_err(|_| SessionError::Closed)?;
            let (html, epoch) = if self.session.settings().dom {
                let (html, epoch) = self
                    .call(self.control.dom(self.observation_limit()))
                    .await
                    .map_err(|_| SessionError::EvidenceUnavailable)?;
                (Some(html), epoch)
            } else {
                (None, self.call(self.control.document_epoch()).await?)
            };
            let url = self.call(self.control.url()).await?;
            Ok(Observation {
                id: new_operation_id(),
                session_id: self.session.inner.backend.id(),
                tab_id: self.tab_id.clone(),
                document_epoch: epoch,
                html,
                url,
                screenshot: None,
            })
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    async fn receipt(
        &self,
        kind: &str,
        operation: Result<serde_json::Value, SessionError>,
    ) -> Result<OperationReceipt, SessionError> {
        let (mut status, result, mut error) = match operation {
            Ok(value) => (OperationStatus::Observed, Some(value), None),
            Err(error) => (
                if error.is_unknown() {
                    OperationStatus::Unknown
                } else {
                    OperationStatus::Rejected
                },
                None,
                Some(error.to_string()),
            ),
        };
        let observation = match self.observe_inner().await {
            Ok(observation) => Some(observation),
            Err(capture_error) => {
                if status == OperationStatus::Observed {
                    status = OperationStatus::Unknown;
                    error = Some(format!(
                        "command returned; post-operation evidence unavailable: {capture_error}"
                    ));
                }
                None
            }
        };
        let receipt = OperationReceipt {
            id: new_operation_id(),
            kind: kind.into(),
            status,
            result,
            observation,
            error,
        };
        self.session.publish(&receipt);
        Ok(receipt)
    }
    pub async fn navigate(&self, url: &str) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Navigate, url)?;
        request::new(url)
            .validate()
            .map_err(|_| SessionError::InvalidInput)?;
        #[cfg(feature = "browser")]
        {
            let result = self
                .call(self.control.navigate(url, self.timeout()))
                .await
                .map(|()| serde_json::Value::Null);
            self.receipt("navigate", result).await
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    #[cfg(feature = "browser")]
    async fn unique_target(&self, selector: &str) -> Result<(), SessionError> {
        let selector = serde_json::to_string(selector).map_err(|_| SessionError::InvalidInput)?;
        let value = self
            .call(
                self.control
                    .evaluate_json(&format!("document.querySelectorAll({selector}).length")),
            )
            .await?;
        if value.as_u64() != Some(1) {
            return Err(SessionError::InvalidInput);
        }
        Ok(())
    }
    pub async fn click(&self, selector: &str) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Click, selector)?;
        #[cfg(feature = "browser")]
        {
            self.unique_target(selector).await?;
            let result = self
                .call(self.control.click(selector))
                .await
                .map(|()| serde_json::Value::Null);
            self.receipt("click", result).await
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    /// Captures once, validates one Contract record, and checks it immediately.
    pub async fn assert_all(
        &self,
        assertion: &assertions::LocalAssertion,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Assert, "")?;
        assertion
            .validate(self.session.settings().maximum_input_bytes)
            .map_err(|_| SessionError::InvalidInput)?;
        if !assertion.is_bound() {
            return Err(SessionError::Unsupported("unbound local Rust checks"));
        }
        #[cfg(feature = "browser")]
        {
            let deadline = timing::deadline()
                .or_else(|| tokio_time::Instant::now().checked_add(self.timeout()))
                .ok_or(SessionError::InvalidInput)?;
            let observation = self.observe_inner().await?;
            let html = observation
                .html
                .as_ref()
                .ok_or(SessionError::EvidenceUnavailable)?;
            let policy = SCOPED_POLICY
                .try_with(Clone::clone)
                .unwrap_or_else(|_| self.session.policy().clone());
            let document = documents::Document::observed_dom(
                observation.id.clone(),
                observation.document_epoch,
                html.as_bytes().to_vec(),
                &policy,
            )
            .map_err(|_| SessionError::EvidenceUnavailable)?;
            let report = self
                .await_assertion(assertion, &document, &policy, deadline)
                .await?;
            let stopped = self.session.inner.backend.cancellation().is_cancelled()
                || SCOPED_CANCELLATION
                    .try_with(CancellationToken::is_cancelled)
                    .unwrap_or(false);
            if stopped {
                return Err(SessionError::Cancelled);
            }
            if tokio_time::Instant::now() >= deadline {
                return Err(SessionError::Deadline);
            }
            let passed = report.passed;
            let result =
                serde_json::to_value(report).map_err(|_| SessionError::EvidenceUnavailable)?;
            if serde_json::to_vec(&result)
                .map_err(|_| SessionError::EvidenceUnavailable)?
                .len()
                > self.session.settings().maximum_result_bytes
            {
                return Err(SessionError::ResultLimit {
                    maximum: self.session.settings().maximum_result_bytes,
                });
            }
            let receipt = OperationReceipt {
                id: new_operation_id(),
                kind: "assert_all".into(),
                status: if passed {
                    OperationStatus::Observed
                } else {
                    OperationStatus::Rejected
                },
                result: Some(result),
                observation: Some(observation),
                error: if passed {
                    None
                } else {
                    Some("assertion group did not pass".into())
                },
            };
            self.session.publish(&receipt);
            Ok(receipt)
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }

    #[cfg(feature = "browser")]
    pub(crate) async fn await_assertion(
        &self,
        assertion: &LocalAssertion,
        document: &Document,
        policy: &Policy,
        deadline: Instant,
    ) -> Result<AssertionReport, SessionError> {
        let scoped = SCOPED_CANCELLATION
            .try_with(Clone::clone)
            .unwrap_or_default();
        let session = self.session.inner.backend.cancellation();
        let evaluation = assertion.evaluate(
            document,
            policy,
            self.session.settings().maximum_input_bytes,
            self.session.settings().maximum_result_bytes,
        );
        tokio::pin!(evaluation);
        tokio::select! {
            biased;
            () = scoped.cancelled() => Err(SessionError::Cancelled),
            () = session.cancelled() => Err(SessionError::Cancelled),
            () = sleep_until(deadline) => Err(SessionError::Deadline),
            result = &mut evaluation => result
                .map_err(|error| SessionError::AssertionEvaluation(error.to_string())),
        }
    }
    pub async fn enter_text(
        &self,
        selector: &str,
        text: &str,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::EnterText, selector)?;
        self.authorize(ActionKind::EnterText, text)?;
        #[cfg(feature = "browser")]
        {
            self.unique_target(selector).await?;
            let result = self
                .call(self.control.enter_text(selector, text))
                .await
                .map(|()| serde_json::Value::Null);
            self.receipt("enter_text", result).await
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    pub async fn screenshot(&self) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Screenshot, "")?;
        #[cfg(feature = "browser")]
        {
            let bytes = self.call(self.control.screenshot()).await?;
            if bytes.len() > automation_record::MAX_OBSERVATION_SCREENSHOT_BYTES {
                let receipt = OperationReceipt {
                    id: new_operation_id(),
                    kind: "screenshot".into(),
                    status: OperationStatus::Rejected,
                    result: Some(
                        serde_json::json!({"captured_bytes":bytes.len(),"maximum_bytes":automation_record::MAX_OBSERVATION_SCREENSHOT_BYTES}),
                    ),
                    observation: self.observe_inner().await.ok(),
                    error: Some(
                        "screenshot was captured but exceeds the retained artifact byte limit"
                            .into(),
                    ),
                };
                self.session.publish(&receipt);
                return Ok(receipt);
            }
            let mut observation = self.observe_inner().await?;
            observation.screenshot = Some(bytes);
            let receipt = OperationReceipt {
                id: new_operation_id(),
                kind: "screenshot".into(),
                status: OperationStatus::Observed,
                result: None,
                observation: Some(observation),
                error: None,
            };
            self.session.publish(&receipt);
            Ok(receipt)
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    pub async fn wait(&self, milliseconds: u64) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Wait, "")?;
        let remaining = self.timeout();
        if remaining.is_zero() {
            return Err(SessionError::Deadline);
        }
        let wait_duration = Duration::from_millis(milliseconds);
        // Intentional Flow delay, never a readiness heuristic.
        let scoped = SCOPED_CANCELLATION
            .try_with(Clone::clone)
            .unwrap_or_default();
        #[cfg(feature = "browser")]
        let cancellation = self.session.inner.backend.cancellation();
        #[cfg(feature = "browser")]
        tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(SessionError::Cancelled),
            () = scoped.cancelled() => return Err(SessionError::Cancelled),
            result = tokio_time::timeout(remaining, tokio_time::sleep(wait_duration)) => {
                if result.is_err() {
                    return Err(SessionError::Deadline);
                }
            },
        }
        #[cfg(not(feature = "browser"))]
        if crate::timing::bound(remaining, tokio::time::sleep(wait_duration))
            .await
            .is_err()
        {
            return Err(SessionError::Deadline);
        }
        self.receipt("wait", Ok(serde_json::Value::Null)).await
    }
    pub async fn assert_condition(
        &self,
        condition: &Condition,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Assert, "")?;
        #[cfg(feature = "browser")]
        {
            let expression = match condition {
                Condition::Visible { .. } => condition_expression(condition)?,
                Condition::Exists { selector } | Condition::CountAtLeast { selector, .. } => {
                    let selector =
                        serde_json::to_string(selector).map_err(|_| SessionError::InvalidInput)?;
                    format!("document.querySelectorAll({selector}).length")
                }
            };
            let actual = self.call(self.control.evaluate_json(&expression)).await?;
            let passed = match condition {
                Condition::Visible { .. } => {
                    actual.as_bool().ok_or(SessionError::EvidenceUnavailable)?
                }
                Condition::Exists { .. } => {
                    actual.as_u64().ok_or(SessionError::EvidenceUnavailable)? > 0
                }
                Condition::CountAtLeast { count, .. } => {
                    actual.as_u64().ok_or(SessionError::EvidenceUnavailable)? >= *count
                }
            };
            self.check_receipt(
                "assert",
                serde_json::json!({"passed":passed,"expected":condition,"actual":actual}),
                passed,
            )
            .await
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = condition;
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    #[expect(
        clippy::significant_drop_tightening,
        reason = "The dispatch/settlement fence must cover cancellation and the complete operation, including cleanup and evidence capture."
    )]
    pub async fn wait_until(
        &self,
        condition: &Condition,
        timeout_ms: u64,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Wait, "")?;
        if timeout_ms == 0 {
            return Err(SessionError::InvalidInput);
        }
        #[cfg(feature = "browser")]
        {
            let expression = condition_expression(condition)?;
            let deadline = timing::deadline()
                .or_else(|| timing::checked_deadline(self.timeout()))
                .ok_or(SessionError::InvalidInput)?;
            timing::scope(deadline, async {
                let original_epoch = self.call(self.control.document_epoch()).await?;
                let mut waiting = self.call(self.control.start_condition_wait(
                    &expression, Duration::from_millis(timeout_ms).min(self.timeout()),
                )).await?;

                let mut settlement = DispatchFence { control: &self.control, unresolved: true };
                let parked = self.session.inner.execution.condition_wait(self.session.settings().yield_on_wait);
                let result = self.call_with_capacity(async {
                    waiting.finish().await.map_err(|_| internal_web_capture::BrowserControlError::ConditionWaitLost)
                }, !self.session.settings().yield_on_wait).await?;
                drop(parked);
                let resumed_epoch = self.call(self.control.document_epoch()).await.map_err(|error| {
                    if matches!(error, SessionError::Deadline) { SessionError::TimeoutAfterDispatch } else { SessionError::Unknown }
                })?;
                if original_epoch != resumed_epoch {
                    self.control.fence();
                    return Err(SessionError::Unknown);
                }
                let receipt = self.check_receipt_in_document(
                    "wait_until",
                    serde_json::json!({"passed":result,"expected":condition,"document_epoch":original_epoch,"yielded":self.session.settings().yield_on_wait}),
                    result,
                    Some(original_epoch),
                ).await?;
                settlement.unresolved = receipt.status == OperationStatus::Unknown || receipt.observation.is_none();
                Ok(receipt)
            }).await
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = condition;
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
    #[expect(
        clippy::unused_async,
        clippy::unused_async_trait_impl,
        reason = "Keep the public async lifecycle contract; dropping Work releases its owned control."
    )]
    pub async fn release(self) -> Result<(), SessionError> {
        drop(self);
        Ok(())
    }

    async fn check_receipt(
        &self,
        kind: &str,
        result: serde_json::Value,
        passed: bool,
    ) -> Result<OperationReceipt, SessionError> {
        self.check_receipt_in_document(kind, result, passed, None)
            .await
    }
    async fn check_receipt_in_document(
        &self,
        kind: &str,
        result: serde_json::Value,
        passed: bool,
        expected_epoch: Option<u64>,
    ) -> Result<OperationReceipt, SessionError> {
        let capture = self.observe_inner().await;
        let invalidated = expected_epoch.is_some_and(|epoch| {
            capture
                .as_ref()
                .is_ok_and(|observation| observation.document_epoch != epoch)
        });
        let complete = capture.is_ok() && !invalidated;
        let receipt = OperationReceipt {
            id: new_operation_id(),
            kind: kind.into(),
            status: if invalidated {
                OperationStatus::Unknown
            } else if !passed {
                OperationStatus::Rejected
            } else if complete {
                OperationStatus::Observed
            } else {
                OperationStatus::Unknown
            },
            result: Some(result),
            observation: capture.ok(),
            error: if invalidated {
                Some(
                    "confirmation belongs to a different document than the parked condition".into(),
                )
            } else if !passed {
                Some("condition was not satisfied".into())
            } else if !complete {
                Some("condition returned true; post-operation evidence unavailable".into())
            } else {
                None
            },
        };
        self.session.publish(&receipt);
        Ok(receipt)
    }
}

#[cfg(feature = "browser")]
fn condition_expression(condition: &Condition) -> Result<String, SessionError> {
    let selector = match condition {
        Condition::Exists { selector }
        | Condition::Visible { selector }
        | Condition::CountAtLeast { selector, .. } => selector,
    };
    if selector.is_empty() || selector.len() > 4096 {
        return Err(SessionError::InvalidInput);
    }
    let selector = serde_json::to_string(selector).map_err(|_| SessionError::InvalidInput)?;
    Ok(match condition {
        Condition::Exists { .. } => format!("document.querySelectorAll({selector}).length > 0"),
        Condition::CountAtLeast { count, .. } => {
            format!("document.querySelectorAll({selector}).length >= {count}")
        }
        Condition::Visible { .. } => format!(
            "Array.from(document.querySelectorAll({selector})).some(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')"
        ),
    })
}
