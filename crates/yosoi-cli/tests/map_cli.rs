#![allow(clippy::panic_in_result_fn)] // Process assertions intentionally fail integration tests.

use std::{
    error::Error,
    fmt::Write as _,
    fs,
    io::{self, Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::PathBuf,
    process::{Command, Output, Stdio},
    str,
    sync::mpsc,
    thread,
    time::Duration,
};

use serde_json::{Value, json};
use tempfile::TempDir;

fn json_at<'a>(value: &'a Value, pointer: &str) -> Result<&'a Value, Box<dyn Error>> {
    value
        .pointer(pointer)
        .ok_or_else(|| io::Error::other(format!("missing JSON value at {pointer}")).into())
}

fn json_at_mut<'a>(value: &'a mut Value, pointer: &str) -> Result<&'a mut Value, Box<dyn Error>> {
    value
        .pointer_mut(pointer)
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

    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_yosoi"));
        command.env("XDG_CONFIG_HOME", &self.config);
        command
    }

    fn run(&self, args: &[&str]) -> Result<Output, Box<dyn Error>> {
        Ok(self.command().args(args).output()?)
    }

    fn write_profiles(&self) -> Result<Vec<u8>, Box<dyn Error>> {
        let mut policy: Value = serde_json::from_str(include_str!(
            "../../yosoi-policy/tests/fixtures/default-policy.json"
        ))?;
        *json_at_mut(&mut policy, "/map/scope/hosts")? = json!("registrable_domain");
        *json_at_mut(&mut policy, "/map/pages")? = json!("disabled");
        *json_at_mut(&mut policy, "/map/subdomains")? = json!("passive");
        *json_at_mut(&mut policy, "/map/limits/max_link_depth")? = json!(1);
        *json_at_mut(&mut policy, "/map/limits/max_requests")? = json!(13);
        *json_at_mut(&mut policy, "/map/limits/max_hosts")? = json!(17);
        *json_at_mut(&mut policy, "/map/limits/max_urls")? = json!(19);
        let map = json_at(&policy, "/map")?.clone();

        let mut versions = serde_json::Map::new();
        versions.insert(
            env!("CARGO_PKG_VERSION").to_owned(),
            json!({
                "active_profile": "inherited",
                "profiles": {
                    "inherited": {"map": map},
                    "other": {"map": map}
                }
            }),
        );
        let bytes = serde_json::to_vec(&json!({
            "format_version": 1,
            "cli_versions": versions
        }))?;
        let path = self.config.join("yosoi/policies.json");
        fs::create_dir_all(path.parent().ok_or("store path has no parent")?)?;
        fs::write(path, &bytes)?;
        Ok(bytes)
    }
}

#[derive(Clone)]
struct SiteConfig {
    robots_status: u16,
    robots_body: Vec<u8>,
    sitemap_status: u16,
    root_html: Vec<u8>,
    docs_html: Vec<u8>,
    child_html: Vec<u8>,
    deep_child_html: Vec<u8>,
    private_html: Vec<u8>,
    hold_path: Option<String>,
}

impl Default for SiteConfig {
    fn default() -> Self {
        Self {
            robots_status: 404,
            robots_body: Vec::new(),
            sitemap_status: 404,
            root_html:
                br#"<a href="/child?b=2&amp;a=1#part">child</a><a href="/private">private</a>"#
                    .to_vec(),
            docs_html:
                br#"<a href="chapter.html">chapter</a><a href="../outside.html">outside</a>"#
                    .to_vec(),
            child_html: b"<main>child</main>".to_vec(),
            deep_child_html: b"<main>chapter</main>".to_vec(),
            private_html: b"<main>private</main>".to_vec(),
            hold_path: None,
        }
    }
}

enum SiteEvent {
    Request(String),
}

struct LoopbackSite {
    address: SocketAddr,
    events: mpsc::Receiver<SiteEvent>,
    held_response: mpsc::Receiver<()>,
    hold_release: mpsc::Sender<()>,
    shutdown: mpsc::Sender<()>,
    worker: Option<thread::JoinHandle<()>>,
}

impl LoopbackSite {
    fn new(config: SiteConfig) -> Result<Self, Box<dyn Error>> {
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let address = listener.local_addr()?;
        let (event_tx, events) = mpsc::channel();
        let (ready_tx, ready_rx) = mpsc::sync_channel(0);
        let (held_tx, held_response) = mpsc::channel();
        let (hold_release, release_rx) = mpsc::channel();
        let (shutdown, shutdown_rx) = mpsc::channel();
        let worker = thread::spawn(move || {
            let _ = ready_tx.send(());
            while let Ok((mut stream, _)) = listener.accept() {
                if shutdown_rx.try_recv().is_ok() {
                    break;
                }
                let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
                let Some(path) = read_request_path(&mut stream) else {
                    continue;
                };
                let _ = event_tx.send(SiteEvent::Request(path.clone()));
                let (status, body) = response_for(&config, &path);
                let reason = match status {
                    200 => "OK",
                    404 => "Not Found",
                    410 => "Gone",
                    503 => "Service Unavailable",
                    _ => "Fixture",
                };
                let headers = format!(
                    "HTTP/1.1 {status} {reason}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                if stream.write_all(headers.as_bytes()).is_err() {
                    continue;
                }
                if config.hold_path.as_deref() == Some(path.split('?').next().unwrap_or_default()) {
                    let _ = held_tx.send(());
                    if release_rx.recv().is_err() {
                        break;
                    }
                }
                let _ = stream.write_all(&body);
            }
        });
        ready_rx.recv_timeout(Duration::from_secs(2))?;
        Ok(Self {
            address,
            events,
            held_response,
            hold_release,
            shutdown,
            worker: Some(worker),
        })
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}{path}", self.address)
    }

    fn schemeless_url(&self, path: &str) -> String {
        format!("{}{path}", self.address)
    }

    fn wait_for_held_response(&self) -> Result<(), Box<dyn Error>> {
        self.held_response
            .recv_timeout(Duration::from_secs(5))
            .map_err(Into::into)
    }

    fn requests_since_last_check(&self) -> Vec<String> {
        self.events
            .try_iter()
            .map(|event| match event {
                SiteEvent::Request(path) => path,
            })
            .collect()
    }

    fn release_hold(&self) {
        let _ = self.hold_release.send(());
    }

    fn finish(mut self) -> Result<Vec<String>, Box<dyn Error>> {
        self.stop()?;
        Ok(self.requests_since_last_check())
    }

    fn stop(&mut self) -> Result<(), Box<dyn Error>> {
        if let Some(worker) = self.worker.take() {
            self.release_hold();
            let _ = self.shutdown.send(());
            let _ = TcpStream::connect_timeout(&self.address, Duration::from_secs(2));
            worker.join().map_err(|_| "loopback fixture panicked")?;
        }
        Ok(())
    }
}

impl Drop for LoopbackSite {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

fn read_request_path(stream: &mut TcpStream) -> Option<String> {
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 1024];
    while bytes.len() < 16_384 && !bytes.windows(4).any(|window| window == b"\r\n\r\n") {
        match stream.read(&mut buffer) {
            Ok(0) | Err(_) => return None,
            Ok(count) => bytes.extend_from_slice(buffer.get(..count)?),
        }
    }
    let request_line = String::from_utf8_lossy(&bytes);
    let mut fields = request_line.lines().next()?.split_whitespace();
    let method = fields.next()?;
    if method != "GET" {
        return None;
    }
    fields.next().map(str::to_owned)
}

fn response_for(config: &SiteConfig, request_path: &str) -> (u16, Vec<u8>) {
    let path = request_path.split('?').next().unwrap_or_default();
    if path == "/robots.txt" {
        return (config.robots_status, config.robots_body.clone());
    }
    if path.starts_with("/sitemap") {
        return (config.sitemap_status, Vec::new());
    }
    match path {
        "/" => (200, config.root_html.clone()),
        "/child" => (200, config.child_html.clone()),
        "/private" => (200, config.private_html.clone()),
        "/docs/" => (200, config.docs_html.clone()),
        "/docs/chapter.html" => (200, config.deep_child_html.clone()),
        "/outside.html" => (200, b"<main>outside</main>".to_vec()),
        _ => (404, Vec::new()),
    }
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn map_value(output: &Output) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(&output.stdout)?)
}

fn assert_map_document(value: &Value) -> Result<(), Box<dyn Error>> {
    assert_eq!(json_at(value, "/schema_version")?.as_u64(), Some(1));
    assert!(json_at(value, "/cli_version")?.is_string());
    assert!(json_at(value, "/seed")?.is_string());
    assert!(json_at(value, "/policy_identity/version")?.is_number());
    assert!(json_at(value, "/policy_identity/sha256")?.is_string());
    assert!(json_at(value, "/map_policy")?.is_object());
    assert!(json_at(value, "/termination")?.is_object());
    assert!(json_at(value, "/summary")?.is_object());
    for field in [
        "hosts",
        "pages",
        "relationships",
        "tree",
        "sources",
        "support_documents",
        "omissions",
        "frontier",
        "request_trace",
    ] {
        assert!(
            json_at(value, &format!("/{field}"))?.is_array(),
            "missing Map array {field}"
        );
    }
    Ok(())
}

fn explain_policy(output: &Output) -> Result<Value, Box<dyn Error>> {
    let text = str::from_utf8(&output.stdout)?;
    let start = text.find('{').ok_or("Explain did not print Policy JSON")?;
    Ok(serde_json::from_str(
        text.get(start..)
            .ok_or("Explain offset is not a character boundary")?,
    )?)
}

fn page<'a>(value: &'a Value, suffix: &str) -> Option<&'a Value> {
    value.get("pages")?.as_array()?.iter().find(|page| {
        page.get("url")
            .and_then(Value::as_str)
            .is_some_and(|url| url.ends_with(suffix))
    })
}

#[test]
fn map_help_and_command_options_accept_case_folded_spellings() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let canonical = home.run(&["map", "--help"])?;
    let folded = home.run(&["MaP", "--HeLp"])?;
    assert_eq!(canonical.status.code(), Some(0));
    assert_eq!(folded.status.code(), Some(0));
    assert_eq!(canonical.stdout, folded.stdout);
    assert!(String::from_utf8_lossy(&canonical.stdout).contains("--mode"));

    let explain = home.run(&["mAp", "example.test/docs/", "--MoDe", "pages", "--ExPlAiN"])?;
    assert_eq!(explain.status.code(), Some(0), "{}", stderr(&explain));
    assert!(String::from_utf8_lossy(&explain.stdout).contains("Policy identity: v"));
    Ok(())
}

#[test]
fn profile_mode_and_limit_overrides_are_explained_without_store_writes()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let original = home.write_profiles()?;
    let inherited = home.run(&["map", "example.test/docs/", "--explain", "-s"])?;
    assert_eq!(inherited.status.code(), Some(0), "{}", stderr(&inherited));
    let inherited_policy = explain_policy(&inherited)?;
    assert_eq!(
        json_at(&inherited_policy, "/map/pages")?.as_str(),
        Some("disabled")
    );
    assert_eq!(
        json_at(&inherited_policy, "/map/subdomains")?.as_str(),
        Some("passive")
    );
    assert_eq!(
        json_at(&inherited_policy, "/map/scope/hosts")?.as_str(),
        Some("registrable_domain")
    );
    assert!(stderr(&inherited).contains("Map: not sent"));

    let overridden = home.run(&[
        "--profile",
        "inherited",
        "map",
        "example.test/docs/",
        "--mode",
        "pages",
        "--depth",
        "3",
        "--max-requests",
        "7",
        "--max-hosts",
        "8",
        "--max-urls",
        "9",
        "--timeout-ms",
        "9000",
        "--robots",
        "respect",
        "--explain",
    ])?;
    assert_eq!(overridden.status.code(), Some(0), "{}", stderr(&overridden));
    let policy = explain_policy(&overridden)?;
    assert_eq!(json_at(&policy, "/map/pages")?.as_str(), Some("explore"));
    assert_eq!(
        json_at(&policy, "/map/subdomains")?.as_str(),
        Some("disabled")
    );
    assert_eq!(
        json_at(&policy, "/map/scope/hosts")?.as_str(),
        Some("seed_host")
    );
    assert_eq!(json_at(&policy, "/map/robots")?.as_str(), Some("respect"));
    assert_eq!(
        json_at(&policy, "/map/limits/max_link_depth")?.as_u64(),
        Some(3)
    );
    assert_eq!(
        json_at(&policy, "/map/limits/max_requests")?.as_u64(),
        Some(7)
    );
    assert_eq!(json_at(&policy, "/map/limits/max_hosts")?.as_u64(), Some(8));
    assert_eq!(json_at(&policy, "/map/limits/max_urls")?.as_u64(), Some(9));
    assert_eq!(
        json_at(&policy, "/map/limits/maximum_elapsed/seconds")?.as_u64(),
        Some(9)
    );
    assert_eq!(fs::read(home.config.join("yosoi/policies.json"))?, original);
    Ok(())
}

#[test]
fn invalid_limits_overflow_and_output_conflicts_fail_before_network_io()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let url = site.url("/");
    let zero = home.run(&["map", &url, "--max-requests", "0"])?;
    assert_eq!(zero.status.code(), Some(1), "{}", stderr(&zero));
    let overflow = home.run(&["map", &url, "--depth", "65536"])?;
    assert_eq!(overflow.status.code(), Some(2), "{}", stderr(&overflow));
    let conflicting = home.run(&["map", &url, "--json", "--raw"])?;
    assert_eq!(
        conflicting.status.code(),
        Some(2),
        "{}",
        stderr(&conflicting)
    );
    let explain_conflict = home.run(&["map", &url, "--explain", "--pipe-document"])?;
    assert_eq!(
        explain_conflict.status.code(),
        Some(2),
        "{}",
        stderr(&explain_conflict)
    );
    assert_eq!(site.finish()?, Vec::<String>::new());
    Ok(())
}

#[test]
fn schemeless_map_seed_uses_https_like_request_cli() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let bare = site.schemeless_url("/");
    let map = home.run(&["map", &bare, "--json", "--max-requests", "1"])?;
    let request = home.run(&["request", &bare, "--explain"])?;
    let value = map_value(&map)?;
    let expected_seed = format!("https://{bare}");
    assert_eq!(
        json_at(&value, "/seed")?.as_str(),
        Some(expected_seed.as_str())
    );
    assert_eq!(request.status.code(), Some(0), "{}", stderr(&request));
    let requests = site.finish()?;
    assert_eq!(
        requests,
        Vec::<String>::new(),
        "schemeless input unexpectedly used HTTP"
    );
    Ok(())
}

#[test]
fn regular_file_redirection_defaults_to_clean_versioned_map_json() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let url = site.url("/");
    let output_path = home.config.join("map.json");
    let file = fs::File::create(&output_path)?;
    let output = home
        .command()
        .args(["map", &url])
        .stdout(Stdio::from(file))
        .output()?;
    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert_eq!(output.stderr.as_slice(), b"");
    let bytes = fs::read(output_path)?;
    assert_eq!(bytes.first(), Some(&b'{'));
    let value: Value = serde_json::from_slice(&bytes)?;
    assert_map_document(&value)?;
    assert_eq!(
        json_at(&value, "/termination/status")?.as_str(),
        Some("exhausted")
    );
    assert!(!String::from_utf8_lossy(&bytes).contains("CLI version:"));
    assert!(site.finish()?.contains(&"/".to_owned()));
    Ok(())
}

#[test]
fn default_pipe_is_typed_document_locate_can_query_for_page_urls() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let url = site.url("/");
    let mut map = home
        .command()
        .args(["map", &url])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let stdout = map.stdout.take().ok_or("Map stdout was not piped")?;
    let located = home
        .command()
        .args(["locate", "--json-path", "$.pages[*].url", "--json"])
        .stdin(Stdio::from(stdout))
        .output()?;
    let mapped = map.wait_with_output()?;
    assert_eq!(mapped.status.code(), Some(0), "{}", stderr(&mapped));
    assert_eq!(located.status.code(), Some(0), "{}", stderr(&located));
    let located_value: Value = serde_json::from_slice(&located.stdout)?;
    assert_eq!(
        json_at(&located_value, "/outcome/status")?.as_str(),
        Some("matched")
    );
    assert!(String::from_utf8_lossy(&located.stdout).contains(&url));
    assert!(site.finish()?.contains(&"/".to_owned()));
    Ok(())
}

#[test]
fn explicit_json_pipe_and_pipe_document_file_replay_keep_their_wire_formats()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let url = site.url("/");

    let mut map = home
        .command()
        .args(["map", &url, "--json"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let stdout = map.stdout.take().ok_or("Map stdout was not piped")?;
    let located_json = home
        .command()
        .args([
            "locate",
            "--stdin",
            "--format",
            "json",
            "--json-path",
            "$.pages[*].url",
            "--json",
        ])
        .stdin(Stdio::from(stdout))
        .output()?;
    let mapped_json = map.wait_with_output()?;
    assert_eq!(
        mapped_json.status.code(),
        Some(0),
        "{}",
        stderr(&mapped_json)
    );
    assert_eq!(
        located_json.status.code(),
        Some(0),
        "{}",
        stderr(&located_json)
    );
    assert_eq!(
        json_at(
            &serde_json::from_slice::<Value>(&located_json.stdout)?,
            "/outcome/status"
        )?,
        "matched"
    );

    let frame_path = home.config.join("map.document");
    let frame_file = fs::File::create(&frame_path)?;
    let framed = home
        .command()
        .args(["map", &url, "--pipe-document"])
        .stdout(Stdio::from(frame_file))
        .output()?;
    assert_eq!(framed.status.code(), Some(0), "{}", stderr(&framed));
    let frame = fs::read(&frame_path)?;
    assert!(frame.starts_with(b"YSOIDOC1"));
    let replay = home
        .command()
        .args([
            "locate",
            "--pipe-document",
            "--json-path",
            "$.pages[*].url",
            "--json",
        ])
        .stdin(Stdio::from(fs::File::open(frame_path)?))
        .output()?;
    assert_eq!(replay.status.code(), Some(0), "{}", stderr(&replay));
    assert_eq!(
        json_at(
            &serde_json::from_slice::<Value>(&replay.stdout)?,
            "/outcome/status"
        )?,
        "matched"
    );
    assert!(site.finish()?.contains(&"/".to_owned()));
    Ok(())
}

#[test]
fn traversal_normalizes_links_and_respect_skips_robots_blocked_pages() -> Result<(), Box<dyn Error>>
{
    let home = CliHome::new()?;
    let config = SiteConfig {
        robots_status: 200,
        robots_body: b"User-agent: *\nDisallow: /private\n".to_vec(),
        ..SiteConfig::default()
    };
    let site = LoopbackSite::new(config)?;
    let url = site.url("/");

    let ignored = home.run(&["map", &url, "--json"])?;
    assert_eq!(ignored.status.code(), Some(0), "{}", stderr(&ignored));
    let ignored_value = map_value(&ignored)?;
    assert_map_document(&ignored_value)?;
    assert_eq!(
        json_at(&ignored_value, "/map_policy/robots")?.as_str(),
        Some("ignore")
    );
    assert_eq!(
        json_at(&ignored_value, "/pages")?.as_array().map(Vec::len),
        Some(3)
    );
    let normalized_child = json_at(&ignored_value, "/pages")?
        .as_array()
        .and_then(|pages| {
            pages.iter().find(|page| {
                page.get("url")
                    .and_then(Value::as_str)
                    .is_some_and(|url| url.contains("/child?b=2&a=1"))
            })
        })
        .ok_or("normalized child URL is missing")?;
    assert_eq!(
        json_at(normalized_child, "/minimum_link_depth")?.as_u64(),
        Some(1)
    );
    assert!(
        json_at(normalized_child, "/url")?
            .as_str()
            .is_some_and(|url| !url.contains('#'))
    );
    assert!(
        json_at(&ignored_value, "/summary/requests")?
            .as_u64()
            .unwrap_or_default()
            >= 4
    );
    let ignored_requests = site.requests_since_last_check();
    assert!(ignored_requests.iter().any(|path| path == "/private"));
    assert!(
        !ignored_requests
            .iter()
            .any(|path| path.starts_with("/outside"))
    );

    let respected = home.run(&["map", &url, "--json", "--robots", "respect"])?;
    assert_eq!(respected.status.code(), Some(0), "{}", stderr(&respected));
    let respected_value = map_value(&respected)?;
    assert_eq!(
        json_at(&respected_value, "/map_policy/robots")?.as_str(),
        Some("respect")
    );
    let skipped = page(&respected_value, "/private").ok_or("missing robots-blocked page")?;
    assert_eq!(
        json_at(skipped, "/exploration/status")?.as_str(),
        Some("skipped")
    );
    assert_eq!(
        json_at(skipped, "/exploration/reason")?.as_str(),
        Some("robots")
    );
    let respected_requests = site.finish()?;
    assert!(!respected_requests.iter().any(|path| path == "/private"));
    assert!(
        respected_requests
            .iter()
            .any(|path| path == "/child?b=2&a=1")
    );
    Ok(())
}

#[test]
fn deep_seed_subtree_traverses_relative_child_without_fetching_siblings()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let url = site.url("/docs/");
    let output = home.run(&["map", &url, "--json", "--depth", "2"])?;
    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    let value = map_value(&output)?;
    assert_eq!(json_at(&value, "/seed")?.as_str(), Some(url.as_str()));
    assert_eq!(json_at(&value, "/pages")?.as_array().map(Vec::len), Some(2));
    assert!(page(&value, "/docs/chapter.html").is_some());
    assert!(
        json_at(&value, "/pages")?
            .as_array()
            .is_some_and(|pages| pages.iter().all(|page| page
                .get("url")
                .unwrap_or(&Value::Null)
                .as_str()
                .is_some_and(|url| url.contains("/docs/"))))
    );
    let requests = site.finish()?;
    assert!(requests.iter().any(|path| path == "/docs/"));
    assert!(requests.iter().any(|path| path == "/docs/chapter.html"));
    assert!(!requests.iter().any(|path| path == "/outside.html"));
    assert!(!requests.iter().any(|path| path == "/"));
    Ok(())
}

#[test]
fn robots_404_is_normal_absence_but_a_source_error_is_partial() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let absent_config = SiteConfig {
        sitemap_status: 410,
        ..SiteConfig::default()
    };
    let absent_site = LoopbackSite::new(absent_config)?;
    let absent = home.run(&["map", &absent_site.url("/"), "--json"])?;
    assert_eq!(absent.status.code(), Some(0), "{}", stderr(&absent));
    let absent_value = map_value(&absent)?;
    assert!(page(&absent_value, "/").is_some());
    assert!(
        json_at(&absent_value, "/support_documents")?
            .as_array()
            .is_some_and(|documents| documents.iter().any(|document| {
                document
                    .get("url")
                    .unwrap_or(&Value::Null)
                    .as_str()
                    .is_some_and(|url| url.ends_with("/robots.txt"))
                    && !document.get("status").is_some_and(|status| {
                        status.to_string().to_ascii_lowercase().contains("failed")
                    })
            }))
    );
    assert!(absent_site.finish()?.contains(&"/robots.txt".to_owned()));

    let config = SiteConfig {
        robots_status: 503,
        ..SiteConfig::default()
    };
    let failed_site = LoopbackSite::new(config)?;
    let failed = home.run(&["map", &failed_site.url("/"), "--json"])?;
    assert_eq!(failed.status.code(), Some(3), "{}", stderr(&failed));
    let failed_value = map_value(&failed)?;
    assert!(page(&failed_value, "/").is_some());
    assert!(
        json_at(&failed_value, "/support_documents")?
            .as_array()
            .is_some_and(|documents| documents.iter().any(|document| {
                document
                    .get("url")
                    .unwrap_or(&Value::Null)
                    .as_str()
                    .is_some_and(|url| url.ends_with("/robots.txt"))
                    && document.get("status").is_some_and(|status| {
                        status.to_string().to_ascii_lowercase().contains("failed")
                    })
            }))
    );
    assert!(failed_site.finish()?.contains(&"/robots.txt".to_owned()));
    Ok(())
}

#[test]
fn request_limit_returns_partial_json_with_pending_seed_frontier() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let site = LoopbackSite::new(SiteConfig::default())?;
    let url = site.url("/");
    let output = home.run(&["map", &url, "--json", "--max-requests", "1"])?;
    assert_eq!(output.status.code(), Some(3), "{}", stderr(&output));
    let value = map_value(&output)?;
    assert_eq!(
        json_at(&value, "/termination/status")?.as_str(),
        Some("limit")
    );
    assert!(
        json_at(&value, "/termination")?
            .to_string()
            .to_ascii_lowercase()
            .contains("request")
    );
    assert!(
        json_at(&value, "/frontier")?
            .as_array()
            .is_some_and(|frontier| {
                frontier
                    .iter()
                    .any(|entry| entry.get("page").is_some_and(|page| page == &url))
            })
    );
    assert_eq!(json_at(&value, "/summary/requests")?.as_u64(), Some(1));
    assert_eq!(site.finish()?, vec!["/robots.txt".to_owned()]);
    Ok(())
}

#[cfg(unix)]
#[test]
fn ctrl_c_cancels_a_held_map_response_and_cleans_up_fixture() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let config = SiteConfig {
        robots_status: 200,
        robots_body: b"User-agent: *\n".to_vec(),
        hold_path: Some("/robots.txt".to_owned()),
        ..SiteConfig::default()
    };
    let site = LoopbackSite::new(config)?;
    let url = site.url("/");
    let mut child = home
        .command()
        .args(["map", &url, "--json", "--timeout-ms", "15000"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let pid = child.id();
    if let Err(error) = site.wait_for_held_response() {
        let _ = Command::new("kill")
            .args(["-KILL", pid.to_string().as_str()])
            .status();
        let _ = child.wait();
        let _ = site.finish();
        return Err(error);
    }
    let pid_text = pid.to_string();
    let signal = Command::new("kill")
        .args(["-INT", pid_text.as_str()])
        .status()?;
    if !signal.success() {
        let _ = Command::new("kill")
            .args(["-KILL", pid_text.as_str()])
            .status();
        let _ = child.wait();
        let _ = site.finish();
        return Err("could not deliver Ctrl-C to Map process".into());
    }

    let (done_tx, done_rx) = mpsc::channel();
    let waiter = thread::spawn(move || {
        let _ = done_tx.send(child.wait_with_output());
    });
    let output = match done_rx.recv_timeout(Duration::from_secs(5)) {
        Ok(result) => result?,
        Err(error) => {
            let _ = Command::new("kill")
                .args(["-KILL", pid_text.as_str()])
                .status();
            site.release_hold();
            let _ = site.finish();
            let _ = waiter.join();
            return Err(error.into());
        }
    };
    waiter.join().map_err(|_| "CLI process waiter panicked")?;
    assert_eq!(output.status.code(), Some(130), "{}", stderr(&output));
    let value = map_value(&output)?;
    assert_eq!(
        json_at(&value, "/termination/status")?.as_str(),
        Some("cancelled")
    );
    assert!(site.finish()?.contains(&"/robots.txt".to_owned()));
    Ok(())
}

#[test]
fn broken_output_consumer_returns_an_error_without_panicking() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let mut many_links = String::new();
    for index in 0..700 {
        let _ = write!(many_links, "<a href=\"/target-{index:04}\">target</a>");
    }
    let config = SiteConfig {
        root_html: many_links.into_bytes(),
        ..SiteConfig::default()
    };
    let site = LoopbackSite::new(config)?;
    let url = site.url("/");
    let mut child = home
        .command()
        .args(["map", &url, "--json", "--depth", "0"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let mut stdout = child.stdout.take().ok_or("Map stdout was not piped")?;
    let consumer = thread::spawn(move || {
        let mut first_byte = [0_u8; 1];
        let _ = stdout.read(&mut first_byte);
    });
    let output = child.wait_with_output()?;
    consumer
        .join()
        .map_err(|_| "broken-pipe consumer panicked")?;
    assert!(output.status.code().is_some_and(|code| code != 0));
    assert!(!stderr(&output).to_ascii_lowercase().contains("panicked at"));
    assert!(site.finish()?.contains(&"/".to_owned()));
    Ok(())
}

#[test]
fn stats_spellings_keep_explain_stdout_clean_and_report_only_to_stderr()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    for flag in ["--stats", "-s", "--stat", "--STATS"] {
        let output = home.run(&["map", "https://example.com/", "--explain", flag])?;
        assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
        assert!(stderr(&output).contains("Map: not sent (--explain)"));
        assert!(stderr(&output).contains("Wall time:"));
        let policy = explain_policy(&output)?;
        assert_eq!(
            json_at(&policy, "/map/limits/max_concurrency")?.as_u64(),
            Some(2)
        );
        assert!(!String::from_utf8_lossy(&output.stdout).contains("Wall time:"));
    }
    Ok(())
}
