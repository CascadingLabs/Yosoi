use crate::documents;
use crate::session;
use crate::session::javascript as session_javascript;
use crate::timing;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::time as tokio_time;

use crate::internal::web_capture::{
    CompletedResponseCandidate, ObservationChange, ObservationResponseFilter, ObservationWatch,
    ObservationWatchOptions,
};
use serde_json::{Value, json};
use tokio::time::Instant;

use super::{UntilCheck, UntilCheckState, UntilReport, UntilScope, UntilTermination};
use crate::{
    assertions::SourceError,
    automation_record::{Observation, OperationReceipt, OperationStatus},
    expect::Expectation,
    flow::{Flow, Step},
    session::{
        ActionKind, DispatchFence, SCOPED_CANCELLATION, SCOPED_POLICY, SessionError, Work,
        new_operation_id,
    },
};

const OBSERVER_CLEANUP_BUDGET: Duration = Duration::from_secs(1);

impl Work {
    #[expect(
        clippy::significant_drop_tightening,
        reason = "The dispatch/settlement fence must cover cancellation and the complete operation, including cleanup and evidence capture."
    )]
    pub(super) async fn until_owned(
        &self,
        trigger: Option<&Step>,
        expected: &Expectation,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Assert, "")?;
        self.authorize(ActionKind::Wait, "")?;
        Flow::new([Step::Until {
            trigger: trigger.cloned().map(Box::new),
            expectation: expected.clone(),
        }])
        .validate()
        .map_err(|_| SessionError::InvalidInput)?;
        let leaves = leaves(expected);
        for leaf in &leaves {
            if let Expectation::Contract { assertion } = leaf
                && !assertion.is_bound()
            {
                return Err(SessionError::Unsupported("unbound local Rust checks"));
            }
        }
        let prepared = trigger
            .map(|step| self.prepare_until_trigger(step))
            .transpose()?;
        let deadline = timing::deadline()
            .or_else(|| timing::checked_deadline(self.timeout()))
            .ok_or(SessionError::InvalidInput)?;
        let epoch = self.call(self.control.document_epoch()).await?;
        let options = watch_options(
            &leaves,
            self.session.settings().watch_capacity,
            self.observation_limit(),
        );
        if leaves.iter().any(|leaf| {
            matches!(
                leaf,
                Expectation::Condition { .. } | Expectation::Contract { .. }
            )
        }) && !self.session.settings().dom
        {
            return Err(SessionError::Unsupported("DOM observation disabled"));
        }
        let mut watch = self
            .call(self.control.start_observation_watch(options))
            .await?;
        // Until acknowledged cleanup, dropping this invocation cannot return an
        // uncertain observer/trigger to another controller on this tab.

        let mut settlement = DispatchFence {
            control: &self.control,
            unresolved: true,
        };
        let mut report = UntilReport {
            version: 1,
            termination: UntilTermination::Unavailable,
            scope: UntilScope {
                protocol: self.browser_identity().map(|identity| identity.protocol),
                session_id: self.session.inner.backend.id(),
                tab_id: self.tab_id.clone(),
                document_epoch: epoch,
                frame_id: Some(watch.frame_id().to_owned()),
                loader_id: watch.loader_id().map(str::to_owned),
            },
            trigger: None,
            evaluations: 0,
            checks: leaves
                .iter()
                .enumerate()
                .map(|(index, leaf)| {
                    Ok(UntilCheck {
                        index: u64::try_from(index).map_err(|_| SessionError::InvalidInput)?,
                        source: source(leaf).into(),
                        state: UntilCheckState::Pending,
                        evidence: None,
                        error: None,
                    })
                })
                .collect::<Result<_, SessionError>>()?,
            error: None,
        };
        let mut observation = None;
        let execution = self
            .run_until(
                &mut watch,
                prepared.as_ref(),
                &leaves,
                deadline,
                &mut report,
                &mut observation,
            )
            .await;
        if let Err(error) = &execution {
            report.termination = match error {
                SessionError::Deadline | SessionError::WatchDeadline => UntilTermination::TimedOut,
                SessionError::Cancelled => UntilTermination::Cancelled,
                SessionError::InvalidPolicy
                | SessionError::InvalidInput
                | SessionError::Denied
                | SessionError::Unsupported(_) => UntilTermination::Rejected,
                _ => UntilTermination::Unavailable,
            };
            report.error = Some(error.to_string().chars().take(4096).collect());
        }

        // Cleanup gets its own bounded budget, independent of an expired or
        // cancelled action. It still participates in worker admission.
        let cleanup = tokio_time::timeout(OBSERVER_CLEANUP_BUDGET, async {
            let _permit = self
                .session
                .inner
                .execution
                .acquire()
                .await
                .map_err(SessionError::from)?;
            let original_scope = self.control.observation_scope_is_current(&watch).await;
            let settled = watch.settle().await;
            if matches!(original_scope, Ok(true)) && settled.is_ok() {
                Ok(())
            } else {
                Err(SessionError::Cleanup)
            }
        })
        .await;
        let cleaned = matches!(cleanup, Ok(Ok(())));
        if cleaned {
            settlement.unresolved = false;
        } else {
            self.control.fence();
            report.termination = UntilTermination::Unavailable;
            report.error = Some("observation cleanup did not establish safe settlement".into());
        }
        let uncertain = !cleaned
            || execution
                .as_ref()
                .err()
                .is_some_and(SessionError::is_unknown)
            || report
                .trigger
                .as_ref()
                .is_some_and(|receipt| receipt.status == OperationStatus::Unknown)
            || self.control.check_authority().is_err();
        if uncertain {
            self.control.fence();
            report.termination = UntilTermination::Unavailable;
            if report.error.is_none() {
                report.error = Some("tab authority or dispatched outcome is uncertain".into());
            }
        }
        let mut status = if uncertain {
            OperationStatus::Unknown
        } else if report.termination == UntilTermination::Satisfied {
            OperationStatus::Observed
        } else {
            OperationStatus::Rejected
        };
        let mut result =
            serde_json::to_value(&report).map_err(|_| SessionError::EvidenceUnavailable)?;
        if serde_json::to_vec(&result)
            .map_err(|_| SessionError::EvidenceUnavailable)?
            .len()
            > self.session.settings().maximum_result_bytes
        {
            // Do not turn oversized evidence into a successful confirmation.
            self.control.fence();
            status = OperationStatus::Unknown;
            report.termination = UntilTermination::Unavailable;
            report.error = Some("confirmation report exceeded its retained byte budget".into());
            for check in &mut report.checks {
                check.evidence = None;
                check.state = UntilCheckState::Unavailable;
                check.error = None;
            }
            // Keep the canonical trigger receipt intact. Its execution status
            // and watermark remain valid even when confirmation evidence fails.
            result =
                serde_json::to_value(&report).map_err(|_| SessionError::EvidenceUnavailable)?;
            if serde_json::to_vec(&result)
                .map_err(|_| SessionError::EvidenceUnavailable)?
                .len()
                > self.session.settings().maximum_result_bytes
            {
                return Err(SessionError::ResultLimit {
                    maximum: self.session.settings().maximum_result_bytes,
                });
            }
        }
        let receipt = OperationReceipt {
            browser: self.browser_identity(),
            id: new_operation_id(),
            kind: "until".into(),
            status,
            result: Some(result),
            observation,
            error: report.error.clone().or_else(|| {
                (status != OperationStatus::Observed)
                    .then(|| format!("until stopped: {:?}", report.termination))
            }),
        };
        self.session.publish(&receipt);
        Ok(receipt)
    }

    fn prepare_until_trigger(&self, trigger: &Step) -> Result<PreparedTrigger, SessionError> {
        match trigger {
            Step::Click { selector } => {
                self.authorize(ActionKind::Click, selector)?;
                Ok(PreparedTrigger::Click(selector.clone()))
            }
            Step::EnterText { selector, text } => {
                self.authorize(ActionKind::EnterText, selector)?;
                self.authorize(ActionKind::EnterText, text)?;
                Ok(PreparedTrigger::EnterText {
                    selector: selector.clone(),
                    text: text.clone(),
                })
            }
            Step::Evaluate { source } => {
                self.authorize(ActionKind::Evaluate, source)?;
                Ok(PreparedTrigger::Evaluate {
                    source: source.clone(),
                    kind: "evaluate",
                })
            }
            Step::EvaluateFile { snapshot } => {
                self.authorize(ActionKind::Evaluate, snapshot.source())?;
                Ok(PreparedTrigger::Evaluate {
                    source: snapshot.source().to_owned(),
                    kind: "evaluate_file",
                })
            }
            Step::EvaluateModule { bundle } => {
                self.authorize(ActionKind::Evaluate, "")?;
                let source = session_javascript::module_expression(
                    bundle,
                    self.session.settings().maximum_input_bytes,
                )?;
                Ok(PreparedTrigger::Evaluate {
                    source,
                    kind: "evaluate_module",
                })
            }
            _ => Err(SessionError::Unsupported("until trigger")),
        }
    }

    async fn dispatch_until_trigger(
        &self,
        trigger: &PreparedTrigger,
        watch: &ObservationWatch,
    ) -> Result<OperationReceipt, SessionError> {
        let deadline = timing::deadline().ok_or(SessionError::InvalidInput)?;
        let _permit = self.execution_permit(deadline).await?;
        if !self
            .call_with_capacity(self.control.observation_scope_is_current(watch), false)
            .await?
        {
            self.control.fence();
            return Err(SessionError::Unknown);
        }
        let started_at_unix_us = observed_at_micros()?;
        let (kind, result) = match trigger {
            PreparedTrigger::Click(selector) => (
                "click",
                self.call_with_capacity(
                    self.control.click_in_observation_scope(selector, watch),
                    false,
                )
                .await
                .map(|()| Value::Null),
            ),
            PreparedTrigger::EnterText { selector, text } => (
                "enter_text",
                self.call_with_capacity(
                    self.control
                        .enter_text_in_observation_scope(selector, text, watch),
                    false,
                )
                .await
                .map(|()| Value::Null),
            ),
            PreparedTrigger::Evaluate { source, kind } => (
                *kind,
                self.call_with_capacity(
                    self.control.evaluate_in_observation_scope(source, watch),
                    false,
                )
                .await,
            ),
        };
        let (status, result, error) = match result {
            Ok(value) => {
                if serde_json::to_vec(&value)
                    .map_err(|_| SessionError::EvidenceUnavailable)?
                    .len()
                    > self.session.settings().maximum_result_bytes / 2
                {
                    (
                        OperationStatus::Unknown,
                        None,
                        Some("trigger returned a result beyond the retained byte limit".into()),
                    )
                } else {
                    (
                        OperationStatus::Observed,
                        Some(json!({"value":value,"started_at_unix_us":started_at_unix_us})),
                        None,
                    )
                }
            }
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
        let receipt = OperationReceipt {
            browser: self.browser_identity(),
            id: new_operation_id(),
            kind: kind.into(),
            status,
            result,
            observation: None,
            error,
        };
        self.session.publish(&receipt);
        Ok(receipt)
    }

    async fn run_until(
        &self,
        watch: &mut ObservationWatch,
        trigger: Option<&PreparedTrigger>,
        leaves: &[&Expectation],
        deadline: Instant,
        report: &mut UntilReport,
        observation: &mut Option<Observation>,
    ) -> Result<(), SessionError> {
        let reserve = if trigger.is_some() { 256 } else { 64 };
        if report
            .encoded_size()
            .map_err(|_| SessionError::InvalidInput)?
            .checked_add(reserve)
            .is_none_or(|size| size > self.session.settings().maximum_result_bytes)
        {
            return Err(SessionError::InvalidPolicy);
        }
        self.require_until_scope(report.scope.document_epoch)
            .await?;
        if let Some(trigger) = trigger {
            let receipt = self.dispatch_until_trigger(trigger, watch).await?;
            let succeeded = receipt.status == OperationStatus::Observed;
            report.trigger = Some(receipt);
            if !succeeded {
                report.termination = UntilTermination::TriggerFailed;
                return Ok(());
            }
        }
        loop {
            self.authorize(ActionKind::Assert, "")?;
            self.require_until_scope(report.scope.document_epoch)
                .await?;
            report.evaluations = report
                .evaluations
                .checked_add(1)
                .ok_or(SessionError::InvalidInput)?;
            self.evaluate_until(leaves, deadline, report, observation)
                .await?;
            self.require_until_scope(report.scope.document_epoch)
                .await?;
            self.authorize(ActionKind::Assert, "")?;
            if report
                .checks
                .iter()
                .any(|check| check.state == UntilCheckState::Rejected)
            {
                report.termination = UntilTermination::Rejected;
                return Ok(());
            }
            if report
                .checks
                .iter()
                .any(|check| check.state == UntilCheckState::Unavailable)
            {
                report.termination = UntilTermination::Unavailable;
                return Ok(());
            }
            if report
                .checks
                .iter()
                .all(|check| check.state == UntilCheckState::Satisfied)
            {
                report.termination = UntilTermination::Satisfied;
                return Ok(());
            }
            let cancellation = self.session.inner.backend.cancellation();
            let scoped = SCOPED_CANCELLATION
                .try_with(Clone::clone)
                .unwrap_or_default();
            let closing = self.control.closing();
            let retained = if self.session.settings().yield_on_wait {
                None
            } else {
                Some(self.execution_permit(deadline).await?)
            };
            let parked = self
                .session
                .inner
                .execution
                .condition_wait(self.session.settings().yield_on_wait);
            let change = tokio::select! {
                biased;
                () = scoped.cancelled() => return Err(SessionError::Cancelled),
                () = cancellation.cancelled() => return Err(SessionError::Cancelled),
                () = closing.cancelled() => return Err(SessionError::Closed),
                event = tokio_time::timeout_at(deadline, watch.next()) => {
                    event.map_err(|_| SessionError::WatchDeadline)?.map_err(|error| SessionError::Execution(format!("parked observation failed: {error}")))?
                }
            };
            drop(parked);
            drop(retained);
            if let ObservationChange::ResponseCompleted(candidate) = change {
                self.capture_until_response(&candidate, leaves, report)
                    .await?;
            }
        }
    }

    async fn require_until_scope(&self, epoch: u64) -> Result<(), SessionError> {
        if self.call(self.control.document_epoch()).await? != epoch {
            self.control.fence();
            return Err(SessionError::Unknown);
        }
        Ok(())
    }

    async fn evaluate_until(
        &self,
        leaves: &[&Expectation],
        deadline: Instant,
        report: &mut UntilReport,
        observation: &mut Option<Observation>,
    ) -> Result<(), SessionError> {
        let needs_dom = leaves.iter().any(|leaf| {
            matches!(
                leaf,
                Expectation::Condition { .. } | Expectation::Contract { .. }
            )
        });
        let current = if needs_dom {
            self.observe_inner().await?
        } else {
            Observation {
                browser: self.browser_identity(),
                id: new_operation_id(),
                session_id: self.session.inner.backend.id(),
                tab_id: self.tab_id.clone(),
                document_epoch: self.call(self.control.document_epoch()).await?,
                html: None,
                url: self.call(self.control.url()).await?,
                screenshot: None,
            }
        };
        if current.document_epoch != report.scope.document_epoch {
            self.control.fence();
            return Err(SessionError::Unknown);
        }
        let policy = SCOPED_POLICY
            .try_with(Clone::clone)
            .unwrap_or_else(|_| self.session.policy().clone());
        let document = current
            .html
            .as_ref()
            .map(|html| {
                documents::Document::observed_dom(
                    current.id.clone(),
                    current.document_epoch,
                    html.as_bytes().to_vec(),
                    &policy,
                )
            })
            .transpose()
            .map_err(|_| SessionError::EvidenceUnavailable)?;
        let evidence_budget = self.until_evidence_budget(leaves.len());
        for (expected, check) in leaves.iter().zip(&mut report.checks) {
            match expected {
                Expectation::Condition { condition } => {
                    let expression = session::condition_expression(condition)?;
                    let actual = self.call(self.control.evaluate_json(&expression)).await?;
                    let passed = actual.as_bool().ok_or(SessionError::EvidenceUnavailable)?;
                    check.state = if passed {
                        UntilCheckState::Satisfied
                    } else {
                        UntilCheckState::Pending
                    };
                    check.evidence = Some(
                        json!({"expected":condition,"actual":passed,"observation_id":current.id,"document_epoch":current.document_epoch,"observed_at_unix_ms":observed_at()?}),
                    );
                }
                Expectation::Contract { assertion } => {
                    let document = document.as_ref().ok_or(SessionError::EvidenceUnavailable)?;
                    let result = self
                        .await_assertion(assertion, document, &policy, deadline)
                        .await?;
                    check.state = if result.checks.iter().any(|item| item.error.is_some()) {
                        UntilCheckState::Rejected
                    } else if result.passed {
                        UntilCheckState::Satisfied
                    } else {
                        match result.source_error {
                            None | Some(SourceError::RecordCount { actual: 0 }) => {
                                UntilCheckState::Pending
                            }
                            Some(SourceError::IncompleteEvidence) => UntilCheckState::Unavailable,
                            _ => UntilCheckState::Rejected,
                        }
                    };
                    check.evidence = Some(
                        json!({"report":result,"observation_id":current.id,"document_epoch":current.document_epoch,"observed_at_unix_ms":observed_at()?}),
                    );
                }
                Expectation::Accessibility { name, role } => {
                    let nodes = self
                        .call(self.control.query_accessibility(
                            name,
                            role.as_deref(),
                            evidence_budget,
                        ))
                        .await?;
                    let nodes = nodes.as_array().ok_or(SessionError::EvidenceUnavailable)?;
                    let matched: Vec<_> = nodes
                        .iter()
                        .filter(|node| node.get("ignored").and_then(Value::as_bool) == Some(false))
                        .cloned()
                        .collect();
                    check.state = if matched.is_empty() {
                        UntilCheckState::Pending
                    } else {
                        UntilCheckState::Satisfied
                    };
                    check.evidence = Some(
                        json!({"name":name,"role":role,"nodes":matched,"document_epoch":current.document_epoch,"observed_at_unix_ms":observed_at()?}),
                    );
                }
                Expectation::Response { .. } => {}
                Expectation::All { .. } => return Err(SessionError::InvalidInput),
            }
            if check.evidence.as_ref().is_some_and(|value| {
                serde_json::to_vec(value).map_or(true, |bytes| bytes.len() > evidence_budget)
            }) {
                check.state = UntilCheckState::Unavailable;
                check.evidence = None;
                check.error = Some("confirmation evidence exceeds its retained byte budget".into());
            }
        }
        *observation = Some(current);
        Ok(())
    }

    fn until_evidence_budget(&self, count: usize) -> usize {
        self.session
            .settings()
            .maximum_result_bytes
            .checked_div(2)
            .and_then(|size| size.checked_div(count.max(1)))
            .unwrap_or(0)
    }

    async fn capture_until_response(
        &self,
        candidate: &CompletedResponseCandidate,
        leaves: &[&Expectation],
        report: &mut UntilReport,
    ) -> Result<(), SessionError> {
        self.require_until_scope(report.scope.document_epoch)
            .await?;
        if !candidate.top_level
            || candidate.started_at_unix_us == 0
            || candidate.document_epoch() != Some(report.scope.document_epoch)
            || candidate.frame_id != report.scope.frame_id
            || candidate.loader_id != report.scope.loader_id
        {
            return Err(SessionError::Unknown);
        }
        let trigger_start = report
            .trigger
            .as_ref()
            .and_then(|trigger| trigger.result.as_ref())
            .and_then(|result| result.get("started_at_unix_us"))
            .and_then(Value::as_u64);
        if trigger_start.is_some_and(|start| candidate.started_at_unix_us < start) {
            return Ok(());
        }
        let needed = leaves.iter().any(|expected| matches!(expected, Expectation::Response { url, method, status, json } if candidate.url == *url && method.as_ref().is_none_or(|method| *method == candidate.method) && status.is_none_or(|status| status == candidate.status) && !json.is_empty()));
        let body = if needed {
            let bytes = self
                .call(
                    self.control
                        .capture_response_body(candidate, self.until_evidence_budget(leaves.len())),
                )
                .await?;
            Some(
                serde_json::from_slice::<Value>(&bytes)
                    .map_err(|_| SessionError::EvidenceUnavailable)?,
            )
        } else {
            None
        };
        for (expected, check) in leaves.iter().zip(&mut report.checks) {
            if let Expectation::Response {
                url,
                method,
                status,
                json: matches,
            } = expected
            {
                if candidate.url != *url
                    || method
                        .as_ref()
                        .is_some_and(|method| *method != candidate.method)
                    || status.is_some_and(|status| status != candidate.status)
                {
                    continue;
                }
                let matched = matches.iter().all(|item| {
                    body.as_ref().and_then(|body| body.pointer(&item.pointer)) == Some(&item.value)
                });
                if matched {
                    check.state = UntilCheckState::Satisfied;
                    check.evidence = Some(
                        json!({"request_id":candidate.request_id,"url":candidate.url,"method":candidate.method,"status":candidate.status,"loader_id":candidate.loader_id,"frame_id":candidate.frame_id,"top_level":candidate.top_level,"started_at_unix_us":candidate.started_at_unix_us,"body":body,"document_epoch":report.scope.document_epoch,"observed_at_unix_ms":observed_at()?}),
                    );
                }
            }
        }
        self.require_until_scope(report.scope.document_epoch)
            .await?;
        Ok(())
    }
}

enum PreparedTrigger {
    Click(String),
    EnterText { selector: String, text: String },
    Evaluate { source: String, kind: &'static str },
}

fn observed_at_micros() -> Result<u64, SessionError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| SessionError::EvidenceUnavailable)?;
    u64::try_from(elapsed.as_micros()).map_err(|_| SessionError::EvidenceUnavailable)
}

fn observed_at() -> Result<u64, SessionError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| SessionError::EvidenceUnavailable)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| SessionError::EvidenceUnavailable)
}

fn leaves(expected: &Expectation) -> Vec<&Expectation> {
    let mut pending = vec![expected];
    let mut leaves = Vec::new();
    while let Some(next) = pending.pop() {
        match next {
            Expectation::All { expectations } => pending.extend(expectations.iter().rev()),
            other => leaves.push(other),
        }
    }
    leaves
}

const fn source(expected: &Expectation) -> &'static str {
    match expected {
        Expectation::Condition { .. } | Expectation::Contract { .. } => "dom",
        Expectation::Accessibility { .. } => "accessibility",
        Expectation::Response { .. } => "network",
        Expectation::All { .. } => "group",
    }
}

fn watch_options(
    expected: &[&Expectation],
    max_events: usize,
    max_bytes: usize,
) -> ObservationWatchOptions {
    ObservationWatchOptions {
        observe_dom: expected.iter().any(|item| {
            matches!(
                item,
                Expectation::Condition { .. }
                    | Expectation::Contract { .. }
                    | Expectation::Accessibility { .. }
            )
        }),
        observe_accessibility: expected
            .iter()
            .any(|item| matches!(item, Expectation::Accessibility { .. })),
        response_filters: expected
            .iter()
            .filter_map(|item| {
                if let Expectation::Response {
                    url,
                    method,
                    status,
                    ..
                } = item
                {
                    Some(ObservationResponseFilter {
                        url: url.clone(),
                        method: method.clone(),
                        status: *status,
                    })
                } else {
                    None
                }
            })
            .collect(),
        max_events,
        max_bytes,
    }
}
