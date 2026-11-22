//! Public file conversion preserves retained HTTP evidence and status semantics.
#![allow(
    clippy::panic_in_result_fn,
    reason = "Assertions report fixture regressions"
)]
use std::{error::Error, io};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
use yosoi::{
    documents::{FileDocument, FileLimits},
    request,
};

#[tokio::test]
async fn complete_body_becomes_typed_file_without_replacing_text_projection()
-> Result<(), Box<dyn Error + Send + Sync>> {
    let payload = b"\x89PNG\r\n\x1a\nfixture-pixels";
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut request = [0u8; 2048];
        let _ = stream.read(&mut request).await?;
        let head = format!(
            "HTTP/1.1 404 Not Found\r\nContent-Type: application/octet-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            payload.len()
        );
        stream.write_all(head.as_bytes()).await?;
        stream.write_all(payload).await?;
        Ok::<_, io::Error>(())
    });
    let response = request::new(format!("http://{address}/wrong.jpg"))
        .send()
        .await?;
    let attempt = response.attempts().next().ok_or("missing attempt")?;
    assert_eq!(attempt.status(), Some(404));
    let document = attempt.file_document(FileLimits::default())?;
    assert!(matches!(document, FileDocument::Image(_)));
    assert_eq!(document.bytes(), payload);
    assert_eq!(
        document.bytes().as_ptr(),
        attempt.body_bytes().ok_or("missing body")?.as_ptr()
    );
    assert_eq!(
        document.metadata().declared_media_type(),
        Some("application/octet-stream")
    );
    assert_eq!(document.metadata().detected_media_type(), Some("image/png"));
    assert!(attempt.file_document(FileLimits { max_bytes: 1 }).is_err());
    server.await??;
    Ok(())
}
