#![allow(clippy::panic_in_result_fn)] // Process assertions intentionally fail completion tests.

use std::{error::Error, process::Command};

#[test]
fn generated_completions_cover_the_finished_command_tree() -> Result<(), Box<dyn Error>> {
    for shell in ["bash", "zsh", "fish", "powershell", "elvish"] {
        let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
            .args(["completions", shell])
            .output()?;
        assert_eq!(
            output.status.code(),
            Some(0),
            "{shell}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(output.stderr.as_slice(), b"", "{shell}");
        let script = String::from_utf8(output.stdout)?;
        assert!(script.contains("yosoi"), "{shell}");
        assert!(script.contains("request"), "{shell}");
        assert!(script.contains("map"), "{shell}");
        assert!(script.contains("locate"), "{shell}");
        assert!(script.contains("policy"), "{shell}");
        assert!(script.contains("search"), "{shell}");
    }
    Ok(())
}

#[test]
fn completions_rejects_operational_profile_selector() -> Result<(), Box<dyn Error>> {
    let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["completions", "bash", "--profile", "daily"])
        .output()?;
    assert_ne!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"");
    assert!(String::from_utf8_lossy(&output.stderr).contains("--profile"));
    Ok(())
}
