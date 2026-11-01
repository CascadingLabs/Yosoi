//! Private Linux X11 display and FFmpeg input owned by one retained Session.

use std::fmt::{self, Debug, Formatter};
#[cfg(target_os = "linux")]
use std::process::Stdio;
use thiserror::Error;
use tokio::process::Child;
#[cfg(target_os = "linux")]
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::Command,
    sync::Mutex,
    time::{Duration, timeout},
};

const DISPLAY_WIDTH: u32 = 1280;
const DISPLAY_HEIGHT: u32 = 720;

#[derive(Debug, Error)]
pub(super) enum PrivateDisplayError {
    #[cfg(target_os = "linux")]
    #[error("private X11 display could not be started")]
    Start,
    #[cfg(target_os = "linux")]
    #[error("private X11 display did not become ready")]
    Readiness,
    #[cfg(not(target_os = "linux"))]
    #[error("the private X11 recording backend is unavailable on this platform")]
    Unsupported,
    #[cfg(target_os = "linux")]
    #[error("FFmpeg could not start the private display recording")]
    Ffmpeg,
}

pub(super) struct PrivateDisplay {
    display: String,
    #[cfg(target_os = "linux")]
    child: Mutex<Option<Child>>,
}

impl Debug for PrivateDisplay {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PrivateDisplay")
            .field("display", &self.display)
            .finish_non_exhaustive()
    }
}

impl PrivateDisplay {
    #[cfg(target_os = "linux")]
    pub(super) async fn start() -> Result<Self, PrivateDisplayError> {
        let mut child = Command::new("Xvfb")
            .args([
                "-displayfd",
                "1",
                "-screen",
                "0",
                "1920x1080x24",
                "-dpi",
                "96",
                "-nolisten",
                "tcp",
            ])
            .env_remove("DISPLAY")
            .env_remove("WAYLAND_DISPLAY")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| PrivateDisplayError::Start)?;
        let stdout = child.stdout.take().ok_or(PrivateDisplayError::Start)?;
        let mut reader = BufReader::new(stdout);
        let mut display_number = String::new();
        let ready = timeout(
            Duration::from_secs(10),
            reader.read_line(&mut display_number),
        )
        .await;
        match ready {
            Ok(Ok(count)) if count > 0 => {
                let display_number = display_number.trim();
                if display_number.is_empty()
                    || !display_number
                        .chars()
                        .all(|character| character.is_ascii_digit())
                {
                    let _ = child.start_kill();
                    let _ = child.wait().await;
                    return Err(PrivateDisplayError::Readiness);
                }
                Ok(Self {
                    display: format!(":{display_number}"),
                    child: Mutex::new(Some(child)),
                })
            }
            _ => {
                let _ = child.start_kill();
                let _ = child.wait().await;
                Err(PrivateDisplayError::Readiness)
            }
        }
    }

    #[cfg(not(target_os = "linux"))]
    pub(super) async fn start() -> Result<Self, PrivateDisplayError> {
        Err(PrivateDisplayError::Unsupported)
    }

    pub(super) fn display(&self) -> &str {
        &self.display
    }

    /// One bounded raw-frame producer shared by browser-visible recording outputs.
    #[cfg(target_os = "linux")]
    pub(super) fn frame_source(
        &self,
        frames_per_second: u32,
    ) -> Result<Child, PrivateDisplayError> {
        let fps = frames_per_second.to_string();
        Command::new("ffmpeg")
            .args([
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-threads",
                "1",
                "-thread_queue_size",
                "2",
                "-f",
                "x11grab",
                "-framerate",
                &fps,
                "-video_size",
                "1920x1080",
                "-i",
            ])
            .arg(format!("{}.0+0,0", self.display))
            .args([
                "-vf",
                "scale=1280:720",
                "-threads",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ])
            .env("DISPLAY", &self.display)
            .env_remove("WAYLAND_DISPLAY")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| PrivateDisplayError::Ffmpeg)
    }

    /// Each logical output has its own encoder so its container and interval are independent.
    #[cfg(target_os = "linux")]
    pub(super) fn output_encoder(frames_per_second: u32) -> Result<Child, PrivateDisplayError> {
        let fps = frames_per_second.to_string();
        Command::new("ffmpeg")
            .args([
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgb24",
                "-video_size",
                "1280x720",
                "-framerate",
                &fps,
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libvpx",
                "-deadline",
                "realtime",
                "-cpu-used",
                "8",
                "-threads",
                "1",
                "-b:v",
                "1000k",
                "-f",
                "webm",
                "pipe:1",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| PrivateDisplayError::Ffmpeg)
    }

    #[cfg(not(target_os = "linux"))]
    pub(super) fn frame_source(&self, _fps: u32) -> Result<Child, PrivateDisplayError> {
        Err(PrivateDisplayError::Unsupported)
    }

    #[cfg(not(target_os = "linux"))]
    pub(super) fn output_encoder(_fps: u32) -> Result<Child, PrivateDisplayError> {
        Err(PrivateDisplayError::Unsupported)
    }

    #[cfg(target_os = "linux")]
    pub(super) async fn close(&self) -> Result<(), PrivateDisplayError> {
        let child = self.child.lock().await.take();
        if let Some(mut child) = child
            && child
                .try_wait()
                .map_err(|_| PrivateDisplayError::Start)?
                .is_none()
        {
            child.start_kill().map_err(|_| PrivateDisplayError::Start)?;
            timeout(Duration::from_secs(5), child.wait())
                .await
                .map_err(|_| PrivateDisplayError::Readiness)?
                .map_err(|_| PrivateDisplayError::Start)?;
        }
        Ok(())
    }

    #[cfg(not(target_os = "linux"))]
    pub(super) async fn close(&self) -> Result<(), PrivateDisplayError> {
        Ok(())
    }
}

impl Drop for PrivateDisplay {
    fn drop(&mut self) {
        #[cfg(target_os = "linux")]
        if let Ok(mut child) = self.child.try_lock()
            && let Some(child) = child.as_mut()
        {
            let _ = child.start_kill();
        }
    }
}

pub(super) const fn dimensions() -> (u32, u32) {
    (DISPLAY_WIDTH, DISPLAY_HEIGHT)
}
