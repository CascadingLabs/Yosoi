//! Acknowledged observer installation separated from its parked completion.
use super::Page;
use crate::internal::browser::error::{Result, VoidCrawlError};
use crate::internal::browser::vendor::chromiumoxide::{
    Page as CdpPage,
    cdp::js_protocol::runtime::{
        AwaitPromiseParams, CallFunctionOnParams, EvaluateParams, ReleaseObjectParams,
        RemoteObjectId,
    },
};
use std::time as std_time;
use std::time::Duration;
use tokio::runtime as tokio_runtime;
use tokio::time as tokio_time;

/// Owns exactly one DOM observer/timer and its remote promise handle.
/// Dropping it requests bounded cancellation without releasing any tab authority.
#[derive(Debug)]
pub struct ConditionWait {
    page: CdpPage,
    object: Option<RemoteObjectId>,
    executor: tokio_runtime::Handle,
    response_deadline: std_time::Instant,
}
impl ConditionWait {
    pub async fn finish(&mut self) -> Result<bool> {
        let object = self.object.as_ref().ok_or_else(|| {
            VoidCrawlError::JsEvalError("condition wait already completed".into())
        })?;
        let mut params = AwaitPromiseParams::new(object.clone());
        params.return_by_value = Some(true);
        let response = self
            .page
            .await_promise_before(params, self.response_deadline)
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        if response.result.exception_details.is_some() {
            return Err(VoidCrawlError::JsEvalError(
                "condition observation was interrupted".into(),
            ));
        }
        let result = response
            .result
            .result
            .value
            .as_ref()
            .and_then(serde_json::Value::as_bool)
            .ok_or_else(|| VoidCrawlError::JsEvalError("condition returned no boolean".into()))?;
        self.page
            .execute(ReleaseObjectParams::new(object.clone()))
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        self.object = None;
        Ok(result)
    }
}
impl Drop for ConditionWait {
    fn drop(&mut self) {
        let Some(object) = self.object.take() else {
            return;
        };
        let page = self.page.clone();
        self.executor.spawn(async move {
            let params = CallFunctionOnParams::builder()
                .function_declaration("function() { this.cancel(); }")
                .object_id(object.clone())
                .return_by_value(true)
                .build();
            if let Ok(params) = params {
                let _ = tokio_time::timeout(Duration::from_secs(1), page.execute(params)).await;
            }
            let _ = tokio_time::timeout(
                Duration::from_secs(1),
                page.execute(ReleaseObjectParams::new(object)),
            )
            .await;
        });
    }
}
impl Page {
    pub async fn start_condition_wait(
        &self,
        expression: &str,
        timeout: Duration,
    ) -> Result<ConditionWait> {
        let timeout_ms =
            u64::try_from(timeout.as_millis()).map_err(|_| VoidCrawlError::InvalidInput {
                operation: "start_condition_wait",
                reason: "timeout exceeds supported range",
            })?;
        if timeout_ms == 0 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "start_condition_wait",
                reason: "timeout must be positive",
            });
        }
        let executor = tokio_runtime::Handle::try_current().map_err(|_| {
            VoidCrawlError::JsEvalError("condition wait requires an executor".into())
        })?;
        let response_deadline = timeout
            .checked_add(Duration::from_secs(2))
            .and_then(|duration| std_time::Instant::now().checked_add(duration))
            .ok_or_else(|| {
                VoidCrawlError::JsEvalError("condition wait deadline is unrepresentable".into())
            })?;
        let source = format!(
            // Timer completion may arrive after its nominal bound. The SDK's
            // original action deadline still governs resumption and capture.
            r#"(() => {{
            let stop;
            const promise = new Promise((resolve, reject) => {{
                let observer; let timer; let settled = false;
                const events = ['load', 'transitionend', 'animationend'];
                const cleanup = () => {{
                    if (observer) observer.disconnect(); clearTimeout(timer);
                    for (const event of events) document.removeEventListener(event, check, true);
                    window.removeEventListener('resize', check);
                }};
                const done = value => {{ if (settled) return; settled = true; cleanup(); resolve(value); }};
                const check = () => {{
                    if (settled) return;
                    try {{ if ({expression}) done(true); }}
                    catch (error) {{ settled = true; cleanup(); reject(error); }}
                }};
                stop = () => done(false);
                observer = new MutationObserver(check);
                observer.observe(document, {{childList:true, attributes:true, characterData:true, subtree:true}});
                for (const event of events) document.addEventListener(event, check, true);
                window.addEventListener('resize', check);
                timer = setTimeout(() => done(false), {timeout_ms});
                check();
            }});
            promise.cancel = () => stop();
            return promise;
        }})()"#
        );
        let params = EvaluateParams::builder()
            .expression(source)
            .await_promise(false)
            .return_by_value(false)
            .build()
            .map_err(VoidCrawlError::JsEvalError)?;
        let result = self
            .inner
            .evaluate_expression(params)
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        let object = result.object().object_id.clone().ok_or_else(|| {
            VoidCrawlError::JsEvalError("condition observer installation returned no handle".into())
        })?;
        Ok(ConditionWait {
            page: self.inner.clone(),
            object: Some(object),
            executor,
            response_deadline,
        })
    }
}
