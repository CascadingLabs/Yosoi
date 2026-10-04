#![allow(clippy::panic_in_result_fn)] // Process assertions intentionally fail integration tests.

use std::{
    error::Error,
    fs,
    io::{self, Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::PathBuf,
    process::{Command, Output, Stdio},
    thread,
};

use serde_json::{Value, json};
use tempfile::TempDir;

fn json_at<'a>(value: &'a Value, pointer: &str) -> Result<&'a Value, Box<dyn Error>> {
    value
        .pointer(pointer)
        .ok_or_else(|| io::Error::other(format!("missing JSON value at {pointer}")).into())
}

struct Journey {
    _directory: TempDir,
    config: PathBuf,
    original_store: Vec<u8>,
}

impl Journey {
    fn new() -> Result<Self, Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let config = directory.path().join("config");
        let path = config.join("yosoi/policies.json");
        fs::create_dir_all(path.parent().ok_or("store has no parent")?)?;
        let mut versions = serde_json::Map::new();
        versions.insert(
            env!("CARGO_PKG_VERSION").to_owned(),
            json!({
                "active_profile": "strict",
                "profiles": {
                    "strict": {"locators": {"max_query_bytes": 1}},
                    "normal": {}
                }
            }),
        );
        let original_store = serde_json::to_vec_pretty(&json!({
            "format_version": 1, "cli_versions": versions
        }))?;
        fs::write(path, &original_store)?;
        Ok(Self {
            _directory: directory,
            config,
            original_store,
        })
    }

    fn store_unchanged(&self) -> Result<bool, Box<dyn Error>> {
        Ok(fs::read(self.config.join("yosoi/policies.json"))? == self.original_store)
    }
}

fn loopback() -> Result<(String, SocketAddr, thread::JoinHandle<()>), Box<dyn Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let address = listener.local_addr()?;
    let url = format!("http://{address}/");
    let server = thread::spawn(move || {
        let Ok((mut stream, _)) = listener.accept() else {
            return;
        };
        let mut request = [0_u8; 1024];
        if stream.read(&mut request).is_err() {
            return;
        }
        let body = b"<h1>Catalog</h1>";
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        if stream.write_all(head.as_bytes()).is_ok() {
            let _ = stream.write_all(body);
        }
    });
    Ok((url, address, server))
}

fn finish_server(
    address: SocketAddr,
    server: thread::JoinHandle<()>,
) -> Result<(), Box<dyn Error>> {
    if !server.is_finished()
        && let Ok(mut stream) = TcpStream::connect(address)
    {
        let _ = stream.write_all(b"GET / HTTP/1.1\r\n\r\n");
    }
    server.join().map_err(|_| "loopback server panicked".into())
}

fn pipeline(journey: &Journey, selected: bool) -> Result<(Output, Output), Box<dyn Error>> {
    let (url, address, server) = loopback()?;
    let mut request = Command::new(env!("CARGO_BIN_EXE_yosoi"));
    if selected {
        request.args(["--profile", "normal"]);
    }
    request.args(["request", &url, "--timeout-ms", "2500"]);
    let mut request = request
        .env("XDG_CONFIG_HOME", &journey.config)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let request_stdout = request.stdout.take().ok_or("Request stdout missing")?;
    let mut locate = Command::new(env!("CARGO_BIN_EXE_yosoi"));
    locate.args(["locate", "--css", "h1", "--json"]);
    if selected {
        locate.args(["--profile", "normal"]);
    }
    let locate_output = locate
        .env("XDG_CONFIG_HOME", &journey.config)
        .stdin(Stdio::from(request_stdout))
        .output()?;
    let request_output = request.wait_with_output()?;
    finish_server(address, server)?;
    Ok((request_output, locate_output))
}

#[test]
fn active_and_explicit_profiles_drive_different_end_to_end_results() -> Result<(), Box<dyn Error>> {
    let journey = Journey::new()?;
    let (request_active, locate_active) = pipeline(&journey, false)?;
    assert_eq!(request_active.status.code(), Some(0));
    assert_eq!(request_active.stderr.as_slice(), b"");
    assert_eq!(locate_active.status.code(), Some(3));
    let active: Value = serde_json::from_slice(&locate_active.stdout)?;
    assert_eq!(
        json_at(&active, "/policy_profile")?.as_str(),
        Some("strict")
    );
    assert_eq!(
        json_at(&active, "/outcome/status")?.as_str(),
        Some("failed")
    );

    let (request_named, locate_named) = pipeline(&journey, true)?;
    assert_eq!(request_named.status.code(), Some(0));
    assert_eq!(request_named.stderr.as_slice(), b"");
    assert_eq!(locate_named.status.code(), Some(0));
    assert_eq!(locate_named.stderr.as_slice(), b"");
    let named: Value = serde_json::from_slice(&locate_named.stdout)?;
    assert_eq!(json_at(&named, "/policy_profile")?.as_str(), Some("normal"));
    assert_eq!(
        json_at(&named, "/outcome/status")?.as_str(),
        Some("matched")
    );
    assert!(journey.store_unchanged()?);
    Ok(())
}

#[test]
fn request_override_is_explained_before_io_and_does_not_edit_profile() -> Result<(), Box<dyn Error>>
{
    let journey = Journey::new()?;
    let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args([
            "request",
            "https://example.test/",
            "--profile",
            "normal",
            "--timeout-ms",
            "2500",
            "--explain",
        ])
        .env("XDG_CONFIG_HOME", &journey.config)
        .output()?;
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr.as_slice(), b"");
    let text = String::from_utf8(output.stdout)?;
    assert!(text.contains("Policy profile: normal"));
    assert!(text.contains("\"maximum_elapsed\": 2500000"));
    assert!(journey.store_unchanged()?);
    Ok(())
}
