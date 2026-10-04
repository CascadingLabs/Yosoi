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

#[cfg(unix)]
use std::{sync::mpsc, time::Duration};

use serde_json::{Value, json};
use tempfile::TempDir;

fn json_at<'a>(value: &'a Value, pointer: &str) -> Result<&'a Value, Box<dyn Error>> {
    value
        .pointer(pointer)
        .ok_or_else(|| io::Error::other(format!("missing JSON value at {pointer}")).into())
}

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

    fn write_profiles(&self) -> Result<Vec<u8>, Box<dyn Error>> {
        let path = self.config.join("yosoi/policies.json");
        fs::create_dir_all(path.parent().ok_or("store path has no parent")?)?;
        let mut versions = serde_json::Map::new();
        versions.insert(
            env!("CARGO_PKG_VERSION").to_owned(),
            json!({
                "active_profile": "slow",
                "profiles": {
                    "slow": {"request": {"maximum_elapsed": 3_000_000}},
                    "fast": {"request": {"maximum_elapsed": 1_000_000}},
                    "multi": {"page": {"acquisitions": [{
                        "kind": "browser",
                        "mode": "headless",
                        "documents": {"kind": "exact", "documents": ["response_document", "rendered_dom"]}
                    }]}}
                }
            }),
        );
        let bytes = serde_json::to_vec(&json!({"format_version": 1, "cli_versions": versions}))?;
        fs::write(path, &bytes)?;
        Ok(bytes)
    }
}

fn loopback(
    status: &str,
    body: &'static [u8],
) -> Result<(String, SocketAddr, thread::JoinHandle<()>), Box<dyn Error>> {
    loopback_with_length(status, body, body.len())
}

fn loopback_with_length(
    status: &str,
    body: &'static [u8],
    declared_length: usize,
) -> Result<(String, SocketAddr, thread::JoinHandle<()>), Box<dyn Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let address = listener.local_addr()?;
    let url = format!("http://{address}/");
    let status = status.to_owned();
    let handle = thread::spawn(move || {
        let Ok((mut stream, _)) = listener.accept() else {
            return;
        };
        let mut request = [0_u8; 1024];
        if stream.read(&mut request).is_err() {
            return;
        }
        let head = format!(
            "HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {declared_length}\r\nConnection: close\r\n\r\n"
        );
        if stream.write_all(head.as_bytes()).is_err() {
            return;
        }
        let _ = stream.write_all(body);
    });
    Ok((url, address, handle))
}

fn finish_server(
    address: SocketAddr,
    handle: thread::JoinHandle<()>,
) -> Result<(), Box<dyn Error>> {
    if !handle.is_finished()
        && let Ok(mut stream) = TcpStream::connect(address)
    {
        let _ = stream.write_all(b"GET / HTTP/1.1\r\n\r\n");
    }
    handle.join().map_err(|_| "loopback server panicked".into())
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

#[test]
fn default_request_reports_a_real_http_response_as_bounded_json() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let (url, address, server) = loopback("200 OK", b"fixture-body")?;
    let output = home.run(&["request", &url, "--json"])?;
    finish_server(address, server)?;

    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert_eq!(output.stderr.as_slice(), b"");
    let value: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(json_at(&value, "/schema_version")?.as_u64(), Some(1));
    assert!(json_at(&value, "/policy_profile")?.is_null());
    assert_eq!(
        json_at(&value, "/attempts/0/state")?.as_str(),
        Some("completed")
    );
    assert_eq!(
        json_at(&value, "/attempts/0/http_status")?.as_u64(),
        Some(200)
    );
    assert_eq!(
        json_at(&value, "/attempts/0/documents/0/state")?.as_str(),
        Some("produced")
    );
    assert!(
        !output
            .stdout
            .windows(b"fixture-body".len())
            .any(|part| part == b"fixture-body")
    );
    Ok(())
}

#[test]
fn stat_reports_timing_and_metadata_without_changing_document_stdout() -> Result<(), Box<dyn Error>>
{
    let home = CliHome::new()?;
    let (url, address, server) = loopback("200 OK", b"fixture-body")?;
    let output = home.run(&["request", &url, "-a", "http", "--raw", "-s"])?;
    finish_server(address, server)?;

    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert_eq!(output.stdout, b"fixture-body");
    let stats = stderr(&output);
    assert!(stats.contains("Request stats:"));
    assert!(stats.contains("Wall time:"));
    assert!(stats.contains("Termination: completed"));
    assert!(stats.contains("Attempt 1: direct_http, HTTP 200, 12 document bytes"));
    Ok(())
}

#[test]
fn regular_file_redirect_writes_document_bytes_without_an_output_flag() -> Result<(), Box<dyn Error>>
{
    let home = CliHome::new()?;
    let (url, address, server) = loopback("200 OK", b"redirected-body")?;
    let output_path = home.config.join("response.txt");
    let output_file = fs::File::create(&output_path)?;
    let result = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["request", &url])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdout(Stdio::from(output_file))
        .output()?;
    finish_server(address, server)?;

    assert_eq!(result.status.code(), Some(0), "{}", stderr(&result));
    assert_eq!(result.stderr.as_slice(), b"");
    assert_eq!(fs::read(output_path)?, b"redirected-body");
    Ok(())
}

#[test]
fn non_success_http_status_still_emits_selected_raw_document() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let (url, address, server) = loopback("404 Not Found", b"missing")?;
    let output = home.run(&["request", &url, "--raw"])?;
    finish_server(address, server)?;

    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert_eq!(output.stdout, b"missing");
    assert_eq!(output.stderr.as_slice(), b"");
    Ok(())
}

#[test]
fn named_profile_and_one_run_flags_change_explanation_without_writing_store()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let original = home.write_profiles()?;
    let active = home.run(&["request", "https://example.test/", "--explain"])?;
    assert_eq!(active.status.code(), Some(0), "{}", stderr(&active));
    assert!(String::from_utf8_lossy(&active.stdout).contains("Policy profile: slow"));
    let output = home.run(&[
        "--profile",
        "fast",
        "request",
        "https://example.test/",
        "--explain",
        "--acquisition",
        "http",
        "--timeout-ms",
        "2500",
    ])?;

    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    let text = String::from_utf8(output.stdout)?;
    assert!(text.contains("Policy profile: fast"));
    assert!(text.contains("\"maximum_elapsed\": 2500000"));
    assert!(text.contains("\"kind\": \"direct_http\""));
    assert_eq!(fs::read(home.config.join("yosoi/policies.json"))?, original);
    Ok(())
}

#[test]
fn schemeless_target_and_short_acquisition_alias_prepare_without_io() -> Result<(), Box<dyn Error>>
{
    let home = CliHome::new()?;
    let http = home.run(&[
        "request",
        "httpbin.org/html",
        "-a",
        "http",
        "--explain",
        "--stat",
    ])?;
    assert_eq!(http.status.code(), Some(0), "{}", stderr(&http));
    assert!(String::from_utf8_lossy(&http.stdout).contains("\"kind\": \"direct_http\""));
    assert!(stderr(&http).contains("Request: not sent (--explain)"));

    let headless = home.run(&["request", "httpbin.org/html", "-A", "headless", "--explain"])?;
    assert_eq!(headless.status.code(), Some(0), "{}", stderr(&headless));
    assert!(String::from_utf8_lossy(&headless.stdout).contains("\"mode\": \"headless\""));

    let explicit = home.run(&["request", "http:example.com", "--explain"])?;
    assert_eq!(explicit.status.code(), Some(0), "{}", stderr(&explicit));
    let host_port = home.run(&["request", "example.org:443", "--explain"])?;
    assert_eq!(host_port.status.code(), Some(0), "{}", stderr(&host_port));
    Ok(())
}

#[test]
fn named_profile_is_bound_for_a_real_request_without_changing_active_selection()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let original = home.write_profiles()?;
    let (url, address, server) = loopback("200 OK", b"saved-profile")?;
    let output = home.run(&["request", &url, "--profile", "fast", "--json"])?;
    finish_server(address, server)?;

    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    let value: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(json_at(&value, "/policy_profile")?.as_str(), Some("fast"));
    assert_eq!(
        json_at(&value, "/attempts/0/state")?.as_str(),
        Some("completed")
    );
    assert_eq!(fs::read(home.config.join("yosoi/policies.json"))?, original);
    Ok(())
}

#[test]
fn missing_selected_profile_fails_before_network_io() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    home.write_profiles()?;
    let output = home.run(&[
        "request",
        "https://example.test/",
        "--profile",
        "missing",
        "--explain",
    ])?;

    assert_ne!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"");
    assert!(stderr(&output).contains("missing"));
    Ok(())
}

#[test]
fn profile_option_and_command_names_ignore_case_but_profile_value_does_not()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    home.write_profiles()?;
    let accepted = home.run(&[
        "ReQuEsT",
        "https://example.test/",
        "--PrOfIlE",
        "fast",
        "--EXPLAIN",
    ])?;
    assert_eq!(accepted.status.code(), Some(0), "{}", stderr(&accepted));
    assert!(String::from_utf8_lossy(&accepted.stdout).contains("Policy profile: fast"));

    let rejected = home.run(&[
        "request",
        "https://example.test/",
        "--profile",
        "FAST",
        "--explain",
    ])?;
    assert_ne!(rejected.status.code(), Some(0));
    assert!(stderr(&rejected).contains("FAST"));
    Ok(())
}

#[test]
fn transport_failure_has_nonzero_exit_and_typed_attempt_result() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let url = format!("http://{}/", listener.local_addr()?);
    drop(listener);
    let output = home.run(&["request", &url, "--json", "--timeout-ms", "1000"])?;

    assert_ne!(output.status.code(), Some(0));
    let value: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(
        json_at(&value, "/attempts/0/state")?.as_str(),
        Some("failed")
    );
    assert!(json_at(&value, "/attempts/0/http_status")?.is_null());
    Ok(())
}

#[test]
fn incomplete_response_does_not_emit_raw_document_bytes() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let (url, address, server) = loopback_with_length("200 OK", b"short", 100)?;
    let output = home.run(&["request", &url, "--raw", "--timeout-ms", "1000", "-s"])?;
    finish_server(address, server)?;

    assert_ne!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"");
    assert_ne!(stderr(&output), "");
    assert!(stderr(&output).contains("Request stats:"));
    Ok(())
}

#[test]
fn policy_commands_reject_operational_profile_flag() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let output = home.run(&["policy", "list", "--profile", "fast"])?;
    assert_ne!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"");
    assert!(stderr(&output).contains("--profile"));
    Ok(())
}

#[test]
fn raw_selection_errors_before_network_io() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    home.write_profiles()?;
    let ambiguous = home.run(&[
        "request",
        "https://example.test/",
        "--raw",
        "--acquisition",
        "http",
        "--acquisition",
        "headless",
    ])?;
    assert_ne!(ambiguous.status.code(), Some(0));
    assert_eq!(ambiguous.stdout.as_slice(), b"");
    assert!(stderr(&ambiguous).contains("--attempt"));

    let missing_view = home.run(&[
        "request",
        "https://example.test/",
        "--raw",
        "--document",
        "dom",
    ])?;
    assert_ne!(missing_view.status.code(), Some(0));
    assert_eq!(missing_view.stdout.as_slice(), b"");
    assert!(stderr(&missing_view).contains("does not request"));

    let ambiguous_documents = home.run(&[
        "request",
        "https://example.test/",
        "--profile",
        "multi",
        "--raw",
    ])?;
    assert_ne!(ambiguous_documents.status.code(), Some(0));
    assert_eq!(ambiguous_documents.stdout.as_slice(), b"");
    assert!(stderr(&ambiguous_documents).contains("--document"));
    Ok(())
}

#[cfg(unix)]
fn cancelled_request(mode: &str) -> Result<Output, Box<dyn Error>> {
    let home = CliHome::new()?;
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let url = format!("http://{}/", listener.local_addr()?);
    let (connected_tx, connected_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let server = thread::spawn(move || {
        let Ok((mut stream, _)) = listener.accept() else {
            return;
        };
        let mut request = [0_u8; 1024];
        if stream.read(&mut request).is_ok() {
            let _ = connected_tx.send(());
            let _ = release_rx.recv();
        }
    });
    let child = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["request", &url, mode, "--timeout-ms", "2000"])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let pid = child.id();
    connected_rx.recv_timeout(Duration::from_secs(5))?;
    let signal = Command::new("kill")
        .args(["-INT", &pid.to_string()])
        .status()?;
    assert!(signal.success());
    let (done_tx, done_rx) = mpsc::channel();
    let waiter = thread::spawn(move || {
        let _ = done_tx.send(child.wait_with_output());
    });
    let output = match done_rx.recv_timeout(Duration::from_secs(5)) {
        Ok(result) => result?,
        Err(error) => {
            let _ = Command::new("kill")
                .args(["-KILL", &pid.to_string()])
                .status();
            let _ = done_rx.recv_timeout(Duration::from_secs(5));
            let _ = release_tx.send(());
            let _ = server.join();
            let _ = waiter.join();
            return Err(error.into());
        }
    };
    release_tx.send(())?;
    server.join().map_err(|_| "loopback server panicked")?;
    waiter.join().map_err(|_| "process waiter panicked")?;

    Ok(output)
}

#[cfg(unix)]
#[test]
fn ctrl_c_cancels_an_active_request_and_reports_terminal_state() -> Result<(), Box<dyn Error>> {
    let output = cancelled_request("--json")?;
    assert_eq!(output.status.code(), Some(130), "{}", stderr(&output));
    let value: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(json_at(&value, "/termination")?.as_str(), Some("cancelled"));
    Ok(())
}

#[cfg(unix)]
#[test]
fn ctrl_c_in_raw_mode_keeps_stdout_empty_and_returns_130() -> Result<(), Box<dyn Error>> {
    let output = cancelled_request("--raw")?;
    assert_eq!(output.status.code(), Some(130), "{}", stderr(&output));
    assert_eq!(output.stdout.as_slice(), b"");
    assert!(stderr(&output).contains("cancelled"));
    Ok(())
}

#[test]
fn stats_long_and_short_spellings_report_explain_timing_on_stderr() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    for flag in ["--stats", "-s", "--stat", "--STATS"] {
        let output = home.run(&["request", "https://example.com/", "--explain", flag])?;
        assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
        assert!(stderr(&output).contains("Request: not sent (--explain)"));
        assert!(stderr(&output).contains("Wall time:"));
        assert!(!String::from_utf8_lossy(&output.stdout).contains("Wall time:"));
    }
    Ok(())
}
