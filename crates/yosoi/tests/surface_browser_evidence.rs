//! Per-representation limits, evidence isolation, and real browser capture.
#![allow(
    clippy::panic_in_result_fn,
    reason = "Test assertions preserve evidence invariants."
)]
use serde_json::json;
use std::error::Error;
use yosoi::{
    documents::{Document, DocumentEpoch},
    surface::{
        Budget, DocumentPolicies, DocumentPolicy, Surface,
        browser::WebSurface,
        model::{ReadOperation, ReadRequest, ReadResult, SourceId, SurfaceRead},
    },
};
type TestResult = Result<(), Box<dyn Error + Send + Sync>>;
const fn request(operation: ReadOperation) -> ReadRequest {
    ReadRequest {
        operation,
        budget: Budget {
            bytes: 65_280,
            items: 100,
        },
        continuation: None,
    }
}
fn ax_document() -> Result<Document, Box<dyn Error + Send + Sync>> {
    Ok(Document::accessibility_tree(
        "native-ax",
        DocumentEpoch::try_from(1)?,
        serde_json::to_vec(&json!({
            "schema":"yosoi.accessibility-tree.v1","document_epoch":1,"root":"root",
            "completeness":{"status":"partial","reason_code":"depth_limited","lost_items":null},
            "nodes":[{"id":"root","parent":null,"children":["search"],"ignored":false,"role":"RootWebArea","accessible_name":"Docs","text":null,"states":{}},
        {"id":"search","parent":"root","children":[],"ignored":false,"role":"button","accessible_name":"Search","text":null,"states":{"focused":false}}]
        }))?,
    )?)
}
#[test]
fn policies_select_document_type_and_reject_source_bytes_depth_and_nodes() -> TestResult {
    let mut policies = DocumentPolicies::default();
    policies.html.max_bytes = 512;
    let html = Document::html("large", format!("<p>{}</p>", "x".repeat(600)).into_bytes())?;
    assert!(Surface::with_policy(&html, &policies).is_err());
    let text = Document::text("independent", "x".repeat(600).into_bytes())?;
    assert!(Surface::with_policy(&text, &policies).is_ok());
    policies.json.max_depth = 1;
    let nested = Document::json("deep", br#"{"a":{"b":1}}"#.to_vec())?;
    assert!(Surface::with_policy(&nested, &policies).is_err());
    policies.json.max_depth = 20;
    policies.json.max_nodes = 2;
    assert!(Surface::with_policy(&nested, &policies).is_err());
    policies.json.max_nodes = 100;
    assert!(Surface::with_policy(&nested, &policies).is_ok());
    policies.ax.max_nodes = 100_001;
    assert!(Surface::with_policy(&text, &policies).is_err());
    Ok(())
}
#[test]
fn ax_and_network_readers_preserve_coverage_budgets_and_foreign_reference_rejection() -> TestResult
{
    let policies = DocumentPolicies::default();
    let ax = WebSurface::with_policy(
        Surface::with_policy(&ax_document()?, &policies)?,
        SourceId::new("ax")?,
        DocumentPolicy {
            response_bytes: 1024,
            ..policies.ax
        },
    )?;
    assert!(!ax.descriptor().controllable);
    assert_eq!(ax.descriptor().representation, "yosoi.web.ax.v1");
    let result = ax.read(&request(ReadOperation::Search {
        query: "Search".into(),
    }))?;
    assert!(serde_json::to_vec(&result)?.len() <= 1024);
    let ReadResult::Page(page) = result else {
        return Err("expected AX page".into());
    };
    assert!(!page.coverage.complete);
    assert!(!page.entries.is_empty());
    let network = Document::json(
        "network",
        serde_json::to_vec(
            &json!({"schema":"yosoi.network.v1","events":[{"method":"Network.responseReceived","params":{"url":"https://owned.example/api"}}]}),
        )?,
    )?;
    let network = WebSurface::with_policy(
        Surface::with_limits(&network, policies.network.limits()?)?,
        SourceId::new("network")?,
        DocumentPolicy {
            response_bytes: 1024,
            ..policies.network
        },
    )?;
    assert!(!network.observation().coverage.complete);
    assert!(!network.descriptor().controllable);
    assert_eq!(network.descriptor().representation, "yosoi.web.network.v1");
    assert!(
        network
            .read(&request(ReadOperation::Inspect {
                reference: ax.root_reference()
            }))
            .is_err()
    );
    let result = network.read(&request(ReadOperation::Search {
        query: "owned.example".into(),
    }))?;
    assert!(serde_json::to_vec(&result)?.len() <= 1024);
    let ReadResult::Page(page) = result else {
        return Err("expected network page".into());
    };
    assert!(!page.coverage.complete);
    assert!(!page.entries.is_empty());
    Ok(())
}

#[test]
fn prepared_document_response_policy_survives_shared_reader_wrapping() -> TestResult {
    let document = Document::html(
        "many",
        format!("<main>{}</main>", "<button>Needle</button>".repeat(30)).into_bytes(),
    )?;
    let policies = DocumentPolicies {
        html: DocumentPolicy {
            response_bytes: 1024,
            ..DocumentPolicy::default()
        },
        ..DocumentPolicies::default()
    };
    let index = Surface::with_policy(&document, &policies)?;
    let page = index.find(
        "Needle",
        None,
        Budget {
            bytes: 65_536,
            items: 100,
        },
    )?;
    assert!(serde_json::to_vec(&page)?.len() <= 1024);
    assert!(page.next.is_some());
    let view = WebSurface::new(index, SourceId::new("bounded")?)?;
    let page = view.read(&request(ReadOperation::Search {
        query: "Needle".into(),
    }))?;
    assert!(serde_json::to_vec(&page)?.len() <= 1024);
    Ok(())
}

#[cfg(all(feature = "browser", unix))]
#[tokio::test(flavor = "current_thread")]
async fn offline_replay_supports_configured_depth_above_the_old_default() -> TestResult {
    use yosoi::{
        Archive,
        surface::{ArchiveLimits, ArchivedSource, Outcome, archive},
    };
    let html = format!("{}Deep{}", "<div>".repeat(100), "</div>".repeat(100));
    let document = Document::html("deep", html.into_bytes())?;
    let policies = DocumentPolicies {
        html: DocumentPolicy {
            max_depth: 128,
            ..DocumentPolicy::default()
        },
        ..DocumentPolicies::default()
    };
    let surface = Surface::with_policy(&document, &policies)?;
    let source = ArchivedSource::capture("deep", &surface)?;
    let mut outcome = Outcome::new("deep", ArchiveLimits::default())?.with_source(source)?;
    outcome.sealed = true;
    let directory = tempfile::tempdir()?;
    let store = Archive::open(directory.path().join("store")).await?;
    let reference = store.write(&outcome).await?;
    let path = directory.path().join("deep.yosoi");
    store.export_file(&reference, &path).await?;
    let result = archive::replay(&path, 1, None, None).await?;
    assert_eq!(
        result
            .get("last_capture")
            .and_then(serde_json::Value::as_str),
        Some(surface.identity())
    );
    Ok(())
}

#[cfg(all(feature = "browser", unix))]
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires reviewed regular Chrome and a matching ChromeDriver"]
async fn native_browser_ax_network_and_archive_observations() -> TestResult {
    use std::{io, str};
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
    };
    use yosoi::surface::{
        ArchivePolicy, SurfaceConnection, SurfacePolicy, archive as surface_archive,
        browser::{BrowserRepresentation, BrowserSurface},
    };
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/", listener.local_addr()?);
    let server = tokio::spawn(async move {
        loop {
            let (mut stream, _) = listener.accept().await?;
            tokio::spawn(async move {
                let mut buffer = [0_u8; 4096];
                let read = stream.read(&mut buffer).await?;
                let line = str::from_utf8(
                    buffer
                        .get(..read)
                        .ok_or_else(|| io::Error::other("read extent"))?,
                )?;
                let body = if line.starts_with("GET /api/data ") {
                    "{\"ok\":true}"
                } else {
                    "<!doctype html><title>Evidence fixture</title><button onclick=\"document.getElementById('ready').textContent='Clicked'\">Search</button><input aria-label='Search docs'><p id='ready'>Loading</p><script>fetch('/api/data').then(r=>r.json()).then(()=>document.getElementById('ready').textContent='Ready')</script>"
                };
                stream
                    .write_all(
                        format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                            body.len(),
                            body
                        )
                        .as_bytes(),
                    )
                    .await?;
                Ok::<_, Box<dyn Error + Send + Sync>>(())
            });
        }
        #[allow(unreachable_code)]
        Ok::<_, io::Error>(())
    });
    let policy = SurfacePolicy {
        archive: ArchivePolicy::Enabled,
        documents: DocumentPolicies {
            ax: DocumentPolicy {
                max_depth: 12,
                response_bytes: 1024,
                ..DocumentPolicies::default().ax
            },
            network: DocumentPolicy {
                response_bytes: 2048,
                ..DocumentPolicy::default()
            },
            ..DocumentPolicies::default()
        },
        ..SurfacePolicy::default()
    };
    let mut browser = BrowserSurface::open(&url, policy, true).await?;
    let run = async {
        browser.execute(json!({"op":"attach"})).await?;
        browser
            .execute(json!({"op":"wait","text":"Ready","present":true}))
            .await?;
        let ax = browser.observe(BrowserRepresentation::Ax).await?;
        assert!(!ax.observation.coverage.complete);
        let result = browser
            .read(
                BrowserRepresentation::Ax,
                request(ReadOperation::Search {
                    query: "Search".into(),
                }),
            )
            .await?;
        assert!(serde_json::to_vec(&result)?.len() <= 1024);
        let ReadResult::Page(page) = result else {
            return Err("expected AX results".into());
        };
        assert!(!page.entries.is_empty());
        assert!(
            browser
                .execute(json!({"op":"focus_evidence","reference":ax.root}))
                .await
                .is_err()
        );
        let network = browser.observe(BrowserRepresentation::Network).await?;
        assert!(!network.observation.coverage.complete);
        let result = browser
            .read(
                BrowserRepresentation::Network,
                request(ReadOperation::Search {
                    query: "/api/data".into(),
                }),
            )
            .await?;
        assert!(serde_json::to_vec(&result)?.len() <= 2048);
        let ReadResult::Page(page) = result else {
            return Err("expected network results".into());
        };
        assert!(!page.entries.is_empty());
        browser.observe(BrowserRepresentation::Ax).await?;
        assert!(
            browser
                .read(
                    BrowserRepresentation::Ax,
                    request(ReadOperation::Inspect { reference: ax.root })
                )
                .await
                .is_err()
        );
        browser.observe(BrowserRepresentation::Dom).await?;
        let result = browser.read(BrowserRepresentation::Dom,request(ReadOperation::Search {query:"Search".into()})).await?;
        let ReadResult::Page(page) = result else {return Err("expected DOM results".into())};
        // DOM literal search returns the text leaf; follow its producer-issued
        // parent rather than manufacturing a selector or reusing an AX address.
        let text = page.entries.iter().find(|entry|entry.preview=="Search").ok_or("DOM text missing")?;
        let parent = browser.read(BrowserRepresentation::Dom,request(ReadOperation::Parent {reference:text.reference.clone()})).await?;
        let ReadResult::Parent(Some(button)) = parent else {return Err("DOM parent missing".into())};
        let focused = browser.execute(json!({"op":"focus_evidence","reference":button})).await?;
        browser.execute(json!({"op":"hot"})).await?;
        let clicked = browser.execute(json!({"op":"click","reference":focused.pointer("/cursor/position/focus"),"expect":{"kind":"text","text":"Clicked","present":true}})).await?;
        assert_eq!(clicked.pointer("/receipt/status").and_then(serde_json::Value::as_str),Some("Confirmed"));
        let outcome = browser.outcome().ok_or("archive outcome missing")?;
        assert!(outcome.sources.len() >= 3);
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }
    .await;
    let closed = browser.close().await;
    server.abort();
    run?;
    let outcome = closed?.ok_or("closed archive outcome missing")?;
    let directory = tempfile::tempdir()?;
    let archive = yosoi::Archive::open(directory.path().join("store")).await?;
    let reference = archive.write(&outcome).await?;
    let file = directory.path().join("evidence.yosoi");
    archive.export_file(&reference, &file).await?;
    let replayed = surface_archive::replay(&file, 1, None, None).await?;
    assert_eq!(
        replayed
            .get("browser_started")
            .and_then(serde_json::Value::as_bool),
        Some(false)
    );
    assert!(
        replayed
            .get("captures")
            .and_then(serde_json::Value::as_u64)
            .is_some_and(|count| count >= 3)
    );
    Ok(())
}
