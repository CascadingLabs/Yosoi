//! Surface evidence and native Session/Work actions for the display-recording spike.
//! No ChromeDriver, external browser launch or direct CDP client is used here.
use serde_json::{Value, json};
use std::{env, error::Error, fs, io, io::Write, path::PathBuf, result::Result as StdResult};
use tokio::io::{AsyncBufReadExt, BufReader, stdin};
use yosoi::{
    automation_record::{OperationReceipt, OperationStatus},
    documents::{Document, DocumentEpoch},
    policy::{Acquisition, BrowserMode, Policy},
    session::{self, Work},
    surface::{self, ActionStatus, Budget, Reference, Surface},
};

type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;
// Snapshot of the Surface evidence adapter used by this self-contained spike.
const EVIDENCE: &str = include_str!("live_recording_evidence.js");
const MAX_CAPTURE: u64 = 16 * 1024 * 1024;

struct Driver {
    work: Option<Work>,
    evidence: Option<surface::Session>,
    epoch: u64,
    output: PathBuf,
    receipts: fs::File,
}

impl Driver {
    fn work(&self) -> Result<&Work> {
        self.work
            .as_ref()
            .ok_or_else(|| io::Error::other("native Work is released").into())
    }

    fn retained(&mut self, receipt: OperationReceipt) -> Result<Value> {
        serde_json::to_writer(&mut self.receipts, &receipt)?;
        self.receipts.write_all(b"\n")?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other(format!(
                "native {} returned {:?}: {:?}",
                receipt.kind, receipt.status, receipt.error
            ))
            .into());
        }
        Ok(receipt.result.unwrap_or(Value::Null))
    }

    async fn eval(&mut self, source: &str) -> Result<Value> {
        let receipt = self.work()?.evaluate(source).await?;
        self.retained(receipt)
    }

    async fn script(&mut self, operation: &str, input: Value) -> Result<Value> {
        self.eval(&format!(
            "(function(){{{EVIDENCE}}}).apply(null,{})",
            json!([operation, input])
        ))
        .await
    }

    async fn capture(&mut self) -> Result<Value> {
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(|| io::Error::other("epoch exhausted"))?;
        let source = format!(
            r#"(()=>{{
          const capture=(function(){{{EVIDENCE}}}).apply(null,["capture",{{epoch:{}}}]);
          const wire=JSON.stringify(capture.wire);
          if(new TextEncoder().encode(wire).byteLength>{MAX_CAPTURE}) throw Error('capture too large');
          window.__ysRecordingWire=Array.from(wire);
          return {{characters:window.__ysRecordingWire.length,url:capture.url,
            normalized_strings:capture.normalized_strings}};
        }})()"#,
            self.epoch
        );
        let metadata = self.eval(&source).await?;
        let length = metadata
            .get("characters")
            .and_then(Value::as_u64)
            .filter(|length| *length <= MAX_CAPTURE)
            .ok_or_else(|| io::Error::other("invalid snapshot size"))?;
        let mut wire = String::new();
        for offset in (0..length).step_by(131_072) {
            let chunk = self
                .eval(&format!(
                    "window.__ysRecordingWire.slice({offset},{}).join('')",
                    offset.saturating_add(131_072)
                ))
                .await?;
            wire.push_str(
                chunk
                    .as_str()
                    .ok_or_else(|| io::Error::other("missing snapshot chunk"))?,
            );
        }
        let document = Document::rendered_dom(
            format!("native-recording-{}", self.epoch),
            DocumentEpoch::try_from(self.epoch)?,
            wire.as_bytes().to_vec(),
        )?;
        fs::write(
            self.output.join(format!("capture-{}.json", self.epoch)),
            wire,
        )?;
        let index = Surface::with_limits(
            &document,
            surface::Limits {
                input_bytes: 16 * 1024 * 1024,
                ..surface::Limits::default()
            },
        )?;
        if let Some(evidence) = &self.evidence {
            evidence.publish(index)?;
        } else {
            let evidence = surface::Session::new(index, surface::SessionPolicy::default())?;
            self.evidence = Some(evidence);
        }
        Ok(
            json!({"root":self.index()?.root(),"capture":self.index()?.identity(),
            "nodes":self.index()?.node_count(),"metadata":metadata}),
        )
    }

    fn index(&self) -> Result<Surface> {
        self.evidence
            .as_ref()
            .ok_or_else(|| io::Error::other("no capture"))?
            .current()
            .map_err(Into::into)
    }

    fn reference(request: &Value) -> Result<Reference> {
        Ok(serde_json::from_value(
            request
                .get("reference")
                .cloned()
                .ok_or_else(|| io::Error::other("reference required"))?,
        )?)
    }

    async fn eligibility(&mut self, reference: &Reference) -> Result<Value> {
        let coordinate = self.index()?.coordinate(reference)?;
        if coordinate.kind != "dom_node" {
            return Err(io::Error::other("DOM target required").into());
        }
        let id: u64 = coordinate.value.parse()?;
        let evidence = self.script("eligibility", json!({"id":id})).await?;
        // Current native Work clicks take a unique selector. Derive a transient
        // structural binding from the exact captured object, never a site locator.
        let selector = self
            .eval(&format!(
                r#"(()=>{{
          const node=window.__ysArticle?.nodes.get({id});
          if(!node || !node.isConnected) return null;
          const path=[];
          for(let part=node;part;part=part.parentElement){{
            const siblings=part.parentElement ? Array.from(part.parentElement.children) : [part];
            path.unshift(CSS.escape(part.localName)+':nth-child('+(siblings.indexOf(part)+1)+')');
          }}
          let selector=path.join('>');
          const href=node.getAttribute('href');
          if(node.localName==='a' && href!==null) selector+='[href='+JSON.stringify(href)+']';
          const matches=document.querySelectorAll(selector);
          return matches.length===1 && matches[0]===node ? selector : null;
        }})()"#
            ))
            .await?;
        Ok(json!({"native":evidence,"selector":selector}))
    }

    async fn command(&mut self, request: &Value) -> Result<Value> {
        let operation = request.get("op").and_then(Value::as_str).unwrap_or("");
        let budget = Budget::default();
        match operation {
            "attach" => {
                self.evidence
                    .as_ref()
                    .ok_or_else(|| io::Error::other("no capture"))?
                    .attach()?;
                Ok(json!({"attached":true}))
            }
            "status" => Ok(
                json!({"controller":"Yosoi Session/Work → Chromiumoxide/CDP",
                "root":self.index()?.root(),"nodes":self.index()?.node_count()}),
            ),
            "overview" => Ok(serde_json::to_value(self.index()?.overview(None, budget)?)?),
            "find" => Ok(serde_json::to_value(self.index()?.find(
                request.get("query").and_then(Value::as_str).unwrap_or(""),
                None,
                budget,
            )?)?),
            "inspect" => Ok(serde_json::to_value(self.index()?.inspect(
                &Self::reference(request)?,
                None,
                budget,
            )?)?),
            "parent" => Ok(serde_json::to_value(
                self.index()?.parent(&Self::reference(request)?)?,
            )?),
            "refresh" => self.capture().await,
            "eligibility" => self.eligibility(&Self::reference(request)?).await,
            "article" => self.script("article", json!({})).await,
            "screenshot" => {
                let receipt = self.work()?.screenshot().await?;
                if let Some(bytes) = receipt
                    .observation
                    .as_ref()
                    .and_then(|o| o.screenshot.as_ref())
                {
                    fs::write(self.output.join("surface.png"), bytes)?;
                }
                self.retained(receipt)?;
                Ok(json!({"path":self.output.join("surface.png")}))
            }
            "scroll" => {
                self.index()?.validate(&Self::reference(request)?)?;
                let delta = request
                    .get("delta_y")
                    .and_then(Value::as_i64)
                    .filter(|d| (-10000..=10000).contains(d))
                    .ok_or_else(|| io::Error::other("invalid scroll delta"))?;
                // The public native Work API has no wheel action yet. This is
                // explicitly a policy-approved script scroll, not trusted input.
                let observed=self.eval(&format!("new Promise(resolve=>{{const before=scrollY;scrollBy(0,{delta});requestAnimationFrame(()=>resolve({{before,after:scrollY,url:location.href}}))}})")).await?;
                Ok(
                    json!({"scroll":"Yosoi Work.evaluate, programmatic", "observed":observed,"observation":self.capture().await?}),
                )
            }
            "click" => {
                let reference = Self::reference(request)?;
                let cursor = self
                    .evidence
                    .as_ref()
                    .ok_or_else(|| io::Error::other("no capture"))?
                    .cursor()?;
                cursor.focus(&reference)?;
                cursor.promote()?;
                let mut lease = cursor.begin_action()?;
                let guard = self.eligibility(&reference).await?;
                let native = guard
                    .get("native")
                    .ok_or_else(|| io::Error::other("missing guard"))?;
                if native.get("eligible") != Some(&Value::Bool(true))
                    || native.get("unchanged") != Some(&Value::Bool(true))
                {
                    let receipt = lease.finish(
                        ActionStatus::Rejected,
                        "captured target is stale or ineligible",
                    )?;
                    return Ok(json!({"receipt":receipt,"guard":guard}));
                }
                let selector = guard
                    .get("selector")
                    .and_then(Value::as_str)
                    .ok_or_else(|| io::Error::other("native binding missing"))?;
                let expected = native
                    .get("href")
                    .and_then(Value::as_str)
                    .ok_or_else(|| io::Error::other("link required"))?;
                lease.revalidate()?;
                lease.mark_dispatched()?;
                let dispatched = self.work()?.click(selector).await;
                let native_receipt = match dispatched {
                    Ok(receipt) => receipt,
                    Err(error) => {
                        let _ = lease.finish(ActionStatus::Unconfirmed, error.to_string());
                        return Err(error.into());
                    }
                };
                let observed = self.retained(native_receipt.clone());
                if let Err(error) = observed {
                    let _ = lease.finish(ActionStatus::Unconfirmed, error.to_string());
                    return Err(error);
                }
                let provenance = json!({"id":native_receipt.id,"status":native_receipt.status,
                    "browser":native_receipt.browser,"observation":native_receipt.observation.as_ref().map(|o|
                        json!({"session_id":o.session_id,"tab_id":o.tab_id,"document_epoch":o.document_epoch,"url":o.url}))});
                let after=self.eval(&format!(r#"new Promise((resolve,reject)=>{{
                  const expected=new URL({});let timer;
                  const check=()=>{{const actual=new URL(location.href);
                    const heading=Array.from(document.getElementsByTagName('h1')).find(n=>n.getClientRects().length);
                    if(actual.origin===expected.origin && actual.pathname===expected.pathname && heading){{
                      clearTimeout(timer);observer.disconnect();resolve({{url:location.href,heading:heading.innerText,title:document.title}});}}
                  }};
                  const observer=new MutationObserver(check);observer.observe(document,{{subtree:true,childList:true,characterData:true}});
                  timer=setTimeout(()=>{{observer.disconnect();reject(Error('destination not observed'))}},15000);check();
                }})"#,serde_json::to_string(expected)?)).await;
                match after {
                    Ok(after) => {
                        let observation = self.capture().await?;
                        let receipt = lease.finish(
                            ActionStatus::Confirmed,
                            "native click and destination URL/heading observed",
                        )?;
                        drop(cursor);
                        Ok(
                            json!({"receipt":receipt,"native_receipt":provenance,"destination":after,"observation":observation}),
                        )
                    }
                    Err(error) => {
                        let receipt = lease.finish(ActionStatus::Unconfirmed, error.to_string())?;
                        Ok(
                            json!({"receipt":receipt,"native_receipt":provenance,"error":error.to_string()}),
                        )
                    }
                }
            }
            _ => Err(io::Error::other("unsupported spike command").into()),
        }
    }
}

async fn serve(driver: &mut Driver, url: &str) -> Result<()> {
    let navigated = driver.work()?.navigate(url).await?;
    driver.retained(navigated)?;
    let observation = driver.capture().await?;
    println!(
        "{}",
        json!({"ok":true,"result":{"event":"ready",
        "controller":"Yosoi Session/Work → Chromiumoxide/CDP","observation":observation}})
    );
    io::stdout().flush()?;
    let mut input = BufReader::new(stdin()).lines();
    while let Some(line) = input.next_line().await? {
        let request: Value = serde_json::from_str(&line)?;
        if request.get("op").and_then(Value::as_str) == Some("close") {
            println!("{}", json!({"ok":true,"result":{"closing":true}}));
            break;
        }
        let reply = match driver.command(&request).await {
            Ok(value) => json!({"id":request.get("id"),"ok":true,"result":value}),
            Err(error) => json!({"id":request.get("id"),"ok":false,"error":error.to_string()}),
        };
        println!("{reply}");
        io::stdout().flush()?;
    }
    drop(input);
    Ok(())
}

async fn run_browser(browser: &session::Session, output: PathBuf, url: &str) -> Result<()> {
    let receipts = fs::File::create(output.join("native-receipts.jsonl"))?;
    let mut driver = Driver {
        work: Some(browser.work().await?),
        evidence: None,
        epoch: 0,
        output,
        receipts,
    };
    let result = serve(&mut driver, url).await;
    let released = {
        let work = driver
            .work
            .take()
            .ok_or_else(|| io::Error::other("native Work already released"))?;
        drop(driver);
        work.release().await
    };
    result?;
    released?;
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut args = env::args().skip(1);
    let mut url = "https://www.msnbc.com/".to_owned();
    let mut output = PathBuf::from(".generated/live-recording/native");
    while let Some(arg) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| io::Error::other("option value required"))?;
        match arg.as_str() {
            "--url" => url = value,
            "--output" => output = value.into(),
            _ => return Err(io::Error::other("unknown option").into()),
        }
    }
    fs::create_dir_all(&output)?;
    let mut policy = Policy::default();
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headful)];
    let settings = session::SessionPolicy {
        mode: BrowserMode::Headful,
        maximum_result_bytes: 1024 * 1024,
        maximum_observation_bytes: 4 * 1024 * 1024,
        operation_timeout_ms: 30_000,
        ..session::SessionPolicy::default()
    };
    let browser = session::new()
        .bind(&policy)
        .configure(settings)
        .allow_javascript()
        .acquire()
        .await?;
    let result = run_browser(&browser, output, &url).await;
    let closed = browser.close().await;
    drop(browser);
    result?;
    closed?;
    Ok(())
}
