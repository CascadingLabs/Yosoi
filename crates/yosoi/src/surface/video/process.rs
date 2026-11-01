use super::VideoError;
use crate::request::CancellationToken;
use std::{io, process::Stdio, sync::Arc, time::Duration};
use tempfile::TempDir;
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::{Child, Command},
    runtime::Handle,
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
    command: Command,
    limit: usize,
    timeout_ms: u64,
    cancellation: &CancellationToken,
    snapshot: Arc<TempDir>,
) -> Result<Output, VideoError> {
    let token = cancellation.child_token();
    let guard = token.clone().drop_guard();
    let runtime = Handle::try_current()
        .map_err(|error| VideoError::Tool(format!("video requires a Tokio runtime: {error}")))?;
    let task = runtime.spawn(async move {
        let _snapshot = snapshot;
        run_owned(command, limit, timeout_ms, &token).await
    });
    let result = task
        .await
        .map_err(|error| VideoError::Tool(format!("decoder owner task failed: {error}")))?;
    guard.disarm();
    result
}

#[cfg(test)]
mod tests {
    use super::{VideoError, run};
    use crate::request::CancellationToken;
    use std::sync::Arc;
    use std::{error::Error, time::Duration};
    use tokio::{io::AsyncReadExt, net::TcpListener, process::Command, time::timeout};

    #[tokio::test(flavor = "current_thread")]
    async fn cooperative_cancellation_reaps_decoder_before_returning()
    -> Result<(), Box<dyn Error + Send + Sync>> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let progress = format!("tcp://{}", listener.local_addr()?);
        let mut command = Command::new("ffmpeg");
        command.args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=16x16:r=2",
            "-progress",
            &progress,
            "-f",
            "null",
            "-",
        ]);
        let cancellation = CancellationToken::new();
        let token = cancellation.clone();
        let snapshot = Arc::new(tempfile::tempdir()?);
        let snapshot_path = snapshot.path().to_owned();
        let decoder =
            tokio::spawn(async move { run(command, 1024, 10_000, &token, snapshot).await });
        let (mut stream, _) = timeout(Duration::from_secs(5), listener.accept()).await??;
        cancellation.cancel();
        let result = timeout(Duration::from_secs(5), decoder).await??;
        if !matches!(result, Err(VideoError::Cancelled)) {
            return Err("decoder did not preserve cancellation after cleanup".into());
        }
        if snapshot_path.exists() {
            return Err("decoder owner did not release its snapshot after cleanup".into());
        }
        let mut progress = Vec::new();
        timeout(Duration::from_secs(5), stream.read_to_end(&mut progress)).await??;
        Ok(())
    }
}
async fn terminate(child: &mut Child) -> Result<(), VideoError> {
    let killed = child.kill().await;
    let reaped = child.wait().await;
    reaped?;
    killed?;
    Ok(())
}
async fn run_owned(
    mut command: Command,
    limit: usize,
    timeout_ms: u64,
    cancellation: &CancellationToken,
) -> Result<Output, VideoError> {
    if cancellation.is_cancelled() {
        return Err(VideoError::Cancelled);
    }
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
    let result = tokio::select! {
        biased;
        () = cancellation.cancelled() => {
            terminate(&mut child).await?;
            return Err(VideoError::Cancelled);
        }
        result = timeout(Duration::from_millis(timeout_ms), async {
        tokio::try_join!(
            bounded_read(stdout, limit),
            bounded_read(stderr, 1024 * 1024),
            child.wait()
        )
        }) => result,
    };
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
            terminate(&mut child).await?;
            Err(error.into())
        }
        Err(_) => {
            terminate(&mut child).await?;
            Err(VideoError::Timeout)
        }
    }
}
