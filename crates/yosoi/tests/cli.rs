#![cfg(feature = "cli")]
#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail integration tests.

use std::{
    error::Error,
    fs,
    io::{self, Write},
    path::Path,
    process::{Command, Output, Stdio},
};

fn run_yosoi(args: &[&str]) -> io::Result<Output> {
    Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(args)
        .output()
}

#[test]
fn search_replay_accepts_a_manifest_filename_in_the_current_directory() -> Result<(), Box<dyn Error>>
{
    let directory = tempfile::tempdir()?;
    fs::write(
        directory.path().join("manifest.json"),
        br#"{"schema_version":1,"records":[]}"#,
    )?;
    let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .current_dir(directory.path())
        .args(["search", "replay", "manifest.json"])
        .output()?;
    if cfg!(not(unix)) {
        assert_eq!(output.status.code(), Some(1));
        assert!(String::from_utf8_lossy(&output.stderr).contains("not certified"));
        return Ok(());
    }
    // An empty, valid evidence bundle has no documents to replay (exit 2).
    // Opening its Archive must succeed rather than fail with EmptyRoot (exit 1).
    assert_eq!(output.status.code(), Some(2), "{output:?}");
    let report: serde_json::Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(report["record_count"], 0);
    assert_eq!(report["network_requests"], 0);
    Ok(())
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
fn surface_image_help_exposes_bounded_pixel_inputs() -> Result<(), Box<dyn Error>> {
    let output = run_yosoi(&["surface", "image", "--help"])?;

    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr.as_slice(), b"");
    let help = String::from_utf8_lossy(&output.stdout);
    for option in [
        "--file",
        "--pixel-artifact-ref",
        "--archive",
        "--max-source-bytes",
        "--max-decoded-bytes",
        "--max-output-pixels",
        "--max-output-bytes",
        "--max-retained-artifacts",
    ] {
        assert!(help.contains(option), "{option}");
    }
    assert_no_ansi(&output.stdout);
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
fn surface_image_cli_returns_direct_overview_and_crop_artifacts() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let source_path = directory.path().join("known-pixels.png");
    let output_directory = directory.path().join("image-output");
    let archive_root = directory.path().join("image-archive");
    let pixels = image::RgbaImage::from_fn(8, 4, |x, y| {
        if x < 4 && y < 2 {
            image::Rgba([240, 10, 20, 255])
        } else {
            image::Rgba([10, 30, 240, 255])
        }
    });
    let mut encoded = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let source_bytes = encoded.into_inner();
    fs::write(&source_path, &source_bytes)?;

    let mut child = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args([
            "surface",
            "image",
            "--file",
            source_path.to_str().ok_or("source path is not UTF-8")?,
            "--output",
            output_directory
                .to_str()
                .ok_or("output path is not UTF-8")?,
            "--archive",
            archive_root.to_str().ok_or("archive path is not UTF-8")?,
            "--max-retained-artifacts",
            "3",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let Some(mut input) = child.stdin.take() else {
        return Err("surface image CLI stdin is unavailable".into());
    };
    writeln!(input, r#"{{"id":"direct","op":"image_direct"}}"#)?;
    writeln!(
        input,
        r#"{{"id":"overview","op":"overview_image","max_side":4}}"#
    )?;
    writeln!(
        input,
        r#"{{"id":"crop","op":"crop_image","rect":{{"x":0,"y":0,"width":4,"height":2}}}}"#
    )?;
    writeln!(
        input,
        r#"{{"id":"retention-limit","op":"resize_image","width":4,"height":2}}"#
    )?;
    writeln!(input, r#"{{"id":"close","op":"close"}}"#)?;
    drop(input);
    let output = child.wait_with_output()?;
    assert_eq!(output.status.code(), Some(0), "{output:?}");
    assert_eq!(output.stderr.as_slice(), b"");

    let stdout = String::from_utf8(output.stdout)?;
    let mut replies = std::collections::BTreeMap::new();
    for line in stdout.lines() {
        let reply: serde_json::Value = serde_json::from_str(line)?;
        if let Some(id) = reply.get("id").and_then(serde_json::Value::as_str) {
            replies.insert(id.to_owned(), reply);
        }
    }
    let artifact_path = |id: &str| -> Result<std::path::PathBuf, Box<dyn Error>> {
        let value = replies
            .get(id)
            .and_then(|reply| reply.pointer("/result/artifact/path"))
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| format!("{id} image artifact path is missing"))?;
        Ok(value.into())
    };

    let direct_path = artifact_path("direct")?;
    assert_eq!(fs::read(direct_path)?, source_bytes);
    let direct_reply = replies
        .get("direct")
        .ok_or("direct image CLI reply is missing")?;
    let pixel_reference = direct_reply
        .pointer("/result/artifact/archive_ref")
        .filter(|value| !value.is_null())
        .ok_or("direct image Archive reference is missing")?;
    let pixel_reference_json = serde_json::to_string(pixel_reference)?;
    let overview_path = artifact_path("overview")?;
    let overview = image::load_from_memory(&fs::read(overview_path)?)?.to_rgba8();
    assert_eq!(overview.dimensions(), (4, 2));
    let crop_path = artifact_path("crop")?;
    let crop = image::load_from_memory(&fs::read(crop_path)?)?.to_rgba8();
    assert_eq!(crop.dimensions(), (4, 2));
    assert_eq!(crop.get_pixel(0, 0).0, [240, 10, 20, 255]);
    let retention_limit_reply = replies
        .get("retention-limit")
        .ok_or("retained-artifact limit reply is missing")?;
    assert_eq!(
        retention_limit_reply.get("ok"),
        Some(&serde_json::Value::Bool(false))
    );
    assert!(
        retention_limit_reply
            .get("error")
            .and_then(serde_json::Value::as_str)
            .is_some_and(|error| error.contains("retained image artifact limit"))
    );

    fs::remove_file(&source_path)?;
    let reopened_output = directory.path().join("reopened-image-output");
    let mut reopened = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args([
            "surface",
            "image",
            "--pixel-artifact-ref",
            &pixel_reference_json,
            "--archive",
            archive_root.to_str().ok_or("archive path is not UTF-8")?,
            "--output",
            reopened_output
                .to_str()
                .ok_or("reopened output path is not UTF-8")?,
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let Some(mut reopened_input) = reopened.stdin.take() else {
        return Err("reopened image CLI stdin is unavailable".into());
    };
    writeln!(reopened_input, r#"{{"id":"direct","op":"image_direct"}}"#)?;
    writeln!(reopened_input, r#"{{"id":"close","op":"close"}}"#)?;
    drop(reopened_input);
    let reopened_output_result = reopened.wait_with_output()?;
    assert_eq!(
        reopened_output_result.status.code(),
        Some(0),
        "{reopened_output_result:?}"
    );
    assert_eq!(reopened_output_result.stderr.as_slice(), b"");
    let reopened_replies: std::collections::BTreeMap<String, serde_json::Value> =
        String::from_utf8(reopened_output_result.stdout)?
            .lines()
            .filter_map(|line| serde_json::from_str(line).ok())
            .filter_map(|reply: serde_json::Value| {
                let id = reply
                    .get("id")
                    .and_then(serde_json::Value::as_str)
                    .map(str::to_owned)?;
                Some((id, reply))
            })
            .collect();
    let reopened_direct = reopened_replies
        .get("direct")
        .ok_or("reopened direct image CLI reply is missing")?;
    let reopened_artifact = reopened_direct
        .pointer("/result/artifact")
        .ok_or("reopened direct image artifact is missing")?;
    assert_eq!(
        reopened_artifact.pointer("/info/identity"),
        direct_reply.pointer("/result/artifact/info/identity")
    );
    let reopened_path = reopened_artifact
        .get("path")
        .and_then(serde_json::Value::as_str)
        .ok_or("reopened direct image path is missing")?;
    let reopened_pixels = image::load_from_memory(&fs::read(reopened_path)?)?.to_rgba8();
    assert_eq!(reopened_pixels.dimensions(), (8, 4));
    assert_eq!(reopened_pixels.get_pixel(0, 0).0, [240, 10, 20, 255]);
    assert!(reopened_output.join("surface.yosoi").is_file());
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
fn sdk_manifest_retains_a_feature_gated_cli_and_private_runtime_boundary()
-> Result<(), Box<dyn Error>> {
    let manifest_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
    let manifest_text = fs::read_to_string(manifest_path)?;
    let manifest: toml::Value = toml::from_str(&manifest_text)?;

    let sdk_marker = manifest
        .get("package")
        .and_then(|package| package.get("metadata"))
        .and_then(|metadata| metadata.get("yosoi"))
        .and_then(|metadata| metadata.get("sdk"))
        .and_then(toml::Value::as_bool);
    assert_eq!(sdk_marker, Some(true));

    let cli_target = manifest
        .get("bin")
        .and_then(toml::Value::as_array)
        .and_then(|targets| {
            targets
                .iter()
                .find(|target| target.get("name").and_then(toml::Value::as_str) == Some("yosoi"))
        })
        .ok_or("SDK manifest must declare the yosoi CLI binary")?;
    let required_features = cli_target
        .get("required-features")
        .and_then(toml::Value::as_array)
        .ok_or("CLI binary must declare required features")?;
    assert!(
        required_features
            .iter()
            .any(|feature| feature.as_str() == Some("cli"))
    );

    let mut package_names = Vec::new();
    collect_dependency_package_names(&manifest, &mut package_names);
    let retired_runtime_packages = [
        "yosoi-browser-core",
        "yosoi-archive",
        "yosoi-contract-validation",
        "yosoi-contracts",
        "yosoi-documents",
        "yosoi-engine",
        "yosoi-extractor",
        "yosoi-map",
        "yosoi-policy",
        "yosoi-types",
        "yosoi-web-capture",
        "yosoi-web-capture-direct-http",
    ];
    for package_name in package_names {
        assert!(
            !retired_runtime_packages.contains(&package_name.as_str()),
            "SDK manifest must not depend on retired runtime package {package_name}"
        );
    }
    Ok(())
}

#[test]
fn self_maintenance_help_and_syntax_are_available() -> Result<(), Box<dyn Error>> {
    for args in [
        vec!["self", "--help"],
        vec!["self", "update", "--help"],
        vec!["self", "uninstall", "--help"],
    ] {
        let output = run_yosoi(&args)?;
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
    let update = run_yosoi(&["self", "update", "--help"])?;
    let text = String::from_utf8(update.stdout)?;
    assert!(text.contains("--target-version"));
    assert!(text.contains("--yes"));
    let invalid = run_yosoi(&["self", "unknown"])?;
    assert_eq!(invalid.status.code(), Some(2));
    let profile = run_yosoi(&["--profile", "example", "self", "uninstall", "--yes"])?;
    assert!(!profile.status.success());
    assert!(String::from_utf8(profile.stderr)?.contains("--profile does not apply"));
    Ok(())
}
