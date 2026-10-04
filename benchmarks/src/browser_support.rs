//! Loopback-only fixtures and resolved specifications for browser benchmarks.

use anyhow::{Context, Result, bail};
use chrono::{DateTime, TimeDelta, Utc};
use std::{
    net::{Ipv4Addr, SocketAddr},
    num::{NonZeroU32, NonZeroU64},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
    time::{Instant as TokioInstant, timeout_at},
};
use tokio_util::sync::CancellationToken;
use yosoi_types::{
    CaptureId, OperationId, Producer, ProducerId, ProducerVersion, ReasonCode, Schema, SchemaId,
    SchemaVersion,
};
use yosoi_web_capture::*;

const MINIMAL_FIXTURE: &[u8] = include_bytes!("../fixtures/browser-capture/minimal.html");
const FULL_FIXTURE: &[u8] = include_bytes!("../fixtures/browser-capture/full.html");
const GROWTH_FIXTURE: &[u8] = include_bytes!("../fixtures/browser-capture/growth.html");
// BrowserSession shutdown has four bounded fallback phases: close, reap, kill,
// and handler termination. The benchmark must give the full fallback sequence
// room to finish while still treating a 45-second cleanup as a hard failure.
const BENCHMARK_BROWSER_CLEANUP_DEADLINE_MILLIS: u64 = 45_000;

#[derive(Clone, Copy, Debug)]
pub enum ArtifactSet {
    Minimal,
    Full,
    Growth,
}
impl ArtifactSet {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "minimal" => Ok(Self::Minimal),
            "full" => Ok(Self::Full),
            "growth" => Ok(Self::Growth),
            _ => bail!("artifact set must be minimal, full, or growth"),
        }
    }
    pub const fn label(self) -> &'static str {
        match self {
            Self::Minimal => "minimal",
            Self::Full => "full",
            Self::Growth => "growth",
        }
    }
    const fn requests(self) -> WebArtifactRequestSet {
        let no = ArtifactRequest::NotRequested;
        let yes = ArtifactRequest::Required;
        match self {
            Self::Minimal => WebArtifactRequestSet::new(no, yes, no, no, no, no, no, no, no),
            Self::Full | Self::Growth => {
                WebArtifactRequestSet::new(yes, yes, yes, yes, no, no, yes, yes, yes)
            }
        }
    }
    const fn captures_all_families(self) -> bool {
        matches!(self, Self::Full | Self::Growth)
    }
}

#[derive(Clone, Copy, Debug)]
pub enum BrowserRunMode {
    Headless,
    Headful,
}
impl BrowserRunMode {
    pub fn parse_native(value: &str) -> Result<Self> {
        match value {
            "native-headless" => Ok(Self::Headless),
            "native-headful" => Ok(Self::Headful),
            _ => bail!("mode must be native-headless or native-headful"),
        }
    }
    pub const fn native_label(self) -> &'static str {
        match self {
            Self::Headless => "native-headless",
            Self::Headful => "native-headful",
        }
    }
    pub const fn label(self) -> &'static str {
        match self {
            Self::Headless => "headless",
            Self::Headful => "headful",
        }
    }
    const fn mode(self) -> BrowserMode {
        match self {
            Self::Headless => BrowserMode::Headless,
            Self::Headful => BrowserMode::Headful,
        }
    }
    pub const fn headful(self) -> bool {
        matches!(self, Self::Headful)
    }
}

#[derive(Clone, Copy, Debug)]
pub enum LoopbackResponseMode {
    Immediate,
    Delayed(Duration),
    PartialDisconnect,
}

#[derive(Debug)]
pub struct LoopbackFixture {
    address: SocketAddr,
    accepted_requests: Arc<AtomicUsize>,
    accepted_request_notification: Arc<tokio::sync::Notify>,
    cancellation: CancellationToken,
    task: JoinHandle<Result<()>>,
}
impl LoopbackFixture {
    pub async fn start(set: ArtifactSet) -> Result<Self> {
        Self::start_with_response_mode(set, LoopbackResponseMode::Immediate).await
    }

    pub async fn start_with_response_mode(
        set: ArtifactSet,
        response_mode: LoopbackResponseMode,
    ) -> Result<Self> {
        let body = match set {
            ArtifactSet::Minimal => MINIMAL_FIXTURE,
            ArtifactSet::Full => FULL_FIXTURE,
            ArtifactSet::Growth => GROWTH_FIXTURE,
        };
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .await
            .context("bind loopback browser fixture")?;
        let address = listener
            .local_addr()
            .context("read loopback fixture address")?;
        if !address.ip().is_loopback() {
            bail!("browser fixture did not bind a loopback address");
        }
        let cancellation = CancellationToken::new();
        let stop = cancellation.clone();
        let body: Arc<[u8]> = Arc::from(body);
        let accepted_requests = Arc::new(AtomicUsize::new(0));
        let task_accepted_requests = Arc::clone(&accepted_requests);
        let accepted_request_notification = Arc::new(tokio::sync::Notify::new());
        let task_accepted_request_notification = Arc::clone(&accepted_request_notification);
        let task = tokio::spawn(async move {
            loop {
                tokio::select! {
                    () = stop.cancelled() => return Ok(()),
                    accepted = listener.accept() => {
                        let (mut stream, peer) = accepted.context("accept browser fixture request")?;
                        if !peer.ip().is_loopback() { bail!("browser fixture rejected non-loopback peer {peer}"); }
                        task_accepted_requests.fetch_add(1, Ordering::Release);
                        task_accepted_request_notification.notify_waiters();
                        let response_body = Arc::clone(&body);
                        let response_stop = stop.clone();
                        tokio::spawn(async move {
                            let mut request = [0_u8; 8192];
                            let read = stream.read(&mut request).await.context("read browser fixture request")?;
                            let path = request.get(..read).and_then(|bytes| std::str::from_utf8(bytes).ok()).and_then(|text| text.lines().next()).and_then(|line| line.split_whitespace().nth(1)).unwrap_or("/");
                            if let LoopbackResponseMode::Delayed(delay) = response_mode {
                                tokio::select! {
                                    () = response_stop.cancelled() => return Ok(()),
                                    () = tokio::time::sleep(delay) => {}
                                }
                            }
                            if matches!(response_mode, LoopbackResponseMode::PartialDisconnect) {
                                let declared = response_body.len().checked_add(100).context("partial response length overflow")?;
                                let head = format!("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {declared}\r\nConnection: close\r\n\r\n");
                                stream.write_all(head.as_bytes()).await.context("write partial fixture response head")?;
                                let retained = response_body.get(..response_body.len().min(16)).unwrap_or_default();
                                stream.write_all(retained).await.context("write partial fixture response prefix")?;
                                return Ok(());
                            }
                            let (status, body) = if path == "/" { ("200 OK", response_body.as_ref()) } else { ("404 Not Found", &[][..]) };
                            let head = format!("HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len());
                            stream.write_all(head.as_bytes()).await.context("write browser fixture response head")?;
                            stream.write_all(body).await.context("write browser fixture response body")?;
                            Ok::<_, anyhow::Error>(())
                        });
                    }
                }
            }
        });
        Ok(Self {
            address,
            accepted_requests,
            accepted_request_notification,
            cancellation,
            task,
        })
    }
    pub fn url(&self) -> String {
        format!("http://127.0.0.1:{}/", self.address.port())
    }
    pub fn accepted_request_count(&self) -> usize {
        self.accepted_requests.load(Ordering::Acquire)
    }
    pub async fn wait_for_accepted_requests(
        &self,
        expected: usize,
        timeout_after: Duration,
    ) -> bool {
        let Some(deadline) = TokioInstant::now().checked_add(timeout_after) else {
            return false;
        };
        loop {
            let notified = self.accepted_request_notification.notified();
            if self.accepted_request_count() >= expected {
                return true;
            }
            if timeout_at(deadline, notified).await.is_err() {
                return self.accepted_request_count() >= expected;
            }
        }
    }
}
impl Drop for LoopbackFixture {
    fn drop(&mut self) {
        self.cancellation.cancel();
        self.task.abort();
    }
}

fn producer() -> Result<Producer> {
    Ok(Producer::new(
        ProducerId::new("com.cascadinglabs.void_crawl_core")?,
        ProducerVersion::new("0.5.0")?,
    ))
}
fn reason() -> Result<ReasonCode> {
    Ok(ReasonCode::new("benchmark.unavailable")?)
}
fn schema(name: &str) -> Result<Schema> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

pub fn spec(
    url: &str,
    artifacts: ArtifactSet,
    mode: BrowserRunMode,
) -> Result<ResolvedBrowserCaptureSpec> {
    spec_with_deadline(url, artifacts, mode, 60_000)
}

pub fn spec_with_deadline(
    url: &str,
    artifacts: ArtifactSet,
    mode: BrowserRunMode,
    deadline_ms: u64,
) -> Result<ResolvedBrowserCaptureSpec> {
    let producer = producer()?;
    let capture_id = CaptureId::random();
    let supported = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let unavailable = ArtifactCapability::Unsupported { reason: reason()? };
    let profile = WebProviderCapabilityProfile::new(
        producer.clone(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            mode.mode(),
        )),
        WebArtifactCapabilitySet::new(
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            unavailable,
            supported.clone(),
            supported.clone(),
            supported,
        ),
    )?;
    let enabled = BrowserCapabilityStatus::Supported;
    let capabilities = CertifiedBrowserCapabilities::new(
        profile,
        &producer,
        mode.mode(),
        BrowserInstrumentationMode::Normal,
        BrowserFamilyCapabilities::new(
            enabled.clone(),
            enabled.clone(),
            enabled.clone(),
            enabled.clone(),
            enabled.clone(),
            BrowserCapabilityStatus::Unsupported { reason: reason()? },
            enabled.clone(),
            enabled.clone(),
            enabled,
        ),
    )?;
    let byte_limit =
        NonZeroU64::new(1_000_000).ok_or_else(|| anyhow::anyhow!("nonzero byte limit"))?;
    let bounds = BrowserProviderBounds::new(
        [
            BrowserByteDomain::RenderedDomUtf8,
            BrowserByteDomain::CdpDecodedBody,
            BrowserByteDomain::DecodedSourceUtf8,
            BrowserByteDomain::AccessibilityJsonUtf8,
            BrowserByteDomain::ScreenshotPng,
            BrowserByteDomain::RuntimeDiagnosticUtf8,
        ]
        .into_iter()
        .filter(|domain| {
            *domain == BrowserByteDomain::RenderedDomUtf8 || artifacts.captures_all_families()
        })
        .map(|domain| {
            BrowserByteBound::new(
                domain,
                byte_limit,
                BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                if domain == BrowserByteDomain::RuntimeDiagnosticUtf8 {
                    BrowserBudgetScope::CaptureAggregate
                } else {
                    BrowserBudgetScope::PerPayload
                },
            )
        })
        .collect(),
        NonZeroU64::new(10_000).ok_or_else(|| anyhow::anyhow!("nonzero event limit"))?,
        NonZeroU32::new(1_000).ok_or_else(|| anyhow::anyhow!("nonzero resource limit"))?,
        NonZeroU32::new(10_000)
            .ok_or_else(|| anyhow::anyhow!("nonzero accessibility node limit"))?,
    )?;
    ResolvedBrowserCaptureSpec::new(
        WebCaptureRequest::new(
            capture_id,
            RequestedWebTarget::parse(url)?,
            WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
                NavigationContext::FreshTopLevel,
            )),
        ),
        artifacts.requests(),
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(
                    deadline_ms
                        .checked_mul(1_000)
                        .context("browser benchmark deadline overflow")?,
                )?,
                None,
                None,
            ),
            SettlementPolicy::Disabled,
        ),
        BrowserNavigationPolicy::new(NavigationCompletionPolicy::ControllerCompleted),
        BrowserAttemptEnvironment::new(mode.mode()),
        bounds,
        capabilities,
        producer,
        OperationId::new("benchmark.browser-capture")?,
        BrowserOutputSchemas::new(
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.source"))
                .transpose()?,
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.source-representation"))
                .transpose()?,
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.decoded-source"))
                .transpose()?,
            Some(schema("benchmark.dom")?),
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.ax"))
                .transpose()?,
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.network"))
                .transpose()?,
            None,
            None,
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.layout"))
                .transpose()?,
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.visual"))
                .transpose()?,
            artifacts
                .captures_all_families()
                .then(|| schema("benchmark.runtime"))
                .transpose()?,
        ),
        BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::AdmitNetworkUrls,
            BrowserHeaderAdmission::Omit,
            if artifacts.captures_all_families() {
                BrowserMainBodyAdmission::AdmitDecodedRepresentation
            } else {
                BrowserMainBodyAdmission::Omit
            },
        ),
    )
    .context("construct loopback browser capture specification")
}

#[derive(Debug)]
pub struct CapturedBrowserAttempt {
    pub result: BrowserAdapterResult,
    pub finished_at: DateTime<Utc>,
}

fn finalization_anchor(result: &BrowserAdapterResult) -> Result<DateTime<Utc>> {
    let lifecycle = result
        .lifecycle()
        .context("browser benchmark result omitted its acquisition lifecycle")?;
    let elapsed = i64::try_from(lifecycle.observed_through().as_microseconds())
        .context("browser benchmark elapsed time exceeds the wall-clock range")?;
    lifecycle
        .started_at()
        .checked_add_signed(TimeDelta::microseconds(elapsed))
        .context("browser benchmark finish anchor exceeds the wall-clock range")
}

pub fn execution_limits(
    processes: NonZeroU32,
    contexts_total: NonZeroU32,
    contexts_per_process: NonZeroU32,
    tabs_total: NonZeroU32,
    queue_depth: NonZeroU32,
    recycle_threshold: NonZeroU32,
) -> Result<BrowserExecutionLimits> {
    BrowserExecutionLimits::new(
        BrowserProcessLimit::new(processes),
        BrowserContextTotalLimit::new(contexts_total),
        BrowserContextsPerProcessLimit::new(contexts_per_process),
        BrowserTabTotalLimit::new(tabs_total),
        BrowserTabsPerSessionLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(queue_depth),
        BrowserQueueWaitLimit::new(NonZeroU64::new(60_000).context("nonzero browser queue wait")?),
        BrowserCleanupDeadline::new(
            NonZeroU64::new(BENCHMARK_BROWSER_CLEANUP_DEADLINE_MILLIS)
                .context("nonzero browser cleanup deadline")?,
        ),
        BrowserRecycleThreshold::new(recycle_threshold),
    )
    .context("construct browser execution limits")
}

pub fn warm_manager(mode: BrowserRunMode) -> Result<yosoi_web_capture::BrowserExecutionManager> {
    Ok(yosoi_web_capture::BrowserExecutionManager::new(
        execution_limits(
            NonZeroU32::MIN,
            NonZeroU32::MIN,
            NonZeroU32::MIN,
            NonZeroU32::MIN,
            NonZeroU32::new(4).context("nonzero warm queue depth")?,
            NonZeroU32::new(1_000).context("nonzero warm recycle threshold")?,
        )?,
        yosoi_web_capture::BrowserExecutionManagerConfig {
            headful: mode.headful(),
            minimal_cdp: false,
        },
    ))
}

pub async fn capture_to_staged_facts(
    spec: &ResolvedBrowserCaptureSpec,
) -> Result<CapturedBrowserAttempt> {
    let result = yosoi_web_capture::capture_attempt(spec, &CancellationToken::new())
        .await
        .context("VoidCrawl loopback capture")?;
    if !result.is_ready() {
        bail!(
            "browser benchmark capture stopped at {:?}",
            result.terminal()
        );
    }
    let finished_at = finalization_anchor(&result)?;
    Ok(CapturedBrowserAttempt {
        result,
        finished_at,
    })
}

pub async fn capture_to_staged_facts_managed(
    manager: &yosoi_web_capture::BrowserExecutionManager,
    spec: &ResolvedBrowserCaptureSpec,
) -> Result<CapturedBrowserAttempt> {
    let result =
        yosoi_web_capture::capture_attempt_managed(manager, spec, &CancellationToken::new())
            .await
            .context("managed VoidCrawl loopback capture")?;
    if !result.is_ready() || result.execution().is_none() {
        bail!("managed browser benchmark did not produce ready execution facts");
    }
    let finished_at = finalization_anchor(&result)?;
    Ok(CapturedBrowserAttempt {
        result,
        finished_at,
    })
}
pub fn finalize(captured: CapturedBrowserAttempt) -> Result<CaptureBundle> {
    let bundle = finalize_browser_capture(
        captured.result,
        BrowserFinalizationInput {
            finished_at: captured.finished_at,
            resource_origin: Observation::Unobserved,
            initiator_origin: Observation::Unobserved,
        },
    )
    .context("finalize browser capture")?;
    if bundle.capture().completeness() != CaptureCompleteness::Complete {
        bail!("browser benchmark finalization produced an incomplete capture");
    }
    Ok(bundle)
}
