use std::{
    collections::BTreeMap,
    env::{args_os, split_paths, var_os},
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use anyhow::{Context, Result, bail};

mod benchmark;
mod benchmark_results;
mod docs;
mod fixtures;
mod fuzz;
mod release;
mod sdk_boundary;
mod version;

const HELP: &str = "\
Repository development tasks

Usage: cargo xtask <task>

Tasks:
  release <command>            Prepare, check, export, and index reviewed release notes
  bump-version <VERSION> [--date-released YYYY-MM-DD] [--dry-run|--check] [-y|--yes]
                               Synchronize release versions and optional citation date
  fmt                          Check Rust formatting
  clippy                       Run Clippy for all targets and features
  test                         Run the workspace test suite with nextest
  deny                         Check dependency advisories, licenses, bans, and sources
  file-lines                   Warn when a Rust source file exceeds 400 lines
  source-size                  Enforce the 400-line production source budget
  check                        Run fmt, clippy, source-size, file-lines, test, and deny
  sdk-boundary                 Compile downstream SDK visibility checks, one worker
  fixtures [verify|materialize] Verify or extract committed locator fixture bytes
  fuzz                         Run the deterministic Direct HTTP fuzz smoke profile
  docs manifest <command>      Generate public-doc manifests and manage version catalogs
  docs reference <command>     Generate, verify, and pack commit-pinned Rust references
  docs check                   Run focused documentation tooling tests serially
  benchmark check              Compile every repository benchmark harness
  benchmark criterion [out]    Collect raw Criterion estimates
  benchmark deterministic [out] Run Gungraun Callgrind measurements
  benchmark allocations [out]  Run Divan allocation count/byte measurements
  benchmark process [out]      Run fresh-process GNU time and raw perf measurements
  benchmark heap [out]         Run fresh-process raw Massif profiles
  benchmark all                Run capture measurement classes sequentially
  benchmark result-dir <class> Print the per-change result directory
  benchmark publish <src> <dst> Retain the previous run and publish a completed result
";

fn main() -> Result<()> {
    let mut arguments = args_os().skip(1);
    let Some(task) = arguments.next() else {
        print!("{HELP}");
        return Ok(());
    };

    match task.to_str() {
        Some("bump-version") => version::run(arguments),
        Some("release") => release::run(arguments),
        Some("docs") => docs::run(arguments),
        Some("sdk-boundary") => no_extra_arguments(arguments).and_then(|()| sdk_boundary::run()),
        Some("benchmark") => benchmark::run(arguments),
        Some("fmt") => no_extra_arguments(arguments).and_then(|()| fmt()),
        Some("clippy") => no_extra_arguments(arguments).and_then(|()| clippy()),
        Some("test") => no_extra_arguments(arguments).and_then(|()| test()),
        Some("deny") => no_extra_arguments(arguments).and_then(|()| deny()),
        Some("file-lines") => no_extra_arguments(arguments).and_then(|()| file_lines()),
        Some("source-size") => no_extra_arguments(arguments).and_then(|()| source_size()),
        Some("check") => no_extra_arguments(arguments).and_then(|()| check()),
        Some("fixtures") => fixtures::run(arguments),
        Some("fuzz") => no_extra_arguments(arguments).and_then(|()| fuzz::run()),
        Some("help" | "--help" | "-h") => {
            no_extra_arguments(arguments)?;
            print!("{HELP}");
            Ok(())
        }
        Some(task) => bail!("unknown task `{task}`\n\n{HELP}"),
        None => bail!("task name must be valid Unicode\n\n{HELP}"),
    }
}

fn no_extra_arguments(mut arguments: impl Iterator<Item = OsString>) -> Result<()> {
    if arguments.next().is_some() {
        bail!("task does not accept additional arguments\n\n{HELP}");
    }
    Ok(())
}

fn benchmark_check() -> Result<()> {
    run_cargo(
        "Criterion benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-benchmarks",
            "--bench",
            "criterion_capture",
            "--no-run",
        ],
    )?;
    run_cargo(
        "document-locator Criterion benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-document-locator-benchmarks",
            "--bench",
            "criterion_document_locators",
            "--no-run",
        ],
    )?;
    run_cargo(
        "decoded-text Criterion benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-document-locator-benchmarks",
            "--bench",
            "criterion_documents",
            "--no-run",
        ],
    )?;
    run_cargo(
        "HTML and rendered-DOM Criterion benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-document-locator-benchmarks",
            "--bench",
            "document_locators",
            "--no-run",
        ],
    )?;
    run_cargo(
        "JSON document-locator Criterion benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-document-locator-benchmarks",
            "--bench",
            "criterion_json",
            "--no-run",
        ],
    )?;
    run_cargo(
        "document-locator allocation benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-document-locator-benchmarks",
            "--bench",
            "allocation_document_locators",
            "--no-run",
        ],
    )?;
    run_cargo(
        "Gungraun benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-benchmarks",
            "--bench",
            "gungraun_capture",
            "--no-run",
        ],
    )?;
    run_cargo(
        "allocation benchmark compilation",
        &[
            "bench",
            "-p",
            "yosoi-benchmarks",
            "--bench",
            "allocation_capture",
            "--no-run",
        ],
    )?;
    run_cargo(
        "process benchmark compilation",
        &[
            "build",
            "--release",
            "-p",
            "yosoi-benchmarks",
            "--bin",
            "profile_capture",
        ],
    )?;
    run_cargo(
        "browser Criterion harness compilation",
        &[
            "bench",
            "-p",
            "yosoi-benchmarks",
            "--bench",
            "criterion_browser",
            "--no-run",
        ],
    )?;
    run_cargo(
        "browser allocation harness compilation",
        &[
            "bench",
            "-p",
            "yosoi-benchmarks",
            "--bench",
            "allocation_browser",
            "--no-run",
        ],
    )?;
    run_cargo(
        "browser profile compilation",
        &[
            "build",
            "--release",
            "-p",
            "yosoi-benchmarks",
            "--bin",
            "profile_browser",
        ],
    )?;
    run_cargo(
        "browser execution profile compilation",
        &[
            "build",
            "--release",
            "-p",
            "yosoi-benchmarks",
            "--bin",
            "profile_browser_execution",
        ],
    )?;
    run_cargo(
        "browser stealth profile compilation",
        &[
            "build",
            "--release",
            "-p",
            "yosoi-benchmarks",
            "--bin",
            "profile_browser_stealth",
        ],
    )?;
    run_cargo(
        "benchmark contract test compilation",
        &[
            "test",
            "-p",
            "yosoi-benchmarks",
            "--test",
            "benchmark_contract",
            "--no-run",
        ],
    )
}

fn workspace_root() -> Result<&'static Path> {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .context("xtask manifest directory must have a workspace parent")
}

fn require_command(command: &str, guidance: &str) -> Result<PathBuf> {
    let path =
        find_command(command).with_context(|| format!("`{command}` is unavailable; {guidance}"))?;
    let output = Command::new(&path)
        .arg("--version")
        .output()
        .with_context(|| format!("failed to inspect `{command}`"))?;
    if !output.status.success() {
        bail!("`{command} --version` failed; {guidance}");
    }
    path.canonicalize()
        .with_context(|| format!("failed to resolve `{command}` path"))
}

fn find_command(command: &str) -> Option<PathBuf> {
    let path = var_os("PATH")?;
    split_paths(&path)
        .map(|directory| directory.join(command))
        .find(|candidate| candidate.is_file())
}

fn fmt() -> Result<()> {
    // `cargo fmt --all` also traverses local path dependencies. During the
    // approved VoidCrawl dogfood override that would format a sibling
    // repository and its vendored sources. Name this workspace's packages
    // explicitly so the gate remains repository-scoped.
    run_cargo(
        "fmt",
        &[
            "fmt",
            "--package",
            "yosoi",
            "--package",
            "yosoi-archive",
            "--package",
            "yosoi-contracts",
            "--package",
            "yosoi-contracts-derive",
            "--package",
            "yosoi-contracts-renamed-dependency-fixture",
            "--package",
            "yosoi-contract-validation",
            "--package",
            "yosoi-extractor",
            "--package",
            "yosoi-types",
            "--package",
            "yosoi-documents",
            "--package",
            "yosoi-web-capture",
            "--package",
            "yosoi-web-capture-direct-http",
            "--package",
            "void_crawl_core",
            "--package",
            "yosoi-benchmarks",
            "--package",
            "yosoi-document-locator-benchmarks",
            "--package",
            "xtask",
            "--",
            "--check",
        ],
    )
}

fn clippy() -> Result<()> {
    run_cargo(
        "clippy",
        &[
            "clippy",
            "--workspace",
            "--all-targets",
            "--all-features",
            "--",
            "-D",
            "warnings",
        ],
    )
}

fn test() -> Result<()> {
    run_cargo(
        "nextest",
        &["nextest", "run", "--workspace", "--all-features"],
    )?;
    run_cargo("yosoi doctests", &["test", "--package", "yosoi", "--doc"])
}

fn deny() -> Result<()> {
    run_cargo("deny", &["deny", "check"])
}

fn check() -> Result<()> {
    fmt()?;
    clippy()?;
    source_size()?;
    file_lines()?;
    test()?;
    deny()
}

const RUST_FILE_LINE_GUIDELINE: usize = 400;
const SOURCE_SIZE_BASELINE: &str = include_str!("../source-size-baseline.txt");

fn source_size() -> Result<()> {
    let workspace_root = workspace_root()?;
    let baseline = parse_source_size_baseline(SOURCE_SIZE_BASELINE)?;
    let mut rust_files = Vec::new();
    collect_rust_files(&workspace_root.join("crates"), &mut rust_files)?;
    rust_files.sort();

    let mut observed_grandfathers = BTreeMap::new();
    let mut violations = Vec::new();
    for path in rust_files {
        let relative = path.strip_prefix(workspace_root).unwrap_or(&path);
        if !is_production_source(relative) {
            continue;
        }
        let relative = relative.to_string_lossy().replace('\\', "/");
        let source = fs::read_to_string(&path)
            .with_context(|| format!("failed to read Rust source {}", path.display()))?;
        let line_count = source.lines().count();
        if line_count <= RUST_FILE_LINE_GUIDELINE {
            if baseline.contains_key(relative.as_str()) {
                violations.push(format!(
                    "{relative} is now {line_count} lines; remove its obsolete grandfather entry"
                ));
            }
            continue;
        }

        match baseline.get(relative.as_str()).copied() {
            Some(maximum) if line_count <= maximum => {
                observed_grandfathers.insert(relative, line_count);
            }
            Some(maximum) => violations.push(format!(
                "{relative} grew to {line_count} lines above its grandfathered ceiling of {maximum}"
            )),
            None => violations.push(format!(
                "{relative} has {line_count} lines and is not grandfathered (target: {RUST_FILE_LINE_GUIDELINE})"
            )),
        }
    }

    for path in baseline.keys() {
        if !observed_grandfathers.contains_key(*path)
            && !violations.iter().any(|item| item.starts_with(*path))
        {
            violations.push(format!(
                "{path} is missing; remove or update its stale grandfather entry"
            ));
        }
    }

    if violations.is_empty() {
        println!(
            "source-size: production sources satisfy the {RUST_FILE_LINE_GUIDELINE}-line target ({} grandfathered)",
            observed_grandfathers.len()
        );
        return Ok(());
    }

    violations.sort();
    bail!(
        "production source-size policy failed:\n  - {}\nhelp: split the changed source behind a small module facade; do not add or raise a grandfather entry",
        violations.join("\n  - ")
    )
}

fn parse_source_size_baseline(source: &str) -> Result<BTreeMap<&str, usize>> {
    let mut baseline = BTreeMap::new();
    for (index, line) in source.lines().enumerate() {
        let line_number = index
            .checked_add(1)
            .context("source-size baseline line number overflowed")?;
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((path, maximum)) = line.split_once('\t') else {
            bail!("invalid source-size baseline line {line_number}");
        };
        let maximum = maximum
            .parse::<usize>()
            .with_context(|| format!("invalid line ceiling on baseline line {line_number}"))?;
        if maximum <= RUST_FILE_LINE_GUIDELINE {
            bail!("unnecessary source-size baseline entry for {path}");
        }
        if baseline.insert(path, maximum).is_some() {
            bail!("duplicate source-size baseline entry for {path}");
        }
    }
    Ok(baseline)
}

fn is_production_source(relative: &Path) -> bool {
    let Some(file_name) = relative.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    relative.starts_with("crates")
        && relative
            .components()
            .any(|component| component.as_os_str() == "src")
        && file_name != "tests.rs"
        && !file_name.ends_with("_tests.rs")
}

fn file_lines() -> Result<()> {
    let workspace_root = workspace_root()?;
    let mut rust_files = Vec::new();
    collect_rust_files(workspace_root, &mut rust_files)?;
    rust_files.sort();

    for path in rust_files {
        let source = fs::read_to_string(&path)
            .with_context(|| format!("failed to read Rust source {}", path.display()))?;
        let line_count = source.lines().count();
        if exceeds_file_line_guideline(line_count) {
            let relative = path.strip_prefix(workspace_root).unwrap_or(&path);
            eprintln!(
                "warning[file-lines]: {} has {line_count} lines (guideline: {RUST_FILE_LINE_GUIDELINE})",
                relative.display()
            );
            eprintln!(
                "  help: split cohesive code into a module directory with a small mod.rs facade, or split tests into focused files"
            );
        }
    }

    Ok(())
}

const fn exceeds_file_line_guideline(line_count: usize) -> bool {
    line_count > RUST_FILE_LINE_GUIDELINE
}

fn collect_rust_files(directory: &Path, files: &mut Vec<PathBuf>) -> Result<()> {
    for entry in fs::read_dir(directory)
        .with_context(|| format!("failed to read directory {}", directory.display()))?
    {
        let entry =
            entry.with_context(|| format!("failed to read an entry in {}", directory.display()))?;
        let path = entry.path();
        let file_type = entry
            .file_type()
            .with_context(|| format!("failed to inspect {}", path.display()))?;

        if file_type.is_dir() {
            if !is_ignored_directory(&path) {
                collect_rust_files(&path, files)?;
            }
        } else if file_type.is_file() && path.extension().is_some_and(|extension| extension == "rs")
        {
            files.push(path);
        }
    }
    Ok(())
}

fn is_ignored_directory(path: &Path) -> bool {
    path.file_name()
        .is_some_and(|name| matches!(name.to_str(), Some(".git" | ".jj" | "target" | "vendor")))
}

fn run_cargo(task: &str, arguments: &[&str]) -> Result<()> {
    let status = Command::new("cargo")
        .args(arguments)
        .status()
        .with_context(|| format!("failed to start cargo for the {task} task"))?;

    if !status.success() {
        bail!("the {task} task failed with {status}");
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        HELP, exceeds_file_line_guideline, is_production_source, parse_source_size_baseline,
    };

    #[test]
    fn help_documents_every_task() {
        for task in [
            "fmt",
            "clippy",
            "test",
            "deny",
            "file-lines",
            "source-size",
            "check",
            "fuzz",
            "benchmark check",
            "benchmark criterion",
            "benchmark deterministic",
            "benchmark allocations",
            "benchmark process",
            "benchmark heap",
            "benchmark result-dir",
            "benchmark publish",
            "fixtures",
            "benchmark all",
        ] {
            assert!(HELP.lines().any(|line| line.trim_start().starts_with(task)));
        }
    }

    #[test]
    fn file_line_guideline_warns_only_above_four_hundred_lines() {
        assert!(!exceeds_file_line_guideline(399));
        assert!(!exceeds_file_line_guideline(400));
        assert!(exceeds_file_line_guideline(401));
    }

    #[test]
    fn source_size_baseline_is_strict_and_production_scope_excludes_tests() {
        let baseline = parse_source_size_baseline(
            "# grandfathered production files\ncrates/example/src/large.rs\t401\n",
        )
        .unwrap();
        assert_eq!(baseline.get("crates/example/src/large.rs"), Some(&401));
        assert!(is_production_source(Path::new(
            "crates/example/src/large.rs"
        )));
        assert!(!is_production_source(Path::new(
            "crates/example/src/large_tests.rs"
        )));
        assert!(!is_production_source(Path::new(
            "crates/example/tests/large.rs"
        )));
    }
}
