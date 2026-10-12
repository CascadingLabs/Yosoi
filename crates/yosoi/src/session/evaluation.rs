#[cfg(feature = "browser")]
use super::JsFrame;
use super::{ActionKind, JsTarget, JsWorld, SessionError, Work};
use crate::{
    action::{JavaScriptModuleBundle, JavaScriptSourceSnapshot},
    automation_record::OperationReceipt,
};

impl Work {
    /// Executes explicitly permitted JavaScript in the current main frame and world.
    /// Returns a bounded effect receipt. Post-dispatch errors or oversized
    /// results can leave effects unknown; permission, input, and authority
    /// failures return [`SessionError`]. Confirm business effects separately.
    pub async fn evaluate(&self, source: &str) -> Result<OperationReceipt, SessionError> {
        self.evaluate_targeted_kind(&JsTarget::default(), source, "evaluate")
            .await
    }

    /// Executes source after uniquely resolving the frame and checking any epoch precondition.
    /// Only the main world is currently supported. Explicit arbitrary-script
    /// permission is required. Returns a bounded receipt or [`SessionError`],
    /// preserving possible post-dispatch uncertainty rather than retrying it.
    pub async fn evaluate_targeted(
        &self,
        target: &JsTarget,
        source: &str,
    ) -> Result<OperationReceipt, SessionError> {
        self.evaluate_targeted_kind(target, source, "evaluate")
            .await
    }

    /// Executes retained construction-time file bytes on the current main frame and world.
    /// No live file read occurs here. Returns a bounded receipt or [`SessionError`]
    /// for invalid snapshots, permissions, authority, or dispatch uncertainty.
    pub async fn evaluate_file(
        &self,
        snapshot: &JavaScriptSourceSnapshot,
    ) -> Result<OperationReceipt, SessionError> {
        self.evaluate_file_targeted(&JsTarget::default(), snapshot)
            .await
    }

    /// Executes a validated file snapshot in one uniquely selected current frame.
    /// Changed disk contents do not replace captured bytes. Only the main world
    /// is supported. Returns a bounded receipt or [`SessionError`]; possible
    /// dispatch must not be interpreted as proof of no effect.
    pub async fn evaluate_file_targeted(
        &self,
        target: &JsTarget,
        snapshot: &JavaScriptSourceSnapshot,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Evaluate, "")?;
        snapshot
            .validate(self.session.settings().maximum_input_bytes)
            .map_err(|_| SessionError::InvalidInput)?;
        self.authorize(ActionKind::Evaluate, snapshot.source())?;
        self.evaluate_authorized_targeted(target, snapshot.source(), "evaluate_file")
            .await
    }

    /// Executes a retained local module bundle on the current main frame and world.
    /// Uses captured bytes instead of rereading files and requires arbitrary-script
    /// permission. Returns a bounded receipt or [`SessionError`], retaining
    /// post-dispatch uncertainty instead of silently retrying.
    pub async fn evaluate_module(
        &self,
        bundle: &JavaScriptModuleBundle,
    ) -> Result<OperationReceipt, SessionError> {
        self.evaluate_module_targeted(&JsTarget::default(), bundle)
            .await
    }

    /// Executes a retained local module graph in one uniquely selected current frame.
    /// Checks bundle structure, input bounds, permission, and any epoch
    /// precondition before dispatch. Isolated worlds are currently unsupported.
    /// Returns a bounded effect receipt or [`SessionError`]; no effect rollback is implied.
    pub async fn evaluate_module_targeted(
        &self,
        target: &JsTarget,
        bundle: &JavaScriptModuleBundle,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Evaluate, "")?;
        if target.world == JsWorld::Isolated {
            return Err(SessionError::Unsupported("isolated JavaScript world"));
        }
        let source = super::javascript::module_expression(
            bundle,
            self.session.settings().maximum_input_bytes,
        )?;
        self.authorize(ActionKind::Evaluate, "")?;
        self.evaluate_authorized_targeted(target, &source, "evaluate_module")
            .await
    }

    async fn evaluate_targeted_kind(
        &self,
        target: &JsTarget,
        source: &str,
        kind: &'static str,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        self.authorize(ActionKind::Evaluate, source)?;
        self.evaluate_authorized_targeted(target, source, kind)
            .await
    }

    async fn evaluate_authorized_targeted(
        &self,
        target: &JsTarget,
        source: &str,
        kind: &'static str,
    ) -> Result<OperationReceipt, SessionError> {
        if target.world == JsWorld::Isolated {
            return Err(SessionError::Unsupported("isolated JavaScript world"));
        }
        #[cfg(feature = "browser")]
        {
            if let Some(expected) = target.expected_document_epoch
                && self.call(self.control.document_epoch()).await? != expected
            {
                return Err(SessionError::InvalidInput);
            }
            let frame = match &target.frame {
                JsFrame::Main => None,
                JsFrame::UrlContains(pattern) => {
                    if pattern.trim().is_empty()
                        || pattern.len() > self.session.settings().maximum_input_bytes
                    {
                        return Err(SessionError::InvalidInput);
                    }
                    if !self.call(self.control.unique_frame(pattern)).await? {
                        return Err(SessionError::InvalidInput);
                    }
                    Some(pattern.as_str())
                }
            };
            let result = self
                .call(self.control.evaluate_json_in(source, frame))
                .await
                .and_then(|value| {
                    if serde_json::to_vec(&value)
                        .map_err(|_| SessionError::EvidenceUnavailable)?
                        .len()
                        > self.session.settings().maximum_result_bytes
                    {
                        return Err(SessionError::ResultLimit {
                            maximum: self.session.settings().maximum_result_bytes,
                        });
                    }
                    Ok(value)
                });
            self.receipt(kind, result).await
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = (source, kind);
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
}
