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
use unicode_width::UnicodeWidthStr as _;
use yosoi_engine::{Document, prelude::DocumentEpoch};

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
    assert_eq!(
        json_at(&match_value, "/outcome/status")?.as_str(),
        Some("matched")
    );
    assert_eq!(
        json_at(&match_value, "/document_profile/representation")?.as_str(),
        Some("source")
    );

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
    assert_eq!(
        json_at(&absent_value, "/outcome/status")?.as_str(),
        Some("no_match")
    );
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
    assert_eq!(missing_format.stdout.as_slice(), b"");
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
    assert_eq!(
        json_at(&value, "/outcome/status")?.as_str(),
        Some("matched")
    );

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
    assert_eq!(
        json_at(&pointer_value, "/outcome/status")?.as_str(),
        Some("matched")
    );

    let text = home.run_with_input(
        &[
            "locate", "--stdin", "--format", "text", "--text", "Yosoi", "--json",
        ],
        b"Hello Yosoi",
    )?;
    assert_eq!(text.status.code(), Some(0), "{}", stderr(&text));
    let text_value: Value = serde_json::from_slice(&text.stdout)?;
    assert_eq!(
        json_at(&text_value, "/outcome/status")?.as_str(),
        Some("matched")
    );
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
    assert_eq!(
        json_at(&active_value, "/policy_profile")?.as_str(),
        Some("active")
    );
    assert_eq!(
        json_at(&active_value, "/outcome/status")?.as_str(),
        Some("failed")
    );

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
    assert_eq!(
        json_at(&chosen_value, "/policy_profile")?.as_str(),
        Some("chosen")
    );
    assert_eq!(
        json_at(&chosen_value, "/outcome/status")?.as_str(),
        Some("matched")
    );
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
    assert_eq!(request_result.stderr.as_slice(), b"");
    assert_eq!(locate.status.code(), Some(0), "{}", stderr(&locate));
    let value: Value = serde_json::from_slice(&locate.stdout)?;
    assert_eq!(
        json_at(&value, "/document_profile/representation")?.as_str(),
        Some("source")
    );
    assert_eq!(
        json_at(&value, "/document_profile/source_format")?.as_str(),
        Some("html")
    );
    assert_eq!(
        json_at(&value, "/outcome/status")?.as_str(),
        Some("matched")
    );
    Ok(())
}

#[test]
fn request_pipe_into_locate_needs_no_output_or_input_mode_flags() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let (url, address, server) = loopback_html()?;
    let mut request = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["request", &url, "-s"])
        .env("XDG_CONFIG_HOME", &home.config)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let request_stdout = request
        .stdout
        .take()
        .ok_or("Request stdout was not piped")?;
    let locate = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["locate", "--css", "h1", "-s"])
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
    assert!(stderr(&request_result).contains("Request stats:"));
    assert!(stderr(&locate).contains("Locate stats:"));
    assert!(stderr(&locate).contains("Outcome: matched"));
    assert!(stderr(&locate).contains("Findings: 1"));
    assert!(!String::from_utf8_lossy(&locate.stdout).contains("Wall time:"));
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
    assert_eq!(malformed.stdout.as_slice(), b"");

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
    assert_eq!(oversized.stdout.as_slice(), b"");
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
    assert_eq!(
        json_at(&value, "/document_profile/representation")?.as_str(),
        Some("rendered_dom")
    );
    assert_eq!(
        json_at(&value, "/document_profile/epoch")?.as_u64(),
        Some(42)
    );
    assert_eq!(json_at(&value, "/outcome/status")?.as_str(), Some("failed"));
    Ok(())
}

#[test]
fn locate_stats_preserve_json_and_report_match_and_no_match() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let source = b"<main><h1>Catalog</h1></main>";
    let args = [
        "locate", "--stdin", "--format", "html", "--css", "h1", "--json",
    ];
    let baseline = home.run_with_input(&args, source)?;
    assert_eq!(baseline.status.code(), Some(0), "{}", stderr(&baseline));
    assert!(baseline.stderr.is_empty());
    for flag in ["--stats", "-s", "--STATS"] {
        let mut with_stats = args.to_vec();
        with_stats.push(flag);
        let output = home.run_with_input(&with_stats, source)?;
        assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
        assert_eq!(output.stdout, baseline.stdout);
        let statistics = stderr(&output);
        assert!(statistics.contains("Locate stats:\nWall time:"));
        assert!(statistics.contains("Input wait/read time:"));
        assert!(statistics.contains("Parse/query time:"));
        assert!(statistics.contains("Output time:"));
        assert!(statistics.contains(&format!("Input bytes: {}", source.len())));
        assert!(statistics.contains("Outcome: matched"));
        assert!(statistics.contains("Findings: 1"));
        assert!(!statistics.contains('\u{1b}'));
    }
    let absent = home.run_with_input(
        &[
            "locate", "--stdin", "--format", "html", "--css", ".missing", "--json", "--stats",
        ],
        source,
    )?;
    assert_eq!(absent.status.code(), Some(1), "{}", stderr(&absent));
    let value: Value = serde_json::from_slice(&absent.stdout)?;
    assert_eq!(
        json_at(&value, "/outcome/status")?.as_str(),
        Some("no_match")
    );
    assert!(stderr(&absent).contains("Outcome: no_match"));
    Ok(())
}

#[test]
fn human_previews_are_bounded_and_full_and_json_keep_complete_values() -> Result<(), Box<dyn Error>>
{
    let home = CliHome::new()?;
    let title = format!("{}\u{1b}[31mENDINGTOKEN", "界".repeat(800));
    let source = format!("<html><head><title>{title}</title></head></html>");
    let args = ["locate", "--stdin", "--format", "html", "--css", "head"];
    let preview = home.run_with_input(&args, source.as_bytes())?;
    assert_eq!(preview.status.code(), Some(0), "{}", stderr(&preview));
    let text = String::from_utf8(preview.stdout)?;
    assert!(text.contains("[preview: 600 of"));
    assert!(!text.contains("ENDINGTOKEN"));
    assert!(!text.contains('\u{1b}'));
    for line in text
        .lines()
        .filter(|line| line.starts_with("    ") && !line.contains("[preview:"))
    {
        assert!(line.width() <= 96);
    }
    let mut full_args = args.to_vec();
    full_args.push("--full");
    let full = home.run_with_input(&full_args, source.as_bytes())?;
    assert_eq!(full.status.code(), Some(0), "{}", stderr(&full));
    let full_text = String::from_utf8(full.stdout)?;
    assert!(full_text.contains("ENDINGTOKEN"));
    assert!(!full_text.contains("[preview:"));
    assert!(!full_text.contains('\u{1b}'));
    let mut json_args = args.to_vec();
    json_args.push("--json");
    let machine = home.run_with_input(&json_args, source.as_bytes())?;
    assert_eq!(machine.status.code(), Some(0), "{}", stderr(&machine));
    let envelope: Value = serde_json::from_slice(&machine.stdout)?;
    let findings = json_at(&envelope, "/outcome/result/findings")?
        .as_array()
        .ok_or("missing findings")?;
    let finding = findings.first().ok_or("missing first finding")?;
    assert_eq!(
        json_at(finding, "/value/value")?.as_str(),
        Some(title.as_str())
    );
    Ok(())
}

#[test]
fn many_findings_have_an_explicit_preview_limit() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let source = (0..12)
        .map(|number| format!("<h1>item-{number}</h1>"))
        .collect::<String>();
    let args = ["locate", "--stdin", "--format", "html", "--css", "h1"];
    let preview = home.run_with_input(&args, source.as_bytes())?;
    assert_eq!(preview.status.code(), Some(0), "{}", stderr(&preview));
    let text = String::from_utf8(preview.stdout)?;
    assert!(text.contains("[showing 10 of 12 findings; use --full or --json]"));
    assert!(!text.contains("item-11"));
    let mut full_args = args.to_vec();
    full_args.push("--full");
    let full = home.run_with_input(&full_args, source.as_bytes())?;
    assert_eq!(full.status.code(), Some(0), "{}", stderr(&full));
    assert!(String::from_utf8(full.stdout)?.contains("item-11"));
    Ok(())
}
