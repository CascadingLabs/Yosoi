#![cfg(feature = "browser")]
//! Explicit live qualification of independent Session-owned visual evidence.

use futures::FutureExt;
use serde_json::Value;
use std::{
    collections::BTreeSet,
    env,
    error::Error,
    io,
    panic::{AssertUnwindSafe, resume_unwind},
    path::PathBuf,
    result::Result as StdResult,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{fs, process::Command};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{Notify, mpsc, oneshot},
    task::{JoinHandle, JoinSet},
    time::{Instant, timeout},
};
use yosoi::{
    Archive,
    archive::{DocumentArchiveRef, ImageDocumentArchiveRef, VideoDocumentArchiveRef},
    automation_record::OperationStatus,
    flow::Condition,
    policy::observe::{RecordingMode, RecordingRule},
    policy::{Acquisition, BrowserMode, Policy},
    session::{
        self, RecordingOptions, RecordingScope, ScreenshotOptions, ScreenshotTarget, SessionPolicy,
    },
};

type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;

struct Fixture {
    base: String,
    paints: mpsc::Receiver<(u32, u32, Instant)>,
    stop: oneshot::Sender<()>,
    task: JoinHandle<()>,
}

impl Fixture {
    async fn start() -> Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let base = format!("http://{}", listener.local_addr()?);
        let (stop, mut stopped) = oneshot::channel();
        let (paints_tx, paints) = mpsc::channel(64);
        let released = Arc::new(Notify::new());
        let task = tokio::spawn(async move {
            let mut clients = JoinSet::new();
            loop {
                tokio::select! {
                    _ = &mut stopped => break,
                    Some(_) = clients.join_next(), if !clients.is_empty() => {},
                    accepted = listener.accept() => {
                        let Ok((mut stream, _)) = accepted else { break };
                        let paints = paints_tx.clone();
                        let released = Arc::clone(&released);
                        clients.spawn(async move {
                            let mut buffer = [0; 8192];
                            let Ok(count) = stream.read(&mut buffer).await else { return };
                            let request = String::from_utf8_lossy(buffer.get(..count).unwrap_or_default());
                            let path = request.split_whitespace().nth(1).unwrap_or("/");
                            let body = if path == "/wait" {
                                released.notified().await;
                                "released"
                            } else if path == "/release" {
                                released.notify_one();
                                "released"
                            } else if path.starts_with("/paint?") {
                                if let Ok(url) = url::Url::parse(&format!("http://fixture{path}")) {
                                    let id = url.query_pairs().find(|(key, _)| key == "id").and_then(|(_, value)| value.parse().ok());
                                    let generation = url.query_pairs().find(|(key, _)| key == "generation").and_then(|(_, value)| value.parse().ok());
                                    if let (Some(id), Some(generation)) = (id, generation) {
                                        let _ = paints.try_send((id, generation, Instant::now()));
                                    }
                                }
                                "ok"
                            } else {
                                include_str!("fixtures/session-observation.html")
                            };
                            let response = format!("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
                            let _ = stream.write_all(response.as_bytes()).await;
                        });
                    }
                }
            }
            clients.abort_all();
            while clients.join_next().await.is_some() {}
        });
        Ok(Self {
            base,
            paints,
            stop,
            task,
        })
    }

    async fn rendered(&mut self, ids: &[u32], generation: u32, since: Instant) -> Result<()> {
        let mut pending: BTreeSet<_> = ids.iter().copied().collect();
        timeout(Duration::from_secs(30), async {
            while !pending.is_empty() {
                let (id, observed_generation, at) = self
                    .paints
                    .recv()
                    .await
                    .ok_or_else(|| io::Error::other("fixture stopped"))?;
                if observed_generation == generation && at >= since {
                    pending.remove(&id);
                }
            }
            Ok::<_, io::Error>(())
        })
        .await??;
        Ok(())
    }

    async fn close(self) {
        let _ = self.stop.send(());
        let _ = self.task.await;
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "live regular Chrome, Xvfb and FFmpeg five-source qualification"]
async fn five_outputs_share_session_without_sharing_recording_lifetimes() -> Result<()> {
    let mut fixture = Fixture::start().await?;
    let mut policy = Policy::default();
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headful)];
    policy.observe.native_tab_capture = true;
    policy.observe.limits.max_recordings = 6;
    policy.observe.recordings.push(RecordingRule {
        mode: RecordingMode::BrowserVisible,
        ..RecordingRule::default()
    });
    let browser = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            mode: BrowserMode::Headful,
            maximum_tabs: 4,
            execution_concurrency: 1,
            ..SessionPolicy::default()
        })
        .allow_javascript()
        .acquire()
        .await?;
    let result = Box::pin(AssertUnwindSafe(qualify(&browser, &mut fixture)).catch_unwind()).await;
    let closed = browser.close().await;
    drop(browser);
    fixture.close().await;
    match result {
        Ok(result) => result?,
        Err(panic) => resume_unwind(panic),
    }
    closed?;
    Ok(())
}

#[expect(
    clippy::cognitive_complexity,
    clippy::significant_drop_tightening,
    reason = "The end-to-end qualification intentionally retains sibling Work and Tab owners across overlapping recording windows."
)]
async fn qualify(browser: &session::Session, fixture: &mut Fixture) -> Result<()> {
    let mut tabs = Vec::new();
    let mut workers = vec![browser.work().await?];
    for _ in 1..4 {
        let tab = browser.new_tab().await?;
        workers.push(tab.work().await?);
        tabs.push(tab);
    }
    for (id, work) in workers.iter().enumerate() {
        eprintln!("PHASE navigate tab {id}");
        work.navigate(&format!("{}/?id={id}", fixture.base)).await?;
    }
    eprintln!("PHASE target screenshot");
    let image = workers
        .first()
        .ok_or_else(|| io::Error::other("initial Work missing"))?
        .screenshot_with(ScreenshotOptions::default().target(ScreenshotTarget::Role {
            role: "button".into(),
            name: "Mark this tab".into(),
            nth: None,
        }))
        .await?;
    assert!(image.document.byte_len() > 0);
    assert!(
        image.metadata.bounds.is_some(),
        "target crop keeps source coordinates"
    );
    let first = workers
        .first()
        .ok_or_else(|| io::Error::other("initial Work missing"))?;
    let stale = ScreenshotOptions {
        expected_document_epoch: Some(u64::MAX),
        ..ScreenshotOptions::default()
    };
    assert!(
        first.screenshot_with(stale).await.is_err(),
        "stale epoch must reject capture"
    );
    assert!(
        first
            .screenshot_with(ScreenshotOptions::default().max_bytes(1))
            .await
            .is_err(),
        "retained screenshot byte bound must apply"
    );
    assert!(
        first
            .screenshot_with(ScreenshotOptions::default().target(ScreenshotTarget::Role {
                role: "button".into(),
                name: "Missing fixture control".into(),
                nth: None,
            }))
            .await
            .is_err(),
        "missing target must not become a viewport capture"
    );
    eprintln!("PHASE browser overview start");
    let options = RecordingOptions::default()
        .max_duration_ms(30_000)
        .frames_per_second(5);
    let overview = browser
        .start_recording(RecordingScope::BrowserVisible, options.clone())
        .await?;
    let mut recordings = Vec::new();
    for (id, work) in workers.iter().enumerate() {
        eprintln!("PHASE tab recording {id} start");
        recordings.push(work.start_recording(options.clone()).await?);
    }
    eprintln!("PHASE all streams rendering");
    let began = Instant::now();
    fixture.rendered(&[0, 1, 2, 3], 0, began).await?;
    let realm = first
        .evaluate(
            "({poisoned:(()=>{try{MediaRecorder.isTypeSupported('video/webm');return false}catch{return true}})(),bindings:Object.getOwnPropertyNames(globalThis).filter(name=>name.startsWith('__yosoi_media_'))})",
        )
        .await?;
    assert_eq!(
        realm.result,
        Some(serde_json::json!({"poisoned": true, "bindings": []})),
        "native recording must ignore site intrinsics and keep its binding private"
    );
    let waiting = workers
        .first()
        .ok_or_else(|| io::Error::other("initial Work missing"))?;
    let releasing = workers
        .get(1)
        .ok_or_else(|| io::Error::other("sibling Work missing"))?;
    let condition = Condition::Exists {
        selector: "[data-released]".into(),
    };
    // Fixture-owned selectors describe the controlled input. No site recipe is hard-coded.
    let (waited, clicked) = tokio::join!(
        waiting.wait_until(&condition, 10_000),
        releasing.click("#mark")
    );
    let clicked = clicked?;
    let clicked_id = clicked.id.clone();
    assert_eq!(clicked.status, OperationStatus::Observed);
    assert_eq!(waited?.status, OperationStatus::Observed);
    let duplicate = workers
        .first()
        .ok_or_else(|| io::Error::other("initial Work missing"))?
        .start_recording(options)
        .await?;
    fixture.rendered(&[0], 0, Instant::now()).await?;
    let short = duplicate.stop().await?;
    assert!(
        !short.segments.is_empty(),
        "second same-tab output must retain native media; outcome={:?}",
        short.metadata()
    );
    let first = workers
        .first()
        .ok_or_else(|| io::Error::other("initial Work missing"))?;
    first
        .navigate(&format!("{}/?id=0&generation=1", fixture.base))
        .await?;
    fixture.rendered(&[0], 1, Instant::now()).await?;
    // Recording owns a read source, not the initiating interaction lease.
    let released = workers.remove(0);
    released.release().await?;
    let reacquired = timeout(Duration::from_secs(5), browser.work()).await??;
    fixture.rendered(&[0], 1, Instant::now()).await?;
    reacquired.release().await?;
    let directory = tempfile::tempdir()?;
    let archive = Archive::open(directory.path()).await?;
    let image_ref = archive.write(&image.document).await?;
    assert_eq!(
        archive.read(&image_ref).await?.sha256(),
        image.document.sha256()
    );
    let mut sources = BTreeSet::new();
    let mut archived_videos = Vec::new();
    let mut archived_recordings = Vec::new();
    let output_path = env::var_os("YOSOI_OBSERVATION_OUTPUT").map(PathBuf::from);
    if let Some(path) = &output_path {
        fs::create_dir_all(path).await?;
        fs::write(path.join("target.png"), image.document.bytes()).await?;
    }
    for (index, handle) in recordings.into_iter().enumerate() {
        let output = handle.stop().await?;
        sources.insert(output.source.id.clone());
        if index == 1 {
            assert!(
                output
                    .actions
                    .iter()
                    .any(|action| action.operation_id == clicked_id),
                "video interval keeps the settled click receipt link"
            );
        }
        let manifest_ref = output.write_to(&archive).await?;
        archived_recordings.push(
            serde_json::json!({"reference":manifest_ref.to_string(), "metadata":output.metadata()}),
        );
        assert!(
            !output.segments.is_empty(),
            "native tab output contains video"
        );
        if index == 0 {
            assert!(
                output.segments.len() >= 2,
                "logical recording must capture the destination document after navigation"
            );
        }
        if let Some(path) = &output_path {
            fs::write(
                path.join(format!("tab-{index}.json")),
                serde_json::to_vec_pretty(&output.metadata())?,
            )
            .await?;
        }
        for (segment_index, segment) in output.segments.iter().enumerate() {
            if let Some(path) = &output_path {
                fs::write(
                    path.join(format!("tab-{index}-{segment_index}.webm")),
                    segment.document.bytes(),
                )
                .await?;
            }
            let reference = archive.write(&segment.document).await?;
            archived_videos.push(serde_json::json!({"reference": reference.to_string(), "sha256":segment.document.sha256()}));
            assert_eq!(
                archive.read(&reference).await?.sha256(),
                segment.document.sha256()
            );
        }
        eprintln!(
            "TAB_RECORDING={}",
            serde_json::to_string(&output.metadata())?
        );
    }
    assert_eq!(sources.len(), 4, "tabs need distinct capture sources");
    let overview = overview.stop().await?;
    assert!(!overview.segments.is_empty(), "overview contains video");
    if let Some(path) = &output_path {
        fs::write(
            path.join("overview.json"),
            serde_json::to_vec_pretty(&overview.metadata())?,
        )
        .await?;
        for (index, segment) in overview.segments.iter().enumerate() {
            fs::write(
                path.join(format!("overview-{index}.webm")),
                segment.document.bytes(),
            )
            .await?;
        }
    }
    eprintln!(
        "BROWSER_RECORDING={}",
        serde_json::to_string(&overview.metadata())?
    );
    let manifest = directory.path().join("acceptance.json");
    fs::write(
        &manifest,
        serde_json::to_vec(&serde_json::json!({
            "image": {"reference":image_ref.to_string(), "sha256":image.document.sha256()},
            "videos": archived_videos,
            "recordings": archived_recordings,
        }))?,
    )
    .await?;
    let child = Command::new(env::current_exe()?)
        .args([
            "--exact",
            "archive_restore_child",
            "--ignored",
            "--nocapture",
        ])
        .env("YOSOI_OBSERVATION_ARCHIVE", directory.path())
        .env("CHROME", "/unavailable-browser")
        .env("FFMPEG", "/unavailable-decoder")
        .output()
        .await?;
    assert!(
        child.status.success(),
        "fresh-process Archive restore: {}",
        String::from_utf8_lossy(&child.stderr)
    );
    for work in workers {
        work.release().await?;
    }
    for tab in tabs {
        tab.close().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "child process of the live media retention qualification"]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Archive restore assertions are the child-process qualification contract."
)]
async fn archive_restore_child() -> Result<()> {
    let directory = env::var_os("YOSOI_OBSERVATION_ARCHIVE")
        .ok_or_else(|| io::Error::other("parent must provide archive directory"))?;
    let directory = PathBuf::from(directory);
    let manifest: Value =
        serde_json::from_slice(&fs::read(directory.join("acceptance.json")).await?)?;
    let archive = Archive::open(&directory).await?;
    let image = manifest
        .get("image")
        .ok_or_else(|| io::Error::other("image manifest missing"))?;
    let reference: ImageDocumentArchiveRef = image
        .get("reference")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("image reference missing"))?
        .parse()?;
    assert_eq!(
        Some(archive.read(&reference).await?.sha256()),
        image.get("sha256").and_then(Value::as_str)
    );
    let videos = manifest
        .get("videos")
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("videos manifest missing"))?;
    assert!(!videos.is_empty(), "archive must retain video references");
    for video in videos {
        let reference: VideoDocumentArchiveRef = video
            .get("reference")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("video reference missing"))?
            .parse()?;
        assert_eq!(
            Some(archive.read(&reference).await?.sha256()),
            video.get("sha256").and_then(Value::as_str)
        );
    }
    let recordings = manifest
        .get("recordings")
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("recording manifest references missing"))?;
    for recording in recordings {
        let reference: DocumentArchiveRef = recording
            .get("reference")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("recording reference missing"))?
            .parse()?;
        let restored = session::RecordingOutcome::read_from(&archive, &reference).await?;
        assert_eq!(
            serde_json::to_value(restored.metadata())?,
            recording
                .get("metadata")
                .cloned()
                .ok_or_else(|| io::Error::other("recording metadata missing"))?
        );
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "live native Chrome automatic-evidence permission and settlement qualification"]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify that evidence failures preserve dispatched effects and gate only later actions."
)]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Work is consumed by async release after both action settlement and evidence assertions; dropping it again is invalid"
)]
async fn automatic_evidence_failure_preserves_effect_and_gates_only_later_actions() -> Result<()> {
    use yosoi::{
        policy::observe::{EvidenceFailurePolicy, ScreenshotScope},
        session::ActionKind,
    };
    let fixture = Fixture::start().await?;
    for behavior in [
        EvidenceFailurePolicy::Continue,
        EvidenceFailurePolicy::Require,
    ] {
        let mut policy = Policy::default();
        policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
        policy.observe.enabled = true;
        policy.observe.failure = behavior;
        policy.observe.screenshots.before = Some(ScreenshotScope::Target);
        policy.observe.screenshots.after = Some(ScreenshotScope::Viewport);
        let browser = session::new()
            .bind(&policy)
            .configure(SessionPolicy {
                allowed_actions: vec![ActionKind::Navigate, ActionKind::Click],
                ..SessionPolicy::default()
            })
            .acquire()
            .await?;
        let result = Box::pin(async {
            let work = browser.work().await?;
            let navigated = work.navigate(&format!("{}/?id=1", fixture.base)).await?;
            assert_eq!(
                navigated.status,
                OperationStatus::Observed,
                "evidence failure must not erase the current action result"
            );
            let clicked = work.click("#mark").await;
            match behavior {
                EvidenceFailurePolicy::Continue => {
                    assert_eq!(clicked?.status, OperationStatus::Observed);
                }
                EvidenceFailurePolicy::Require => assert!(
                    clicked.is_err(),
                    "required evidence gates subsequent actions"
                ),
            }
            let evidence = browser.evidence();
            assert!(
                !evidence.entries().is_empty(),
                "configured capture failures remain visible"
            );
            assert!(
                evidence
                    .entries()
                    .iter()
                    .all(|entry| entry.capture.is_none()),
                "automatic policy must not override Screenshot denial"
            );
            assert!(
                evidence
                    .entries()
                    .iter()
                    .any(|entry| entry.operation_id == navigated.id),
                "evidence links to the dispatched action receipt"
            );
            work.release().await?;
            Ok::<_, Box<dyn Error + Send + Sync>>(())
        })
        .await;
        let closed = browser.close().await;
        drop(browser);
        result?;
        closed?;
    }
    fixture.close().await;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "live Chrome tab audio and FFmpeg qualification, requires owned PULSE_SINK"]
async fn native_audio_recordings_preserve_reciprocal_pause_isolation() -> Result<()> {
    if !env::var("PULSE_SINK").is_ok_and(|sink| sink.starts_with("yosoi_")) {
        return Err(io::Error::other("run with a disposable yosoi_ PulseAudio null sink").into());
    }
    let fixture = Fixture::start().await?;
    let mut policy = Policy::default();
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headful)];
    policy.observe.native_tab_capture = true;
    let browser = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            mode: BrowserMode::Headful,
            maximum_tabs: 2,
            execution_concurrency: 1,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let result = Box::pin(AssertUnwindSafe(qualify_audio(&browser, &fixture)).catch_unwind()).await;
    let closed = browser.close().await;
    drop(browser);
    fixture.close().await;
    match result {
        Ok(result) => result?,
        Err(panic) => resume_unwind(panic),
    }
    closed?;
    Ok(())
}

#[expect(
    clippy::cognitive_complexity,
    clippy::significant_drop_tightening,
    reason = "The audio qualification intentionally retains both tab Work leases and source handles across reciprocal sampling windows."
)]
async fn qualify_audio(browser: &session::Session, fixture: &Fixture) -> Result<()> {
    let tab = browser.new_tab().await?;
    let workers = [browser.work().await?, tab.work().await?];
    for (id, work) in workers.iter().enumerate() {
        work.navigate(&format!("{}/?id={id}", fixture.base)).await?;
        work.click("#tone").await?;
        work.wait_until(
            &Condition::Exists {
                selector: "#tone[data-playing=true]".into(),
            },
            5000,
        )
        .await?;
    }
    let options = RecordingOptions::default()
        .max_duration_ms(30_000)
        .frames_per_second(5)
        .include_audio(true);
    let mut recordings = Vec::new();
    for work in &workers {
        recordings.push(work.start_recording(options.clone()).await?);
    }
    let first = workers
        .first()
        .ok_or_else(|| io::Error::other("first audio Work missing"))?;
    // These waits define intentional audio sampling windows, not readiness polling.
    first.wait(2000).await?;
    let mut phases = Vec::new();
    for paused in [0_usize, 1] {
        let work = workers
            .get(paused)
            .ok_or_else(|| io::Error::other("audio Work missing"))?;
        work.click("#tone").await?;
        work.wait_until(
            &Condition::Exists {
                selector: "#tone[data-playing=false]".into(),
            },
            5000,
        )
        .await?;
        let pause = unix_ms()?;
        first.wait(2000).await?;
        work.click("#tone").await?;
        work.wait_until(
            &Condition::Exists {
                selector: "#tone[data-playing=true]".into(),
            },
            5000,
        )
        .await?;
        let resumed = unix_ms()?;
        phases.push((paused, pause, resumed));
    }
    first.wait(2000).await?;
    let output_path = env::var_os("YOSOI_OBSERVATION_OUTPUT").map_or_else(
        || ".generated/session-observation-audio".into(),
        PathBuf::from,
    );
    fs::create_dir_all(&output_path).await?;
    let mut decoded = Vec::new();
    let mut origins = Vec::new();
    for (id, handle) in recordings.into_iter().enumerate() {
        let output = handle.stop().await?;
        assert_eq!(
            output.segments.len(),
            1,
            "audio fixture remains in one document"
        );
        let segment = output
            .segments
            .first()
            .ok_or_else(|| io::Error::other("audio segment missing"))?;
        let origin = output
            .source
            .started_at_unix_ms
            .and_then(|start| start.checked_add(segment.metadata.start_offset_ms))
            .ok_or_else(|| io::Error::other("audio source clock unavailable"))?;
        origins.push(origin);
        let file = output_path.join(format!("audio-tab-{id}.webm"));
        fs::write(&file, segment.document.bytes()).await?;
        fs::write(
            output_path.join(format!("audio-tab-{id}.json")),
            serde_json::to_vec_pretty(&output.metadata())?,
        )
        .await?;
        let pcm = Command::new("ffmpeg")
            .args(["-v", "error", "-threads", "1", "-i"])
            .arg(&file)
            .args([
                "-t",
                "30",
                "-map",
                "0:a:0",
                "-af",
                "aresample=async=1:first_pts=0",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-f",
                "s16le",
                "pipe:1",
            ])
            .output()
            .await?;
        assert!(
            pcm.status.success(),
            "decode actual tab audio: {}",
            String::from_utf8_lossy(&pcm.stderr)
        );
        decoded.push(pcm.stdout);
    }
    let mut proof = Vec::new();
    for (paused, start, end) in phases {
        let mut rms = Vec::new();
        for (id, pcm) in decoded.iter().enumerate() {
            let origin = origins
                .get(id)
                .copied()
                .ok_or_else(|| io::Error::other("source clock missing"))?;
            let start = start
                .checked_sub(origin)
                .and_then(|value| value.checked_add(400))
                .ok_or_else(|| io::Error::other("invalid audio start"))?;
            let end = end
                .checked_sub(origin)
                .and_then(|value| value.checked_sub(400))
                .ok_or_else(|| io::Error::other("invalid audio end"))?;
            rms.push(pcm_rms(pcm, start, end)?);
        }
        let quiet = rms
            .get(paused)
            .copied()
            .ok_or_else(|| io::Error::other("paused source absent"))?;
        let other = usize::from(paused == 0);
        let active = rms
            .get(other)
            .copied()
            .ok_or_else(|| io::Error::other("audible source absent"))?;
        proof.push(serde_json::json!({"paused":paused,"pause_unix_ms":start,"resume_unix_ms":end,"rms_pcm":rms}));
        assert!(
            active > 100.0,
            "the other tab must remain audible: {active}"
        );
        assert!(
            quiet < 5.0 && quiet < active * 0.01,
            "paused tab must become silent independently: quiet={quiet} active={active}"
        );
    }
    fs::write(
        output_path.join("audio-proof.json"),
        serde_json::to_vec_pretty(&proof)?,
    )
    .await?;
    for work in workers {
        work.release().await?;
    }
    tab.close().await?;
    Ok(())
}

fn unix_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn pcm_rms(pcm: &[u8], start_ms: u64, end_ms: u64) -> Result<f64> {
    let offset = |ms: u64| -> Result<usize> {
        let value = ms
            .checked_mul(48)
            .and_then(|samples| samples.checked_mul(2))
            .ok_or_else(|| io::Error::other("PCM range overflow"))?;
        Ok(usize::try_from(value)?)
    };
    let samples = pcm
        .get(offset(start_ms)?..offset(end_ms)?)
        .filter(|bytes| !bytes.is_empty())
        .ok_or_else(|| io::Error::other("PCM window unavailable"))?;
    let mut count = 0_u64;
    let mut squares = 0.0;
    for pair in samples.as_chunks::<2>().0 {
        let value = f64::from(i16::from_le_bytes(*pair));
        squares = value.mul_add(value, squares);
        count = count
            .checked_add(1)
            .ok_or_else(|| io::Error::other("PCM sample count overflow"))?;
    }
    if count == 0 {
        return Err(io::Error::other("empty PCM window").into());
    }
    Ok((squares / f64::from(u32::try_from(count)?)).sqrt())
}
