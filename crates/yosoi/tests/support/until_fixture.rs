#![allow(dead_code)] // Shared fixture capabilities are used by different test/example consumers.
use std::{
    collections::{HashMap, VecDeque},
    io,
    net::Ipv4Addr,
    sync::atomic::{AtomicBool, Ordering},
    sync::{Arc, Mutex},
};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{mpsc, oneshot, watch},
    task::{JoinHandle, JoinSet},
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestEvent {
    pub method: String,
    pub target: String,
    pub correlation: Option<String>,
}

#[derive(Default)]
struct Shared {
    requests: Mutex<HashMap<String, usize>>,
    gates: Mutex<HashMap<String, watch::Sender<bool>>>,
    events: Mutex<Option<mpsc::UnboundedSender<RequestEvent>>>,
    open_gates: AtomicBool,
}

pub struct UntilFixture {
    base_url: String,
    shutdown: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<io::Result<()>>>,
    events: mpsc::UnboundedReceiver<RequestEvent>,
    pending: VecDeque<RequestEvent>,
    shared: Arc<Shared>,
}

impl UntilFixture {
    pub async fn start() -> io::Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let (events_tx, events) = mpsc::unbounded_channel();
        let shared = Arc::new(Shared::default());
        if let Ok(mut sender) = shared.events.lock() {
            *sender = Some(events_tx);
        }
        let task_shared = Arc::clone(&shared);
        let task = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    biased;
                    _ = &mut shutdown_rx => break,
                    accepted = listener.accept() => {
                        let (stream, _) = accepted?;
                        let shared = Arc::clone(&task_shared);
                        connections.spawn(async move {
                            let _ = serve(stream, shared).await;
                        });
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
            task: Some(task),
            events,
            pending: VecDeque::new(),
            shared,
        })
    }

    pub fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base_url)
    }

    pub async fn wait_for(&mut self, target: &str) -> io::Result<RequestEvent> {
        if let Some(position) = self.pending.iter().position(|event| event.target == target) {
            return self
                .pending
                .remove(position)
                .ok_or_else(|| io::Error::other("request event disappeared"));
        }
        loop {
            let event = self
                .events
                .recv()
                .await
                .ok_or_else(|| io::Error::other("fixture stopped before the request"))?;
            if event.target == target {
                return Ok(event);
            }
            self.pending.push_back(event);
        }
    }

    pub async fn wait_for_correlated(
        &mut self,
        target: &str,
        correlation: &str,
    ) -> io::Result<RequestEvent> {
        if let Some(position) = self.pending.iter().position(|event| {
            event.target == target && event.correlation.as_deref() == Some(correlation)
        }) {
            return self
                .pending
                .remove(position)
                .ok_or_else(|| io::Error::other("correlated request event disappeared"));
        }
        loop {
            let event =
                self.events.recv().await.ok_or_else(|| {
                    io::Error::other("fixture stopped before the correlated request")
                })?;
            if event.target == target && event.correlation.as_deref() == Some(correlation) {
                return Ok(event);
            }
            self.pending.push_back(event);
        }
    }

    #[expect(
        clippy::significant_drop_tightening,
        reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
    )]
    pub fn release(&self, gate: &str) -> io::Result<()> {
        let gates = self
            .shared
            .gates
            .lock()
            .map_err(|_| io::Error::other("fixture gate lock was poisoned"))?;
        let sender = gates
            .get(gate)
            .ok_or_else(|| io::Error::other(format!("unknown or unreached gate {gate}")))?;
        sender.send_replace(true);
        Ok(())
    }

    #[expect(
        clippy::significant_drop_tightening,
        reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
    )]
    pub fn release_all(&self) -> io::Result<()> {
        self.shared.open_gates.store(true, Ordering::Release);
        let gates = self
            .shared
            .gates
            .lock()
            .map_err(|_| io::Error::other("fixture gate lock was poisoned"))?;
        for sender in gates.values() {
            sender.send_replace(true);
        }
        Ok(())
    }

    pub fn request_count(&self, target: &str) -> io::Result<usize> {
        let requests = self
            .shared
            .requests
            .lock()
            .map_err(|_| io::Error::other("fixture request counter lock was poisoned"))?;
        Ok(requests.get(target).copied().unwrap_or(0))
    }

    pub async fn shutdown(mut self) -> io::Result<()> {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        if let Some(task) = self.task.take() {
            task.await
                .map_err(|error| io::Error::other(error.to_string()))??;
        }
        Ok(())
    }
}

impl Drop for UntilFixture {
    fn drop(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
    }
}

async fn serve(mut stream: TcpStream, shared: Arc<Shared>) -> io::Result<()> {
    let mut request = Vec::with_capacity(2_048);
    loop {
        let mut buffer = [0_u8; 1_024];
        let read = stream.read(&mut buffer).await?;
        if read == 0 {
            return Ok(());
        }
        request.extend_from_slice(
            buffer
                .get(..read)
                .ok_or_else(|| io::Error::other("request length exceeded its buffer"))?,
        );
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
        if request.len() >= 8_192 {
            return Err(io::Error::other("request headers exceeded 8 KiB"));
        }
    }

    let request_text = String::from_utf8_lossy(&request);
    let request_line = request_text
        .lines()
        .next()
        .ok_or_else(|| io::Error::other("request had no request line"))?;
    let mut parts = request_line.split_whitespace();
    let method = parts
        .next()
        .ok_or_else(|| io::Error::other("request had no method"))?;
    let target = parts
        .next()
        .ok_or_else(|| io::Error::other("request had no target"))?;
    let route = target.split('?').next().unwrap_or(target);

    let body = match route {
        "/until" => page(),
        "/enter-until" => {
            record(&shared, method, target, None)?;
            enter_page()
        }
        "/replacement" => {
            record(&shared, method, target, None)?;
            if query_value(target, "attempt") == Some("target-scope") {
                "<!doctype html><html><body><p id=\"receipt\">replacement-ready</p><script>fetch('/marker?attempt=target-scope', {cache:'no-store'});</script></body></html>".to_owned()
            } else {
                "<!doctype html><html><body><p id=\"receipt\">replacement-ready</p></body></html>"
                    .to_owned()
            }
        }
        "/trigger" => {
            record(&shared, method, target, None)?;
            "triggered".to_owned()
        }
        "/api" => {
            let query_attempt = query_value(target, "attempt").unwrap_or("missing");
            let attempt = header_value(&request_text, "x-until-attempt").unwrap_or(query_attempt);
            let stage = header_value(&request_text, "x-until-stage").unwrap_or(attempt);
            let gate = format!("api:{stage}");
            let receiver = register_request(&shared, method, target, &gate, Some(stage))?;
            if query_value(target, "fast") != Some("1") {
                wait_gate(receiver).await?;
            }
            format!(
                "{{\"attempt\":\"{}\",\"receipt\":\"receipt:{}\",\"ax_name\":\"Ready {}\"}}",
                json_escape(attempt),
                json_escape(attempt),
                json_escape(attempt)
            )
        }
        "/gate/dom" | "/gate/ax" => {
            let kind = route.trim_start_matches("/gate/");
            let gate = gate_for_query(kind, target)?;
            let receiver = register_request(&shared, method, target, &gate, None)?;
            wait_gate(receiver).await?;
            "released".to_owned()
        }
        "/gate/contract" => {
            let attempt = query_value(target, "attempt")
                .ok_or_else(|| io::Error::other("contract gate is missing its attempt"))?;
            let phase = query_value(target, "phase")
                .ok_or_else(|| io::Error::other("contract gate is missing its phase"))?;
            let gate = format!("contract:{attempt}:{phase}");
            let receiver = register_request(&shared, method, target, &gate, None)?;
            wait_gate(receiver).await?;
            "released".to_owned()
        }
        "/marker" => {
            record(&shared, method, target, None)?;
            "observed".to_owned()
        }
        _ => {
            respond(&mut stream, "404 Not Found", "text/plain", "not found").await?;
            return Ok(());
        }
    };

    respond(
        &mut stream,
        "200 OK",
        if route == "/api" {
            "application/json"
        } else if route == "/until" || route == "/enter-until" || route == "/replacement" {
            "text/html; charset=utf-8"
        } else {
            "text/plain; charset=utf-8"
        },
        &body,
    )
    .await
}

fn register_request(
    shared: &Shared,
    method: &str,
    target: &str,
    gate: &str,
    correlation: Option<&str>,
) -> io::Result<watch::Receiver<bool>> {
    let receiver = {
        let mut gates = shared
            .gates
            .lock()
            .map_err(|_| io::Error::other("fixture gate lock was poisoned"))?;
        gates
            .entry(gate.to_owned())
            .or_insert_with(|| watch::channel(shared.open_gates.load(Ordering::Acquire)).0)
            .subscribe()
    };
    record(shared, method, target, correlation)?;
    Ok(receiver)
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn record(
    shared: &Shared,
    method: &str,
    target: &str,
    correlation: Option<&str>,
) -> io::Result<()> {
    {
        let mut requests = shared
            .requests
            .lock()
            .map_err(|_| io::Error::other("fixture request counter lock was poisoned"))?;
        let count = requests.entry(target.to_owned()).or_insert(0);
        *count = count.saturating_add(1);
    }
    let event = RequestEvent {
        method: method.to_owned(),
        target: target.to_owned(),
        correlation: correlation.map(str::to_owned),
    };
    let sender = shared
        .events
        .lock()
        .map_err(|_| io::Error::other("fixture event lock was poisoned"))?
        .as_ref()
        .cloned()
        .ok_or_else(|| io::Error::other("fixture event channel is closed"))?;
    sender
        .send(event)
        .map_err(|_| io::Error::other("fixture event receiver is closed"))
}

fn header_value<'a>(request: &'a str, name: &str) -> Option<&'a str> {
    request.lines().find_map(|line| {
        let (key, value) = line.split_once(':')?;
        key.eq_ignore_ascii_case(name).then_some(value.trim())
    })
}

fn gate_for_query(kind: &str, target: &str) -> io::Result<String> {
    gate_for_query_field(kind, target, "attempt")
}

fn gate_for_query_field(kind: &str, target: &str, field: &str) -> io::Result<String> {
    let value = query_value(target, field)
        .ok_or_else(|| io::Error::other(format!("gated request is missing {field}")))?;
    Ok(format!("{kind}:{value}"))
}

fn query_value<'a>(target: &'a str, name: &str) -> Option<&'a str> {
    target.split_once('?')?.1.split('&').find_map(|part| {
        let (key, value) = part.split_once('=')?;
        (key == name).then_some(value)
    })
}

async fn wait_gate(mut receiver: watch::Receiver<bool>) -> io::Result<()> {
    loop {
        if *receiver.borrow_and_update() {
            return Ok(());
        }
        receiver
            .changed()
            .await
            .map_err(|_| io::Error::other("fixture gate closed before release"))?;
    }
}

async fn respond(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &str,
) -> io::Result<()> {
    let headers = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(headers.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.shutdown().await
}

fn json_escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn page() -> String {
    r#"<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Until acceptance fixture</title></head>
<body>
  <main>
    <button id="trigger" type="button">Run attempt</button>
    <output id="click-count">0</output>
    <p id="stale">stale:none</p>
    <p id="receipt" hidden>receipt:none</p>
    <button id="ax-status" type="button" aria-label="Waiting">Waiting</button>
    <output id="noise"></output>
    <section id="contract">
      <output id="contract-receipt">receipt:none</output>
      <output id="contract-status">idle</output>
      <output id="contract-price">not-money</output>
    </section>
  </main>
  <script>
    const params = new URLSearchParams(location.search);
    const attempt = params.get('attempt') || 'current';
    const stale = params.get('stale') === '1';
    const staged = params.get('stages') === '1';
    const contractSequence = params.get('contract') === '1';
    const noRecord = params.get('no-record') === '1';
    const pretrigger = params.get('pretrigger') === '1';
    const fast = params.get('fast') === '1';
    const targetResolutionGate = params.get('target-resolution-gate') === '1';
    const noiseCount = Number(params.get('noise') || '0');
    let clicks = 0;
    const fetchNoStore = (url, headers = {}) => fetch(url, { cache: 'no-store', headers });
    if (targetResolutionGate) {
      const originalQuerySelectorAll = document.querySelectorAll.bind(document);
      document.querySelectorAll = (selector) => {
        if (selector === '#trigger') {
          return Object.defineProperty({}, 'length', {
            get() {
              return fetchNoStore(`/gate/contract?attempt=${attempt}&phase=target-resolution`)
                .then(() => {
                  location.assign(`/replacement?attempt=${attempt}`);
                  return new Promise(() => {});
                });
            },
          });
        }
        return originalQuerySelectorAll(selector);
      };
    }
    if (noRecord) document.querySelector('#contract').remove();

    async function runAttempt(fromClick) {
      if (fromClick) {
        clicks += 1;
        document.querySelector('#click-count').textContent = String(clicks);
        await fetchNoStore(`/trigger?attempt=${attempt}`);
      }
      if (stale) {
        const oldResponse = await fetchNoStore(`/api?attempt=${attempt}`, {
          'X-Until-Attempt': 'old',
        });
        const oldPayload = await oldResponse.json();
        document.querySelector('#stale').textContent = `stale:${oldPayload.attempt}`;
      }
      const responseHeaders = { 'X-Until-Attempt': attempt };
      if (pretrigger && fromClick) {
        responseHeaders['X-Until-Attempt'] = 'current';
        responseHeaders['X-Until-Stage'] = 'trigger';
      }
      const response = await fetchNoStore(
        `/api?attempt=${attempt}${fast ? '&fast=1' : ''}`,
        responseHeaders,
      );
      const payload = await response.json();
      if (params.get('navigate') === '1') {
        location.assign('/replacement');
        return;
      }
      if (contractSequence) {
        await fetchNoStore(`/gate/contract?attempt=${attempt}&phase=first`);
        const contractReceipt = document.querySelector('#contract-receipt');
        const contractStatus = document.querySelector('#contract-status');
        if (contractReceipt) contractReceipt.textContent = payload.receipt;
        await fetchNoStore(`/gate/contract?attempt=${attempt}&phase=second`);
        if (contractReceipt) contractReceipt.textContent = 'receipt:old';
        if (contractStatus) contractStatus.textContent = 'ready';
        await fetchNoStore(`/gate/contract?attempt=${attempt}&phase=final`);
        if (contractReceipt) contractReceipt.textContent = payload.receipt;
        if (contractStatus) contractStatus.textContent = 'ready';
      } else if (staged) {
        await fetchNoStore(`/gate/dom?attempt=${attempt}`);
      }
      const noise = document.querySelector('#noise');
      for (let index = 0; index < noiseCount; index += 1) {
        noise.textContent = `background:${index}`;
      }
      document.querySelector('#receipt').textContent = payload.receipt;
      document.querySelector('#receipt').hidden = false;
      const contractReceipt = document.querySelector('#contract-receipt');
      const contractStatus = document.querySelector('#contract-status');
      if (!contractSequence && contractReceipt && contractStatus) {
        contractReceipt.textContent = payload.receipt;
        contractStatus.textContent = 'ready';
      }
      if (staged) await fetchNoStore(`/gate/ax?attempt=${attempt}`);
      const axStatus = document.querySelector('#ax-status');
      axStatus.setAttribute('aria-label', payload.ax_name);
      axStatus.textContent = payload.ax_name;
    }

    document.querySelector('#trigger').addEventListener('click', async () => {
      await runAttempt(true);
    });
    if (params.get('auto') === '1') void runAttempt(false);
    if (pretrigger) {
      void fetchNoStore(`/api?attempt=${attempt}`, {
        'X-Until-Attempt': 'current',
        'X-Until-Stage': 'pretrigger',
      }).then(() => fetchNoStore(`/marker?attempt=${attempt}`));
    }
  </script>
</body>
</html>"#
        .to_owned()
}

fn enter_page() -> String {
    r#"<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Until text-entry fixture</title></head>
<body>
  <label for="entry">Product reference</label>
  <input id="entry" type="text" autocomplete="off">
  <p id="confirmation" data-value="" hidden>Waiting for input</p>
  <div id="entry-status" role="status" aria-label="Waiting">Waiting</div>
  <script>
    const params = new URLSearchParams(location.search);
    const attempt = params.get('attempt') || 'typed';
    const expectedValue = params.get('expected');
    const replaceOnFocus = params.get('replace-on-focus') === '1';
    const entry = document.querySelector('#entry');
    const replaceWithTrap = () => {
      if (!entry.isConnected) return;
      const trap = document.createElement('input');
      trap.id = 'trap';
      trap.type = 'text';
      entry.replaceWith(trap);
      trap.focus();
    };
    if (replaceOnFocus) {
      entry.addEventListener('focus', replaceWithTrap, { once: true });
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') replaceWithTrap();
      });
    }
    entry.addEventListener('input', async () => {
      const value = entry.value;
      if (value === expectedValue) {
        await fetch(`/gate/contract?attempt=${attempt}&phase=input`, { cache: 'no-store' });
      }
      entry.setAttribute('data-value', value);
      const confirmation = document.querySelector('#confirmation');
      confirmation.setAttribute('data-value', value);
      confirmation.textContent = `Received ${value}`;
      confirmation.hidden = false;
      const status = document.querySelector('#entry-status');
      status.setAttribute('aria-label', `Entered ${value}`);
      status.textContent = `Entered ${value}`;
    });
  </script>
</body>
</html>"#
        .to_owned()
}
