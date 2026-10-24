//! Open an article through bounded surface reads, then observe its actual outcome.
//! Uses ys::surface directly. See surface_article/README.md for commands.
#[path = "../src/bin/yosoi/surface_command/adapter.rs"]
mod adapter;
use adapter::{Browser, ELEMENT, Result, Trace};
use serde_json::{Value, json};
use std::{env, fs, io, path::PathBuf};
use yosoi as ys;
use ys::surface::{ActionStatus, Budget, Cursor, Reference, Session, SessionPolicy, Surface};

struct Options {
    url: String,
    query: String,
    output: PathBuf,
    accept_terms: bool,
    headless: bool,
}
impl Options {
    fn parse() -> Result<Self> {
        let mut options = Self {
            url: "https://www.cnn.com/".into(),
            query: String::new(),
            output: ".local/index-article".into(),
            accept_terms: false,
            headless: false,
        };
        let mut args = env::args().skip(1);
        while let Some(argument) = args.next() {
            match argument.as_str() {
                "--accept-terms" => options.accept_terms = true,
                "--headless" => options.headless = true,
                "--url" | "--query" | "--output" => {
                    let value = args
                        .next()
                        .ok_or_else(|| io::Error::other(format!("missing value for {argument}")))?;
                    match argument.as_str() {
                        "--url" => options.url = value,
                        "--query" => options.query = value,
                        _ => options.output = value.into(),
                    }
                }
                _ => return Err(io::Error::other(format!("unknown argument: {argument}")).into()),
            }
        }
        if options.query.is_empty() {
            return Err(io::Error::other("pass --query with text from an article link").into());
        }
        let url = url::Url::parse(&options.url)?;
        if !matches!(url.scheme(), "http" | "https") {
            return Err(io::Error::other("--url must use HTTP(S)").into());
        }
        Ok(options)
    }
}
// Inspection chunks are source fragments, not necessarily complete JSON records.
fn inspect_record(
    cursor: &Cursor,
    reference: &Reference,
    trace: &mut Trace,
) -> Result<Option<Value>> {
    let mut detail = cursor.inspect(reference, None, Budget::default())?;
    trace.read("surface.inspect", &detail)?;
    if detail.total_bytes > 16 * 1024 {
        return Ok(None);
    }
    let mut content = detail.content;
    for _ in 0..8 {
        let Some(token) = detail.next else {
            return Ok(Some(serde_json::from_str(&content)?));
        };
        detail = cursor.inspect(reference, Some(&token), Budget::default())?;
        trace.read("surface.inspect", &detail)?;
        content.push_str(&detail.content);
    }
    Ok(None)
}
struct Target {
    reference: Reference,
    id: u64,
    evidence: Value,
}
async fn locate(
    browser: &Browser,
    index: &Surface,
    cursor: &Cursor,
    query: &str,
    consent: bool,
    trace: &mut Trace,
) -> Result<Target> {
    let mut token = None;
    for _ in 0..8 {
        let page = cursor.find(query, token.as_ref(), Budget::default())?;
        trace.read("surface.find", &page)?;
        for entry in &page.entries {
            if !entry.preview.to_lowercase().contains(&query.to_lowercase()) {
                continue;
            }
            let mut reference = Some(entry.reference.clone());
            for _ in 0..5 {
                let Some(current) = reference else { break };
                if let Some(node) = inspect_record(cursor, &current, trace)? {
                    let tag = node.get("tag_name").and_then(Value::as_str);
                    if tag == Some("a") || (consent && tag == Some("button")) {
                        let coordinate = index.coordinate(&current)?;
                        if coordinate.kind != "dom_node" {
                            break;
                        }
                        let id: u64 = coordinate.value.parse()?;
                        let evidence = browser.script("eligibility", json!({"id":id})).await?;
                        trace.event(
                            "target.eligibility",
                            json!({"reference":current,"native":evidence}),
                        );
                        let indexed_href = node
                            .get("attributes")
                            .and_then(Value::as_array)
                            .and_then(|attributes| {
                                attributes.iter().find(|attribute| {
                                    attribute.get("name").and_then(Value::as_str) == Some("href")
                                })
                            })
                            .and_then(|attribute| attribute.get("value"))
                            .and_then(Value::as_str);
                        let actual = evidence.get("href").and_then(Value::as_str);
                        let href_matches = match (indexed_href, actual) {
                            (Some(href), Some(actual)) => {
                                url::Url::parse(
                                    evidence
                                        .get("url")
                                        .and_then(Value::as_str)
                                        .unwrap_or_default(),
                                )?
                                .join(href)?
                                .as_str()
                                    == actual
                            }
                            (None, None) => consent,
                            _ => false,
                        };
                        let text = evidence
                            .get("text")
                            .and_then(Value::as_str)
                            .unwrap_or_default();
                        let relevant = if consent {
                            text.trim() == query
                        } else {
                            text.to_lowercase().contains(&query.to_lowercase())
                                && actual.is_some_and(|href| {
                                    href.starts_with("https://") || href.starts_with("http://")
                                })
                        };
                        if evidence.get("eligible") == Some(&Value::Bool(true))
                            && href_matches
                            && relevant
                        {
                            return Ok(Target {
                                reference: current,
                                id,
                                evidence,
                            });
                        }
                        break;
                    }
                }
                reference = index.parent(&current)?;
            }
        }
        token = page.next;
        if token.is_none() {
            break;
        }
    }
    Err(io::Error::other(format!(
        "no eligible indexed target for {query:?}; inspect trace for blockers"
    ))
    .into())
}
async fn click(
    browser: &Browser,
    session: &Session,
    cursor: &Cursor,
    target: &Target,
    consent: bool,
    epoch: u64,
    trace: &mut Trace,
) -> Result<Value> {
    cursor.focus(&target.reference)?;
    cursor.promote()?;
    trace.event("cursor.hot", serde_json::to_value(cursor.status()?)?);
    let mut lease = cursor.begin_action()?;
    let current = browser
        .script("eligibility", json!({"id":target.id}))
        .await?;
    trace.event("target.revalidated", current.clone());
    if current.get("eligible") != Some(&Value::Bool(true))
        || current.get("href") != target.evidence.get("href")
        || current.get("text") != target.evidence.get("text")
        || current.get("url") != target.evidence.get("url")
    {
        let receipt = lease.finish(
            ActionStatus::Rejected,
            "live target changed or became ineligible",
        )?;
        trace.event("action.receipt", serde_json::to_value(receipt)?);
        return Err(io::Error::other("target became ineligible before dispatch").into());
    }
    let element = browser.script("element", json!({"id":target.id})).await?;
    let id = element
        .get(ELEMENT)
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("reference has no browser node"))?;
    lease.revalidate()?;
    lease.mark_dispatched()?;
    trace.event(
        "action.dispatch",
        json!({"reference":target.reference,"effect":"native WebDriver element click"}),
    );
    let result = async {
        browser
            .post(&format!("/element/{id}/click"), json!({}))
            .await?;
        // The new document is observed independently of the old URL/DOM. No fixed readiness sleeps.
        browser
            .script(
                "watch",
                json!({"kind":if consent {"consent_gone"} else {"article"},
            "before_url":current.get("url"),"expected_url":current.get("href"),"timeout_ms":15000}),
            )
            .await
    }
    .await;
    session.invalidate("native click dispatched; awaiting new browser evidence")?;
    match result {
        Ok(outcome) => {
            trace.event("browser.postcondition", outcome.clone());
            session.publish(browser.capture(epoch, trace).await?.0)?;
            let confirmed = if consent {
                outcome.get("state").and_then(Value::as_str) == Some("consent_gone")
            } else {
                matches!(
                    outcome.get("state").and_then(Value::as_str),
                    Some("readable" | "subscription_required")
                )
            };
            let receipt = lease.finish(if confirmed {ActionStatus::Confirmed} else {ActionStatus::Unconfirmed},
                if !confirmed {"click dispatched; requested postcondition was not observed before the timeout"} else if consent {"postcondition: consent modal disappeared"} else {"postcondition: destination URL and article heading observed; body access recorded separately"})?;
            trace.event("action.receipt", serde_json::to_value(receipt)?);
            cursor.cool()?;
            Ok(outcome)
        }
        Err(error) => {
            let receipt = lease.finish(
                ActionStatus::Unconfirmed,
                format!("dispatch outcome uncertain: {error}"),
            )?;
            trace.event("action.receipt", serde_json::to_value(receipt)?);
            Err(error)
        }
    }
}
async fn run(browser: &Browser, options: &Options, trace: &mut Trace) -> Result<Value> {
    browser.post("/url", json!({"url":options.url})).await?;
    let home = browser
        .script("watch", json!({"kind":"home","timeout_ms":8000}))
        .await?;
    trace.event("browser.home", home.clone());
    browser.screenshot(&options.output, "before").await?;
    let index = browser.capture(1, trace).await?.0;
    let session = Session::new(index, SessionPolicy::default())?;
    let cursor = session.cursor()?;
    trace.event("cursor.detached", serde_json::to_value(cursor.status()?)?);
    session.attach()?;
    trace.event(
        "cursor.live_reader",
        serde_json::to_value(cursor.status()?)?,
    );
    trace.read(
        "surface.overview",
        &cursor.overview(None, Budget::default())?,
    )?;
    if home.get("state").and_then(Value::as_str) == Some("consent_required") {
        if !options.accept_terms {
            return Ok(
                json!({"state":"consent_required","note":"rerun with --accept-terms only after authorizing the CNN Agree action"}),
            );
        }
        let target = locate(browser, &session.current()?, &cursor, "Agree", true, trace).await?;
        click(browser, &session, &cursor, &target, true, 2, trace).await?;
    }
    // Consent can reload the document after its modal disappears. Never reuse
    // the old native binding: capture again and search again with fresh refs.
    let mut selected = None;
    for attempt in 0..3_u64 {
        match locate(
            browser,
            &session.current()?,
            &cursor,
            &options.query,
            false,
            trace,
        )
        .await
        {
            Ok(target) => {
                selected = Some(target);
                break;
            }
            Err(error) => {
                let binding = browser.script("binding", json!({})).await?;
                if binding.get("current") == Some(&Value::Bool(true)) {
                    return Err(error);
                }
                trace.event("document.replaced", binding);
                session.invalidate("document replaced after capture; discard old references")?;
                session.publish(
                    browser
                        .capture(3_u64.saturating_add(attempt), trace)
                        .await?
                        .0,
                )?;
            }
        }
    }
    let target = selected
        .ok_or_else(|| io::Error::other("document kept changing before target selection"))?;
    let outcome = click(browser, &session, &cursor, &target, false, 6, trace).await?;
    // Return to bounded reading in the destination's newly published index.
    trace.read(
        "surface.destination_overview",
        &cursor.overview(None, Budget::default())?,
    )?;
    if let Some(heading) = outcome.get("heading").and_then(Value::as_str) {
        trace.read(
            "surface.destination_heading",
            &cursor.find(heading, None, Budget::default())?,
        )?;
    }
    browser.screenshot(&options.output, "after").await?;
    Ok(outcome)
}
#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let options = Options::parse()?;
    fs::create_dir_all(&options.output)?;
    let mut trace = Trace::new(&options.output);
    let mut browser = Browser::open(options.headless).await?;
    trace.event("browser.identity", browser.capabilities.clone());
    trace.event("browser.session", json!({"source":browser.session_key()}));
    let result = run(&browser, &options, &mut trace).await;
    if result.is_err() {
        let _ = browser.screenshot(&options.output, "failure").await;
    }
    let closed = browser.close().await;
    let outcome = match &result {
        Ok(value) => value.clone(),
        Err(error) => json!({"state":"failed","error":error.to_string()}),
    };
    let report = json!({"sdk":"ys::surface (use yosoi as ys)","adapter":"example-only ChromeDriver, native clicks, light DOM",
        "url":options.url,"query":options.query,"accept_terms":options.accept_terms,"headless":options.headless,
        "read_budget_bytes":Budget::default().bytes,"surface_read_bytes":trace.read_bytes,
        "outcome":outcome,"events":trace.events,"dropped_events":trace.dropped_events});
    fs::write(
        options.output.join("trace.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!(
        "{}",
        serde_json::to_string_pretty(
            &json!({"outcome":outcome,"trace":options.output.join("trace.json"),"surface_read_bytes":trace.read_bytes})
        )?
    );
    result?;
    closed?;
    Ok(())
}
