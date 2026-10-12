#![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail tests.

use super::*;
use flate2::{Compression, write::GzEncoder};
#[cfg(unix)]
use std::os::unix::fs::symlink;
use std::{hint::black_box, slice};

#[test]
fn release_versions_and_platforms_are_bounded() -> Result<()> {
    for version in ["0.3.0", "0.2.1", "0.3.0-rc.1"] {
        validate_version(version)?;
    }
    for version in [
        "latest",
        "v0.3.0",
        "0.0.0",
        "0.03.0",
        "0.3.0-rc.0",
        "0.3.0/evil",
        "0.3.10001",
        "0.3.0-rc.1;echo",
    ] {
        assert!(validate_version(version).is_err(), "{version}");
    }
    for os in ["linux", "macos"] {
        for cpu in ["x86_64", "aarch64"] {
            assert!(platform(os, cpu).is_ok());
        }
    }
    assert_eq!(platform("windows", "x86_64")?, "windows-x86_64");
    assert!(platform("windows", "aarch64").is_err());
    Ok(())
}

fn standalone(root: &Path) -> Result<PathBuf> {
    fs::create_dir_all(root)?;
    let executable = root.join(if cfg!(windows) { "yosoi.exe" } else { "yosoi" });
    fs::write(&executable, "previous executable")?;
    write_receipt(
        &root.join(RECEIPT),
        &Receipt {
            schema: 1,
            method: "standalone".into(),
            version: "0.2.1".into(),
            sha256: digest(&executable)?,
            path_added: false,
        },
    )?;
    Ok(executable)
}

#[test]
fn receipt_binds_ownership_and_method_changes_take_precedence() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let executable = standalone(&temp.path().join("bin"))?;
    assert!(matches!(owner(&executable)?, Owner::Standalone(_)));
    fs::write(temp.path().join(".crates2.json"), serde_json::json!({"installs": {"yosoi 0.2.1 (registry)": {"bins": [executable.file_name().and_then(|name| name.to_str()).context("name")?]}}}).to_string())?;
    assert_eq!(owner(&executable)?, Owner::Cargo);
    fs::remove_file(temp.path().join(".crates2.json"))?;
    fs::write(temp.path().join("pyvenv.cfg"), "home = python")?;
    assert_eq!(owner(&executable)?, Owner::PythonEnvironment);
    fs::write(temp.path().join("uv-receipt.toml"), "")?;
    assert_eq!(owner(&executable)?, Owner::Uv);
    fs::remove_file(temp.path().join("pyvenv.cfg"))?;
    fs::write(&executable, "replacement from another method")?;
    assert!(owner(&executable).is_err());
    Ok(())
}

#[test]
fn package_guidance_is_specific_and_never_runs_a_manager() -> Result<()> {
    let latest = SelfAction::Update {
        target_version: None,
        yes: true,
    };
    let pin = SelfAction::Update {
        target_version: Some("0.3.0-rc.1".into()),
        yes: true,
    };
    let uninstall = SelfAction::Uninstall { yes: true };
    assert_eq!(guidance(&Owner::Uv, &latest)?, "uv tool upgrade yosoi-cli");
    assert_eq!(
        guidance(&Owner::Uv, &pin)?,
        "uv tool install --force yosoi-cli==0.3.0rc1"
    );
    assert_eq!(
        guidance(&Owner::Cargo, &uninstall)?,
        "cargo uninstall yosoi"
    );
    assert_eq!(
        guidance(&Owner::Uv, &uninstall)?,
        "uv tool uninstall yosoi-cli"
    );
    assert!(guidance(&Owner::PythonEnvironment, &uninstall)?.contains("no permanent"));
    Ok(())
}

#[test]
fn maintenance_lock_excludes_other_operations() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let lock = Lock::acquire(temp.path())?;
    assert!(Lock::acquire(temp.path()).is_err());
    drop(lock);
    assert!(Lock::acquire(temp.path()).is_ok());
    Ok(())
}

#[cfg(unix)]
#[test]
fn uninstall_preserves_unrelated_files_and_rejects_changed_binary() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let executable = standalone(temp.path())?;
    fs::write(temp.path().join("saved-evidence.json"), "evidence")?;
    let receipt = load_receipt(&executable)?;
    fs::write(&executable, "changed binary")?;
    assert!(uninstall(&executable, &receipt).is_err());
    assert!(executable.exists());
    fs::write(&executable, "previous executable")?;
    uninstall(&executable, &receipt)?;
    assert!(!executable.exists());
    assert!(!temp.path().join(RECEIPT).exists());
    assert_eq!(
        fs::read_to_string(temp.path().join("saved-evidence.json"))?,
        "evidence"
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn replacement_commits_receipt_and_rolls_back_on_receipt_failure() -> Result<()> {
    for fail in [false, true] {
        let temp = tempfile::tempdir()?;
        let executable = standalone(temp.path())?;
        let previous = load_receipt(&executable)?;
        let staging = tempfile::tempdir_in(temp.path())?;
        let candidate = staging.path().join("new");
        fs::write(&candidate, "new executable")?;
        if !fail {
            write_receipt(
                &staging.path().join(RECEIPT),
                &Receipt {
                    version: "0.3.0".into(),
                    sha256: digest(&candidate)?,
                    ..previous.clone()
                },
            )?;
        }
        let result = replace(&executable, &previous, &candidate, &staging);
        assert_eq!(result.is_err(), fail);
        assert_eq!(
            load_receipt(&executable)?.version,
            if fail { "0.2.1" } else { "0.3.0" }
        );
        assert_eq!(
            fs::read_to_string(executable)?,
            if fail {
                "previous executable"
            } else {
                "new executable"
            }
        );
    }
    Ok(())
}

#[test]
fn prompts_default_to_yes_for_update_and_no_for_uninstall() -> Result<()> {
    assert!(confirmation("", true)?);
    assert!(!confirmation("", false)?);
    for value in ["Y", "yes", " Yes "] {
        assert!(confirmation(value, false)?);
    }
    for value in ["n", "NO", " no "] {
        assert!(!confirmation(value, true)?);
    }
    assert!(confirmation("maybe", true).is_err());
    Ok(())
}

fn tar_fixture(name: &str, kind: u8, contents: &[u8], extra: bool) -> Result<(Vec<u8>, String)> {
    let mut archive = vec![0_u8; 512];
    archive
        .get_mut(..name.len())
        .context("name too long")?
        .copy_from_slice(name.as_bytes());
    archive
        .get_mut(100..108)
        .context("mode")?
        .copy_from_slice(b"0000755\0");
    archive
        .get_mut(124..136)
        .context("size")?
        .copy_from_slice(format!("{:011o}\0", contents.len()).as_bytes());
    archive.get_mut(148..156).context("checksum")?.fill(b' ');
    *archive.get_mut(156).context("type")? = kind;
    archive
        .get_mut(257..263)
        .context("magic")?
        .copy_from_slice(b"ustar\0");
    let sum: u64 = archive.iter().map(|c| u64::from(*c)).sum();
    archive
        .get_mut(148..156)
        .context("checksum")?
        .copy_from_slice(format!("{sum:06o}\0 ").as_bytes());
    archive.extend_from_slice(contents);
    archive.resize(
        archive
            .len()
            .div_ceil(512)
            .checked_mul(512)
            .and_then(|size| size.checked_add(1024))
            .context("fixture size overflow")?,
        0,
    );
    if extra {
        *archive.last_mut().context("tail")? = 1;
    }
    let mut compressor = GzEncoder::new(Vec::new(), Compression::fast());
    compressor.write_all(&archive)?;
    let bytes = compressor.finish()?;
    let hash = format!("{:x}", Sha256::digest(&bytes));
    Ok((bytes, hash))
}

#[test]
fn verified_archive_rejects_links_traversal_extra_members_and_corruption() -> Result<()> {
    let (bytes, hash) = tar_fixture("yosoi", b'0', b"binary", false)?;
    assert_eq!(archive_binary(&bytes, &hash, "yosoi")?, b"binary");
    assert!(archive_binary(&bytes, &"0".repeat(64), "yosoi").is_err());
    for (name, kind, extra) in [
        ("../yosoi", b'0', false),
        ("yosoi", b'2', false),
        ("yosoi", b'1', false),
        ("yosoi", b'0', true),
    ] {
        let (bytes, hash) = tar_fixture(name, kind, b"binary", extra)?;
        assert!(archive_binary(&bytes, &hash, "yosoi").is_err());
    }
    assert!(checksum(b"", "archive.tar.gz").is_err());
    let manifest = format!("{hash}  archive.tar.gz\n{hash}  archive.tar.gz\n");
    assert!(checksum(manifest.as_bytes(), "archive.tar.gz").is_err());
    Ok(())
}

#[test]
fn uv_export_receipt_handles_copied_binaries_and_custom_roots() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let tool_root = temp.path().join("tools with spaces");
    let env_dir = tool_root.join("yosoi-cli");
    let bin_dir = temp.path().join("exported bin");
    let env_bin = env_dir.join(if cfg!(windows) { "Scripts" } else { "bin" });
    fs::create_dir_all(&env_bin)?;
    fs::create_dir_all(&bin_dir)?;
    let name = if cfg!(windows) { "yosoi.exe" } else { "yosoi" };
    let executable = bin_dir.join(name);
    fs::write(&executable, "same executable")?;
    fs::write(env_bin.join(name), "same executable")?;
    let receipt = toml::Value::try_from(
        serde_json::json!({"tool":{"entrypoints":[{"name":"yosoi", "install-path":executable.to_str().context("path")?}]}}),
    )?;
    fs::write(env_dir.join("uv-receipt.toml"), toml::to_string(&receipt)?)?;
    let location = find_uv_installation(&executable.canonicalize()?, slice::from_ref(&tool_root))?
        .context("UV ownership missing")?;
    assert_eq!(location.0, tool_root.canonicalize()?);
    fs::write(&executable, "replacement from standalone")?;
    assert!(find_uv_installation(&executable.canonicalize()?, &[tool_root])?.is_none());
    Ok(())
}

#[cfg(unix)]
#[test]
fn symlink_receipt_is_rejected() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let executable = standalone(temp.path())?;
    fs::rename(temp.path().join(RECEIPT), temp.path().join("other.json"))?;
    symlink(temp.path().join("other.json"), temp.path().join(RECEIPT))?;
    assert!(owner(&executable).is_err());
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn executable_version_is_checked_before_commit() -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempfile::tempdir()?;
    let candidate = temp.path().join("candidate");
    fs::write(&candidate, "#!/bin/sh\nprintf 'yosoi 0.3.0\\n'\n")?;
    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o755))?;
    verify_binary(&candidate, "0.3.0").await?;
    assert!(verify_binary(&candidate, "0.2.1").await.is_err());
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn update_stage_verifies_archive_and_version_then_commits_or_preserves() -> Result<()> {
    for invalid_version in [false, true] {
        let temp = tempfile::tempdir()?;
        let executable = standalone(temp.path())?;
        let receipt = load_receipt(&executable)?;
        let body = if invalid_version {
            b"#!/bin/sh\necho 'yosoi 0.1.0'\n".as_slice()
        } else {
            b"#!/bin/sh\necho 'yosoi 0.3.0'\n".as_slice()
        };
        let (archive, hash) = tar_fixture("yosoi", b'0', body, false)?;
        let staged = stage_archive(temp.path(), &receipt, "0.3.0", &archive, &hash).await;
        if invalid_version {
            assert!(staged.is_err());
            assert_eq!(load_receipt(&executable)?.version, "0.2.1");
            assert_eq!(fs::read_to_string(&executable)?, "previous executable");
        } else {
            let (staging, candidate) = staged?;
            replace(&executable, &receipt, &candidate, &staging)?;
            verify_binary(&executable, "0.3.0").await?;
            assert_eq!(load_receipt(&executable)?.version, "0.3.0");
            assert!(matches!(owner(&executable)?, Owner::Standalone(_)));
        }
    }
    Ok(())
}

#[tokio::test]
async fn download_rejects_http_errors_and_oversize_bodies() -> Result<()> {
    let _ = ring_crypto_provider().install_default();
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
    };
    for (status, length, succeeds) in [
        ("200 OK", 4, true),
        ("200 OK", 9, false),
        ("404 Not Found", 4, false),
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let address = listener.local_addr()?;
        let task = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await?;
            let mut request = [0; 1024];
            let read = stream.read(&mut request).await?;
            assert!(read > 0);
            stream.write_all(format!("HTTP/1.1 {status}\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n{}", "x".repeat(length)).as_bytes()).await?;
            Ok::<(), io::Error>(())
        });
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(5))
            .build()?;
        let result = download(&client, &format!("http://{address}/asset"), 8).await;
        assert_eq!(result.is_ok(), succeeds);
        task.await??;
    }
    Ok(())
}

#[test]
fn windows_helper_launcher_and_embedded_payload_compile_on_the_host() {
    black_box(launch_windows_helper);
    assert!(include_str!("windows-helper.ps1").contains("Wait-Process -InputObject $parent"));
}

#[test]
fn implicit_updates_never_downgrade_and_explicit_pins_can() -> Result<()> {
    for (installed, latest, updates) in [
        ("0.4.0-rc.1", "0.3.0", false),
        ("0.4.0-rc.2", "0.4.0-rc.1", false),
        ("0.4.0-rc.1", "0.4.0-rc.2", true),
        ("0.4.0-rc.1", "0.4.0", true),
        ("0.4.0", "0.4.0-rc.1", false),
        ("0.3.9", "0.3.10", true),
        ("0.3.10", "0.3.9", false),
        ("0.3.0", "0.3.0", false),
    ] {
        assert_eq!(should_update(installed, latest, false)?, updates);
        assert_eq!(should_update(installed, latest, true)?, installed != latest);
    }
    assert!(should_update("0.3.0", "malformed", false).is_err());
    Ok(())
}
