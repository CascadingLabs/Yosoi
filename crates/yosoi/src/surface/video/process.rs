use super::VideoError;
use std::{io, process::Stdio, time::Duration};
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::Command,
    time::timeout,
};
pub(super) struct Output {
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}
pub(super) async fn bounded_read<R: AsyncRead + Unpin>(
    reader: R,
    limit: usize,
) -> io::Result<Vec<u8>> {
    let bound = u64::try_from(limit)
        .map_err(|_| io::Error::other("output limit overflow"))?
        .checked_add(1)
        .ok_or_else(|| io::Error::other("output limit overflow"))?;
    let mut bytes = Vec::new();
    reader.take(bound).read_to_end(&mut bytes).await?;
    if bytes.len() > limit {
        return Err(io::Error::other(
            "video tool output exceeded its byte limit",
        ));
    }
    Ok(bytes)
}
pub(super) async fn run(
    mut command: Command,
    limit: usize,
    timeout_ms: u64,
) -> Result<Output, VideoError> {
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("tool stdout missing"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| io::Error::other("tool stderr missing"))?;
    let result = timeout(Duration::from_millis(timeout_ms), async {
        tokio::try_join!(
            bounded_read(stdout, limit),
            bounded_read(stderr, 1024 * 1024),
            child.wait()
        )
    })
    .await;
    match result {
        Ok(Ok((stdout, stderr, status))) => {
            if !status.success() {
                return Err(VideoError::Tool(
                    String::from_utf8_lossy(&stderr)
                        .chars()
                        .take(1024)
                        .collect(),
                ));
            }
            Ok(Output { stdout, stderr })
        }
        Ok(Err(error)) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            Err(error.into())
        }
        Err(_) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            Err(VideoError::Timeout)
        }
    }
}
