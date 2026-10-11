use std::{io, net::Ipv4Addr, sync::Arc, time::Duration};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{Barrier, oneshot},
    task::{JoinHandle, JoinSet},
};

pub(crate) struct SessionFixture {
    base_url: String,
    shutdown: Option<oneshot::Sender<()>>,
    task: JoinHandle<io::Result<()>>,
}

impl SessionFixture {
    pub(crate) async fn start() -> io::Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let rendezvous = Arc::new(Barrier::new(2));
        let task = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    biased;
                    _ = &mut shutdown_rx => break,
                    accepted = listener.accept() => {
                        let (stream, _) = accepted?;
                        let rendezvous = Arc::clone(&rendezvous);
                        connections.spawn(async move { let _ = serve(stream, rendezvous).await; });
                    }
                    Some(_) = connections.join_next(), if !connections.is_empty() => {}
                }
            }
            connections.abort_all();
            while connections.join_next().await.is_some() {}
            Ok(())
        });

        Ok(Self {
            base_url: format!("http://{address}"),
            shutdown: Some(shutdown),
            task,
        })
    }

    pub(crate) fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base_url)
    }

    pub(crate) async fn shutdown(mut self) -> io::Result<()> {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.task
            .await
            .map_err(|error| io::Error::other(error.to_string()))??;
        Ok(())
    }
}

async fn serve(mut stream: TcpStream, rendezvous: Arc<Barrier>) -> io::Result<()> {
    let mut request = Vec::with_capacity(2_048);
    loop {
        let mut buffer = [0_u8; 1_024];
        let read = stream.read(&mut buffer).await?;
        if read == 0 {
            return Ok(());
        }
        let read_buffer = buffer
            .get(..read)
            .ok_or_else(|| io::Error::other("loopback read length exceeded its buffer"))?;
        request.extend_from_slice(read_buffer);
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
        if request.len() >= 8_192 {
            return Err(io::Error::other("loopback request headers exceeded 8 KiB"));
        }
    }

    let request_text = String::from_utf8_lossy(&request);
    let request_line = request_text
        .lines()
        .next()
        .ok_or_else(|| io::Error::other("loopback request had no request line"))?;
    let raw_path = request_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| io::Error::other("loopback request had no path"))?;
    let path = raw_path
        .split('?')
        .next()
        .ok_or_else(|| io::Error::other("missing route"))?;

    if path == "/drop" {
        return stream.shutdown().await;
    }
    if let Some(delay) = path.strip_prefix("/delay/")
        && let Ok(milliseconds) = delay.parse::<u64>()
    {
        tokio::time::sleep(Duration::from_millis(milliseconds)).await;
    }
    if path == "/rendezvous" {
        rendezvous.wait().await;
    }

    let cookie = request_text.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("cookie").then_some(value.trim())
    });
    let shared_cookie = cookie.is_some_and(|value| {
        value
            .split(';')
            .any(|part| part.trim() == "yosoi_context=shared")
    });

    let (body, extra_headers) = match path {
        "/assertions" => (
            include_str!("../../../../spikes/browser-automation/fixtures/session-flow.html"),
            "",
        ),
        "/seed" => (
            "<!doctype html><html><body><main><h1>Cookie seeded</h1></main></body></html>",
            "Set-Cookie: yosoi_context=shared; Path=/; SameSite=Lax\r\n",
        ),
        "/check" if shared_cookie => (
            "<!doctype html><html><body><main><p id=\"context\">shared-context</p></main></body></html>",
            "",
        ),
        "/rendezvous" if shared_cookie => (
            "<!doctype html><html><body><main><p id=\"context\">shared-context</p></main></body></html>",
            "",
        ),
        "/check" => (
            "<!doctype html><html><body><main><p id=\"context\">isolated-context</p></main></body></html>",
            "",
        ),
        "/rendezvous" => (
            "<!doctype html><html><body><main><p id=\"context\">isolated-context</p></main></body></html>",
            "",
        ),
        _ => (
            "<!doctype html><html><body><main><h1>Local session fixture</h1><button id=\"go\">Go</button></main></body></html>",
            "",
        ),
    };

    let response_head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\n{extra_headers}Connection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(response_head.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.shutdown().await
}
