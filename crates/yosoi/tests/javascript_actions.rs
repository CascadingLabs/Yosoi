use std::env as std_env;
use std::process as std_process;
use std::{
    error::Error,
    fs, io,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use yosoi::flow as yosoi_flow;

use yosoi::{
    Archive, action,
    automation_record::{AutomationRecord, OperationReceipt, OperationStatus},
    flow::{Flow, FlowOutcome, FlowTermination, Step, StepOutcome},
};

struct TemporaryDirectory(PathBuf);

impl TemporaryDirectory {
    fn new(label: &str) -> io::Result<Self> {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_nanos();
        let path = std_env::temp_dir().join(format!(
            "yosoi-javascript-{label}-{}-{nonce}",
            std_process::id()
        ));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TemporaryDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn file_action_keeps_the_exact_utf8_snapshot_and_provenance_after_the_file_changes() {
    let temporary = TemporaryDirectory::new("snapshot").expect("temporary directory is created");
    let path = temporary.path().join("capture.js");
    let source = "// café\r\nconst text = 'import x from \\\"./fake.js\\\"';\r\nexport const value = `✓`;  \r\n";
    fs::write(&path, source.as_bytes()).expect("source fixture is written");

    let step = action::evaluate_file(&path).expect("valid JavaScript source is snapshotted");
    fs::write(&path, b"export const changed = true;\n").expect("source fixture can change");

    let Step::EvaluateFile { snapshot } = step else {
        panic!("file constructor must create an EvaluateFile action");
    };
    assert_eq!(snapshot.source(), source);
    assert_eq!(snapshot.byte_len(), source.len());
    assert_eq!(snapshot.provenance().byte_len(), source.len());
    assert!(
        snapshot
            .provenance()
            .sha256()
            .chars()
            .all(|character| character.is_ascii_hexdigit())
    );
    assert_eq!(
        snapshot.provenance().origin(),
        &action::JavaScriptSourceOrigin::File { path }
    );
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Archive assertions report exact source retention regressions."
)]
async fn file_and_module_sources_survive_an_archive_round_trip_exactly()
-> Result<(), Box<dyn Error>> {
    let temporary = TemporaryDirectory::new("archive")?;
    let file_path = temporary.path().join("standalone.js");
    let entry_path = temporary.path().join("entry.js");
    let child_path = temporary.path().join("child.js");
    let file_source = "// π\nexport const fileValue = 'exact  ';\n";
    let entry_source =
        "import { childValue } from './child.js';\nexport const result = childValue;\n";
    let child_source = "export const childValue = 'preserved';\n";
    fs::write(&file_path, file_source.as_bytes())?;
    fs::write(&entry_path, entry_source.as_bytes())?;
    fs::write(&child_path, child_source.as_bytes())?;

    let file_step = action::evaluate_file(&file_path)?;
    let module_step = action::run_module_with_export(&entry_path, "result")?;
    fs::write(&file_path, b"export const replaced = true;\n")?;
    fs::write(&entry_path, b"export const replaced = true;\n")?;
    fs::write(&child_path, b"export const childValue = 'replaced';\n")?;

    let flow = Flow::new([file_step, module_step]);
    let outcome = FlowOutcome {
        version: 2,
        flow: flow.clone(),
        steps: vec![
            unknown_step(0, vec![0], "evaluate_file"),
            unknown_step(1, vec![1], "evaluate_module"),
        ],
        terminal: FlowTermination::Unknown,
        continuation_defaults: yosoi_flow::FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    let record = AutomationRecord::new("javascript-source-round-trip", Vec::new(), Vec::new())?
        .with_flow_outcome(outcome)?;

    let archive = Archive::open(temporary.path()).await?;
    let reference = record.write_to(&archive).await?;
    drop(archive);
    let reopened = Archive::open(temporary.path()).await?;
    let restored = AutomationRecord::read_from(&reopened, &reference).await?;
    let restored_outcome = restored
        .flow_outcome()
        .ok_or_else(|| io::Error::other("Archive omitted the JavaScript Flow outcome"))?;

    let Some(Step::EvaluateFile { snapshot }) = restored_outcome.flow.steps().first() else {
        return Err(io::Error::other("Archive changed the file action kind").into());
    };
    assert_eq!(snapshot.source(), file_source);
    assert_eq!(snapshot.byte_len(), file_source.len());

    let Some(Step::EvaluateModule { bundle }) = restored_outcome.flow.steps().get(1) else {
        return Err(io::Error::other("Archive changed the module action kind").into());
    };
    assert_eq!(bundle.result_export(), Some("result"));
    let entry = bundle
        .modules()
        .get(bundle.entry())
        .ok_or_else(|| io::Error::other("Archive omitted the entry module"))?;
    assert_eq!(entry.snapshot().source(), entry_source);
    let child = bundle
        .modules()
        .values()
        .find(|module| module.snapshot().source() == child_source)
        .ok_or_else(|| io::Error::other("Archive omitted the imported module source"))?;
    assert_eq!(child.snapshot().source(), child_source);
    assert_eq!(
        restored_outcome.flow.steps(),
        flow.steps(),
        "Archive changed the source-bearing Flow steps"
    );
    Ok(())
}

fn unknown_step(index: u64, flow_path: Vec<u64>, kind: &str) -> StepOutcome {
    StepOutcome {
        index,
        flow_path,
        receipt: OperationReceipt {
            browser: None,
            id: format!("javascript-operation-{index}"),
            kind: kind.to_owned(),
            status: OperationStatus::Unknown,
            result: None,
            observation: None,
            error: Some("record constructed without browser execution".to_owned()),
        },
        failure: None,
        cancellation: None,
        cancelled_flow: None,
    }
}
