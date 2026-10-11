#![allow(clippy::panic_in_result_fn)]
use super::{apply, plan};
use anyhow::Result;
use std::{ffi::OsString, fs, io::Cursor};

#[test]
fn bump_updates_prereleases_renames_targets_and_lockfiles_without_touching_vendor() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    fs::create_dir_all(root.join("crates/demo"))?;
    fs::create_dir_all(root.join("fuzz"))?;
    fs::create_dir_all(root.join("vendor/demo"))?;
    fs::write(
        root.join("Cargo.toml"),
        "[workspace]\nmembers = [\"crates/demo\"]\n[workspace.package]\nversion = \"0.1.0\"\n[workspace.dependencies]\ndemo = { version = \"0.1.0\", path = \"crates/demo\" } # keep\nexternal = \"1\"\n",
    )?;
    fs::write(
        root.join("crates/demo/Cargo.toml"),
        "[package]\nname = \"demo\"\nversion.workspace = true\n[target.'cfg(unix)'.build-dependencies]\nrenamed = { package = \"demo\", path = \".\", version = \"=0.1.0\" }\n",
    )?;
    fs::write(
        root.join("fuzz/Cargo.toml"),
        "[package]\nname = \"demo-fuzz\"\nversion = \"0.0.0\" # keep too\n[dependencies.demo]\npath = \"../crates/demo\"\nversion = \"0.1.0\"\n",
    )?;
    let vendor = "[package]\nname = \"vendor\"\nversion = \"9.0.0\"\n";
    fs::write(root.join("vendor/demo/Cargo.toml"), vendor)?;
    let lock = "version = 4\n[[package]]\nname = \"demo\"\nversion = \"0.1.0\"\n[[package]]\nname = \"demo-fuzz\"\nversion = \"0.0.0\"\ndependencies = [\"demo 0.1.0\", \"external\", \"demo 9.0.0\"]\n[[package]]\nname = \"external\"\nversion = \"1.0.0\"\nsource = \"registry+https://example.com\"\n";
    for path in ["Cargo.lock", "fuzz/Cargo.lock"] {
        fs::write(root.join(path), lock)?;
    }
    fs::write(
        root.join("CITATION.cff"),
        "cff-version: 1.2.0\nversion: \"0.0.3a27\"\ndate-released: 2026-07-31\n",
    )?;
    let changes = plan(root, "0.2.0-beta.3", None)?;
    assert_eq!(changes.len(), 6);
    assert!(fs::read_to_string(root.join("Cargo.toml"))?.contains("0.1.0"));
    apply(&changes)?;
    assert!(plan(root, "0.2.0-beta.3", None)?.is_empty());
    let root_manifest = fs::read_to_string(root.join("Cargo.toml"))?;
    assert!(root_manifest.contains("version = \"=0.2.0-beta.3\""));
    assert!(root_manifest.contains("# keep"));
    assert!(root_manifest.contains("external = \"1\""));
    assert!(
        fs::read_to_string(root.join("crates/demo/Cargo.toml"))?
            .contains("version.workspace = true")
    );
    assert!(fs::read_to_string(root.join("fuzz/Cargo.toml"))?.contains("# keep too"));
    assert!(fs::read_to_string(root.join("Cargo.lock"))?.contains("demo 0.2.0-beta.3"));
    assert!(fs::read_to_string(root.join("Cargo.lock"))?.contains("demo 9.0.0"));
    assert_eq!(
        fs::read_to_string(root.join("vendor/demo/Cargo.toml"))?,
        vendor
    );
    assert!(fs::read_to_string(root.join("CITATION.cff"))?.contains("date-released: 2026-07-31"));
    Ok(())
}

#[test]
fn bump_preserves_independently_versioned_packages_and_exact_requirements() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    fs::create_dir_all(root.join("crates/runtime"))?;
    fs::create_dir_all(root.join("crates/derive"))?;
    fs::write(
        root.join("Cargo.toml"),
        "[workspace]\nmembers = [\"crates/runtime\", \"crates/derive\"]\n[workspace.package]\nversion = \"0.1.0\"\n[workspace.metadata.yosoi-release]\nindependent-version-packages = [\"macro-derive\"]\n[workspace.dependencies]\nruntime = { path = \"crates/runtime\", version = \"=0.1.0\" }\nderive = { package = \"macro-derive\", path = \"crates/derive\", version = \"=0.1.0\" }\n",
    )?;
    fs::write(
        root.join("crates/runtime/Cargo.toml"),
        "[package]\nname = \"runtime\"\nversion.workspace = true\n[dependencies]\nderive.workspace = true\n",
    )?;
    fs::write(
        root.join("crates/derive/Cargo.toml"),
        "[package]\nname = \"macro-derive\"\nversion = \"0.1.0\"\n",
    )?;
    fs::write(
        root.join("Cargo.lock"),
        "version = 4\n[[package]]\nname = \"runtime\"\nversion = \"0.1.0\"\n[[package]]\nname = \"macro-derive\"\nversion = \"0.1.0\"\n",
    )?;
    fs::write(root.join("CITATION.cff"), "version: \"0.1.0\"\n")?;

    apply(&plan(root, "0.1.1", None)?)?;

    let root_manifest = fs::read_to_string(root.join("Cargo.toml"))?;
    assert!(root_manifest.contains("version = \"0.1.1\""));
    assert!(root_manifest.contains("version = \"=0.1.1\""));
    assert!(root_manifest.contains("version = \"=0.1.0\""));
    assert!(
        fs::read_to_string(root.join("crates/runtime/Cargo.toml"))?
            .contains("version.workspace = true")
    );
    assert!(
        fs::read_to_string(root.join("crates/derive/Cargo.toml"))?.contains("version = \"0.1.0\"")
    );
    let lock = fs::read_to_string(root.join("Cargo.lock"))?;
    assert!(lock.contains("name = \"runtime\"\nversion = \"0.1.1\""));
    assert!(lock.contains("name = \"macro-derive\"\nversion = \"0.1.0\""));
    assert!(plan(root, "0.1.1", None)?.is_empty());
    Ok(())
}

#[test]
fn bump_rejects_nonexact_independent_dependency_requirements() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    fs::create_dir_all(root.join("crates/runtime"))?;
    fs::create_dir_all(root.join("crates/derive"))?;
    fs::write(
        root.join("Cargo.toml"),
        "[workspace]\nmembers = [\"crates/runtime\", \"crates/derive\"]\n[workspace.package]\nversion = \"0.1.0\"\n[workspace.metadata.yosoi-release]\nindependent-version-packages = [\"macro-derive\"]\n[workspace.dependencies]\nderive = { package = \"macro-derive\", path = \"crates/derive\", version = \"0.1\" }\n",
    )?;
    fs::write(
        root.join("crates/runtime/Cargo.toml"),
        "[package]\nname = \"runtime\"\nversion.workspace = true\n[dependencies]\nderive.workspace = true\n",
    )?;
    fs::write(
        root.join("crates/derive/Cargo.toml"),
        "[package]\nname = \"macro-derive\"\nversion = \"0.1.0\"\n",
    )?;
    fs::write(root.join("CITATION.cff"), "version: \"0.1.0\"\n")?;

    let error = plan(root, "0.1.1", None).expect_err("broad requirement must be rejected");
    assert!(
        error
            .to_string()
            .contains("exact independent version =0.1.0")
    );
    assert!(!fs::read_to_string(root.join("Cargo.toml"))?.contains("version = \"0.1.1\""));
    Ok(())
}

#[test]
fn invalid_metadata_and_concurrent_edits_leave_files_untouched() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    let manifest = "[workspace]\n[workspace.package]\nversion = \"0.1.0\"\n";
    fs::write(root.join("Cargo.toml"), manifest)?;
    fs::write(root.join("CITATION.cff"), "cff-version: 1.2.0\n")?;
    assert!(plan(root, "0.2.0", None).is_err());
    assert_eq!(fs::read_to_string(root.join("Cargo.toml"))?, manifest);
    fs::write(root.join("CITATION.cff"), "version: \"0.1.0\"\n")?;
    let changes = plan(root, "0.2.0", None)?;
    fs::write(root.join("Cargo.toml"), "# concurrent edit\n")?;
    assert!(apply(&changes).is_err());
    assert_eq!(
        fs::read_to_string(root.join("CITATION.cff"))?,
        "version: \"0.1.0\"\n"
    );
    Ok(())
}

#[test]
fn cargo_accepts_bumped_prerelease_with_locked_resolution() -> Result<()> {
    use std::process::Command;
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    fs::write(
        root.join("Cargo.toml"),
        "[workspace]\nmembers = [\"crates/core\", \"crates/client\"]\nresolver = \"2\"\n[workspace.package]\nversion = \"0.1.0\"\n[workspace.dependencies]\ndemo-core = { path = \"crates/core\", version = \"0.1.0\" }\n",
    )?;
    for name in ["core", "client"] {
        let directory = root.join("crates").join(name);
        fs::create_dir_all(directory.join("src"))?;
        fs::write(directory.join("src/lib.rs"), "")?;
        let dependencies = if name == "client" {
            "[dependencies]\ndemo-core.workspace = true\n"
        } else {
            ""
        };
        fs::write(
            directory.join("Cargo.toml"),
            format!(
                "[package]\nname = \"demo-{name}\"\nversion = \"0.1.0\"\nedition = \"2024\"\n{dependencies}"
            ),
        )?;
    }
    fs::write(root.join("CITATION.cff"), "version: \"0.1.0\"\n")?;
    let generated = Command::new("cargo")
        .args(["generate-lockfile", "--offline"])
        .current_dir(root)
        .output()?;
    assert!(
        generated.status.success(),
        "{}",
        String::from_utf8_lossy(&generated.stderr)
    );
    apply(&plan(root, "0.3.0-beta.4", None)?)?;
    let lock = fs::read_to_string(root.join("Cargo.lock"))?;
    let checked = Command::new("cargo")
        .args(["metadata", "--format-version", "1", "--offline", "--locked"])
        .current_dir(root)
        .output()?;
    assert!(
        checked.status.success(),
        "{}",
        String::from_utf8_lossy(&checked.stderr)
    );
    let metadata: serde_json::Value = serde_json::from_slice(&checked.stdout)?;
    for package in metadata["packages"].as_array().unwrap() {
        assert_eq!(package["version"], "0.3.0-beta.4");
    }
    assert_eq!(fs::read_to_string(root.join("Cargo.lock"))?, lock);
    Ok(())
}

#[test]
fn release_date_is_validated_updated_and_checked() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    fs::write(
        root.join("Cargo.toml"),
        "[workspace]\n[workspace.package]\nversion = \"0.2.0\"\n",
    )?;
    fs::write(
        root.join("CITATION.cff"),
        "cff-version: 1.2.0\nversion: \"0.2.0\"\ndate-released: 2026-07-31\n",
    )?;
    for invalid in [
        "2026-02-29",
        "2026-13-01",
        "2026-10-4",
        "0000-01-01",
        "+10000-01-01",
        "October 4",
    ] {
        assert!(plan(root, "0.2.0", Some(invalid)).is_err());
    }
    let changes = plan(root, "0.2.0", Some("2026-10-04"))?;
    assert_eq!(changes.len(), 1);
    assert!(fs::read_to_string(root.join("CITATION.cff"))?.contains("2026-07-31"));
    apply(&changes)?;
    assert_eq!(
        fs::read_to_string(root.join("CITATION.cff"))?,
        "cff-version: 1.2.0\nversion: \"0.2.0\"\ndate-released: 2026-10-04\n"
    );
    assert!(plan(root, "0.2.0", Some("2026-10-04"))?.is_empty());
    assert_eq!(plan(root, "0.2.0", Some("2026-10-05"))?.len(), 1);
    assert!(plan(root, "0.2.0", None)?.is_empty());
    fs::write(root.join("CITATION.cff"), "version: \"0.2.0\"")?;
    apply(&plan(root, "0.2.0", Some("2028-02-29"))?)?;
    assert!(
        fs::read_to_string(root.join("CITATION.cff"))?.ends_with("\ndate-released: 2028-02-29\n")
    );
    Ok(())
}

fn cli_options(arguments: &[&str]) -> Result<super::Options> {
    super::Options::parse(arguments.iter().map(OsString::from))
}

fn cli_fixture() -> Result<tempfile::TempDir> {
    let directory = tempfile::tempdir()?;
    fs::write(
        directory.path().join("Cargo.toml"),
        "[workspace]\n[workspace.package]\nversion = \"0.1.0\"\n",
    )?;
    fs::write(
        directory.path().join("CITATION.cff"),
        "version: \"0.1.0\"\ndate-released: 2026-07-31\n",
    )?;
    Ok(directory)
}

#[test]
fn cli_preview_check_and_cancellation_do_not_write_or_leave_staging_files() -> Result<()> {
    for (arguments, answer, succeeds) in [
        (vec!["0.2.0", "--dry-run"], "yes\n", true),
        (vec!["0.2.0", "--check"], "yes\n", false),
        (vec!["0.1.0", "--check"], "", true),
        (vec!["0.2.0"], "no\n", true),
        (vec!["0.2.0"], "\n", true),
        (vec!["0.2.0"], "", true),
        (vec!["0.2.0"], "maybe\n", false),
    ] {
        let fixture = cli_fixture()?;
        let before = fs::read_to_string(fixture.path().join("Cargo.toml"))?;
        let mut input = Cursor::new(answer.as_bytes());
        let mut output = Vec::new();
        let result = super::execute(
            fixture.path(),
            &cli_options(&arguments)?,
            &mut input,
            &mut output,
        );
        assert_eq!(result.is_ok(), succeeds, "{arguments:?}: {result:?}");
        assert_eq!(
            fs::read_to_string(fixture.path().join("Cargo.toml"))?,
            before
        );
        assert_eq!(fs::read_dir(fixture.path())?.count(), 2);
        if arguments.len() > 1 {
            assert_eq!(input.position(), 0);
        }
    }
    Ok(())
}

#[test]
fn cli_yes_or_script_flag_commits_after_staging_and_does_not_prompt_on_noop() -> Result<()> {
    for flag in [None, Some("-y"), Some("--yes")] {
        let fixture = cli_fixture()?;
        let mut arguments = vec!["0.2.0", "--date-released", "2026-10-04"];
        if let Some(flag) = flag {
            arguments.push(flag);
        }
        let options = cli_options(&arguments)?;
        let mut input = Cursor::new(b"YES\n");
        let mut output = Vec::new();
        super::execute(fixture.path(), &options, &mut input, &mut output)?;
        let output = String::from_utf8(output)?;
        assert!(output.contains("Staging check passed"));
        assert_eq!(output.contains("Apply these changes?"), flag.is_none());
        assert_eq!(input.position() == 0, flag.is_some());
        assert!(plan(fixture.path(), "0.2.0", Some("2026-10-04"))?.is_empty());
        let mut output = Vec::new();
        super::execute(fixture.path(), &options, &mut input, &mut output)?;
        assert!(!String::from_utf8(output)?.contains("Apply these changes?"));
        assert_eq!(fs::read_dir(fixture.path())?.count(), 2);
    }
    Ok(())
}

#[test]
fn cli_rejects_bad_or_conflicting_arguments_before_any_write() -> Result<()> {
    for arguments in [
        vec![],
        vec!["bad"],
        vec!["0.2.0", "--check", "--dry-run"],
        vec!["0.2.0", "--date-released"],
        vec!["0.2.0", "-y", "--yes"],
        vec!["0.2.0", "--check", "-y"],
        vec!["0.2.0", "--unknown"],
    ] {
        assert!(cli_options(&arguments).is_err(), "{arguments:?}");
    }
    let fixture = cli_fixture()?;
    let options = cli_options(&["0.2.0", "--date-released", "2026-02-29", "-y"])?;
    let mut input = Cursor::new(b"");
    assert!(super::execute(fixture.path(), &options, &mut input, &mut Vec::new()).is_err());
    assert!(plan(fixture.path(), "0.1.0", None)?.is_empty());
    Ok(())
}
