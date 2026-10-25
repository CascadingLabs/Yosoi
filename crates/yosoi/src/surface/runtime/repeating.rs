//! Live repetition resolves recorded intentions against newly captured surfaces.
use super::{Driver, Operation, Result, Target, recording};
use crate::surface::{Budget, Reference};
use serde_json::{Value, json};
use std::{fs, io, path::Path};

pub async fn resolve(driver: &Driver, target: &Target) -> Result<Reference> {
    if target.query.is_empty() || target.query.len() > 512 || target.tag.is_empty() {
        return Err(io::Error::other("replay target requires a query and tag").into());
    }
    let surface = driver.session.current()?;
    let mut token = None;
    let mut eligible = Vec::new();
    for _ in 0..16 {
        let page = surface.find(&target.query, token.as_ref(), Budget::default())?;
        for entry in page.entries {
            let mut reference = Some(entry.reference);
            for _ in 0..8 {
                let Some(current) = reference else { break };
                let detail = surface.inspect(&current, None, Budget::default())?;
                let mut content = detail.content;
                let mut continuation = detail.next;
                if detail.total_bytes > 16 * 1024 {
                    break;
                }
                while let Some(next) = continuation {
                    let detail = surface.inspect(&current, Some(&next), Budget::default())?;
                    content.push_str(&detail.content);
                    continuation = detail.next;
                }
                let node: Value = serde_json::from_str(&content)?;
                if node.get("tag_name").and_then(Value::as_str) == Some(target.tag.as_str()) {
                    let id = driver.native_id(&current)?;
                    let native = driver
                        .browser
                        .script("eligibility", json!({"id":id}))
                        .await?;
                    if native.get("eligible") == Some(&Value::Bool(true))
                        && native.get("unchanged") == Some(&Value::Bool(true))
                        && !eligible.contains(&current)
                    {
                        eligible.push(current);
                    }
                    break;
                }
                reference = surface.parent(&current)?;
            }
        }
        token = page.next;
        if token.is_none() {
            break;
        }
    }
    if token.is_some() {
        return Err(
            io::Error::other("target search was incomplete; refine the recorded query").into(),
        );
    }
    if eligible.len() != 1 {
        return Err(io::Error::other(format!(
            "recorded intention resolved to {} eligible targets; refusing to retarget ambiguously",
            eligible.len()
        ))
        .into());
    }
    eligible
        .into_iter()
        .next()
        .ok_or_else(|| io::Error::other("target absent").into())
}
pub async fn run(
    path: &Path,
    count: usize,
    headless: bool,
    output: &Path,
    mut on_iteration: impl FnMut(Value),
) -> Result<()> {
    if !(1..=100).contains(&count) {
        return Err(io::Error::other("count must be 1..100").into());
    }
    let (archive, record) = recording::load(path).await?;
    if record
        .operations()
        .iter()
        .any(|operation| operation.kind == "surface.video.source")
    {
        return Err(io::Error::other(
            "video is not controllable; use surface replay for offline evidence",
        )
        .into());
    }
    if !record.operations().iter().any(|op| {
        op.kind == "surface.closed"
            && op.result.as_ref().and_then(|v| v.get("browser_closed")) == Some(&Value::Bool(true))
    }) {
        return Err(
            io::Error::other("record is not sealed after successful browser cleanup").into(),
        );
    }
    let run = record
        .operations()
        .iter()
        .find(|op| op.kind == "surface.run")
        .and_then(|op| op.result.as_ref())
        .ok_or_else(|| io::Error::other("record lacks run metadata"))?;
    if run.get("schema").and_then(Value::as_str) != Some("yosoi.surface.run.v1") {
        return Err(io::Error::other("unsupported surface run schema").into());
    }
    let url = run
        .get("url")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("record lacks initial URL"))?
        .to_owned();
    super::web::validate_url(&url)?;
    let mut clicks = Vec::new();
    for receipt in record
        .operations()
        .iter()
        .filter(|op| op.kind == "surface.command")
    {
        let value = receipt
            .result
            .as_ref()
            .ok_or_else(|| io::Error::other("missing recorded command"))?;
        let command: Operation = serde_json::from_value(
            value
                .get("command")
                .cloned()
                .ok_or_else(|| io::Error::other("missing recorded command input"))?,
        )?;
        if matches!(
            command,
            Operation::Click { .. }
                | Operation::Fill { .. }
                | Operation::Key { .. }
                | Operation::Scroll { .. }
                | Operation::Navigate { .. }
        ) {
            if !matches!(
                command,
                Operation::Click {
                    target: Some(_),
                    expect: Some(_),
                    ..
                }
            ) {
                return Err(io::Error::other("live repetition currently requires explicit click intentions and postconditions for every recorded effect").into());
            }
            if value
                .get("outcome")
                .and_then(|v| v.get("receipt"))
                .and_then(|r| r.get("status"))
                .and_then(Value::as_str)
                != Some("Confirmed")
            {
                return Err(io::Error::other(
                    "cannot repeat a record containing rejected or unconfirmed effects",
                )
                .into());
            }
            clicks.push(command);
        }
    }
    if clicks.is_empty() {
        return Err(io::Error::other("record has no repeatable clicks").into());
    }
    fs::create_dir_all(output)?;
    for iteration in 1..=count {
        let directory = output.join(format!("run-{iteration}"));
        fs::create_dir_all(&directory)?;
        let mut driver = super::web::open_web(
            &url,
            headless,
            directory.clone(),
            Some(archive.root().to_owned()),
        )
        .await?;
        let execution = async {
            driver.session.attach()?;
            driver.cursor.promote()?;
            for click in &clicks {
                let Operation::Click {
                    target: Some(target),
                    expect,
                    ..
                } = click
                else {
                    return Err(io::Error::other("invalid click recipe").into());
                };
                let reference = resolve(&driver, target).await?;
                let operation = Operation::Click {
                    reference,
                    expect: expect.clone(),
                    target: Some(target.clone()),
                };
                let result = driver
                    .effect(
                        match &operation {
                            Operation::Click { reference, .. } => reference,
                            _ => return Err(io::Error::other("invalid click recipe").into()),
                        },
                        &operation,
                    )
                    .await;
                if let Some(recording) = driver.recording.as_mut() {
                    recording
                        .command(serde_json::to_value(&operation)?, &result)
                        .await?;
                }
                let result = result?;
                if result
                    .get("receipt")
                    .and_then(|r| r.get("status"))
                    .and_then(Value::as_str)
                    != Some("Confirmed")
                {
                    return Err(io::Error::other("repeated effect was not confirmed").into());
                }
            }
            driver.browser.screenshot(&directory, "final").await?;
            driver.browser.script("location", json!({})).await
        }
        .await;
        let closed = driver.close().await;
        let location = execution?;
        closed?;
        on_iteration(
            json!({"iteration":iteration,"confirmed_clicks":clicks.len(),"record":directory.join("record.json"),"mode":"live","fresh_session":true,"final_url":location.get("url")}),
        );
    }
    Ok(())
}
