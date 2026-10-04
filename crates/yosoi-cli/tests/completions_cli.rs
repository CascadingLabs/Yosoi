#![allow(clippy::panic_in_result_fn)] // Process assertions intentionally fail completion tests.

use std::{error::Error, fs, path::PathBuf, process::Command};

#[test]
fn generated_completions_cover_the_finished_command_tree() -> Result<(), Box<dyn Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    for (shell, filename) in [
        ("bash", "yosoi.bash"),
        ("zsh", "_yosoi"),
        ("fish", "yosoi.fish"),
        ("powershell", "yosoi.ps1"),
        ("elvish", "yosoi.elv"),
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
            .args(["completions", shell])
            .output()?;
        assert_eq!(
            output.status.code(),
            Some(0),
            "{shell}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stderr.is_empty(), "{shell}");
        let script = String::from_utf8(output.stdout)?;
        assert!(script.contains("yosoi"), "{shell}");
        assert!(script.contains("request"), "{shell}");
        assert!(script.contains("map"), "{shell}");
        assert!(script.contains("locate"), "{shell}");
        assert!(script.contains("policy"), "{shell}");
        assert_eq!(
            script.as_bytes(),
            fs::read(root.join("completions").join(filename))?,
            "{shell} static script is stale"
        );
    }
    Ok(())
}

#[test]
fn completions_rejects_operational_profile_selector() -> Result<(), Box<dyn Error>> {
    let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["completions", "bash", "--profile", "daily"])
        .output()?;
    assert_ne!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("--profile"));
    Ok(())
}
