//! Document observations use native realms rather than injected epoch globals.

use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::{
    browser::{BrowserEngine, MoliProfile},
    internal::{
        browser::{
            DocumentEpoch, DocumentFrameScope, DocumentScope, ProtectedUrl, RenderedDomSnapshot,
            document_snapshot,
        },
        types::BrowserFrameId,
    },
};

use super::session::{Page, SessionError};

#[derive(Clone, Debug)]
pub struct Frame {
    pub context: String,
    pub url: String,
}

impl Page {
    pub async fn document_scope(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<DocumentScope, SessionError> {
        let (url, realm) = self
            .evaluate("location.href", cancellation, deadline)
            .await?;
        let url = url.as_str().ok_or(SessionError::Serialization)?.to_owned();
        self.scope_for(realm, url).await
    }

    async fn scope_for(&self, realm: String, url: String) -> Result<DocumentScope, SessionError> {
        let mut document = self.document.lock().await;
        if document.0.as_ref() != Some(&realm) {
            document.1 = document.1.checked_add(1).ok_or(SessionError::Capacity)?;
            document.0 = Some(realm);
        }
        Ok(DocumentScope {
            frame_id: BrowserFrameId(self.frame_id),
            epoch: DocumentEpoch::Known(document.1),
            frame: DocumentFrameScope::TopLevel,
            url: Some(ProtectedUrl::new(url)),
        })
    }

    pub async fn rendered_dom_snapshot(
        &self,
        max_bytes: usize,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<RenderedDomSnapshot, SessionError> {
        if max_bytes == 0 {
            return Err(SessionError::Capacity);
        }
        // The transport separately bounds provider materialization. The returned
        // payload reports retention after materialization, as the CDP backend does.
        let (value, realm) = self.evaluate("({html:(document.doctype ? new XMLSerializer().serializeToString(document.doctype)+'\\n' : '')+(document.documentElement?.outerHTML ?? ''),url:location.href})", cancellation, deadline).await?;
        let html = value
            .get("html")
            .and_then(Value::as_str)
            .ok_or(SessionError::Serialization)?
            .to_owned();
        let url = value
            .get("url")
            .and_then(Value::as_str)
            .ok_or(SessionError::Serialization)?
            .to_owned();
        let scope = self.scope_for(realm.clone(), url).await?;
        let (_, current) = self.evaluate("0", cancellation, deadline).await?;
        if realm != current {
            return Err(SessionError::DocumentChanged);
        }
        document_snapshot::rendered_dom(html, scope, max_bytes).map_err(|_| SessionError::Capacity)
    }

    pub async fn frames(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Vec<Frame>, SessionError> {
        let tree = self
            .command(
                "browsingContext.getTree",
                json!({"root":self.context}),
                cancellation,
                deadline,
            )
            .await?;
        let roots = tree
            .get("contexts")
            .and_then(Value::as_array)
            .ok_or(SessionError::Serialization)?;
        let root = roots
            .first()
            .filter(|_| roots.len() == 1)
            .ok_or(SessionError::Context)?;
        if root.get("context").and_then(Value::as_str) != Some(self.context.as_str()) {
            return Err(SessionError::Context);
        }
        let mut frames = Vec::new();
        let mut pending = vec![(root, 0usize)];
        while let Some((frame, depth)) = pending.pop() {
            if depth > 32 || frames.len() >= 1024 {
                return Err(SessionError::Capacity);
            }
            let context = frame
                .get("context")
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty() && id.len() <= 512)
                .ok_or(SessionError::Context)?
                .to_owned();
            let url = frame
                .get("url")
                .and_then(Value::as_str)
                .ok_or(SessionError::Serialization)?
                .to_owned();
            if frames.iter().any(|frame: &Frame| frame.context == context) {
                return Err(SessionError::Context);
            }
            frames.push(Frame { context, url });
            if let Some(children) = frame.get("children").and_then(Value::as_array) {
                if pending.len().saturating_add(children.len()) > 1024 {
                    return Err(SessionError::Capacity);
                }
                for child in children.iter().rev() {
                    pending.push((child, depth.saturating_add(1)));
                }
            }
        }
        Ok(frames)
    }

    pub async fn screenshot_png(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Vec<u8>, SessionError> {
        if self.session.config.engine == BrowserEngine::Moli
            && self.session.config.moli_profile != MoliProfile::Layout
        {
            return Err(SessionError::Unsupported(
                "screenshot requires the Moli layout profile",
            ));
        }
        let reply = self
            .command(
                "browsingContext.captureScreenshot",
                json!({"context":self.context,"origin":"viewport","format":{"type":"image/png"}}),
                cancellation,
                deadline,
            )
            .await?;
        let encoded = reply
            .get("data")
            .and_then(Value::as_str)
            .ok_or(SessionError::Serialization)?;
        let bytes = STANDARD
            .decode(encoded)
            .map_err(|_| SessionError::Serialization)?;
        if !bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
            return Err(SessionError::Serialization);
        }
        Ok(bytes)
    }
}
