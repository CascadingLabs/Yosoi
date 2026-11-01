#![cfg(feature = "cli")]
//! Offline CLI ingestion uses the same read requests and producer-issued references.
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    error::Error,
    fs,
    io::{self, BufRead, BufReader, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
};
use tempfile::TempDir;

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;
type CliReader = (Child, ChildStdin, BufReader<ChildStdout>, Value);

#[derive(Deserialize)]
struct Cases {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    format: String,
    content: String,
    query: String,
}

fn next_reply(output: &mut BufReader<ChildStdout>) -> Result<Value, Box<dyn Error + Send + Sync>> {
    let mut line = String::new();
    if output.read_line(&mut line)? == 0 {
        return Err(io::Error::other("Surface CLI closed before replying").into());
    }
    Ok(serde_json::from_str(&line)?)
}

fn exchange(
    input: &mut ChildStdin,
    output: &mut BufReader<ChildStdout>,
    command: &Value,
) -> Result<Value, Box<dyn Error + Send + Sync>> {
    serde_json::to_writer(&mut *input, command)?;
    input.write_all(b"\n")?;
    input.flush()?;
    next_reply(output)
}

fn start(directory: &TempDir, case: &Case) -> Result<CliReader, Box<dyn Error + Send + Sync>> {
    let path = directory.path().join(format!("{}.fixture", case.name));
    fs::write(&path, case.content.as_bytes())?;
    let mut command = Command::new(env!("CARGO_BIN_EXE_yosoi"));
    command
        .args(["surface", "document", "--format"])
        .arg(&case.format)
        .arg("--file")
        .arg(&path)
        .arg("--id")
        .arg(&case.name)
        .arg("--source")
        .arg(format!("fixture:{}", case.name))
        .args(["--response-bytes", "1024"]);
    if matches!(case.format.as_str(), "rendered-dom" | "accessibility-tree") {
        command.args(["--epoch", "7"]);
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let input = child
        .stdin
        .take()
        .ok_or_else(|| io::Error::other("Surface CLI stdin missing"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("Surface CLI stdout missing"))?;
    let mut output = BufReader::new(stdout);
    let ready = next_reply(&mut output)?;
    Ok((child, input, output, ready))
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions intentionally fail when an offline Document class loses CLI parity."
)]
fn cli_reads_all_six_documents_with_the_shared_protocol_and_no_action_authority() -> TestResult {
    let cases: Cases =
        serde_json::from_str(include_str!("../../../python/parity/surface-vectors.json"))?;
    let directory = tempfile::tempdir()?;
    for case in cases.cases {
        let format = match case.format.as_str() {
            "rendered_dom" => "rendered-dom",
            "accessibility_tree" => "accessibility-tree",
            value => value,
        };
        let case = Case {
            format: format.into(),
            ..case
        };
        let (mut child, mut input, mut output, ready) = start(&directory, &case)?;
        assert_eq!(ready["ok"], Value::Bool(true), "{}: {ready}", case.format);
        assert_eq!(
            ready["result"]["controllable"],
            Value::Bool(false),
            "{}",
            case.format
        );
        assert_eq!(
            ready["result"]["descriptor"]["controllable"],
            Value::Bool(false)
        );

        let describe = exchange(&mut input, &mut output, &json!({"id":1,"op":"describe"}))?;
        assert_eq!(
            describe["ok"],
            Value::Bool(true),
            "{}: {describe}",
            case.format
        );
        let expanded = exchange(
            &mut input,
            &mut output,
            &json!({
                "id":2,
                "op":"read",
                "request":{"operation":{"kind":"expand","reference":ready["result"]["root"]}},
            }),
        )?;
        assert_eq!(
            expanded["ok"],
            Value::Bool(true),
            "{}: {expanded}",
            case.format
        );
        assert_eq!(expanded["result"]["kind"], "page");
        assert!(serde_json::to_vec(&expanded["result"])?.len() <= 1024);
        for operation in ["overview", "search"] {
            let request = match operation {
                "overview" => json!({"operation":{"kind":"overview"}}),
                _ => json!({"operation":{"kind":"search","query":case.query}}),
            };
            let result = exchange(
                &mut input,
                &mut output,
                &json!({"id":2,"op":"read","request":request}),
            )?;
            assert_eq!(
                result["ok"],
                Value::Bool(true),
                "{} {operation}: {result}",
                case.format
            );
            assert_eq!(result["result"]["kind"], "page");
            assert!(serde_json::to_vec(&result["result"])?.len() <= 1024);
            if operation == "search" {
                let reference = result["result"]["data"]["entries"]
                    .as_array()
                    .and_then(|entries| entries.first())
                    .and_then(|entry| entry.get("reference"))
                    .cloned()
                    .ok_or_else(|| io::Error::other("CLI search returned no evidence"))?;
                let inspect = exchange(
                    &mut input,
                    &mut output,
                    &json!({
                        "id":3,
                        "op":"read",
                        "request":{"operation":{"kind":"inspect","reference":reference}},
                    }),
                )?;
                assert_eq!(
                    inspect["ok"],
                    Value::Bool(true),
                    "{}: {inspect}",
                    case.format
                );
                assert_eq!(inspect["result"]["kind"], "inspection");
                assert!(serde_json::to_vec(&inspect["result"])?.len() <= 1024);
                let parent = exchange(
                    &mut input,
                    &mut output,
                    &json!({
                        "id":4,
                        "op":"read",
                        "request":{"operation":{"kind":"parent","reference":reference}},
                    }),
                )?;
                assert_eq!(parent["ok"], Value::Bool(true), "{}: {parent}", case.format);
                assert_eq!(parent["result"]["kind"], "parent");
            }
        }

        let invalid = exchange(
            &mut input,
            &mut output,
            &json!({
                "id":4,
                "op":"read",
                "request":{"operation":{"kind":"search","query":""}},
            }),
        )?;
        assert_eq!(invalid["ok"], Value::Bool(false), "{}", case.format);
        let rejected = exchange(&mut input, &mut output, &json!({"id":5,"op":"click"}))?;
        assert_eq!(rejected["ok"], Value::Bool(false), "{}", case.format);
        let closed = exchange(&mut input, &mut output, &json!({"id":6,"op":"close"}))?;
        assert_eq!(closed["ok"], Value::Bool(true), "{}", case.format);
        drop(input);
        let status = child.wait()?;
        assert!(status.success(), "{}: {status}", case.format);
    }
    Ok(())
}
