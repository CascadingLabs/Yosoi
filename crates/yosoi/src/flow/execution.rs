//! Shared execution for managed and caller-owned Flow invocations.

pub use super::error::FlowInvokeError;
use crate::expect;
use crate::request;
use crate::{
    assertions::AssertionError,
    automation_record::{OperationReceipt, OperationStatus},
    flow::{
        Continuation, FailureCapturePolicy, Flow, FlowCancellationCause, FlowFailureCause,
        FlowLimits, FlowOutcome, FlowPolicy, FlowStopCause, FlowStopReason, FlowTermination,
        FlowValidationError, SkippedStep, Step, StepOutcome, StopScope,
    },
    policy::Policy,
    session::{self, SessionError, Work},
    timing,
};
use std::future as std_future;
#[cfg(test)]
use std::iter as std_iter;
use std::vec as std_vec;
use std::{future::Future, pin::Pin, time::Duration};

#[expect(
    clippy::significant_drop_tightening,
    reason = "Ownership is moved into a task or consumed by async release; the nursery follows Drop fields after that move."
)]
pub(super) async fn invoke(
    flow: &Flow,
    policy: Option<&Policy>,
    work: Option<&Work>,
    cancellation: &request::CancellationToken,
    allow_javascript: bool,
) -> Result<FlowOutcome, FlowInvokeError> {
    flow.validate_with_limits(FlowLimits::default())
        .map_err(FlowInvokeError::InvalidFlow)?;
    validate_bound_assertions(flow).map_err(FlowInvokeError::InvalidFlow)?;
    let cancellation = cancellation.child_token();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let cancellation = &cancellation;

    if let Some(policy) = policy {
        policy.validate().map_err(FlowInvokeError::Policy)?;
    }

    if let Some(work) = work {
        if let Some(policy) = policy {
            let scoped = Box::pin(work.scoped(
                policy,
                execute_flow(
                    flow,
                    work,
                    resolve_root_default(Some(policy), work.default_action_timeout()),
                    policy.flow,
                    cancellation,
                ),
            ));
            return session::with_cancellation(cancellation, scoped)
                .await
                .map_err(|source| FlowInvokeError::Session {
                    source,
                    outcome: None,
                    cleanup: None,
                });
        }
        let executing = Box::pin(execute_flow(
            flow,
            work,
            resolve_root_default(None, work.default_action_timeout()),
            *work.flow_policy(),
            cancellation,
        ));
        return Ok(session::with_cancellation(cancellation, executing).await);
    }

    let default_policy = Policy::default();
    let policy = policy.unwrap_or(&default_policy);
    let mut builder = session::new().bind(policy);
    if allow_javascript {
        builder = builder.allow_javascript();
    }
    let acquiring = builder.acquire_cancellable(cancellation);
    let session = acquiring.await.map_err(|source| FlowInvokeError::Session {
        source,
        outcome: None,
        cleanup: None,
    })?;

    let work = match tokio::select! {
        biased;
        () = cancellation.cancelled() => Err(SessionError::Cancelled),
        result = session.work() => result,
    } {
        Ok(work) => work,
        Err(source) => {
            let cleanup = session.close().await.err();
            return Err(FlowInvokeError::Session {
                source,
                outcome: None,
                cleanup,
            });
        }
    };

    let scoped = Box::pin(work.scoped(
        policy,
        execute_flow(
            flow,
            &work,
            resolve_root_default(Some(policy), work.default_action_timeout()),
            policy.flow,
            cancellation,
        ),
    ));
    let executed = session::with_cancellation(cancellation, scoped).await;
    let release_result = work.release().await;
    let close_result = session.close().await;
    drop(session);
    let mut outcome = match executed {
        Ok(outcome) => outcome,
        Err(source) => {
            return Err(FlowInvokeError::Session {
                source,
                outcome: None,
                cleanup: close_result.err(),
            });
        }
    };

    outcome
        .cleanup
        .push(cleanup_receipt("session.release", release_result));
    outcome
        .cleanup
        .push(cleanup_receipt("session.close", close_result));
    if outcome.terminal == FlowTermination::Completed
        && outcome
            .cleanup
            .iter()
            .any(|receipt| receipt.status != OperationStatus::Observed)
    {
        outcome.terminal = FlowTermination::CompletedWithIssues;
    }

    Ok(outcome)
}

// Validation has already bounded nesting before this walk. Persisted descriptors
// remain inspectable, but cannot execute absent their explicitly rebound Rust code.
fn validate_bound_assertions(flow: &Flow) -> Result<(), FlowValidationError> {
    for step in flow.steps() {
        if step.requires_cancellation_binding() {
            return Err(FlowValidationError::UnboundCancellation);
        }
        match step.operation() {
            Step::NestedFlow { flow } => validate_bound_assertions(flow)?,
            Step::Until { expectation, .. } => validate_bound_expectation(expectation)?,
            Step::AssertAll { assertion } if !assertion.is_bound() => {
                return Err(FlowValidationError::Assertion(AssertionError::Unbound));
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_bound_expectation(expected: &expect::Expectation) -> Result<(), FlowValidationError> {
    match expected {
        expect::Expectation::Contract { assertion } if !assertion.is_bound() => {
            Err(FlowValidationError::Assertion(AssertionError::Unbound))
        }
        expect::Expectation::All { expectations } => {
            for child in expectations {
                validate_bound_expectation(child)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

struct FlowFrame<'a> {
    flow: &'a Flow,
    cursor: usize,
    inherited_timeout: Duration,
    on_failure: Continuation,
    on_cancellation: Continuation,
    local_cancellation: Option<request::CancellationToken>,
}

type ActionExecutionFuture<'a> =
    Pin<Box<dyn Future<Output = Result<OperationReceipt, SessionError>> + Send + 'a>>;

struct FlowExecution {
    steps: Vec<StepOutcome>,
    terminal: FlowTermination,
    stop_reason: Option<FlowStopReason>,
    skipped_steps: Vec<SkippedStep>,
}

async fn execute_flow(
    flow: &Flow,
    work: &Work,
    default_timeout: Duration,
    policy: FlowPolicy,
    cancellation: &request::CancellationToken,
) -> FlowOutcome {
    let execution = execute_flow_steps_with_policy(
        flow,
        default_timeout,
        policy,
        cancellation,
        || work.session_cancelled(),
        |step, timeout, action_cancellation| {
            Box::pin(async move {
                Box::pin(session::with_cancellation(
                    &action_cancellation,
                    execute_action(timeout, execute_step(step.operation(), work)),
                ))
                .await
            })
        },
    )
    .await;

    let has_failure = execution.steps.iter().any(|step| step.failure.is_some());
    let failure_capture = match (flow.capture_on_failure, has_failure) {
        (FailureCapturePolicy::Screenshot, true) => Some(match work.screenshot().await {
            Ok(receipt) => receipt,
            Err(source) => failure_capture_error_receipt(&source),
        }),
        _ => None,
    };

    FlowOutcome {
        version: 3,
        flow: flow.clone(),
        steps: execution.steps,
        terminal: execution.terminal,
        continuation_defaults: policy,
        stop_reason: execution.stop_reason,
        skipped_steps: execution.skipped_steps,
        cleanup: Vec::new(),
        failure_capture,
    }
}

async fn execute_flow_steps_with_policy<'flow, 'action, F, C>(
    flow: &'flow Flow,
    default_timeout: Duration,
    policy: FlowPolicy,
    cancellation: &request::CancellationToken,
    session_cancelled: C,
    mut execute: F,
) -> FlowExecution
where
    C: Fn() -> bool,
    F: FnMut(Step, Duration, request::CancellationToken) -> ActionExecutionFuture<'action>,
{
    let root_timeout = resolve_flow_timeout(flow, default_timeout);
    let mut frames = vec![FlowFrame {
        flow,
        cursor: 0,
        inherited_timeout: root_timeout,
        on_failure: flow.on_failure_override().unwrap_or(policy.on_failure),
        on_cancellation: flow
            .on_cancellation_override()
            .unwrap_or(policy.on_cancellation),
        local_cancellation: None,
    }];
    let mut flow_path = Vec::new();
    let mut steps = Vec::new();
    let mut skipped_steps = Vec::new();
    let mut terminal = FlowTermination::Completed;
    let mut stop_reason = None;
    let mut had_issues = false;

    while !frames.is_empty() {
        let FrameStep {
            flow: current_flow,
            index: step_index,
            inherited_timeout,
            on_failure,
            on_cancellation,
        } = match advance_frame(&mut frames, &mut flow_path) {
            FrameAdvance::Ready(step) => step,
            FrameAdvance::Complete => break,
            FrameAdvance::Overflow => {
                terminal = FlowTermination::Failed;
                break;
            }
        };

        let Ok(step_index_u64) = u64::try_from(step_index) else {
            terminal = FlowTermination::Failed;
            break;
        };
        let Some(step) = current_flow.steps.get(step_index) else {
            terminal = FlowTermination::Failed;
            break;
        };
        if let Step::NestedFlow { flow: child } = step.operation() {
            let child_timeout = resolve_flow_timeout(child, inherited_timeout);
            let child_failure = step
                .failure_override()
                .or_else(|| child.on_failure_override())
                .unwrap_or(on_failure);
            let child_cancellation = step
                .cancellation_override()
                .or_else(|| child.on_cancellation_override())
                .unwrap_or(on_cancellation);
            flow_path.push(step_index_u64);
            frames.push(FlowFrame {
                flow: child,
                cursor: 0,
                inherited_timeout: child_timeout,
                on_failure: child_failure,
                on_cancellation: child_cancellation,
                local_cancellation: step.cancellation_token().cloned(),
            });
            continue;
        }

        let selected_timeout = resolve_action_timeout(step, inherited_timeout);
        let mut local_tokens = frames
            .iter()
            .filter_map(|frame| frame.local_cancellation.clone())
            .collect::<Vec<_>>();
        if let Some(token) = step.cancellation_token() {
            local_tokens.push(token.clone());
        }
        let mut provenance = flow_path.clone();
        provenance.push(step_index_u64);
        let (result, local_cancelled) = if session_cancelled() || cancellation.is_cancelled() {
            (Err(SessionError::Cancelled), false)
        } else {
            dispatch_action(
                step,
                selected_timeout,
                cancellation,
                local_tokens,
                &mut execute,
            )
            .await
        };
        let session_stopped = session_cancelled();
        let authority_closed = matches!(&result, Err(SessionError::Closed));
        let invocation_stopped = cancellation.is_cancelled();
        let cancelled_flow_frame =
            if local_cancelled && !session_stopped && !invocation_stopped && !authority_closed {
                frames.iter().enumerate().find_map(|(index, frame)| {
                    frame
                        .local_cancellation
                        .as_ref()
                        .is_some_and(request::CancellationToken::is_cancelled)
                        .then_some(index)
                })
            } else {
                None
            };
        let cancelled_flow = cancelled_flow_frame
            .map(|frame_index| flow_path.iter().take(frame_index).copied().collect());
        let Ok(result_index) = u64::try_from(steps.len()) else {
            terminal = FlowTermination::Failed;
            break;
        };
        let (receipt, failure, mut step_cancellation) = match result {
            Ok(receipt) => {
                let failure = match receipt.status {
                    OperationStatus::Observed => None,
                    OperationStatus::Rejected => Some(FlowFailureCause::Rejected),
                    OperationStatus::Unknown => Some(FlowFailureCause::UnknownOutcome),
                };
                (receipt, failure, None)
            }
            Err(source) => {
                let failure = classify_action_failure(
                    &source,
                    invocation_stopped || session_stopped,
                    authority_closed,
                    local_cancelled,
                );
                (error_receipt(step, step_index_u64, &source), failure, None)
            }
        };

        if session_stopped {
            step_cancellation = Some(FlowCancellationCause::Session);
        } else if invocation_stopped {
            step_cancellation = Some(FlowCancellationCause::Invocation);
        } else if local_cancelled {
            step_cancellation = Some(FlowCancellationCause::Step);
        }

        let unknown = receipt.status == OperationStatus::Unknown;
        had_issues |= failure.is_some() || step_cancellation.is_some() || unknown;
        steps.push(StepOutcome {
            index: result_index,
            flow_path: provenance.clone(),
            receipt,
            failure,
            cancellation: step_cancellation,
            cancelled_flow,
        });

        if let Some((boundary, cause)) = terminal_boundary(
            unknown,
            invocation_stopped || session_stopped,
            authority_closed,
        ) {
            terminal = boundary;
            skip_invocation_remaining(&frames, &flow_path, &provenance, cause, &mut skipped_steps);
            stop_reason = Some(FlowStopReason {
                flow_path: provenance,
                cause,
                continuation: None,
            });
            break;
        }

        let failure_continuation = failure.map(|_| step.failure_override().unwrap_or(on_failure));
        let cancellation_continuation =
            step_cancellation.map(|_| step.cancellation_override().unwrap_or(on_cancellation));
        let selected_stop = [failure_continuation, cancellation_continuation]
            .into_iter()
            .flatten()
            .filter_map(|continuation| match continuation {
                Continuation::Continue => None,
                Continuation::Stop(scope) => Some((continuation, scope)),
            })
            .max_by_key(|(_, scope)| match scope {
                StopScope::CurrentFlow => 0_u8,
                StopScope::Invocation => 1_u8,
            });

        if let Some((continuation, StopScope::Invocation)) = selected_stop {
            let cause = if cancellation_continuation.is_some_and(|value| value == continuation) {
                FlowStopCause::Cancellation
            } else {
                FlowStopCause::Failure
            };
            terminal = if cause == FlowStopCause::Cancellation {
                FlowTermination::Cancelled
            } else {
                FlowTermination::Failed
            };
            skip_invocation_remaining(&frames, &flow_path, &provenance, cause, &mut skipped_steps);
            stop_reason = Some(FlowStopReason {
                flow_path: provenance,
                cause,
                continuation: Some(continuation),
            });
            break;
        }

        if let Some(cancelled_frame) = cancelled_flow_frame {
            skip_cancelled_flow_remaining(
                &frames,
                &flow_path,
                cancelled_frame,
                &provenance,
                &mut skipped_steps,
            );
            while frames.len() > cancelled_frame {
                frames.pop();
            }
            flow_path.truncate(cancelled_frame.saturating_sub(1));
            continue;
        }

        if let Some((continuation, StopScope::CurrentFlow)) = selected_stop {
            let cause = if cancellation_continuation.is_some_and(|value| value == continuation) {
                FlowStopCause::Cancellation
            } else {
                FlowStopCause::Failure
            };

            skip_current_flow_remaining(
                &frames,
                &flow_path,
                &provenance,
                cause,
                &mut skipped_steps,
            );
            if frames.len() <= 1 {
                terminal = if cause == FlowStopCause::Cancellation {
                    FlowTermination::Cancelled
                } else {
                    FlowTermination::Failed
                };
                stop_reason = Some(FlowStopReason {
                    flow_path: provenance,
                    cause,
                    continuation: Some(continuation),
                });
                break;
            }
            frames.pop();
            let _ = flow_path.pop();
        }
    }

    if terminal == FlowTermination::Completed && had_issues {
        terminal = FlowTermination::CompletedWithIssues;
    }

    FlowExecution {
        steps,
        terminal,
        stop_reason,
        skipped_steps,
    }
}

#[cfg(test)]
async fn execute_flow_steps<'flow, 'action, F>(
    flow: &'flow Flow,
    default_timeout: Duration,
    mut execute: F,
) -> (Vec<StepOutcome>, FlowTermination)
where
    F: FnMut(Step, Duration) -> ActionExecutionFuture<'action>,
{
    let cancellation = request::CancellationToken::new();
    let execution = execute_flow_steps_with_policy(
        flow,
        default_timeout,
        FlowPolicy::default(),
        &cancellation,
        || false,
        |step, timeout, _action_cancellation| execute(step, timeout),
    )
    .await;
    (execution.steps, execution.terminal)
}

fn cancellation_trigger(
    mut tokens: std_vec::IntoIter<request::CancellationToken>,
) -> Pin<Box<dyn Future<Output = ()> + Send>> {
    Box::pin(async move {
        if let Some(token) = tokens.next() {
            tokio::select! {
                biased;
                () = token.cancelled() => {},
                () = cancellation_trigger(tokens) => {},
            }
        } else {
            std_future::pending::<()>().await;
        }
    })
}

const fn classify_action_failure(
    source: &SessionError,
    hard_cancelled: bool,
    authority_closed: bool,
    local_cancelled: bool,
) -> Option<FlowFailureCause> {
    if source.is_unknown() {
        Some(FlowFailureCause::UnknownOutcome)
    } else if source.is_cancelled() && hard_cancelled {
        None
    } else if authority_closed || !source.is_cancelled() || !local_cancelled {
        Some(FlowFailureCause::Execution)
    } else {
        None
    }
}

const fn terminal_boundary(
    unknown: bool,
    hard_cancelled: bool,
    authority_closed: bool,
) -> Option<(FlowTermination, FlowStopCause)> {
    if unknown {
        Some((FlowTermination::Unknown, FlowStopCause::UnknownOutcome))
    } else if hard_cancelled {
        Some((FlowTermination::Cancelled, FlowStopCause::Cancellation))
    } else if authority_closed {
        Some((FlowTermination::Failed, FlowStopCause::UnsafeState))
    } else {
        None
    }
}

struct FrameStep<'a> {
    flow: &'a Flow,
    index: usize,
    inherited_timeout: Duration,
    on_failure: Continuation,
    on_cancellation: Continuation,
}
enum FrameAdvance<'a> {
    Ready(FrameStep<'a>),
    Complete,
    Overflow,
}
fn advance_frame<'a>(frames: &mut Vec<FlowFrame<'a>>, path: &mut Vec<u64>) -> FrameAdvance<'a> {
    loop {
        let Some(frame) = frames.last_mut() else {
            return FrameAdvance::Complete;
        };
        if frame.cursor < frame.flow.steps.len() {
            let index = frame.cursor;
            let Some(cursor) = index.checked_add(1) else {
                return FrameAdvance::Overflow;
            };
            frame.cursor = cursor;
            return FrameAdvance::Ready(FrameStep {
                flow: frame.flow,
                index,
                inherited_timeout: frame.inherited_timeout,
                on_failure: frame.on_failure,
                on_cancellation: frame.on_cancellation,
            });
        }
        frames.pop();
        if !frames.is_empty() {
            path.pop();
        }
    }
}

async fn dispatch_action<'action, F>(
    step: &Step,
    timeout: Duration,
    cancellation: &request::CancellationToken,
    local_tokens: Vec<request::CancellationToken>,
    execute: &mut F,
) -> (Result<OperationReceipt, SessionError>, bool)
where
    F: FnMut(Step, Duration, request::CancellationToken) -> ActionExecutionFuture<'action>,
{
    if local_tokens
        .iter()
        .any(request::CancellationToken::is_cancelled)
    {
        return (Err(SessionError::Cancelled), true);
    }
    let action_cancellation = cancellation.child_token();
    let action = execute(
        step.operation().clone(),
        timeout,
        action_cancellation.clone(),
    );
    tokio::pin!(action);
    if local_tokens.is_empty() {
        return (action.await, false);
    }
    let stopped = cancellation_trigger(local_tokens.into_iter());
    tokio::pin!(stopped);
    tokio::select! {
        biased;
        result = &mut action => (result, false),
        () = &mut stopped => {
            action_cancellation.cancel();
            (action.await, true)
        }
    }
}

fn skip_invocation_remaining(
    frames: &[FlowFrame<'_>],
    flow_path: &[u64],
    stopped_by: &[u64],
    cause: FlowStopCause,
    output: &mut Vec<SkippedStep>,
) {
    for (frame_index, frame) in frames.iter().enumerate().rev() {
        let prefix: Vec<_> = flow_path.iter().take(frame_index).copied().collect();
        append_remaining_from_frame(
            frame,
            &prefix,
            stopped_by,
            cause,
            StopScope::Invocation,
            output,
        );
    }
}

fn skip_current_flow_remaining(
    frames: &[FlowFrame<'_>],
    flow_path: &[u64],
    stopped_by: &[u64],
    cause: FlowStopCause,
    output: &mut Vec<SkippedStep>,
) {
    if let Some((index, frame)) = frames.iter().enumerate().next_back() {
        let prefix: Vec<_> = flow_path.iter().take(index).copied().collect();
        append_remaining_from_frame(
            frame,
            &prefix,
            stopped_by,
            cause,
            StopScope::CurrentFlow,
            output,
        );
    }
}

fn skip_cancelled_flow_remaining(
    frames: &[FlowFrame<'_>],
    flow_path: &[u64],
    owner_frame: usize,
    stopped_by: &[u64],
    output: &mut Vec<SkippedStep>,
) {
    for (frame_index, frame) in frames.iter().enumerate().skip(owner_frame).rev() {
        let prefix: Vec<_> = flow_path.iter().take(frame_index).copied().collect();
        append_remaining_from_frame(
            frame,
            &prefix,
            stopped_by,
            FlowStopCause::Cancellation,
            StopScope::CurrentFlow,
            output,
        );
    }
}

fn append_remaining_from_frame(
    frame: &FlowFrame<'_>,
    prefix: &[u64],
    stopped_by: &[u64],
    cause: FlowStopCause,
    scope: StopScope,
    output: &mut Vec<SkippedStep>,
) {
    for (position, step) in frame.flow.steps().iter().enumerate().skip(frame.cursor) {
        let Ok(index) = u64::try_from(position) else {
            continue;
        };
        let mut path = prefix.to_vec();
        path.push(index);
        append_leaf_paths(step, &mut path, stopped_by, cause, scope, output);
    }
}

fn append_leaf_paths(
    step: &Step,
    path: &mut Vec<u64>,
    stopped_by: &[u64],
    cause: FlowStopCause,
    scope: StopScope,
    output: &mut Vec<SkippedStep>,
) {
    if let Step::NestedFlow { flow } = step.operation() {
        for (position, child_step) in flow.steps().iter().enumerate() {
            let Ok(index) = u64::try_from(position) else {
                continue;
            };
            path.push(index);
            append_leaf_paths(child_step, path, stopped_by, cause, scope, output);
            let _ = path.pop();
        }
        return;
    }
    output.push(SkippedStep {
        flow_path: path.clone(),
        stopped_by: stopped_by.to_vec(),
        cause,
        scope,
    });
}

fn resolve_flow_timeout(flow: &Flow, inherited: Duration) -> Duration {
    flow.timeout_duration().unwrap_or(inherited)
}

fn resolve_root_default(policy: Option<&Policy>, session_default: Duration) -> Duration {
    policy.map_or(session_default, |policy| {
        Duration::from_millis(policy.default_action_timeout_ms)
    })
}

fn resolve_action_timeout(step: &Step, inherited: Duration) -> Duration {
    step.timeout_duration().unwrap_or(inherited)
}

async fn execute_action<T>(
    timeout: Duration,
    operation: impl Future<Output = Result<T, SessionError>>,
) -> Result<T, SessionError> {
    let deadline = timing::checked_deadline(timeout).ok_or(SessionError::InvalidInput)?;
    timing::scope(deadline, operation).await
}

async fn execute_step(step: &Step, work: &Work) -> Result<OperationReceipt, SessionError> {
    match step {
        Step::AssertAll { assertion } => work.assert_all(assertion).await,
        Step::Until {
            trigger,
            expectation,
        } => work.until(trigger.as_deref(), expectation).await,
        Step::Timed { .. } | Step::Configured { .. } | Step::NestedFlow { .. } => {
            Err(SessionError::InvalidInput)
        }
        Step::Navigate { url } => work.navigate(url).await,
        Step::Click { selector } => work.click(selector).await,
        Step::EnterText { selector, text } => work.enter_text(selector, text).await,
        Step::Wait { milliseconds } => work.wait(*milliseconds).await,
        Step::Screenshot => work.screenshot().await,
        Step::Assert { condition } => work.assert_condition(condition).await,
        Step::WaitUntil {
            condition,
            timeout_ms,
        } => Box::pin(work.wait_until(condition, *timeout_ms)).await,
        Step::Evaluate { source } => work.evaluate(source).await,
        Step::EvaluateFile { snapshot } => work.evaluate_file(snapshot).await,
        Step::EvaluateModule { bundle } => work.evaluate_module(bundle).await,
    }
}

fn error_receipt(step: &Step, index: u64, error: &SessionError) -> OperationReceipt {
    let is_unknown = error.is_unknown();
    let status = if is_unknown {
        OperationStatus::Unknown
    } else {
        OperationStatus::Rejected
    };
    OperationReceipt {
        id: session::new_operation_id(),
        kind: format!(
            "{}:{}",
            if is_unknown {
                "dispatch-unknown"
            } else {
                "not-dispatched"
            },
            step.kind()
        ),
        status,
        result: None,
        observation: None,
        error: Some(format!("flow step {index}: {error}")),
    }
}

fn failure_capture_error_receipt(error: &SessionError) -> OperationReceipt {
    OperationReceipt {
        id: session::new_operation_id(),
        kind: "failure_capture:screenshot".to_owned(),
        status: if error.is_unknown() {
            OperationStatus::Unknown
        } else {
            OperationStatus::Rejected
        },
        result: None,
        observation: None,
        error: Some(format!("post-failure screenshot capture: {error}")),
    }
}

fn cleanup_receipt(kind: &'static str, result: Result<(), SessionError>) -> OperationReceipt {
    match result {
        Ok(()) => OperationReceipt {
            id: session::new_operation_id(),
            kind: kind.to_owned(),
            status: OperationStatus::Observed,
            result: None,
            observation: None,
            error: None,
        },
        Err(error) => OperationReceipt {
            id: session::new_operation_id(),
            kind: kind.to_owned(),
            status: if error.is_unknown() {
                OperationStatus::Unknown
            } else {
                OperationStatus::Rejected
            },
            result: None,
            observation: None,
            error: Some(error.to_string()),
        },
    }
}

#[cfg(all(test, feature = "browser"))]
#[test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn public_invocation_futures_stay_below_the_inline_size_budget() {
    use std::mem::size_of_val;

    const MAX_INLINE_BYTES: usize = 4 * 1024;

    let flow = Flow::new(std_iter::empty());
    let policy = Policy::default();
    let bound = flow.bind(&policy);

    let flow_future = flow.invoke();
    let bound_future = bound.invoke();
    let flow_size = size_of_val(&flow_future);
    let bound_size = size_of_val(&bound_future);

    assert!(
        flow_size <= MAX_INLINE_BYTES,
        "Flow::invoke future is {flow_size} bytes; maximum is {MAX_INLINE_BYTES}"
    );
    assert!(
        bound_size <= MAX_INLINE_BYTES,
        "BoundFlow::invoke future is {bound_size} bytes; maximum is {MAX_INLINE_BYTES}"
    );
}

#[cfg(test)]
#[path = "execution_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "continuation_tests.rs"]
mod continuation_tests;
