//! Public Request and Session routing regressions against controlled local hosts.
#![allow(
    clippy::panic_in_result_fn,
    reason = "fixture assertions report networking regressions"
)]

use std::{
    error::Error,
    io,
    net::{IpAddr, SocketAddr},
    time::Duration,
};

#[cfg(feature = "browser")]
use async_tungstenite::tungstenite::handshake::derive_accept_key;
#[cfg(feature = "browser")]
use std::net::Ipv6Addr;
use tokio::time::timeout;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::JoinHandle,
};
#[cfg(feature = "browser")]
use yosoi::{
    flow,
    policy::{Acquisition, BrowserMode},
    session,
};
use yosoi::{
    policy::{
        DirectHttpRedirectTargets, DirectHttpRedirects, IpFamily, Network, Policy, RedirectHopLimit,
    },
    request::{self, AttemptState, CancellationToken, ResponseTermination},
};

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

#[test]
fn stacked_network_and_engine_declarations_keep_distinct_roundtrip_identities() -> TestResult {
    use yosoi::browser::{BrowserConfig, BrowserEngine};
    let default = Policy::default();
    let routed = Policy {
        network: Network {
            ip_family: IpFamily::Ipv4Only,
            ..Network::default()
        },
        ..default.clone()
    };
    let optional = Policy {
        browser: BrowserConfig {
            engine: BrowserEngine::Firefox,
            ..BrowserConfig::default()
        },
        ..default.clone()
    };
    let combined = Policy {
        network: routed.network.clone(),
        ..optional.clone()
    };
    let cases = [default, routed, optional, combined];
    for (index, policy) in cases.iter().enumerate() {
        let restored: Policy = serde_json::from_str(&serde_json::to_string(policy)?)?;
        assert_eq!(policy.effective_identity()?, restored.effective_identity()?);
        for other in cases.iter().skip(index.saturating_add(1)) {
            assert_ne!(policy.effective_identity()?, other.effective_identity()?);
        }
    }
    Ok(())
}

#[cfg(feature = "browser-bidi")]
#[tokio::test]
async fn stacked_optional_engine_rejects_custom_network_before_launch() -> TestResult {
    use yosoi::browser::{BrowserConfig, BrowserEngine};
    for engine in [BrowserEngine::Firefox, BrowserEngine::Moli] {
        let policy = Policy {
            browser: BrowserConfig {
                engine,
                ..BrowserConfig::default()
            },
            network: Network {
                ip_family: IpFamily::Ipv4Only,
                ..Network::default()
            },
            ..Policy::default()
        };
        let result = session::new().bind(&policy).acquire().await;
        assert!(matches!(
            result,
            Err(session::SessionError::Unsupported(
                "custom network routing is supported only by Chrome sessions"
            ))
        ));
        drop(result);
    }
    Ok(())
}

async fn fixture(
    bind: &str,
    response: Vec<u8>,
) -> io::Result<(SocketAddr, JoinHandle<io::Result<(SocketAddr, String)>>)> {
    let listener = TcpListener::bind(bind).await?;
    let address = listener.local_addr()?;
    let task = tokio::spawn(async move {
        let (mut stream, peer) = listener.accept().await?;
        let head = read_head(&mut stream).await?;
        stream.write_all(&response).await?;
        Ok((peer, head))
    });
    Ok((address, task))
}

fn html() -> Vec<u8> {
    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 15\r\nConnection: close\r\n\r\n<h1>route</h1>\n".to_vec()
}

async fn read_head(stream: &mut TcpStream) -> io::Result<String> {
    let mut head = Vec::new();
    while !head.ends_with(b"\r\n\r\n") {
        if head.len() >= 32 * 1024 {
            return Err(io::Error::other("fixture header too large"));
        }
        head.push(stream.read_u8().await?);
    }
    String::from_utf8(head).map_err(io::Error::other)
}

#[tokio::test]
async fn network_request_family_and_source_reach_the_wire() -> TestResult {
    for (bind, family, source) in [
        ("127.0.0.1:0", IpFamily::Ipv4Only, "127.0.0.1"),
        ("[::1]:0", IpFamily::Ipv6Only, "::1"),
    ] {
        let (address, server) = fixture(bind, html()).await?;
        let policy = Policy {
            network: Network {
                ip_family: family,
                source_address: Some(source.parse()?),
                proxy: None,
            },
            ..Policy::default()
        };
        let response = request::new(format!("http://{address}/route?example=1"))
            .bind(&policy)
            .send()
            .await?;
        let attempt = response.attempts().next().ok_or("missing attempt")?;
        assert_eq!(attempt.state(), AttemptState::Completed);
        assert_eq!(attempt.body_bytes(), Some(b"<h1>route</h1>\n".as_slice()));
        assert_eq!(response.policy_snapshot().policy().network, policy.network);
        let (peer, head) = server.await??;
        assert_eq!(peer.ip(), source.parse::<IpAddr>()?);
        assert!(head.starts_with("GET /route?example=1 HTTP/1.1"));
    }
    Ok(())
}

#[tokio::test]
async fn network_redirect_cannot_escape_the_selected_family() -> TestResult {
    let forbidden = TcpListener::bind("[::1]:0").await?;
    let response = format!(
        "HTTP/1.1 302 Found\r\nLocation: http://{}/blocked\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        forbidden.local_addr()?
    );
    let (address, server) = fixture("127.0.0.1:0", response.into_bytes()).await?;
    let mut policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv4Only,
            ..Network::default()
        },
        ..Policy::default()
    };
    policy.request.direct_http_redirects = DirectHttpRedirects::Follow {
        max_hops: RedirectHopLimit::try_from(2_u32)?,
        targets: DirectHttpRedirectTargets::AllowHttpAndHttps,
    };
    let response = request::new(format!("http://{address}/redirect"))
        .bind(&policy)
        .send()
        .await?;
    assert!(matches!(
        response.attempts().next().ok_or("missing attempt")?.state(),
        AttemptState::Failed(_)
    ));
    server.await??;
    assert!(
        timeout(Duration::from_millis(50), forbidden.accept())
            .await
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn network_request_routes_unresolvable_origin_through_authenticated_proxy() -> TestResult {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let proxy = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let connect = read_head(&mut stream).await?;
        assert!(connect.starts_with("CONNECT no-dns.invalid:80 HTTP/1.1"));
        assert!(connect.contains("Proxy-Authorization: Basic dXNlcjpwYXNz"));
        stream.write_all(b"HTTP/1.1 200 OK\r\n\r\n").await?;
        let origin = read_head(&mut stream).await?;
        assert!(origin.starts_with("GET /route HTTP/1.1"));
        assert!(!origin.to_lowercase().contains("proxy-authorization"));
        stream.write_all(&html()).await?;
        Ok::<_, io::Error>(())
    });
    let policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv4Only,
            proxy: Some(format!("http://user:pass@{proxy}")),
            ..Network::default()
        },
        ..Policy::default()
    };
    let response = request::new("http://no-dns.invalid/route")
        .bind(&policy)
        .send()
        .await?;
    assert_eq!(
        response
            .attempts()
            .next()
            .ok_or("missing attempt")?
            .body_bytes(),
        Some(b"<h1>route</h1>\n".as_slice())
    );
    server.await??;
    Ok(())
}

#[tokio::test]
async fn network_proxy_rejection_never_falls_back_to_direct() -> TestResult {
    let origin = TcpListener::bind("127.0.0.1:0").await?;
    let proxy = TcpListener::bind("127.0.0.1:0").await?;
    let proxy_address = proxy.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut stream, _) = proxy.accept().await?;
        let _head = read_head(&mut stream).await?;
        stream.write_all(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await?;
        Ok::<_, io::Error>(())
    });
    let policy = Policy {
        network: Network {
            proxy: Some(format!("http://{proxy_address}")),
            ..Network::default()
        },
        ..Policy::default()
    };
    let response = request::new(format!("http://{}/", origin.local_addr()?))
        .bind(&policy)
        .send()
        .await?;
    assert!(matches!(
        response.attempts().next().ok_or("missing attempt")?.state(),
        AttemptState::Failed(_)
    ));
    server.await??;
    assert!(
        timeout(Duration::from_millis(50), origin.accept())
            .await
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn network_cancellation_closes_a_pending_upstream_handshake() -> TestResult {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let policy = Policy {
        network: Network {
            proxy: Some(format!("http://{address}")),
            ..Network::default()
        },
        ..Policy::default()
    };
    let cancellation = CancellationToken::new();
    let cancel_request = cancellation.clone();
    let sending = tokio::spawn(async move {
        request::new("https://no-dns.invalid/")
            .bind(&policy)
            .send_cancellable(&cancel_request)
            .await
    });
    let (mut upstream, _) = timeout(Duration::from_secs(5), listener.accept()).await??;
    let _head = read_head(&mut upstream).await?;
    cancellation.cancel();
    let response = timeout(Duration::from_secs(2), sending).await???;
    assert_eq!(response.termination(), ResponseTermination::Cancelled);
    let mut byte = [0];
    let read = timeout(Duration::from_secs(2), upstream.read(&mut byte)).await?;
    assert!(matches!(read, Ok(0) | Err(_)));
    Ok(())
}

#[cfg(feature = "browser")]
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Work is consumed by async release; the nursery tracks its Drop fields beyond that move"
)]
async fn network_session_uses_bound_route_and_rejects_rebinding() -> TestResult {
    let (address, server) = fixture("[::1]:0", html()).await?;
    let mut policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv6Only,
            source_address: Some("::1".parse()?),
            proxy: None,
        },
        ..Policy::default()
    };
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
    let session = session::new().bind(&policy).acquire().await?;
    let response = request::new(format!("http://{address}/route"))
        .in_session(&session)
        .send()
        .await;
    let mut changed = policy.clone();
    changed.network.ip_family = IpFamily::Ipv4Only;
    changed.network.source_address = None;
    let rejected = request::new("http://127.0.0.1/")
        .in_session(&session)
        .bind(&changed)
        .send()
        .await;
    let work = session.work().await?;
    let rerouted_flow = flow::new([])
        .bind(&changed)
        .with_lease(&work)
        .invoke()
        .await;
    work.release().await?;
    assert!(rerouted_flow.is_err());
    session.close().await?;
    drop(session);
    let response = response?;
    assert_eq!(
        response
            .attempts()
            .next()
            .ok_or("missing browser attempt")?
            .state(),
        AttemptState::Completed
    );
    let outcome = response
        .attempts()
        .next()
        .ok_or("missing browser attempt")?
        .documents()
        .next()
        .ok_or("missing browser DOM")?
        .outcome();
    let request::DocumentOutcome::Produced(document) = outcome else {
        return Err("browser DOM was not produced".into());
    };
    let tree: serde_json::Value = serde_json::from_slice(document.bytes())?;
    let nodes = tree
        .get("nodes")
        .and_then(serde_json::Value::as_array)
        .ok_or("missing DOM nodes")?;
    assert!(
        nodes
            .iter()
            .any(
                |node| node.get("kind").and_then(serde_json::Value::as_str) == Some("text")
                    && node.get("value").and_then(serde_json::Value::as_str) == Some("route")
            )
    );
    assert!(rejected.is_err());
    let (peer, _) = server.await??;
    assert_eq!(peer.ip(), "::1".parse::<IpAddr>()?);
    Ok(())
}

#[cfg(feature = "browser")]
#[tokio::test(flavor = "current_thread")]
async fn network_session_reaches_an_unresolvable_origin_only_through_its_proxy() -> TestResult {
    use tokio::{sync::mpsc, task::JoinSet};

    let listener = TcpListener::bind("[::1]:0").await?;
    let address = listener.local_addr()?;
    let (observed, mut observations) = mpsc::channel(8);
    let stop = CancellationToken::new();
    let stopped = stop.clone();
    let server = tokio::spawn(async move {
        let mut children = JoinSet::new();
        loop {
            tokio::select! {
                biased;
                () = stopped.cancelled() => break,
                _ = children.join_next(), if !children.is_empty() => {},
                accepted = listener.accept() => {
                    let (mut stream, peer) = accepted?;
                    let observed = observed.clone();
                    children.spawn(async move {
                        let head = read_head(&mut stream).await?;
                        if !head.starts_with("CONNECT proxy-origin.invalid:8123 HTTP/1.1") {
                            stream.write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n").await?;
                            return Ok::<_, io::Error>(());
                        }
                        assert!(head.contains("Proxy-Authorization: Basic dXNlcjpwYXNz"));
                        stream.write_all(b"HTTP/1.1 200 OK\r\n\r\n").await?;
                        let request = read_head(&mut stream).await?;
                        assert!(!request.to_lowercase().contains("proxy-authorization"));
                        if request.starts_with("GET /route HTTP/1.1") { let _ = observed.send(peer).await; }
                        stream.write_all(&html()).await?;
                        Ok(())
                    });
                }
            }
        }
        children.abort_all();
        while children.join_next().await.is_some() {}
        Ok::<_, io::Error>(())
    });
    let mut policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv6Only,
            source_address: Some("::1".parse()?),
            proxy: Some(format!("http://user:pass@{address}")),
        },
        ..Policy::default()
    };
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
    let session = session::new().bind(&policy).acquire().await?;
    let response = request::new("http://proxy-origin.invalid:8123/route")
        .in_session(&session)
        .send()
        .await;
    session.close().await?;
    drop(session);
    stop.cancel();
    server.await??;
    let response = response?;
    let document = response
        .attempts()
        .next()
        .ok_or("missing browser attempt")?
        .documents()
        .next()
        .ok_or("missing browser DOM")?
        .outcome();
    let request::DocumentOutcome::Produced(document) = document else {
        return Err("proxy did not produce a browser DOM".into());
    };
    let tree: serde_json::Value = serde_json::from_slice(document.bytes())?;
    assert!(
        tree.get("nodes")
            .and_then(serde_json::Value::as_array)
            .ok_or("missing DOM nodes")?
            .iter()
            .any(|node| node.get("value").and_then(serde_json::Value::as_str) == Some("route"))
    );
    assert_eq!(
        observations
            .recv()
            .await
            .ok_or("proxy never received the origin request")?
            .ip(),
        Ipv6Addr::LOCALHOST
    );
    Ok(())
}

#[cfg(feature = "browser")]
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Work is consumed by async release; the nursery tracks its Drop fields beyond that move"
)]
async fn network_session_routes_frames_workers_websockets_and_service_workers() -> TestResult {
    use std::sync::{Arc, Mutex};
    use tokio::task::JoinSet;
    use tokio_util::sync::CancellationToken;

    let forbidden = TcpListener::bind("127.0.0.1:0").await?;
    let forbidden_url = format!("http://{}/blocked", forbidden.local_addr()?);
    let listener = TcpListener::bind("[::1]:0").await?;
    let address = listener.local_addr()?;
    let observed = Arc::new(Mutex::new(Vec::<(String, SocketAddr)>::new()));
    let requests = Arc::clone(&observed);
    let stop = CancellationToken::new();
    let stopped = stop.clone();
    let server = tokio::spawn(async move {
        let mut children = JoinSet::new();
        loop {
            tokio::select! {
                biased;
                () = stopped.cancelled() => break,
                _ = children.join_next(), if !children.is_empty() => {},
                accepted = listener.accept() => {
                    let (mut stream, peer) = accepted?;
                    let requests = Arc::clone(&requests);
                    let forbidden_url = forbidden_url.clone();
                    children.spawn(async move {
                        let Ok(head) = read_head(&mut stream).await else { return Ok::<_, io::Error>(()); };
                        let path = head.split_whitespace().nth(1).ok_or_else(|| io::Error::other("missing path"))?;
                        requests.lock().map_err(|_| io::Error::other("fixture lock poisoned"))?.push((path.to_owned(), peer));
                        if path == "/ws" {
                            let key = head.lines().find_map(|line| {
                                let (name, value) = line.split_once(':')?;
                                name.eq_ignore_ascii_case("sec-websocket-key").then_some(value.trim())
                            }).ok_or_else(|| io::Error::other("missing WebSocket key"))?;
                            let accept = derive_accept_key(key.as_bytes());
                            stream.write_all(format!("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").as_bytes()).await?;
                            stream.write_all(b"\x81\x05hello").await?;
                            return Ok(());
                        }
                        if path == "/redirect" {
                            stream.write_all(format!("HTTP/1.1 302 Found\r\nLocation: {forbidden_url}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await?;
                            return Ok(());
                        }
                        let (kind, body) = match path {
                            "/worker.js" => ("application/javascript", "fetch('/worker').then(r=>r.text()).then(value=>postMessage(value));"),
                            "/sw.js" => ("application/javascript", "self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('message',e=>e.waitUntil(fetch('/service-worker').then(r=>r.text()).then(value=>e.source.postMessage(value))));"),
                            "/fetch" => ("text/plain", "fetch"),
                            "/worker" => ("text/plain", "worker"),
                            "/service-worker" => ("text/plain", "service-worker"),
                            _ => ("text/html", "<h1>route</h1>"),
                        };
                        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await?;
                        Ok(())
                    });
                }
            }
        }
        children.abort_all();
        while children.join_next().await.is_some() {}
        Ok::<_, io::Error>(())
    });
    let mut policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv6Only,
            source_address: Some("::1".parse()?),
            proxy: None,
        },
        ..Policy::default()
    };
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
    let session = session::new()
        .bind(&policy)
        .allow_javascript()
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&format!("http://{address}/")).await?;
    let result = work.evaluate(r#"(async () => {
        const fetched = fetch('/fetch').then(r=>r.text());
        const worker = new Promise((resolve,reject)=>{const worker=new Worker('/worker.js');worker.onmessage=e=>{resolve(e.data);worker.terminate()};worker.onerror=reject});
        const websocket = new Promise((resolve,reject)=>{const socket=new WebSocket(location.href.replace('http:','ws:')+'ws');socket.onmessage=e=>{resolve(e.data);socket.close()};socket.onerror=reject});
        const serviceWorker = new Promise(async (resolve,reject)=>{try{navigator.serviceWorker.addEventListener('message',e=>resolve(e.data),{once:true});await navigator.serviceWorker.register('/sw.js');const registration=await navigator.serviceWorker.ready;registration.active.postMessage('fetch')}catch(error){reject(error)}});
        const frame = new Promise(resolve=>{const frame=document.createElement('iframe');frame.onload=()=>resolve('frame');frame.src='/frame';document.body.append(frame)});
        const blocked = fetch('/redirect',{mode:'no-cors'}).then(()=> 'unexpected').catch(()=> 'blocked');
        return await Promise.all([fetched,worker,websocket,serviceWorker,frame,blocked]);
    })()"#).await;
    work.release().await?;
    session.close().await?;
    drop(session);
    stop.cancel();
    server.await??;
    let receipt = result?;
    let seen = observed
        .lock()
        .map_err(|_| io::Error::other("fixture lock poisoned"))?
        .clone();
    assert_eq!(
        receipt.result,
        Some(serde_json::json!([
            "fetch",
            "worker",
            "hello",
            "service-worker",
            "frame",
            "blocked"
        ])),
        "status={:?} error={:?} observed={seen:?}",
        receipt.status,
        receipt.error
    );
    {
        let observed = observed
            .lock()
            .map_err(|_| io::Error::other("fixture lock poisoned"))?;
        for required in [
            "/fetch",
            "/worker.js",
            "/worker",
            "/sw.js",
            "/service-worker",
            "/ws",
            "/frame",
            "/redirect",
        ] {
            assert!(
                observed.iter().any(|(path, _)| path == required),
                "missing {required}: {observed:?}"
            );
        }
        assert!(
            observed
                .iter()
                .all(|(_, peer)| peer.ip() == Ipv6Addr::LOCALHOST)
        );
    }
    assert!(
        timeout(Duration::from_millis(50), forbidden.accept())
            .await
            .is_err()
    );
    Ok(())
}
