//! One Surface driver over either the existing isolated source or an owned native Work.
use super::{native::NativeBrowser, process};
use crate::{
    documents::Document,
    session::Work,
    surface::{
        DocumentPolicies, PixelArtifact, Surface,
        connection::{Result, Trace},
    },
};
use serde_json::Value;
use std::io;

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

    pub async fn consume_work(work: Work, documents: DocumentPolicies) -> Result<Self> {
        let native = NativeBrowser::new(work, documents).await?;
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

    pub async fn screenshot(&self) -> Result<PixelArtifact> {
        match &self.source {
            Source::Driver(browser) => browser.screenshot().await,
            Source::Native(browser) => browser.screenshot().await,
        }
    }

    pub async fn close(&mut self) -> Result<()> {
        match &mut self.source {
            Source::Driver(browser) => browser.close().await,
            Source::Native(browser) => browser.close().await,
        }
    }
}
