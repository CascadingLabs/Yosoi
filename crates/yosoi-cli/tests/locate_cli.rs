#![allow(clippy::panic_in_result_fn)] // Process assertions intentionally fail integration tests.

use std::{
    error::Error,
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::PathBuf,
    process::{Command, Output, Stdio},
    thread,
};

use serde_json::{Value, json};
use tempfile::TempDir;
use yosoi::{Document, prelude::DocumentEpoch};

struct CliHome {
    _directory: TempDir,
    config: PathBuf,
}

impl CliHome {
    fn new() -> Result<Self, Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let config = directory.path().join("config");
        fs::create_dir_all(&config)?;
        Ok(Self {
            _directory: directory,
            config,
        })
    }

    fn run(&self, args: &[&str]) -> Result<Output, Box<dyn Error>> {
        Ok(Command::new(env!("CARGO_BIN_EXE_yosoi"))
            .args(args)
            .env("XDG_CONFIG_HOME", &self.config)
            .output()?)
    }

    fn run_with_input(&self, args: &[&str], input: &[u8]) -> Result<Output, Box<dyn Error>> {
        let mut child = Command::new(env!("CARGO_BIN_EXE_yosoi"))
            .args(args)
            .env("XDG_CONFIG_HOME", &self.config)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut stdin = child.stdin.take().ok_or("CLI stdin was not piped")?;
        stdin.write_all(input)?;
        drop(stdin);
        Ok(child.wait_with_output()?)
    }

    fn write_profiles(&self) -> Result<Vec<u8>, Box<dyn Error>> {
        let path = self.config.join("yosoi/policies.json");
        fs::create_dir_all(path.parent().ok_or("store path has no parent")?)?;
        let mut versions = serde_json::Map::new();
        versions.insert(
            env!("CARGO_PKG_VERSION").to_owned(),
            json!({
                "active_profile": "active",
            "profiles": {
                "active": {"documents": {"max_input_bytes": 1}},
                "chosen": {}
            }
            }),
        );
        let bytes = serde_json::to_vec(&json!({"format_version": 1, "cli_versions": versions}))?;
        fs::write(path, &bytes)?;
        Ok(bytes)
    }
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn loopback_html() -> Result<(String, SocketAddr, thread::JoinHandle<()>), Box<dyn Error>> {
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
        let body = b"<main><h1>Catalog</h1></main>";
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

#[test]
fn html_file_reports_match_and_no_match_with_distinct_exit_codes() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let file = home.config.join("page.html");
    fs::write(&file, b"<main><h1>Catalog</h1></main>")?;
    let path = file.to_str().ok_or("fixture path is not UTF-8")?;

    let matched = home.run(&[
        "locate", "--file", path, "--format", "html", "--css", "h1", "--json",
    ])?;
    assert_eq!(matched.status.code(), Some(0), "{}", stderr(&matched));
    let match_value: Value = serde_json::from_slice(&matched.stdout)?;
    assert_eq!(match_value["outcome"]["status"], "matched");
    assert_eq!(match_value["document_profile"]["representation"], "source");

    let human = home.run(&["locate", "--file", path, "--format", "html", "--css", "h1"])?;
    assert_eq!(human.status.code(), Some(0), "{}", stderr(&human));
    let human_text = String::from_utf8(human.stdout)?;
    assert!(human_text.contains("Matched:"));
    assert!(human_text.contains("Catalog"));

    let absent = home.run(&[
        "locate", "--file", path, "--format", "html", "--css", ".missing", "--json",
    ])?;
    assert_eq!(absent.status.code(), Some(1), "{}", stderr(&absent));
    let absent_value: Value = serde_json::from_slice(&absent.stdout)?;
    assert_eq!(absent_value["outcome"]["status"], "no_match");
    Ok(())
}

#[test]
fn raw_stdin_requires_format_and_json_path_finds_value() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let missing_format = home.run_with_input(
        &["locate", "--stdin", "--json-path", "$.name"],
        b"{\"name\":\"Yosoi\"}",
    )?;
    assert_ne!(missing_format.status.code(), Some(0));
    assert!(missing_format.stdout.is_empty());
    assert!(stderr(&missing_format).contains("--format"));

    let matched = home.run_with_input(
        &[
            "locate",
            "--format",
            "json",
            "--json-path",
            "$.name",
            "--json",
        ],
        b"{\"name\":\"Yosoi\"}",
    )?;
    assert_eq!(matched.status.code(), Some(0), "{}", stderr(&matched));
    let value: Value = serde_json::from_slice(&matched.stdout)?;
    assert_eq!(value["outcome"]["status"], "matched");

    let pointer = home.run_with_input(
        &[
            "locate",
            "--stdin",
            "--format",
            "json",
            "--json-pointer",
            "/name",
            "--json",
        ],
        b"{\"name\":\"Yosoi\"}",
    )?;
    assert_eq!(pointer.status.code(), Some(0), "{}", stderr(&pointer));
    let pointer_value: Value = serde_json::from_slice(&pointer.stdout)?;
    assert_eq!(pointer_value["outcome"]["status"], "matched");

    let text = home.run_with_input(
        &[
            "locate", "--stdin", "--format", "text", "--text", "Yosoi", "--json",
        ],
        b"Hello Yosoi",
    )?;
    assert_eq!(text.status.code(), Some(0), "{}", stderr(&text));
    let text_value: Value = serde_json::from_slice(&text.stdout)?;
    assert_eq!(text_value["outcome"]["status"], "matched");
    Ok(())
}

#[test]
fn locate_resolves_active_or_named_policy_without_rewriting_json() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let original = home.write_profiles()?;
    let args = [
        "locate", "--stdin", "--format", "text", "--text", "Yosoi", "--json",
    ];
    let active = home.run_with_input(&args, b"Yosoi")?;
    assert_eq!(active.status.code(), Some(3), "{}", stderr(&active));
    let active_value: Value = serde_json::from_slice(&active.stdout)?;
    assert_eq!(active_value["policy_profile"], "active");
    assert_eq!(active_value["outcome"]["status"], "failed");

    let chosen = home.run_with_input(
        &[
            "locate",
            "--stdin",
            "--format",
            "text",
            "--text",
            "Yosoi",
            "--json",
            "--profile",
            "chosen",
        ],
        b"Yosoi",
    )?;
    assert_eq!(chosen.status.code(), Some(0), "{}", stderr(&chosen));
    let chosen_value: Value = serde_json::from_slice(&chosen.stdout)?;
    assert_eq!(chosen_value["policy_profile"], "chosen");
    assert_eq!(chosen_value["outcome"]["status"], "matched");
    assert_eq!(fs::read(home.config.join("yosoi/policies.json"))?, original);
    Ok(())
}

#[test]
fn request_to_locate_os_pipe_preserves_source_profile() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let (url, address, server) = loopback_html()?;
    let mut request = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["request", &url])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let request_stdout = request
        .stdout
        .take()
        .ok_or("Request stdout was not piped")?;
    let locate = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["locate", "--css", "h1", "--json"])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdin(Stdio::from(request_stdout))
        .output()?;
    let request_result = request.wait_with_output()?;
    finish_server(address, server)?;

    assert_eq!(
        request_result.status.code(),
        Some(0),
        "{}",
        stderr(&request_result)
    );
    assert!(request_result.stderr.is_empty());
    assert_eq!(locate.status.code(), Some(0), "{}", stderr(&locate));
    let value: Value = serde_json::from_slice(&locate.stdout)?;
    assert_eq!(value["document_profile"]["representation"], "source");
    assert_eq!(value["document_profile"]["source_format"], "html");
    assert_eq!(value["outcome"]["status"], "matched");
    Ok(())
}

#[test]
fn request_pipe_into_locate_needs_no_output_or_input_mode_flags() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let (url, address, server) = loopback_html()?;
    let mut request = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["request", &url])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let request_stdout = request
        .stdout
        .take()
        .ok_or("Request stdout was not piped")?;
    let locate = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["locate", "--css", "h1"])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdin(Stdio::from(request_stdout))
        .output()?;
    let request_result = request.wait_with_output()?;
    finish_server(address, server)?;

    assert_eq!(
        request_result.status.code(),
        Some(0),
        "{}",
        stderr(&request_result)
    );
    assert_eq!(locate.status.code(), Some(0), "{}", stderr(&locate));
    assert!(String::from_utf8_lossy(&locate.stdout).contains("Catalog"));
    Ok(())
}

#[test]
fn malformed_and_oversized_pipe_frames_fail_without_output() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let malformed = home.run_with_input(
        &["locate", "--pipe-document", "--text", "x"],
        b"not-a-document",
    )?;
    assert_ne!(malformed.status.code(), Some(0));
    assert!(malformed.stdout.is_empty());

    let header = serde_json::to_vec(&json!({
        "format_version": 1,
        "document_id": "oversized",
        "profile": {"representation":"source","source_format":"text","schema":"utf8_text","epoch":null},
        "byte_len": 67_108_865
    }))?;
    let mut frame = b"YSOIDOC1".to_vec();
    frame.extend_from_slice(&u32::try_from(header.len())?.to_be_bytes());
    frame.extend_from_slice(&header);
    let oversized = home.run_with_input(&["locate", "--pipe-document", "--text", "x"], &frame)?;
    assert_ne!(oversized.status.code(), Some(0));
    assert!(oversized.stdout.is_empty());
    assert!(stderr(&oversized).contains("limit"));
    Ok(())
}

#[test]
fn typed_rendered_dom_frame_keeps_epoch_and_cannot_be_relabelled_source()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let document =
        Document::rendered_dom("rendered", DocumentEpoch::try_from(42)?, b"{}".to_vec())?;
    let header = serde_json::to_vec(&json!({
        "format_version": 1,
        "document_id": document.id(),
        "profile": document.profile(),
        "byte_len": document.byte_len()
    }))?;
    let mut frame = b"YSOIDOC1".to_vec();
    frame.extend_from_slice(&u32::try_from(header.len())?.to_be_bytes());
    frame.extend_from_slice(&header);
    frame.extend_from_slice(document.bytes());
    let output = home.run_with_input(
        &["locate", "--pipe-document", "--css", "h1", "--json"],
        &frame,
    )?;
    assert_eq!(output.status.code(), Some(3), "{}", stderr(&output));
    let value: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(value["document_profile"]["representation"], "rendered_dom");
    assert_eq!(value["document_profile"]["epoch"], 42);
    assert_eq!(value["outcome"]["status"], "failed");
    Ok(())
}
