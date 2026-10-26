//! Owned optional-engine launch and bounded, engine-specific admission.

#[cfg(unix)]
use rustix::io::Errno;
#[cfg(unix)]
use rustix::process as process_control;
use std::env;
use std::io as std_io;
use std::mem;
use std::{fmt, path::PathBuf, process::Stdio, time::Duration};
use tokio::fs as tokio_fs;
use tokio::io as tokio_io;
use tokio::runtime::Handle as RuntimeHandle;

use sha2::{Digest, Sha256};
use tempfile::TempDir;
use thiserror::Error;
use tokio::{
    io::{AsyncRead, AsyncReadExt, BufReader},
    process::{Child, Command},
    task::JoinHandle,
    time::{Instant, timeout_at},
};
use tokio_util::sync::CancellationToken;

use crate::browser::{BrowserConfig, BrowserConfigurationError, BrowserEngine, MoliProfile};

/// Admitted release identity is not a Chrome-compatible wire banner.
#[derive(Clone, Debug)]
pub struct ExecutableIdentity {
    pub engine: BrowserEngine,
    pub executable: PathBuf,
    pub release_version: String,
    pub sha256: String,
}

#[derive(Debug, Error)]
pub enum LaunchError {
    #[error(transparent)]
    Configuration(#[from] BrowserConfigurationError),
    #[error(
        "optional browser executable unavailable; install it or configure an absolute executable"
    )]
    ExecutableUnavailable,
    #[error("optional browser release is not in the admitted release snapshot")]
    UnsupportedRelease,
    #[error("owned optional-browser launch is not qualified on this platform")]
    UnsupportedPlatform,
    #[error("optional browser startup failed")]
    Startup,
    #[error("optional browser startup output exceeded its bound")]
    StartupOutput,
    #[error("optional browser startup deadline elapsed")]
    Deadline,
    #[error("optional browser startup cancelled")]
    Cancelled,
    #[error("owned browser process cleanup could not be confirmed")]
    CleanupUncertain,
}

/// A child and its disposable profile are one ownership unit.
pub struct OwnedProcess {
    child: Option<Child>,
    profile: Option<TempDir>,
    drains: Vec<JoinHandle<()>>,
    #[cfg(unix)]
    group: Option<process_control::Pid>,
    pub endpoint: String,
    pub identity: ExecutableIdentity,
}

impl fmt::Debug for OwnedProcess {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OwnedProcess")
            .field("identity", &self.identity)
            .field("running", &self.child.is_some())
            .finish_non_exhaustive()
    }
}

impl OwnedProcess {
    pub async fn launch(
        config: &BrowserConfig,
        headful: bool,
        routed: bool,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Self, LaunchError> {
        config.validate_headful(headful)?;
        if cancellation.is_cancelled() {
            return Err(LaunchError::Cancelled);
        }
        if Instant::now() >= deadline {
            return Err(LaunchError::Deadline);
        }
        if config.endpoint.is_some() || config.engine == BrowserEngine::Chrome {
            return Err(LaunchError::Startup);
        }
        if !cfg!(target_os = "linux") {
            return Err(LaunchError::UnsupportedPlatform);
        }
        let identity = admit(config, cancellation, deadline).await?;
        let profile = tempfile::Builder::new()
            .prefix("yosoi-bidi-")
            .tempdir()
            .map_err(|_| LaunchError::Startup)?;
        if routed {
            // Match Chrome's <-loopback> bypass override. This is confined to
            // the owned, ephemeral profile and strengthens the requested route.
            if config.engine != BrowserEngine::Firefox {
                return Err(LaunchError::Startup);
            }
            tokio_fs::write(
                profile.path().join("user.js"),
                b"user_pref(\"network.proxy.allow_hijacking_localhost\", true);\n",
            )
            .await
            .map_err(|_| LaunchError::Startup)?;
        }
        let mut command = Command::new(&identity.executable);
        command
            .kill_on_drop(true)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(unix)]
        command.process_group(0);
        for key in [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
            "MOZ_DISABLE_CONTENT_SANDBOX",
            "MOZ_DISABLE_GPU_SANDBOX",
            "MOZ_DISABLE_GMP_SANDBOX",
            "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS",
            "MOZ_HEADLESS",
        ] {
            command.env_remove(key);
        }
        command
            .env("RAYON_NUM_THREADS", "1")
            .env("TOKIO_WORKER_THREADS", "1");
        match config.engine {
            BrowserEngine::Firefox => {
                command
                    .args(["--no-remote", "--profile"])
                    .arg(profile.path())
                    .args([
                        "--remote-debugging-port",
                        "0",
                        "--width",
                        "1280",
                        "--height",
                        "900",
                    ]);
                if !headful {
                    command.arg("--headless");
                }
                command.arg("about:blank");
            }
            BrowserEngine::Moli => {
                command
                    .args([
                        "serve",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "0",
                        "--profile-dir",
                    ])
                    .arg(profile.path())
                    .args([
                        "--log-level",
                        "info",
                        "--http-max-concurrent",
                        "8",
                        "--http-max-host-open",
                        "4",
                        "--http-max-response-size",
                        "16777216",
                        "--http-timeout",
                        "15000",
                    ]);
                if config.moli_profile == MoliProfile::Layout {
                    command.arg("--layout");
                }
                if config.moli_resources {
                    command.arg("--resource");
                }
                if !config.moli_allow_private_networks {
                    command.arg("--block-private-networks");
                }
            }
            BrowserEngine::Chrome => return Err(LaunchError::Startup),
        }
        if cancellation.is_cancelled() {
            return Err(LaunchError::Cancelled);
        }
        if Instant::now() >= deadline {
            return Err(LaunchError::Deadline);
        }
        let child = command.spawn().map_err(|_| LaunchError::Startup)?;
        #[cfg(unix)]
        let group = child
            .id()
            .filter(|pid| *pid > 1)
            .and_then(|pid| i32::try_from(pid).ok())
            .and_then(process_control::Pid::from_raw)
            .ok_or(LaunchError::Startup)?;
        let mut owned = Self {
            child: Some(child),
            profile: Some(profile),
            drains: Vec::new(),
            #[cfg(unix)]
            group: Some(group),
            endpoint: String::new(),
            identity,
        };
        let result = owned.ready(cancellation, deadline).await;
        if let Err(error) = result {
            if let Some(cleanup_deadline) = Instant::now().checked_add(Duration::from_secs(5)) {
                let _ = owned.close_before(cleanup_deadline).await;
            }
            return Err(error);
        }
        Ok(owned)
    }

    async fn ready(
        &mut self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), LaunchError> {
        let child = self.child.as_mut().ok_or(LaunchError::Startup)?;
        let mut stdout = BufReader::new(child.stdout.take().ok_or(LaunchError::Startup)?);
        let mut stderr = BufReader::new(child.stderr.take().ok_or(LaunchError::Startup)?);
        let mut out_open = true;
        let mut err_open = true;
        let mut out_line = Vec::new();
        let mut err_line = Vec::new();
        loop {
            let line = tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(LaunchError::Cancelled),
                line = timeout_at(deadline, bounded_line(&mut stdout, &mut out_line)), if out_open => {
                    let line = line.map_err(|_| LaunchError::Deadline)??;
                    if line.is_none() { out_open = false; }
                    line
                }
                line = timeout_at(deadline, bounded_line(&mut stderr, &mut err_line)), if err_open => {
                    let line = line.map_err(|_| LaunchError::Deadline)??;
                    if line.is_none() { err_open = false; }
                    line
                }
                else => return Err(LaunchError::Startup),
            };
            if let Some(line) = line
                && let Some(endpoint) = readiness_endpoint(&line, self.identity.engine)
            {
                self.endpoint = endpoint;
                self.drains.push(tokio::spawn(async move {
                    let _ = tokio_io::copy(&mut stdout, &mut tokio_io::sink()).await;
                }));
                self.drains.push(tokio::spawn(async move {
                    let _ = tokio_io::copy(&mut stderr, &mut tokio_io::sink()).await;
                }));
                return Ok(());
            }
        }
    }

    /// Signal only the still-owned child's private process group, then reap it.
    pub async fn close_before(&mut self, deadline: Instant) -> Result<(), LaunchError> {
        if let Some(child) = self.child.as_mut() {
            signal_owned(child);
            timeout_at(deadline, child.wait())
                .await
                .map_err(|_| LaunchError::CleanupUncertain)?
                .map_err(|_| LaunchError::CleanupUncertain)?;
            self.child = None;
        }
        for task in self.drains.drain(..) {
            task.abort();
            timeout_at(deadline, task)
                .await
                .map_err(|_| LaunchError::CleanupUncertain)?
                .ok();
        }
        #[cfg(target_os = "linux")]
        if let Some(group) = self.group {
            wait_group_reaped(group, deadline).await?;
        }
        if !self.group_gone() {
            return Err(LaunchError::CleanupUncertain);
        }
        self.profile = None;
        Ok(())
    }

    fn group_gone(&mut self) -> bool {
        #[cfg(unix)]
        if let Some(group) = self.group {
            if !matches!(
                process_control::test_kill_process_group(group),
                Err(Errno::SRCH)
            ) {
                return false;
            }
            self.group = None;
        }
        true
    }
}

impl Drop for OwnedProcess {
    fn drop(&mut self) {
        let Some(mut child) = self.child.take() else {
            if !self.group_gone()
                && let Some(profile) = self.profile.take()
            {
                let _ = profile.keep();
            }
            for task in self.drains.drain(..) {
                task.abort();
            }
            return;
        };
        signal_owned(&mut child);
        let profile = self.profile.take();
        let drains = mem::take(&mut self.drains);
        #[cfg(unix)]
        let group = self.group.take();
        if let Ok(runtime) = RuntimeHandle::try_current() {
            runtime.spawn(async move {
                let Some(deadline) = Instant::now().checked_add(Duration::from_secs(5)) else {
                    for task in drains {
                        task.abort();
                    }
                    if let Some(profile) = profile {
                        let _ = profile.keep();
                    }
                    return;
                };
                let reaped = matches!(timeout_at(deadline, child.wait()).await, Ok(Ok(_)));
                let mut drains_complete = true;
                for task in drains {
                    task.abort();
                    drains_complete &= timeout_at(deadline, task).await.is_ok();
                }
                #[cfg(target_os = "linux")]
                let group_gone = match group {
                    Some(group) => wait_group_reaped(group, deadline).await.is_ok(),
                    None => true,
                };
                #[cfg(all(unix, not(target_os = "linux")))]
                let group_gone = group.is_none_or(|group| {
                    matches!(
                        process_control::test_kill_process_group(group),
                        Err(Errno::SRCH)
                    )
                });
                #[cfg(not(unix))]
                let group_gone = true;
                if reaped && group_gone && drains_complete {
                    drop(profile);
                } else if let Some(profile) = profile {
                    let _ = profile.keep();
                }
            });
        } else {
            for task in drains {
                task.abort();
            }
            // With no runtime there is no cleanup proof. Keep the profile rather
            // than delete files a child may still own. Admission remains fenced.
            if let Some(profile) = profile {
                let _ = profile.keep();
            }
        }
    }
}

/// pidfds wake once a process exits and again when it is reaped. Waiting on
/// remaining group members is read-only; no PID is signalled after the leader
/// has been reaped, so PID reuse cannot turn cleanup into an unrelated kill.
/// See https://man7.org/linux/man-pages/man2/pidfd_open.2.html.
#[cfg(target_os = "linux")]
async fn wait_group_reaped(
    group: process_control::Pid,
    deadline: Instant,
) -> Result<(), LaunchError> {
    use process_control::{Pid, PidfdFlags, pidfd_open};
    use tokio_io::{Interest, unix::AsyncFd};

    for _ in 0..4 {
        if matches!(
            process_control::test_kill_process_group(group),
            Err(Errno::SRCH)
        ) {
            return Ok(());
        }
        let collect = async {
            let mut directory = tokio_fs::read_dir("/proc")
                .await
                .map_err(|_| LaunchError::CleanupUncertain)?;
            let mut descriptors = Vec::new();
            while let Some(entry) = directory
                .next_entry()
                .await
                .map_err(|_| LaunchError::CleanupUncertain)?
            {
                let Some(pid) = entry
                    .file_name()
                    .to_str()
                    .and_then(|name| name.parse::<i32>().ok())
                    .filter(|pid| *pid > 1)
                    .and_then(Pid::from_raw)
                else {
                    continue;
                };
                let Ok(stat) = tokio_fs::read_to_string(entry.path().join("stat")).await else {
                    continue;
                };
                if stat_process_group(&stat) != Some(group.as_raw_pid()) {
                    continue;
                }
                if descriptors.len() >= 1024 {
                    return Err(LaunchError::CleanupUncertain);
                }
                match pidfd_open(pid, PidfdFlags::empty()) {
                    Ok(fd) => {
                        // Tokio 1.54 deprecates the generic safe constructor.
                        // This private OwnedFd stays open, unchanged and owned
                        // by AsyncFd until deregistration, satisfying the new
                        // registration invariant without an unsafe call. Keep
                        // compatibility with the supported Tokio 1.48+ range.
                        #[allow(
                            deprecated,
                            reason = "The private OwnedFd preserves descriptor identity for the full AsyncFd lifetime; older supported Tokio versions lack register_with_interest."
                        )]
                        let descriptor = AsyncFd::with_interest(fd, Interest::READABLE)
                            .map_err(|_| LaunchError::CleanupUncertain)?;
                        descriptors.push(descriptor);
                    }
                    Err(Errno::SRCH) => {}
                    Err(_) => return Err(LaunchError::CleanupUncertain),
                }
            }
            Ok::<_, LaunchError>(descriptors)
        };
        let descriptors = timeout_at(deadline, collect)
            .await
            .map_err(|_| LaunchError::CleanupUncertain)??;
        if descriptors.is_empty() {
            return if matches!(
                process_control::test_kill_process_group(group),
                Err(Errno::SRCH)
            ) {
                Ok(())
            } else {
                Err(LaunchError::CleanupUncertain)
            };
        }
        for descriptor in descriptors {
            loop {
                let mut ready = timeout_at(deadline, descriptor.readable())
                    .await
                    .map_err(|_| LaunchError::CleanupUncertain)?
                    .map_err(|_| LaunchError::CleanupUncertain)?;
                if ready.ready().is_read_closed() {
                    break;
                }
                // Do not read a pidfd (read is unsupported). Consume the exit
                // notification, then wait for the kernel's distinct reap edge.
                ready.clear_ready();
            }
        }
    }
    if matches!(
        process_control::test_kill_process_group(group),
        Err(Errno::SRCH)
    ) {
        Ok(())
    } else {
        Err(LaunchError::CleanupUncertain)
    }
}

#[cfg(target_os = "linux")]
fn stat_process_group(stat: &str) -> Option<i32> {
    // comm may itself contain spaces and closing parentheses.
    stat.rsplit_once(") ")?
        .1
        .split_whitespace()
        .nth(2)?
        .parse()
        .ok()
}

fn signal_owned(child: &mut Child) {
    #[cfg(unix)]
    if let Some(pid) = child
        .id()
        .filter(|pid| *pid > 1)
        .and_then(|pid| i32::try_from(pid).ok())
        .and_then(process_control::Pid::from_raw)
    {
        let _ = process_control::kill_process_group(pid, process_control::Signal::KILL);
    }
    let _ = child.start_kill();
}

async fn admit(
    config: &BrowserConfig,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<ExecutableIdentity, LaunchError> {
    let name = match config.engine {
        BrowserEngine::Firefox => "firefox",
        BrowserEngine::Moli => "moli",
        BrowserEngine::Chrome => return Err(LaunchError::Startup),
    };
    let key = match config.engine {
        BrowserEngine::Firefox => "YOSOI_FIREFOX_EXECUTABLE",
        _ => "YOSOI_MOLI_EXECUTABLE",
    };
    let path = match config
        .executable
        .clone()
        .or_else(|| env::var_os(key).map(PathBuf::from))
    {
        Some(path) => path,
        None => which::which(name).map_err(|_| LaunchError::ExecutableUnavailable)?,
    };
    if !path.is_absolute() {
        return Err(LaunchError::ExecutableUnavailable);
    }
    let path = tokio::select! {
        biased;
        () = cancellation.cancelled() => return Err(LaunchError::Cancelled),
        path = timeout_at(deadline, tokio_fs::canonicalize(path)) => path.map_err(|_| LaunchError::Deadline)?.map_err(|_| LaunchError::ExecutableUnavailable)?,
    };
    let mut command = Command::new(&path);
    command
        .arg("--version")
        .kill_on_drop(true)
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = command
        .spawn()
        .map_err(|_| LaunchError::ExecutableUnavailable)?;
    let stdout = child
        .stdout
        .take()
        .ok_or(LaunchError::ExecutableUnavailable)?;
    let read = async {
        let mut bytes = Vec::new();
        stdout
            .take(4096)
            .read_to_end(&mut bytes)
            .await
            .map_err(|_| LaunchError::ExecutableUnavailable)?;
        if !child
            .wait()
            .await
            .map_err(|_| LaunchError::ExecutableUnavailable)?
            .success()
        {
            return Err(LaunchError::ExecutableUnavailable);
        }
        String::from_utf8(bytes).map_err(|_| LaunchError::UnsupportedRelease)
    };
    let banner = tokio::select! {
        biased;
        () = cancellation.cancelled() => return Err(LaunchError::Cancelled),
        result = timeout_at(deadline, read) => result.map_err(|_| LaunchError::Deadline)??,
    };
    let (expected, release_version) = match config.engine {
        BrowserEngine::Firefox => ("Mozilla Firefox 158.0.1", "158.0.1"),
        BrowserEngine::Moli => ("moli 1.1.19", "1.1.19"),
        BrowserEngine::Chrome => return Err(LaunchError::UnsupportedRelease),
    };
    if !banner.lines().any(|line| line.trim() == expected) {
        return Err(LaunchError::UnsupportedRelease);
    }
    let mut file = tokio_fs::File::open(&path)
        .await
        .map_err(|_| LaunchError::ExecutableUnavailable)?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0_u8; 65_536];
    loop {
        let count = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(LaunchError::Cancelled),
            read = timeout_at(deadline, file.read(&mut buffer)) => read.map_err(|_| LaunchError::Deadline)?.map_err(|_| LaunchError::ExecutableUnavailable)?,
        };
        if count == 0 {
            break;
        }
        let chunk = buffer
            .get(..count)
            .ok_or(LaunchError::ExecutableUnavailable)?;
        hash.update(chunk);
    }
    Ok(ExecutableIdentity {
        engine: config.engine,
        executable: path,
        release_version: release_version.to_owned(),
        sha256: format!("{:x}", hash.finalize()),
    })
}

async fn bounded_line<R: AsyncRead + Unpin>(
    reader: &mut R,
    bytes: &mut Vec<u8>,
) -> Result<Option<String>, LaunchError> {
    loop {
        match reader.read_u8().await {
            Ok(b'\n') => {
                return Ok(Some(
                    String::from_utf8_lossy(&mem::take(bytes)).into_owned(),
                ));
            }
            Ok(byte) => {
                if bytes.len() >= 8192 {
                    return Err(LaunchError::StartupOutput);
                }
                bytes.push(byte);
            }
            Err(error) if error.kind() == std_io::ErrorKind::UnexpectedEof => {
                return if bytes.is_empty() {
                    Ok(None)
                } else {
                    Ok(Some(
                        String::from_utf8_lossy(&mem::take(bytes)).into_owned(),
                    ))
                };
            }
            Err(_) => return Err(LaunchError::Startup),
        }
    }
}

fn readiness_endpoint(line: &str, engine: BrowserEngine) -> Option<String> {
    let ready = match engine {
        BrowserEngine::Firefox => line.contains("WebDriver BiDi listening"),
        BrowserEngine::Moli => line.contains("protocol server listening"),
        BrowserEngine::Chrome => false,
    };
    if !ready {
        return None;
    }
    let (_, port) = line.split_once("127.0.0.1:")?;
    let port: String = port.chars().take_while(char::is_ascii_digit).collect();
    let port = port.parse::<u16>().ok().filter(|port| *port != 0)?;
    Some(format!("ws://127.0.0.1:{port}/session"))
}

#[cfg(test)]
mod tests {
    #![allow(
        clippy::panic_in_result_fn,
        reason = "Native cleanup tests assert the ownership contract."
    )]
    use super::*;
    use std::error as std_error;

    #[cfg(target_os = "linux")]
    #[test]
    fn process_group_parse_preserves_parentheses_in_kernel_comm() {
        assert_eq!(stat_process_group("123 (a ) b) S 1 456 456 0 0"), Some(456));
        assert_eq!(stat_process_group("malformed"), None);
    }
    use crate::internal::browser::bidi::transport::{BidiConnection, TransportLimits};
    use serde_json::json;
    type TestResult = Result<(), Box<dyn std_error::Error + Send + Sync>>;

    #[test]
    fn readiness_requires_a_valid_engine_banner_and_nonzero_port() {
        assert_eq!(
            readiness_endpoint(
                "INFO protocol server listening addr=\u{1b}[0m127.0.0.1:12000",
                BrowserEngine::Moli
            )
            .as_deref(),
            Some("ws://127.0.0.1:12000/session")
        );
        assert!(
            readiness_endpoint("unrelated ws://127.0.0.1:12000", BrowserEngine::Firefox).is_none()
        );
        assert!(
            readiness_endpoint(
                "WebDriver BiDi listening on ws://127.0.0.1:0",
                BrowserEngine::Firefox
            )
            .is_none()
        );
    }

    #[tokio::test]
    async fn partial_readiness_line_survives_future_cancellation() -> TestResult {
        use futures_util::{FutureExt, poll};
        use tokio_io::AsyncWriteExt;
        let (mut writer, mut reader) = tokio_io::duplex(128);
        writer.write_all(b"partial").await?;
        let mut buffered = Vec::new();
        {
            let future = bounded_line(&mut reader, &mut buffered).fuse();
            tokio::pin!(future);
            assert!(poll!(future).is_pending());
        }
        assert_eq!(buffered, b"partial");
        writer.write_all(b"-line\n").await?;
        assert_eq!(
            bounded_line(&mut reader, &mut buffered).await?.as_deref(),
            Some("partial-line")
        );
        Ok(())
    }

    #[tokio::test]
    #[ignore = "requires explicit pinned Moli executable; native acceptance job supplies it"]
    async fn native_moli_owned_launch_and_logical_cleanup() -> TestResult {
        let executable =
            env::var_os("YOSOI_MOLI_EXECUTABLE").ok_or("YOSOI_MOLI_EXECUTABLE required")?;
        let config = BrowserConfig {
            engine: BrowserEngine::Moli,
            executable: Some(PathBuf::from(executable)),
            moli_profile: MoliProfile::Layout,
            ..BrowserConfig::default()
        };
        let cancellation = CancellationToken::new();
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(30))
            .ok_or(LaunchError::Deadline)?;
        let mut process =
            OwnedProcess::launch(&config, false, false, &cancellation, deadline).await?;
        let connection = BidiConnection::connect(
            &process.endpoint,
            TransportLimits::default(),
            &cancellation,
            deadline,
        )
        .await?;
        connection
            .command(
                "session.new",
                json!({"capabilities":{}}),
                &cancellation,
                deadline,
            )
            .await?;
        let user = connection
            .command(
                "browser.createUserContext",
                json!({}),
                &cancellation,
                deadline,
            )
            .await?;
        let owner = user
            .get("userContext")
            .and_then(serde_json::Value::as_str)
            .ok_or("missing context owner")?;
        connection
            .command(
                "browsingContext.create",
                json!({"type":"tab","userContext":owner}),
                &cancellation,
                deadline,
            )
            .await?;
        // Close proves owned contexts/session were acknowledged before socket close.
        connection.close().await?;
        drop(connection);
        process.close_before(deadline).await?;
        assert!(process.child.is_none());
        assert!(process.profile.is_none());
        assert_eq!(process.identity.release_version, "1.1.19");
        assert_eq!(process.identity.sha256.len(), 64);
        Ok(())
    }
}
