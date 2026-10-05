#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail integration tests.

use std::{
    error::Error,
    fs, io,
    path::Path,
    process::{Command, Output},
};

fn run_yosoi(args: &[&str]) -> io::Result<Output> {
    Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(args)
        .output()
}

fn assert_no_ansi(bytes: &[u8]) {
    assert!(
        !bytes.windows(2).any(|window| window == b"\x1b["),
        "redirected command output should not contain ANSI escape sequences"
    );
}

#[test]
fn bare_invocation_prints_root_help_to_stdout() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&[])?;

    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr.as_slice(), b"");
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("Usage: yosoi"));
    assert!(stdout.contains("Options:"));
    assert!(stdout.contains("-v, --version"));
    assert!(stdout.contains("-h, --help"));
    assert_no_ansi(&output.stdout);
    Ok(())
}

#[test]
fn explicit_help_prints_root_help_to_stdout() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&["--help"])?;

    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr.as_slice(), b"");
    assert!(String::from_utf8_lossy(&output.stdout).contains("Usage: yosoi"));
    assert_no_ansi(&output.stdout);
    Ok(())
}

#[test]
fn help_name_ignores_capitalization() -> Result<(), Box<dyn Error>> {
    let canonical = run_yosoi(&["--help"])?;
    for spelling in ["-H", "--HELP", "--HeLp"] {
        let output = run_yosoi(&[spelling])?;
        assert_eq!(output.status.code(), Some(0), "{spelling}");
        assert_eq!(output.stderr.as_slice(), b"", "{spelling}");
        assert_eq!(output.stdout, canonical.stdout, "{spelling}");
    }
    Ok(())
}

#[test]
fn explicit_version_prints_version_to_stdout() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&["--version"])?;

    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr.as_slice(), b"");
    assert!(String::from_utf8_lossy(&output.stdout).starts_with("yosoi "));
    assert_no_ansi(&output.stdout);
    Ok(())
}

#[test]
fn version_name_ignores_capitalization() -> Result<(), Box<dyn Error>> {
    let canonical = run_yosoi(&["--version"])?;
    for spelling in ["-v", "-V", "--VERSION", "--VeRsIoN"] {
        let output = run_yosoi(&[spelling])?;
        assert_eq!(output.status.code(), Some(0), "{spelling}");
        assert_eq!(output.stderr.as_slice(), b"", "{spelling}");
        assert_eq!(output.stdout, canonical.stdout, "{spelling}");
    }
    Ok(())
}

#[test]
fn policy_subcommand_version_keeps_lowercase_canonical_spelling() -> Result<(), Box<dyn Error>> {
    for spelling in ["-v", "-V", "--VeRsIoN"] {
        let output = run_yosoi(&["policy", spelling])?;
        assert_eq!(output.status.code(), Some(0), "{spelling}");
        assert_eq!(output.stderr.as_slice(), b"", "{spelling}");
        assert!(String::from_utf8_lossy(&output.stdout).contains(env!("CARGO_PKG_VERSION")));
    }
    Ok(())
}

#[test]
fn unknown_flag_fails_with_only_a_stderr_diagnostic() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&["--not-a-real-option"])?;

    assert_eq!(output.status.code(), Some(2));
    assert_eq!(output.stdout.as_slice(), b"");
    assert_ne!(output.stderr.as_slice(), b"");
    assert_no_ansi(&output.stderr);
    Ok(())
}

#[test]
fn unexpected_operand_fails_with_only_a_stderr_diagnostic() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&["not-a-command"])?;

    assert_eq!(output.status.code(), Some(2));
    assert_eq!(output.stdout.as_slice(), b"");
    assert_ne!(output.stderr.as_slice(), b"");
    assert_no_ansi(&output.stderr);
    Ok(())
}

#[test]
fn misspelled_help_suggests_help_in_diagnostic_only() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&["--hlep"])?;

    assert_eq!(output.status.code(), Some(2));
    assert_eq!(output.stdout.as_slice(), b"");
    assert!(String::from_utf8_lossy(&output.stderr).contains("--help"));
    assert_no_ansi(&output.stderr);
    Ok(())
}

fn collect_dependency_package_names(value: &toml::Value, package_names: &mut Vec<String>) {
    let Some(table) = value.as_table() else {
        return;
    };

    for (key, child) in table {
        if matches!(
            key.as_str(),
            "dependencies" | "dev-dependencies" | "build-dependencies"
        ) {
            if let Some(dependencies) = child.as_table() {
                for (dependency_key, specification) in dependencies {
                    let package_name = specification
                        .get("package")
                        .and_then(toml::Value::as_str)
                        .unwrap_or(dependency_key);
                    package_names.push(package_name.to_owned());
                }
            }
        } else {
            collect_dependency_package_names(child, package_names);
        }
    }
}

#[test]
fn manifest_dependencies_respect_the_crate_boundary() -> Result<(), Box<dyn Error>> {
    let manifest_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
    let manifest_text = fs::read_to_string(manifest_path)?;
    let manifest: toml::Value = toml::from_str(&manifest_text)?;
    let normal_dependencies = manifest
        .get("dependencies")
        .and_then(toml::Value::as_table)
        .ok_or("CLI manifest must declare normal dependencies")?;
    let has_public_sdk_dependency = normal_dependencies.iter().any(|(key, specification)| {
        specification
            .get("package")
            .and_then(toml::Value::as_str)
            .unwrap_or(key)
            == "yosoi"
    });
    assert!(has_public_sdk_dependency);

    let mut package_names = Vec::new();
    collect_dependency_package_names(&manifest, &mut package_names);
    for package_name in package_names {
        assert_ne!(package_name, "void_crawl_core");
        assert_ne!(package_name, "yosoi-engine");
        assert!(package_name == "yosoi" || !package_name.starts_with("yosoi-"));
    }
    Ok(())
}
