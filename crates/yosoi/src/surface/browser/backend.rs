//! One Surface driver over either the existing isolated source or an owned native Work.
use super::{native::NativeBrowser, process};
use crate::{
    documents::Document,
    session::Work,
    surface::{
        DocumentPolicies, NetworkObservationPolicy, NetworkPayload, NetworkPayloadRef, Surface,
        connection::{Result, Trace},
    },
};
use serde_json::Value;
use std::{io, path::Path};

pub(super) enum Source {
    Driver(Box<process::Browser>),
    Native(Box<NativeBrowser>),
}

pub(super) struct Browser {
    source: Source,
    key: String,
    pub documents: DocumentPolicies,
    pub capabilities: Value,
}

impl Browser {
    pub async fn open_with_policy(headless: bool, documents: DocumentPolicies) -> Result<Self> {
        let browser = process::Browser::open_with_policy(headless, documents.clone()).await?;
        Ok(Self {
            key: browser.session_key().into(),
            capabilities: browser.capabilities.clone(),
            source: Source::Driver(Box::new(browser)),
            documents,
        })
    }

    pub async fn consume_work(
        work: Work,
        documents: DocumentPolicies,
        network_policy: NetworkObservationPolicy,
    ) -> Result<Self> {
        let native = NativeBrowser::new(work, documents, network_policy).await?;
        Ok(Self {
            key: native.key().into(),
            capabilities: native.capabilities(),
            documents: native.documents.clone(),
            source: Source::Native(Box::new(native)),
        })
    }

    pub const fn native(&self) -> Option<&NativeBrowser> {
        match &self.source {
            Source::Native(native) => Some(&**native),
            Source::Driver(_) => None,
        }
    }

    pub fn network_window_limit(&self) -> Option<usize> {
        self.native().map(NativeBrowser::network_window_limit)
    }

    pub fn session_key(&self) -> &str {
        &self.key
    }

    pub async fn script(&self, operation: &str, input: Value) -> Result<Value> {
        match &self.source {
            Source::Driver(browser) => browser.script(operation, input).await,
            Source::Native(browser) => browser.script(operation, input).await,
        }
    }

    pub async fn post(&self, route: &str, input: Value) -> Result<Value> {
        match &self.source {
            Source::Driver(browser) => browser.post(route, input).await,
            Source::Native(_) => Err(io::Error::other(
                "WebDriver command is unavailable on a native Session binding",
            )
            .into()),
        }
    }

    pub async fn capture(
        &self,
        epoch: u64,
        trace: &mut Trace,
    ) -> Result<(Surface, Document, Value)> {
        match &self.source {
            Source::Driver(browser) => browser.capture(epoch, trace).await,
            Source::Native(browser) => browser.capture(epoch, trace).await,
        }
    }

    pub async fn capture_evidence(
        &self,
        epoch: u64,
        representation: super::BrowserRepresentation,
    ) -> Result<(Surface, Document, Value)> {
        match &self.source {
            Source::Driver(_) => {
                Err(io::Error::other("isolated browser supports DOM evidence only").into())
            }
            Source::Native(browser) => browser.capture_evidence(epoch, representation).await,
        }
    }

    pub async fn subscribe_network(&mut self, retain_bodies: Option<bool>) -> Result<Value> {
        match &mut self.source {
            Source::Driver(_) => Err(io::Error::other(
                "isolated ChromeDriver does not expose Surface network event subscriptions",
            )
            .into()),
            Source::Native(native) => {
                let result = native.subscribe_network(retain_bodies).await?;
                self.capabilities = native.capabilities();
                Ok(result)
            }
        }
    }

    pub async fn cancel_network(&mut self) -> Result<Value> {
        match &mut self.source {
            Source::Driver(_) => Err(io::Error::other(
                "isolated ChromeDriver does not expose Surface network event subscriptions",
            )
            .into()),
            Source::Native(native) => {
                let result = native.cancel_network().await?;
                self.capabilities = native.capabilities();
                Ok(result)
            }
        }
    }

    pub async fn wait_network_event(
        &self,
        after_sequence: u64,
        timeout_ms: u64,
    ) -> Result<Value> {
        match &self.source {
            Source::Driver(_) => Err(io::Error::other(
                "isolated ChromeDriver does not expose native network event streams",
            )
            .into()),
            Source::Native(native) => {
                native.wait_network_event(after_sequence, timeout_ms).await
            }
        }
    }

    pub fn read_network_payload(
        &self,
        reference: &NetworkPayloadRef,
        offset: usize,
        max_bytes: usize,
    ) -> Result<Value> {
        match &self.source {
            Source::Driver(_) => Err(io::Error::other(
                "isolated ChromeDriver does not retain native network payloads",
            )
            .into()),
            Source::Native(native) => native.read_network_payload(reference, offset, max_bytes),
        }
    }

    pub fn retained_network_payload(
        &self,
        id: &str,
    ) -> Option<(NetworkPayloadRef, NetworkPayload)> {
        self.native()?.retained_network_payload(id)
    }

    pub async fn screenshot(&self, output: &Path, name: &str) -> Result<()> {
        match &self.source {
            Source::Driver(browser) => browser.screenshot(output, name).await,
            Source::Native(browser) => browser.screenshot(output, name).await,
        }
    }

    pub async fn close(&mut self) -> Result<()> {
        match &mut self.source {
            Source::Driver(browser) => browser.close().await,
            Source::Native(browser) => browser.close().await,
        }
    }
}
