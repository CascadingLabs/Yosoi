//! Live repetition resolves recorded intentions against newly captured surfaces.
use super::super::{
    process::Browser,
    session::{Driver, validate_effect, validate_url},
};
use crate::surface::{Budget, Reference, Session, SessionPolicy};
use crate::surface::{
    SurfacePolicy,
    archive::Recording,
    connection::{Operation, Request, Result, Target, Trace},
};
use crate::{
    automation_record::{AutomationRecord, OperationStatus},
    surface::Outcome,
};

#[derive(Debug, thiserror::Error)]
#[error("rerun failed: {source}")]
pub(in crate::surface::browser) struct RunFailure {
    pub outcomes: Vec<Outcome>,
    #[source]
    pub source: Box<dyn Error + Send + Sync>,
}
use serde_json::{Value, json};
use std::{collections::BTreeMap, error::Error, fs, io, path::Path};

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
fn procedure(record: &AutomationRecord) -> Result<(String, Vec<Operation>)> {
    if record
        .operations()
        .iter()
        .any(|receipt| receipt.kind == "surface.failure")
    {
        return Err(io::Error::other(
            "a prior procedure failed; inspect its retained failure before authoring another run",
        )
        .into());
    }
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
    validate_url(&url)?;
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
        validate_effect(&command)?;
        if serde_json::to_vec(&command)?.len() > 65536 {
            return Err(io::Error::other("procedure command exceeds 64 KiB").into());
        }
        if let Operation::Click {
            target: Some(target),
            ..
        }
        | Operation::Fill {
            target: Some(target),
            ..
        }
        | Operation::Key {
            target: Some(target),
            ..
        } = &command
            && (target.query.is_empty() || target.query.len() > 512 || target.tag.is_empty())
        {
            return Err(io::Error::other("invalid target intention").into());
        }
        if let Operation::Wait { text, .. } = &command
            && (text.is_empty() || text.len() > 512)
        {
            return Err(io::Error::other("invalid wait text").into());
        }
        if matches!(command, Operation::Wait { .. }) {
            if receipt.status != OperationStatus::Observed
                || value
                    .pointer("/outcome/condition/state")
                    .and_then(Value::as_str)
                    .is_none_or(|state| state == "timeout")
            {
                return Err(io::Error::other("cannot repeat an unconfirmed wait").into());
            }
            clicks.push(command);
            continue;
        }
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
                } | Operation::Fill {
                    target: Some(_),
                    ..
                } | Operation::Key {
                    target: Some(_),
                    expect: Some(_),
                    ..
                } | Operation::Scroll {
                    expect: Some(_),
                    ..
                } | Operation::Navigate { .. }
            ) {
                return Err(io::Error::other("live repetition requires target intentions for element effects and postconditions for every effect").into());
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
        return Err(io::Error::other("record has no repeatable procedure").into());
    }
    Ok((url, clicks))
}
pub(super) async fn run(
    record: &AutomationRecord,
    count: usize,
    policy: SurfacePolicy,
    headless: bool,
    output: &Path,
) -> Result<Vec<Outcome>> {
    if !(1..=100).contains(&count) {
        return Err(io::Error::other("count must be 1..100").into());
    }
    let (url, clicks) = procedure(record)?;
    fs::create_dir_all(output)?;
    for iteration in 1..=count {
        if output.join(format!("run-{iteration}")).exists() {
            return Err(io::Error::other("rerun destination already exists").into());
        }
    }
    let mut outcomes = Vec::new();
    for iteration in 1..=count {
        let directory = output.join(format!("run-{iteration}"));
        fs::create_dir_all(&directory)?;
        let mut trace = Trace::new(&directory);
        let root = policy
            .archive_root
            .clone()
            .unwrap_or_else(|| output.join("archive"));
        let mut recording = Recording::open(&root, &directory, &url).await?;
        recording.set_limits(policy.archive_limits);
        policy.documents.validate()?;
        let mut browser = match Browser::open_with_policy(headless, policy.documents.clone()).await
        {
            Ok(browser) => browser,
            Err(error) => {
                recording.fault();
                let _ = recording
                    .command(
                        json!({"op":"open"}),
                        &Err(io::Error::other(error.to_string()).into()),
                    )
                    .await;
                let _ = recording
                    .close(&Err(io::Error::other(
                        "browser initialization did not confirm cleanup",
                    )
                    .into()))
                    .await;
                outcomes.push(recording.outcome());
                return Err(Box::new(RunFailure {
                    outcomes,
                    source: error,
                }));
            }
        };
        let initial = async {
            browser.post("/url", json!({"url":url})).await?;
            let (surface, document, snapshot) = browser.capture(1, &mut trace).await?;
            recording.capture(&document, &surface, &snapshot, 1).await?;
            Ok::<_, Box<dyn Error + Send + Sync>>(surface)
        }
        .await;
        let surface = match initial {
            Ok(value) => value,
            Err(error) => {
                recording.fault();
                let closed = browser.close().await;
                let _ = recording
                    .command(
                        json!({"op":"open"}),
                        &Err(io::Error::other(error.to_string()).into()),
                    )
                    .await;
                let _ = recording.close(&closed).await;
                outcomes.push(recording.outcome());
                return Err(Box::new(RunFailure {
                    outcomes,
                    source: error,
                }));
            }
        };
        let session = Session::new(surface, SessionPolicy::default())?;
        session.attach()?;
        let cursor = session.cursor()?;
        cursor.promote()?;
        let mut driver = Driver {
            browser,
            session,
            cursor,
            epoch: 1,
            trace,
            recording_fault: false,
            recording: Some(recording),
            evidence: BTreeMap::new(),
        };
        let execution = async {
            for click in &clicks {
                let reference = match click {
                    Operation::Click {
                        target: Some(target),
                        ..
                    }
                    | Operation::Fill {
                        target: Some(target),
                        ..
                    }
                    | Operation::Key {
                        target: Some(target),
                        ..
                    } => Some(resolve(&driver, target).await?),
                    Operation::Scroll { .. } | Operation::Navigate { .. } => {
                        Some(driver.session.current()?.root())
                    }
                    Operation::Wait { .. } => None,
                    _ => return Err(io::Error::other("unsupported procedure operation").into()),
                };
                let mut value = serde_json::to_value(click)?;
                if let Some(reference) = reference {
                    value
                        .as_object_mut()
                        .ok_or_else(|| io::Error::other("invalid procedure object"))?
                        .insert("reference".into(), serde_json::to_value(reference)?);
                }
                let operation: Operation = serde_json::from_value(value)?;
                let request = Request {
                    id: Value::Null,
                    budget: 4096,
                    items: 20,
                    continuation: None,
                    operation: operation.clone(),
                };
                let result = driver.command(&request).await;
                driver.record_reply(&operation, &result)?;
                let result = driver.persist_command(&operation, result).await?;
                let confirmed = if matches!(operation, Operation::Wait { .. }) {
                    result
                        .pointer("/condition/state")
                        .and_then(Value::as_str)
                        .is_some_and(|state| state != "timeout")
                } else {
                    result
                        .get("receipt")
                        .and_then(|r| r.get("status"))
                        .and_then(Value::as_str)
                        == Some("Confirmed")
                };
                if !confirmed {
                    return Err(io::Error::other("repeated effect was not confirmed").into());
                }
            }
            driver.browser.screenshot(&directory, "final").await?;
            driver.browser.script("location", json!({})).await
        }
        .await;
        if let Err(error) = &execution
            && let Some(recording) = &mut driver.recording
        {
            let _ = recording.failure(&error.to_string()).await;
        }
        let detached = driver.session.detach();
        let closed = driver.browser.close().await;
        let archived = if let Some(recording) = driver.recording.as_mut() {
            recording.close(&closed).await
        } else {
            Ok(())
        };
        if let Some(recording) = &driver.recording {
            outcomes.push(recording.outcome());
        }
        let settled = execution
            .map(|_| ())
            .and(archived)
            .and_then(|()| detached.map_err(Into::into))
            .and(closed);
        if let Err(source) = settled {
            return Err(Box::new(RunFailure { outcomes, source }));
        }
    }
    Ok(outcomes)
}

#[cfg(test)]
mod tests {
    use super::{Result, procedure};
    use crate::automation_record::{AutomationRecord, OperationReceipt, OperationStatus};
    use serde_json::{Value, json};
    fn record(commands: Vec<Value>) -> Result<AutomationRecord> {
        let mut receipts: Vec<OperationReceipt> = vec![serde_json::from_value(json!({
            "id":"run", "kind":"surface.run", "status":OperationStatus::Observed,
            "result":{"schema":"yosoi.surface.run.v1","url":"https://example.invalid/"},
            "observation":null,"error":null
        }))?];
        for (index, command) in commands.into_iter().enumerate() {
            receipts.push(serde_json::from_value(json!({
                "id":format!("command-{index}"),"kind":"surface.command","status":OperationStatus::Observed,
                "result":{"command":command,"outcome":{"receipt":{"status":"Confirmed"},"condition":{"state":"matched"}}},
                "observation":null,"error":null
            }))?);
        }
        receipts.push(serde_json::from_value(json!({
            "id":"closed","kind":"surface.closed","status":OperationStatus::Observed,
            "result":{"browser_closed":true},"observation":null,"error":null
        }))?);
        Ok(AutomationRecord::new("recipe", Vec::new(), receipts)?)
    }
    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Regression assertions; fixture errors propagate."
    )]
    fn supported_effects_and_wait_preflight_as_one_procedure() -> Result<()> {
        let reference = json!({"capture":"old-capture","node":0});
        let target = json!({"query":"Go","tag":"button"});
        let expect = json!({"kind":"text","text":"Done","present":true});
        let record = record(vec![
            json!({"op":"click","reference":reference,"target":target,"expect":expect}),
            json!({"op":"fill","reference":reference,"target":target,"text":"text"}),
            json!({"op":"key","reference":reference,"target":target,"key":"Enter","expect":expect}),
            json!({"op":"scroll","reference":reference,"delta_y":300,"expect":expect}),
            json!({"op":"navigate","reference":reference,"url":"https://example.invalid/next"}),
            json!({"op":"wait","text":"Done","present":true}),
        ])?;
        let (_, commands) = procedure(&record)?;
        assert_eq!(commands.len(), 6);
        Ok(())
    }
    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Regression assertions; fixture errors propagate."
    )]
    fn invalid_later_operation_rejects_the_whole_procedure() -> Result<()> {
        let reference = json!({"capture":"old-capture","node":0});
        for command in [
            json!({"op":"key","reference":reference,"key":"Enter"}),
            json!({"op":"navigate","reference":reference,"url":"file:///tmp/file"}),
            json!({"op":"invented_action"}),
        ] {
            let record = record(vec![
                json!({"op":"navigate","reference":reference,"url":"https://example.invalid/valid"}),
                command,
            ])?;
            assert!(procedure(&record).is_err());
        }
        Ok(())
    }
}
