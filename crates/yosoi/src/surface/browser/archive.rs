//! Browser capture, replay and fresh-session archive procedures.
use crate::{
    Archive,
    automation_record::{Observation, OperationStatus},
    documents::Document,
    surface::{
        ArchiveLimits, ArchivePolicy, ArchivedSource, Budget, DocumentPolicy, ExecutionError,
        Outcome, Surface, SurfacePolicy,
        archive::{Capture, Loaded, Recording, capture_descriptors},
        connection::Result,
    },
    view::View,
};
use serde_json::{Value, json};
use std::{error::Error, io, path::Path, result::Result as StdResult};
use uuid::Uuid;
#[cfg(feature = "browser")]
pub(super) mod repeating;
impl Recording {
    pub async fn open(root: &Path, output: &Path, url: &str) -> Result<Self> {
        let archive = Archive::open(root).await?;
        let mut recording = Self {
            archive,
            outcome: Outcome::new(
                format!("surface-{}", Uuid::new_v4()),
                ArchiveLimits::default(),
            )?,
            output: output.to_owned(),
            handle: None,
            sequence: 0,
            pending: None,
        };
        recording.push("surface.run",OperationStatus::Observed,json!({"schema":"yosoi.surface.run.v1","url":url,"recording_policy":{"mode":"archive","captures":"rendered_dom_and_html","checkpoint":"each_command"}}),None,None)?;
        Ok(recording)
    }
    pub async fn capture(
        &mut self,
        document: &Document,
        surface: &Surface,
        snapshot: &Value,
        epoch: u64,
    ) -> Result<()> {
        let reference = self.archive.write_document(document).await?;
        self.outcome.retain(ArchivedSource::new(
            reference.to_string(),
            document,
            Some(surface),
        ))?;
        let observation = Observation {
            browser: None,
            id: format!("{}:capture:{epoch}", self.outcome.record.id()),
            session_id: self.outcome.record.id().into(),
            tab_id: "primary".into(),
            document_epoch: epoch,
            html: snapshot
                .get("html")
                .and_then(Value::as_str)
                .map(str::to_owned),
            url: snapshot
                .get("url")
                .and_then(Value::as_str)
                .map(str::to_owned),
            screenshot: None,
        };
        self.outcome.record.push_observation(observation.clone())?;
        let capture = Capture {
            schema: "yosoi.surface.capture.v1".into(),
            document: reference,
            surface: surface.identity().into(),
            normalized_strings: snapshot
                .get("normalized_strings")
                .cloned()
                .unwrap_or_else(|| json!([])),
        };
        self.push(
            "surface.capture",
            OperationStatus::Observed,
            serde_json::to_value(capture)?,
            Some(observation),
            None,
        )?;
        self.checkpoint().await?;
        Ok(())
    }
    pub async fn close(&mut self, closed: &Result<()>) -> Result<()> {
        let pending = self.abandon_pending();
        let receipt = self.push(
            "surface.closed",
            if closed.is_ok() {
                OperationStatus::Observed
            } else {
                OperationStatus::Unknown
            },
            json!({"browser_closed":closed.is_ok()}),
            None,
            closed.as_ref().err().map(ToString::to_string),
        );
        self.finalize().await?;
        pending?;
        receipt?;
        Ok(())
    }
}
pub(in crate::surface) async fn replay_loaded(
    loaded: &Loaded,
    repeat: usize,
    query: Option<&str>,
) -> Result<Value> {
    let archive = &loaded.archive;
    let record = &loaded.record;
    let captures = capture_descriptors(record)?;
    let retained: Vec<_> = loaded
        .outcome
        .as_ref()
        .map(|value| {
            value
                .sources
                .iter()
                .filter(|source| source.surface.is_some())
                .collect()
        })
        .unwrap_or_default();
    if captures.is_empty() && retained.is_empty() {
        return Err(io::Error::other("record has no captured surfaces").into());
    }
    let mut last = None;
    for _ in 0..repeat {
        if captures.is_empty() {
            for source in &retained {
                last = Some(source.restore_surface(DocumentPolicy::maximum_limits())?);
            }
        }
        for capture in &captures {
            let document = archive.read_document(&capture.document).await?;
            let surface = Surface::with_limits(&document, DocumentPolicy::maximum_limits())?;
            if surface.identity() != capture.surface {
                return Err(io::Error::other(
                    "restored surface identity differs from recorded identity",
                )
                .into());
            }
            last = Some(surface);
        }
        for observation in record.observations() {
            // AX and network observations are reconstructed from their typed
            // Documents above; they deliberately have no captured HTML.
            if observation.html.is_some() {
                View::from_observation(observation, 20)?;
            }
        }
    }
    let last = last.ok_or_else(|| io::Error::other("last surface absent"))?;
    let matches = query
        .map(|q| {
            last.find(
                q,
                None,
                Budget {
                    bytes: 2048,
                    items: 5,
                },
            )
        })
        .transpose()?;
    let mut actions: Vec<_> = record
        .operations()
        .iter()
        .filter(|op| {
            op.kind == "surface.command"
                && op
                    .result
                    .as_ref()
                    .and_then(|v| v.get("outcome"))
                    .and_then(|v| v.get("receipt"))
                    .is_some()
        })
        .map(|op| json!({"id":op.id,"status":op.status}))
        .collect();
    let actions_omitted = actions.len().saturating_sub(8);
    actions.truncate(8);
    Ok(
        json!({"mode":"offline","browser_started":false,"controllable":false,"record":record.id(),"iterations":repeat,"captures":if captures.is_empty(){retained.len()}else{captures.len()},"offline_views":record.observations().len(),"last_capture":last.identity(),"last_url":record.observations().last().and_then(|observation|observation.url.as_ref()),"actions":actions,"actions_omitted":actions_omitted,"matches":matches}),
    )
}

#[cfg(feature = "browser")]
/// Explicitly executes a confirmed web recipe against fresh isolated sessions.
///
/// Preflight rejects incomplete/unsealed outcomes and unsupported procedures
/// before launching a browser. Targets are resolved uniquely from new evidence;
/// saved references never grant authority. Each successful iteration returns
/// a separate outcome. Failures retain evidence in the selected output directory.
pub async fn rerun(
    value: &Outcome,
    policy: SurfacePolicy,
    count: usize,
    headless: bool,
) -> StdResult<Vec<Outcome>, ExecutionError> {
    let result = async {
        value.validate()?;
        policy.archive_limits.validate()?;
        if !value.sealed {
            return Err(io::Error::other("record is not sealed after finalization").into());
        }
        if !value.complete {
            return Err(io::Error::other("rerun requires complete retained evidence").into());
        }
        if policy.archive != ArchivePolicy::Enabled {
            return Err(io::Error::other("rerun requires enabled archive policy").into());
        }
        let temporary = tempfile::tempdir()?;
        let output = policy
            .output
            .clone()
            .unwrap_or_else(|| temporary.path().join("runs"));
        repeating::run(&value.record, count, policy, headless, &output).await
    }
    .await;
    result.map_err(error)
}

#[cfg(feature = "browser")]
pub(super) fn error(error: Box<dyn Error + Send + Sync>) -> ExecutionError {
    match error.downcast::<repeating::RunFailure>() {
        Ok(failed) => ExecutionError::Execution {
            outcomes: failed.outcomes,
            source: failed.source,
        },
        Err(error) => ExecutionError::Operation(error),
    }
}
