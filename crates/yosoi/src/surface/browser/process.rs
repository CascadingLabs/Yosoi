//! Experimental ChromeDriver transport shared by the surface CLI and article example.
use crate::internal::browser::session::browser_distribution::supported_chrome_executable;
use crate::surface::connection::{Result, Trace};
use crate::{
    documents::{Document, DocumentEpoch},
    surface::{DocumentPolicies, Surface},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use rustls::crypto::{CryptoProvider, ring};
use serde_json::{Value, json};
use std::{env, fs, io, path::Path, process::Stdio, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::{Child, Command},
    time::timeout,
};
const SCRIPT: &str = include_str!("extract.js");
pub(super) const ELEMENT: &str = "element-6066-11e4-a52e-4f735466cecf";
#[derive(Debug)]
pub struct Browser {
    client: reqwest::Client,
    base: String,
    session: String,
    pub capabilities: Value,
    driver: Child,
    profile: tempfile::TempDir,
    pub(super) documents: DocumentPolicies,
}
impl Browser {
    pub fn session_key(&self) -> &str {
        &self.session
    }
    pub(super) async fn open_with_policy(
        headless: bool,
        documents: DocumentPolicies,
    ) -> Result<Self> {
        documents.validate()?;
        if CryptoProvider::get_default().is_none() {
            ring::default_provider()
                .install_default()
                .map_err(|_| io::Error::other("could not install the Rustls crypto provider"))?;
        }
        let profile = tempfile::tempdir()?;
        let driver_bin = env::var("CHROMEDRIVER").unwrap_or_else(|_| "chromedriver".into());
        let browser_bin = supported_chrome_executable(env::var("CHROME").ok().as_deref()).await?;
        let mut driver = Command::new(driver_bin)
            .args(["--port=0", "--allowed-ips=127.0.0.1"])
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()?;
        let stdout = driver
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("driver stdout missing"))?;
        let mut lines = BufReader::new(stdout).lines();
        let port = timeout(Duration::from_secs(10), async {
            while let Some(line) = lines.next_line().await? {
                if let Some(value) =
                    line.strip_prefix("ChromeDriver was started successfully on port ")
                {
                    return Ok::<_, io::Error>(value.trim_end_matches('.').to_owned());
                }
            }
            Err(io::Error::other("driver exited before announcing its port"))
        })
        .await??;
        // Drain stdout so later driver diagnostics cannot block its pipe.
        tokio::spawn(async move { while let Ok(Some(_)) = lines.next_line().await {} });
        let mut browser = Self {
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(65))
                .build()?,
            base: format!("http://127.0.0.1:{port}"),
            session: String::new(),
            capabilities: Value::Null,
            driver,
            profile,
            documents,
        };
        let mut flags = vec![
            "--no-first-run".to_owned(),
            "--no-default-browser-check".to_owned(),
            "--window-size=1440,1000".to_owned(),
            format!("--user-data-dir={}", browser.profile.path().display()),
        ];
        if headless {
            flags.push("--headless=new".into());
        }
        let created = browser.command(reqwest::Method::POST, "/session", Some(json!({"capabilities":{"alwaysMatch":{
            "browserName":"chrome","pageLoadStrategy":"eager","goog:loggingPrefs":{"performance":"ALL"},"goog:chromeOptions":{"binary":browser_bin,"args":flags,"perfLoggingPrefs":{"enableNetwork":true,"enablePage":false}}}}}))).await?;
        browser.capabilities = created.get("capabilities").cloned().unwrap_or(Value::Null);
        browser.session = created
            .get("sessionId")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("driver session ID missing"))?
            .into();
        browser
            .post(
                "/timeouts",
                json!({"pageLoad":45000,"script":20000,"implicit":0}),
            )
            .await?;
        Ok(browser)
    }
    pub async fn command(
        &self,
        method: reqwest::Method,
        route: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        let request = self.client.request(method, format!("{}{route}", self.base));
        let response = if let Some(body) = body {
            request.json(&body)
        } else {
            request
        }
        .send()
        .await?;
        let status = response.status();
        let value: Value = response.json().await?;
        let value = value
            .get("value")
            .cloned()
            .ok_or_else(|| io::Error::other("missing WebDriver response value"))?;
        if !status.is_success() || value.get("error").is_some() {
            return Err(io::Error::other(format!("WebDriver: {value}")).into());
        }
        Ok(value)
    }
    pub async fn post(&self, route: &str, body: Value) -> Result<Value> {
        self.command(
            reqwest::Method::POST,
            &format!("/session/{}{route}", self.session),
            Some(body),
        )
        .await
    }
    pub async fn script(&self, operation: &str, input: Value) -> Result<Value> {
        let route = if operation == "watch" {
            "/execute/async"
        } else {
            "/execute/sync"
        };
        self.post(route, json!({"script":SCRIPT,"args":[operation,input]}))
            .await
    }
    pub async fn capture(
        &self,
        epoch: u64,
        trace: &mut Trace,
    ) -> Result<(Surface, Document, Value)> {
        let captured = self.script("capture", json!({"epoch":epoch,"limits":self.documents.dom,"html_limits":self.documents.html})).await?;
        let wire = captured
            .get("wire")
            .ok_or_else(|| io::Error::other("capture lacks DOM evidence"))?;
        let document = Document::rendered_dom(
            format!("surface-{}-{epoch}", self.session),
            DocumentEpoch::try_from(epoch)?,
            serde_json::to_vec(wire)?,
        )?;
        let index = match Surface::with_limits(&document, self.documents.dom.limits()?) {
            Ok(index) => index,
            Err(error) => {
                let artifact = trace.output.join(format!("rejected-capture-{epoch}.json"));
                fs::write(&artifact, document.bytes())?;
                trace.event(
                    "capture.rejected",
                    json!({"artifact":artifact,"error":error.to_string()}),
                );
                return Err(error.into());
            }
        };
        trace.event("capture", json!({"url":captured.get("url"),"epoch":epoch,"capture":index.identity(),"nodes":index.node_count(),"source_bytes":index.source_bytes(),"normalized_strings":captured.get("normalized_strings")}));
        Ok((index, document, captured))
    }
    pub(super) async fn capture_evidence(
        &self,
        epoch: u64,
        representation: super::BrowserRepresentation,
    ) -> Result<(Surface, Document, Value)> {
        use super::BrowserRepresentation;
        let policy = representation.policy(&self.documents);
        let location = self.script("location", json!({})).await?;
        let id = format!("surface-{}-{representation:?}-{epoch}", self.session);
        let document = match representation {
            BrowserRepresentation::Dom => {
                return Err(io::Error::other("DOM capture uses the retained live session").into());
            }
            BrowserRepresentation::Ax => {
                let before = self.cdp("Page.getFrameTree", json!({})).await?;
                let captured = self
                    .cdp(
                        "Accessibility.getFullAXTree",
                        json!({"depth":policy.max_depth}),
                    )
                    .await?;
                let after = self.cdp("Page.getFrameTree", json!({})).await?;
                if before.pointer("/frameTree/frame/loaderId")
                    != after.pointer("/frameTree/frame/loaderId")
                    || before.pointer("/frameTree/frame/id") != after.pointer("/frameTree/frame/id")
                {
                    return Err(io::Error::other(
                        "document changed during AX capture; observe again",
                    )
                    .into());
                }
                super::evidence::accessibility_document(
                    id,
                    epoch,
                    captured
                        .get("nodes")
                        .ok_or_else(|| io::Error::other("AX tree missing nodes"))?,
                    policy,
                )?
            }
            BrowserRepresentation::Network => {
                let logs = self.post("/log", json!({"type":"performance"})).await?;
                let logs = logs
                    .as_array()
                    .ok_or_else(|| io::Error::other("network log is not an array"))?;
                let mut events = Vec::new();
                let mut bytes = 0usize;
                let mut observed = 0usize;
                for entry in logs {
                    let raw = entry
                        .get("message")
                        .and_then(Value::as_str)
                        .ok_or_else(|| io::Error::other("network log message missing"))?;
                    let envelope: Value = serde_json::from_str(raw)?;
                    let message = envelope
                        .get("message")
                        .ok_or_else(|| io::Error::other("network log envelope invalid"))?;
                    if !message
                        .get("method")
                        .and_then(Value::as_str)
                        .is_some_and(|m| m.starts_with("Network."))
                    {
                        continue;
                    }
                    observed = observed.saturating_add(1);
                    let size = serde_json::to_vec(message)?.len().saturating_add(1);
                    if bytes.saturating_add(size) <= policy.max_bytes.saturating_sub(512)
                        && events.len() < policy.max_nodes.saturating_sub(16) / 16
                    {
                        bytes = bytes.saturating_add(size);
                        events.push(message.clone());
                    }
                }
                Document::json(
                    id,
                    serde_json::to_vec(
                        &json!({"schema":"yosoi.network.v1","document_epoch":epoch,
                    "url":location.get("url"),"coverage":{"complete":false,"reason":"browser_network_log_window"},
                    "events_observed":observed,"events_retained":events.len(),"events_omitted":observed.saturating_sub(events.len()),
                    "response_bodies":"not_collected","events":events}),
                    )?,
                )?
            }
        };
        let index = Surface::with_limits(&document, policy.limits()?)?;
        Ok((index, document, location))
    }
    async fn cdp(&self, command: &str, params: Value) -> Result<Value> {
        self.post("/goog/cdp/execute", json!({"cmd":command,"params":params}))
            .await
    }
    pub async fn screenshot(&self, output: &Path, name: &str) -> Result<()> {
        let value = self
            .command(
                reqwest::Method::GET,
                &format!("/session/{}/screenshot", self.session),
                None,
            )
            .await?;
        let encoded = value
            .as_str()
            .ok_or_else(|| io::Error::other("invalid screenshot"))?;
        fs::write(
            output.join(format!("{name}.png")),
            STANDARD.decode(encoded)?,
        )?;
        Ok(())
    }
    pub async fn close(&mut self) -> Result<()> {
        let result = self
            .command(
                reqwest::Method::DELETE,
                &format!("/session/{}", self.session),
                None,
            )
            .await;
        self.driver.kill().await?;
        self.driver.wait().await?;
        result?;
        Ok(())
    }
}
