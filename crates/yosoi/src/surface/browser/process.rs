//! Experimental ChromeDriver transport shared by the surface CLI and article example.
use crate::internal::browser::session::browser_distribution::supported_chrome_executable;
use crate::surface::connection::{Result, Trace};
use crate::{
    documents::{Document, DocumentEpoch, FileLimits, FileMetadata, ImageDocument},
    surface::{
        Limits, PixelArtifact, PixelCoordinateKind, PixelCoordinateSpace, PixelLimits,
        PixelOrientation, PixelSource, Surface,
    },
};
use base64::{Engine, engine::general_purpose::STANDARD};
use image::{ImageFormat, ImageReader};
use rustls::crypto::{CryptoProvider, ring};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{env, fs, io, process::Stdio, time::Duration};
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
}
impl Browser {
    pub fn session_key(&self) -> &str {
        &self.session
    }
    pub async fn open(headless: bool) -> Result<Self> {
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
            "browserName":"chrome","pageLoadStrategy":"eager","goog:chromeOptions":{"binary":browser_bin,"args":flags}}}}))).await?;
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
        let captured = self.script("capture", json!({"epoch":epoch})).await?;
        let wire = captured
            .get("wire")
            .ok_or_else(|| io::Error::other("capture lacks DOM evidence"))?;
        let document = Document::rendered_dom(
            format!("surface-{}-{epoch}", self.session),
            DocumentEpoch::try_from(epoch)?,
            serde_json::to_vec(wire)?,
        )?;
        let index = match Surface::with_limits(
            &document,
            Limits {
                input_bytes: 32 * 1024 * 1024,
                ..Limits::default()
            },
        ) {
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
    pub async fn screenshot(&self) -> Result<PixelArtifact> {
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
        let limits = PixelLimits::default().validate()?;
        let encoded_limit = limits
            .max_output_bytes
            .checked_add(2)
            .and_then(|value| value.checked_div(3))
            .and_then(|value| value.checked_mul(4))
            .ok_or_else(|| io::Error::other("screenshot size limit overflow"))?;
        if encoded.len() > encoded_limit {
            return Err(io::Error::other("screenshot exceeds pixel output byte limit").into());
        }
        let bytes = STANDARD.decode(encoded)?;
        if bytes.len() > limits.max_output_bytes {
            return Err(io::Error::other("screenshot exceeds pixel output byte limit").into());
        }
        let mut reader = ImageReader::new(std::io::Cursor::new(&bytes)).with_guessed_format()?;
        if reader.format() != Some(ImageFormat::Png) {
            return Err(io::Error::other("browser screenshot is not PNG").into());
        }
        let mut decode_limits = image::Limits::default();
        decode_limits.max_image_width = Some(limits.max_side);
        decode_limits.max_image_height = Some(limits.max_side);
        decode_limits.max_alloc = Some(
            u64::try_from(limits.max_decoded_bytes)
                .map_err(|_| io::Error::other("pixel allocation limit does not fit u64"))?,
        );
        reader.limits(decode_limits);
        let (width, height) = reader.into_dimensions()?;
        limits.check_output(width, height, bytes.len())?;
        let digest = Sha256::digest(&bytes);
        let source_id = format!("browser-screenshot-v1:{}:{digest:x}", self.session);
        let metadata = FileMetadata::new()
            .with_declared_media_type("image/png")?
            .with_source(format!("browser:{}", self.session))?;
        let document = ImageDocument::from_bytes_with_metadata(
            format!("browser-screenshot-{digest:x}"),
            bytes,
            metadata,
            FileLimits::new(
                u64::try_from(limits.max_output_bytes)
                    .map_err(|_| io::Error::other("pixel byte limit does not fit u64"))?,
            )?,
        )?;
        PixelArtifact::from_raster_document(
            document,
            PixelSource::BrowserScreenshot {
                identity: source_id,
            },
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DecodedCanvas,
                width,
                height,
                orientation: PixelOrientation::NotApplicable,
            },
        )
        .map_err(Into::into)
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
