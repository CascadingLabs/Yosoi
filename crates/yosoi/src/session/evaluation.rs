#[cfg(feature = "browser")]
use super::JsFrame;
use super::{ActionKind, JsTarget, JsWorld, SessionError, Work};
use crate::{
    action::{JavaScriptModuleBundle, JavaScriptSourceSnapshot},
    automation_record::OperationReceipt,
};

impl Work {
    pub async fn evaluate(&self, source: &str) -> Result<OperationReceipt, SessionError> {
        self.evaluate_targeted_kind(&JsTarget::default(), source, "evaluate")
            .await
    }

    pub async fn evaluate_targeted(
        &self,
        target: &JsTarget,
        source: &str,
    ) -> Result<OperationReceipt, SessionError> {
        self.evaluate_targeted_kind(target, source, "evaluate")
            .await
    }

    pub async fn evaluate_file(
        &self,
        snapshot: &JavaScriptSourceSnapshot,
    ) -> Result<OperationReceipt, SessionError> {
        self.evaluate_file_targeted(&JsTarget::default(), snapshot)
            .await
    }

    pub async fn evaluate_file_targeted(
        &self,
        target: &JsTarget,
        snapshot: &JavaScriptSourceSnapshot,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation().await?;
        self.authorize(ActionKind::Evaluate, "")?;
        snapshot
            .validate(self.session.settings().maximum_input_bytes)
            .map_err(|_| SessionError::InvalidInput)?;
        self.authorize(ActionKind::Evaluate, snapshot.source())?;
        self.evaluate_authorized_targeted(target, snapshot.source(), "evaluate_file")
            .await
    }

    pub async fn evaluate_module(
        &self,
        bundle: &JavaScriptModuleBundle,
    ) -> Result<OperationReceipt, SessionError> {
        self.evaluate_module_targeted(&JsTarget::default(), bundle)
            .await
    }

    pub async fn evaluate_module_targeted(
        &self,
        target: &JsTarget,
        bundle: &JavaScriptModuleBundle,
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation().await?;
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
        let _operation = self.operation().await?;
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
            if let Some(expected) = target.expected_document_epoch {
                if self.call(self.control.document_epoch()).await? != expected {
                    return Err(SessionError::InvalidInput);
                }
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
