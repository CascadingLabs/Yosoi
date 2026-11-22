//! Retained native Session/Work binding; it never launches a second browser.
use crate::{
    automation_record::OperationStatus,
    documents::{Document, DocumentEpoch},
    internal::browser::page::SurfaceInput,
    session::{ActionKind, Work},
    surface::{
        DocumentPolicies, Surface,
        connection::{Operation, Result, Trace},
    },
};
use serde_json::{Value, json};
use std::{fs, io, path::Path};

pub(super) struct NativeBrowser {
    work: Option<Work>,
    key: String,
    session_id: String,
    tab_id: String,
    binding_id: String,
    pub documents: DocumentPolicies,
}

impl NativeBrowser {
    pub async fn new(work: Work, mut documents: DocumentPolicies) -> Result<Self> {
        documents.validate()?;
        let limit = work.surface_observation_limit();
        documents.dom.max_bytes = documents.dom.max_bytes.min(limit);
        documents.html.max_bytes = documents.html.max_bytes.min(limit);
        let (session_id, tab_id) = work.surface_identity();
        let binding_id = uuid::Uuid::new_v4().to_string();
        // Validate this provider and authority before returning a binding.
        work.surface_script("location", json!({})).await?;
        Ok(Self {
            key: format!("native-{session_id}-{tab_id}-{binding_id}"),
            session_id,
            tab_id,
            binding_id,
            work: Some(work),
            documents,
        })
    }

    fn work(&self) -> Result<&Work> {
        self.work
            .as_ref()
            .ok_or_else(|| io::Error::other("native Surface Work was released").into())
    }

    pub fn key(&self) -> &str {
        &self.key
    }

    pub fn capabilities(&self) -> Value {
        json!({"backend":"native_session","sessionId":self.session_id,"tabId":self.tab_id,"bindingId":self.binding_id,
            "ownership":"Surface close releases Work; the retained Session and tab are not explicitly closed"})
    }

    pub fn authorize(&self, operation: &Operation) -> Result<()> {
        let (kind, input) = match operation {
            Operation::Click { .. } => (ActionKind::Click, ""),
            Operation::Fill { text, .. } => (ActionKind::EnterText, text.as_str()),
            Operation::Key { key, .. } => (ActionKind::EnterText, key.as_str()),
            Operation::Scroll { .. } => (ActionKind::Scroll, ""),
            Operation::Navigate { url, .. } => (ActionKind::Navigate, url.as_str()),
            _ => return Err(io::Error::other("not a native Surface action").into()),
        };
        Ok(self.work()?.surface_authorize(kind, input)?)
    }

    pub async fn script(&self, operation: &str, input: Value) -> Result<Value> {
        Ok(self.work()?.surface_script(operation, input).await?)
    }

    pub async fn capture(
        &self,
        epoch: u64,
        trace: &mut Trace,
    ) -> Result<(Surface, Document, Value)> {
        let mut captured = self.script("capture", json!({"epoch":epoch,"limits":self.documents.dom,"html_limits":self.documents.html})).await?;
        let native_epoch = captured
            .get("native_document_epoch")
            .and_then(Value::as_u64)
            .ok_or_else(|| io::Error::other("native document epoch missing"))?;
        // Surface's positive capture sequence and the native browser's document
        // epoch are different clocks. An untouched native about:blank starts at
        // epoch zero; preserve that provenance without inventing a native epoch.
        let wire = captured
            .get("wire")
            .ok_or_else(|| io::Error::other("native capture lacks DOM evidence"))?;
        let wire_bytes = serde_json::to_vec(wire)?;
        let captured_fields = captured
            .as_object_mut()
            .ok_or_else(|| io::Error::other("native capture result is not an object"))?;
        captured_fields.insert("session_id".into(), self.session_id.clone().into());
        captured_fields.insert("tab_id".into(), self.tab_id.clone().into());
        captured_fields.insert("capture_sequence".into(), epoch.into());
        let document = Document::rendered_dom(
            format!("surface-{}-{epoch}", self.key),
            DocumentEpoch::try_from(epoch)?,
            wire_bytes,
        )?;
        let index = Surface::with_limits(&document, self.documents.dom.limits()?)?;
        trace.event("capture", json!({"url":captured.get("url"),"epoch":epoch,
            "capture":index.identity(),"nodes":index.node_count(),"source_bytes":index.source_bytes(),
            "native_session_id":self.session_id,"native_tab_id":self.tab_id,"native_document_epoch":native_epoch,"capture_sequence":epoch}));
        Ok((index, document, captured))
    }

    pub async fn capture_evidence(
        &self,
        epoch: u64,
        representation: super::BrowserRepresentation,
    ) -> Result<(Surface, Document, Value)> {
        let policy = representation.policy(&self.documents);
        let mut location = self.script("location", json!({})).await?;
        let document = match representation {
            super::BrowserRepresentation::Ax => {
                let captured = self.work()?.surface_ax(policy.max_depth).await?;
                let native_epoch = captured
                    .get("native_document_epoch")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| io::Error::other("native AX epoch missing"))?;
                if location
                    .get("native_document_epoch")
                    .and_then(Value::as_u64)
                    != Some(native_epoch)
                {
                    return Err(io::Error::other(
                        "native document changed during AX capture; observe again",
                    )
                    .into());
                }
                let location_object = location
                    .as_object_mut()
                    .ok_or_else(|| io::Error::other("native location result is not an object"))?;
                location_object.insert("session_id".into(), self.session_id.clone().into());
                location_object.insert("tab_id".into(), self.tab_id.clone().into());
                super::evidence::accessibility_document(
                    format!("surface-{}-ax-{epoch}", self.key),
                    epoch,
                    captured
                        .get("nodes")
                        .ok_or_else(|| io::Error::other("native AX nodes missing"))?,
                    policy,
                )?
            }
            super::BrowserRepresentation::Network => {
                return Err(io::Error::other(
                    "native Surface network observation is not available on this binding",
                )
                .into());
            }
            super::BrowserRepresentation::Dom => {
                return Err(io::Error::other("DOM capture uses the retained tab").into());
            }
        };
        let index = Surface::with_limits(&document, policy.limits()?)?;
        Ok((index, document, location))
    }

    pub async fn input(&self, input: SurfaceInput) -> Result<String> {
        let receipt = self.work()?.surface_input(&input).await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other(format!(
                "native Surface dispatch {:?}: {:?}",
                receipt.status, receipt.error
            ))
            .into());
        }
        Ok(receipt.id)
    }

    pub async fn navigate(&self, url: &str) -> Result<String> {
        let receipt = self.work()?.navigate(url).await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other(format!(
                "native navigation {:?}: {:?}",
                receipt.status, receipt.error
            ))
            .into());
        }
        Ok(receipt.id)
    }

    pub async fn screenshot(&self, output: &Path, name: &str) -> Result<()> {
        let receipt = self.work()?.screenshot().await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other("native screenshot did not complete").into());
        }
        let bytes = receipt
            .observation
            .and_then(|value| value.screenshot)
            .ok_or_else(|| io::Error::other("native screenshot evidence missing"))?;
        fs::write(output.join(format!("{name}.png")), bytes)?;
        Ok(())
    }

    pub async fn close(&mut self) -> Result<()> {
        if let Some(work) = self.work.take() {
            work.release().await?;
        }
        Ok(())
    }
}
