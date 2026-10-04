//! Native orchestration for serial capture measurements; browser matrices remain separate.
use std::{
    env,
    ffi::OsString,
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
};

use anyhow::{Context, Result, bail};

use super::benchmark_results::{copy_directory, publish, result_directory, write_identity};

#[derive(Clone, Copy)]
enum Measurement {
    Criterion,
    Callgrind,
    Allocations,
    Process,
    Heap,
}

impl Measurement {
    fn parse(value: &str) -> Result<Self> {
        match value {
            "criterion" => Ok(Self::Criterion),
            "deterministic" | "callgrind" => Ok(Self::Callgrind),
            "allocations" => Ok(Self::Allocations),
            "process" => Ok(Self::Process),
            "heap" => Ok(Self::Heap),
            _ => bail!("unknown capture measurement class `{value}`"),
        }
    }
    const fn name(self) -> &'static str {
        match self {
            Self::Criterion => "criterion",
            Self::Callgrind => "callgrind",
            Self::Allocations => "allocations",
            Self::Process => "process",
            Self::Heap => "heap",
        }
    }
}

pub fn run(mut arguments: impl Iterator<Item = OsString>) -> Result<()> {
    let task = arguments
        .next()
        .context("benchmark requires a measurement class; see cargo xtask --help")?;
    let task = task.to_str().context("benchmark class must be Unicode")?;
    match task {
        "result-dir" => {
            let class = arguments
                .next()
                .context("result-dir requires a measurement class")?;
            let class = class
                .to_str()
                .context("measurement class must be Unicode")?;
            let class = if class == "browser" {
                "browser"
            } else {
                Measurement::parse(class)?.name()
            };
            super::no_extra_arguments(arguments)?;
            println!("{}", result_directory(class)?.display());
            Ok(())
        }
        "publish" => {
            let staging = arguments
                .next()
                .context("publish requires staging and destination")?;
            let destination = arguments.next().context("publish requires destination")?;
            super::no_extra_arguments(arguments)?;
            publish(Path::new(&staging), Path::new(&destination))
        }
        "check" => {
            super::no_extra_arguments(arguments)?;
            super::benchmark_check()
        }
        "all" => {
            super::no_extra_arguments(arguments)?;
            for class in [
                Measurement::Criterion,
                Measurement::Callgrind,
                Measurement::Allocations,
                Measurement::Process,
                Measurement::Heap,
            ] {
                measure(class, None)?;
            }
            Ok(())
        }
        value => {
            let class = Measurement::parse(value)?;
            let destination = arguments.next().map(PathBuf::from);
            super::no_extra_arguments(arguments)?;
            measure(class, destination)
        }
    }
}

fn measure(class: Measurement, destination: Option<PathBuf>) -> Result<()> {
    preflight(class)?;
    let root = super::workspace_root()?;
    let destination = match destination {
        Some(path) => path,
        None => result_directory(class.name())?,
    };
    let destination = root.join(destination);
    let parent = destination
        .parent()
        .context("measurement destination requires a parent")?;
    fs::create_dir_all(root.join("target"))?;
    let lock = File::create(root.join("target/.capture-benchmark.lock"))?;
    lock.try_lock()
        .context("another capture measurement is running; run measurements sequentially")?;
    fs::create_dir_all(parent)?;
    let staging = tempfile::Builder::new()
        .prefix(".benchmark-staging-")
        .tempdir_in(parent)?;
    write_identity(staging.path(), class.name())?;
    if let Err(error) = collect(class, staging.path()) {
        let diagnostics = staging.keep();
        return Err(error).with_context(|| {
            format!(
                "measurement failed; previous result unchanged; diagnostics at {}",
                diagnostics.display()
            )
        });
    }
    publish(staging.path(), &destination)?;
    println!(
        "{} measurement written to {}",
        class.name(),
        destination.display()
    );
    Ok(())
}

fn preflight(class: Measurement) -> Result<()> {
    match class {
        Measurement::Callgrind => {
            super::require_command("valgrind", "install Valgrind for Callgrind")?;
            super::require_command(
                "gungraun-runner",
                "cargo install gungraun-runner --version 0.19.4 --locked",
            )?;
        }
        Measurement::Process => {
            super::require_command("/usr/bin/time", "install GNU time")?;
            super::require_command("perf", "install perf")?;
        }
        Measurement::Heap => {
            super::require_command("valgrind", "install Valgrind for Massif")?;
        }
        Measurement::Criterion | Measurement::Allocations => {}
    }
    Ok(())
}

fn cargo() -> Result<Command> {
    let mut command = Command::new("cargo");
    command
        .current_dir(super::workspace_root()?)
        .env("CARGO_BUILD_JOBS", "1")
        .env("CMAKE_BUILD_PARALLEL_LEVEL", "1")
        .env("CARGO_TARGET_DIR", super::workspace_root()?.join("target"));
    Ok(command)
}

fn logged(command: &mut Command, output: &Path, name: &str, required: bool) -> Result<ExitStatus> {
    fs::write(
        output.join(format!("{name}.command.txt")),
        format!("{command:?}\n"),
    )?;
    let stdout = File::create(output.join(format!("{name}.stdout.txt")))?;
    let stderr = File::create(output.join(format!("{name}.stderr.txt")))?;
    let status = command
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .status()
        .with_context(|| format!("failed to start {name}"))?;
    fs::write(
        output.join(format!("{name}.status.txt")),
        format!("{status}\n"),
    )?;
    if required && !status.success() {
        bail!("{name} failed with {status}; see {}", output.display());
    }
    Ok(status)
}

fn collect(class: Measurement, output: &Path) -> Result<()> {
    match class {
        Measurement::Criterion => {
            let mut command = cargo()?;
            command
                .args([
                    "bench",
                    "--jobs",
                    "1",
                    "-p",
                    "yosoi-benchmarks",
                    "--bench",
                    "criterion_capture",
                    "--",
                    "--warm-up-time",
                    "1",
                    "--measurement-time",
                    "2",
                    "--sample-size",
                    "10",
                    "--noplot",
                ])
                .env("CRITERION_HOME", output.join("criterion-raw"));
            logged(&mut command, output, "criterion", true)?;
            if !output.join("criterion-raw").is_dir() {
                bail!("Criterion produced no raw estimates");
            }
        }
        Measurement::Callgrind => {
            let raw =
                super::workspace_root()?.join("target/gungraun/yosoi-benchmarks/gungraun_capture");
            if raw.exists() {
                fs::remove_dir_all(&raw)?;
            }
            let mut command = cargo()?;
            command.args([
                "bench",
                "--jobs",
                "1",
                "-p",
                "yosoi-benchmarks",
                "--bench",
                "gungraun_capture",
                "--",
                "--save-summary=pretty-json",
            ]);
            logged(&mut command, output, "callgrind", true)?;
            copy_directory(&raw, &output.join("gungraun-raw"))?;
        }
        Measurement::Allocations => {
            let mut command = cargo()?;
            command.args([
                "bench",
                "--jobs",
                "1",
                "-p",
                "yosoi-benchmarks",
                "--bench",
                "allocation_capture",
                "--",
                "--sample-count",
                "100",
                "--sample-size",
                "1",
                "--color",
                "never",
            ]);
            logged(&mut command, output, "allocations", true)?;
        }
        Measurement::Process | Measurement::Heap => collect_processes(class, output)?,
    }
    Ok(())
}

fn collect_processes(class: Measurement, output: &Path) -> Result<()> {
    let mut build = cargo()?;
    build.args([
        "build",
        "--jobs",
        "1",
        "--release",
        "-p",
        "yosoi-benchmarks",
        "--bin",
        "profile_capture",
    ]);
    logged(&mut build, output, "build", true)?;
    let binary = super::workspace_root()?.join("target/release/profile_capture");
    let iterations = env::var("CAS307_PROCESS_ITERATIONS").unwrap_or_else(|_| "10".to_owned());
    if iterations
        .parse::<u32>()
        .context("CAS307_PROCESS_ITERATIONS must be positive")?
        == 0
    {
        bail!("CAS307_PROCESS_ITERATIONS must be positive");
    }
    for workload in ["full", "compressed", "redirect", "truncated"] {
        match class {
            Measurement::Process => {
                let mut time = Command::new("/usr/bin/time");
                time.args(["-v", "-o"])
                    .arg(output.join(format!("time-{workload}.txt")))
                    .arg(&binary)
                    .args([workload, &iterations]);
                logged(&mut time, output, &format!("time-{workload}"), true)?;
                let mut perf = Command::new("perf");
                perf.args(["stat", "-x", ";", "-e", "task-clock,cycles,instructions,branches,branch-misses,cache-references,cache-misses,context-switches,page-faults", "-o"]).arg(output.join(format!("perf-{workload}.txt"))).arg("--").arg(&binary).args([workload, &iterations]);
                let status = logged(&mut perf, output, &format!("perf-{workload}"), false)?;
                if !status.success() {
                    println!("perf counters unavailable for {workload}; diagnostics retained");
                }
            }
            Measurement::Heap => {
                let mut command = Command::new("valgrind");
                command
                    .args(["--tool=massif", "--stacks=yes", "--time-unit=i"])
                    .arg(format!(
                        "--massif-out-file={}",
                        output.join(format!("massif-{workload}.out")).display()
                    ))
                    .arg(&binary)
                    .args([workload, "1"]);
                logged(&mut command, output, &format!("massif-{workload}"), true)?;
            }
            _ => bail!("expected a process or heap measurement"),
        }
    }
    Ok(())
}
