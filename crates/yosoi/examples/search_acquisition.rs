//! Capture one public search page through the SDK for offline diagnosis.
//!
//! Usage: search_acquisition URL http|headless OUTPUT_DIR [BROWSER_EXECUTABLE]
//! Captures contain page/query content; review before sharing or committing.

use std::{env, error::Error, fs, path::PathBuf};

use serde_json::json;
use yosoi::{
    Policy,
    policy::{Acquisition, BrowserMode, DocumentRequest, MaximumElapsed, Page},
    request::{self, DocumentOutcome},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let url = args.next().ok_or("URL is required")?;
    let mode = args.next().ok_or("http or headless is required")?;
    let output = PathBuf::from(args.next().ok_or("output directory is required")?);
    let executable = args.next().map(PathBuf::from);
    if args.next().is_some() {
        return Err("too many arguments".into());
    }
    let acquisition = match mode.as_str() {
        "http" => Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
        "headless" => Acquisition::Browser(BrowserMode::Headless).documents([
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
        ]),
        _ => return Err("mode must be http or headless".into()),
    };
    let mut policy = Policy {
        page: Page::new(vec![acquisition])?,
        ..Policy::default()
    };
    policy.browser.executable = executable;
    policy.request.maximum_elapsed = MaximumElapsed::try_from(60_000_000)?;
    policy.validate()?;
    fs::create_dir(&output)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        fs::set_permissions(&output, fs::Permissions::from_mode(0o700))?;
    }
    let response = request::new(url).bind(&policy).send().await?;
    let mut attempts = Vec::new();
    for (index, attempt) in response.attempts().enumerate() {
        let mut documents = Vec::new();
        for item in attempt.documents() {
            let outcome = item.outcome();
            let state = match outcome {
                DocumentOutcome::Produced(_) => "produced".to_owned(),
                DocumentOutcome::Partial { reasons, .. } => {
                    format!("partial:{reasons:?}")
                }
                DocumentOutcome::Unavailable(reason) => {
                    format!("unavailable:{reason:?}")
                }
                DocumentOutcome::Unprojectable(reason) => {
                    format!("unprojectable:{reason:?}")
                }
            };
            let artifact = if let Some(document) = outcome.document() {
                let name = format!("attempt-{index}-{:?}.data", item.requested());
                fs::write(output.join(&name), document.bytes())?;
                Some(
                    json!({"file": name, "bytes": document.byte_len(), "class": format!("{:?}", document.class())}),
                )
            } else {
                None
            };
            documents.push(json!({"requested": format!("{:?}", item.requested()), "outcome": state, "artifact": artifact}));
        }
        attempts.push(json!({
            "capture_id": attempt.capture_id().to_string(),
            "status": attempt.status(), "state": format!("{:?}", attempt.state()),
            "diagnostic": format!("{:?}", attempt.diagnostic()), "documents": documents,
        }));
    }
    let manifest = json!({"request_id": response.request_id().to_string(), "target": response.requested_target(), "acquisition": mode,
        "effective_policy": {"version": policy.effective_identity()?.version(), "digest": policy.effective_identity()?.digest().to_string()},
        "source_revision": option_env!("YOSOI_BUILD_SOURCE_REVISION"),
        "sdk_version": env!("CARGO_PKG_VERSION"),
        "capture_environment": {"status": "unavailable", "reason": "public_requests_response_does_not_expose_capture_environment; use Search diagnostic captures for this fact"}, "attempts": attempts});
    let encoded = serde_json::to_vec_pretty(&manifest)?;
    fs::write(output.join("manifest.json"), &encoded)?;
    println!("{}", String::from_utf8(encoded)?);
    Ok(())
}
