use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};

pub struct Fixture {
    pub(super) url: String,
    server: JoinHandle<()>,
}

impl Fixture {
    pub(super) async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind fixture");
        let address = listener.local_addr().expect("fixture address");
        let server = tokio::spawn(async move {
            loop {
                let (mut stream, _) = listener.accept().await.expect("accept fixture request");
                let mut request = Vec::new();
                let mut buffer = [0_u8; 1024];
                while !request.windows(4).any(|window| window == b"\r\n\r\n") {
                    let read = stream
                        .read(&mut buffer)
                        .await
                        .expect("read fixture request");
                    if read == 0 {
                        break;
                    }
                    request
                        .extend_from_slice(buffer.get(..read).expect("read stays within buffer"));
                }
                let (title, content) = if request.starts_with(b"GET /reserved ") {
                    ("IANA Reserved Domains", "IANA reserved domain fixture")
                } else {
                    (
                        "Example Domain",
                        "This domain is a deterministic browser test fixture.",
                    )
                };
                let body = format!(
                    "<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'><title>{title}</title></head><body><h1>{title}</h1><p>{content}</p></body></html>"
                );
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                stream
                    .write_all(response.as_bytes())
                    .await
                    .expect("write fixture response");
                stream.shutdown().await.expect("close fixture response");
            }
        });
        Self {
            url: format!("http://{address}/"),
            server,
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.server.abort();
    }
}
