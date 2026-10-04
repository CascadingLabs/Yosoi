#![allow(clippy::panic_in_result_fn)] // Process assertions intentionally fail integration tests.

use std::{
    error::Error,
    fs, io,
    path::PathBuf,
    process::{Command, Output},
};

use serde_json::{Value, json};
use tempfile::TempDir;
use yosoi_engine::Policy;

struct CliHome {
    _directory: TempDir,
    config: PathBuf,
}

impl CliHome {
    fn new() -> Result<Self, Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let config = directory.path().join("config");
        fs::create_dir_all(&config)?;
        Ok(Self {
            _directory: directory,
            config,
        })
    }

    fn store_path(&self) -> PathBuf {
        self.config.join("yosoi").join("policies.json")
    }

    fn write_store(&self, value: &Value) -> Result<(), Box<dyn Error>> {
        let path = self.store_path();
        fs::create_dir_all(path.parent().ok_or("store path has no parent")?)?;
        fs::write(path, serde_json::to_vec_pretty(value)?)?;
        Ok(())
    }

    fn run(&self, args: &[&str]) -> io::Result<Output> {
        Command::new(env!("CARGO_BIN_EXE_yosoi"))
            .args(args)
            .env("XDG_CONFIG_HOME", &self.config)
            .output()
    }
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn current_store(profile: Value) -> Value {
    let mut versions = serde_json::Map::new();
    versions.insert(env!("CARGO_PKG_VERSION").to_owned(), profile);
    json!({"format_version": 1, "cli_versions": versions})
}

#[test]
fn path_and_missing_store_leave_defaults_unwritten() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let path = home.run(&["policy", "path"])?;
    assert_eq!(path.status.code(), Some(0));
    assert_eq!(stdout(&path).trim(), home.store_path().to_string_lossy());

    let listed = home.run(&["policy", "list"])?;
    assert_eq!(listed.status.code(), Some(0));
    assert!(stdout(&listed).contains("No profiles"));
    let validated = home.run(&["policy", "validate"])?;
    assert_eq!(validated.status.code(), Some(0), "{}", stderr(&validated));
    assert!(stdout(&validated).contains("Valid Policy '<defaults>'"));
    assert!(!home.store_path().exists());
    Ok(())
}

#[test]
fn json_authored_profile_can_be_listed_and_validated() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    home.write_store(&current_store(json!({
        "active_profile": "next-run",
        "profiles": {
            "next-run": {
                "page": {"acquisitions": [
                    {"kind": "direct_http", "documents": {"kind": "current"}}
                ]},
                "request": {"maximum_elapsed": 15_000_000}
            }
        }
    })))?;
    let original = fs::read(home.store_path())?;

    let listed = home.run(&["policy", "list"])?;
    assert_eq!(listed.status.code(), Some(0), "{}", stderr(&listed));
    assert!(stdout(&listed).contains("* next-run"));
    let active = home.run(&["policy", "validate"])?;
    let named = home.run(&["policy", "validate", "next-run"])?;
    assert_eq!(active.status.code(), Some(0), "{}", stderr(&active));
    assert!(stdout(&active).contains("Policy 'next-run'"));
    assert_eq!(stdout(&active), stdout(&named));
    assert_eq!(fs::read(home.store_path())?, original);
    Ok(())
}

#[test]
fn map_policy_choices_in_current_json_profile_validate_without_rewrite()
-> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let mut authored_map = serde_json::to_value(Policy::default().map)?;
    *authored_map
        .get_mut("pages")
        .ok_or_else(|| io::Error::other("Policy fixture has no pages field"))? = json!("disabled");
    home.write_store(&current_store(json!({
        "active_profile": "map-off",
        "profiles": {"map-off": {"map": authored_map}}
    })))?;
    let original = fs::read(home.store_path())?;

    let output = home.run(&["policy", "validate"])?;
    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert!(stdout(&output).contains("Policy 'map-off'"));
    assert_eq!(fs::read(home.store_path())?, original);
    Ok(())
}

#[test]
fn missing_active_profile_is_an_error() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    home.write_store(&current_store(json!({
        "active_profile": "missing", "profiles": {}
    })))?;

    let output = home.run(&["policy", "validate"])?;
    assert_ne!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"");
    assert!(stderr(&output).contains("missing"));
    Ok(())
}

#[test]
fn malformed_json_fails_without_writing() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let path = home.store_path();
    fs::create_dir_all(path.parent().ok_or("store path has no parent")?)?;
    fs::write(&path, b"{ malformed")?;

    let output = home.run(&["policy", "list"])?;
    assert_ne!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"");
    assert_eq!(fs::read(path)?, b"{ malformed");
    Ok(())
}

#[test]
fn older_version_is_ignored_without_changing_the_store() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let old = json!({
        "format_version": 1,
        "cli_versions": {"0.0.7": {"future_field": true}}
    });
    home.write_store(&old)?;
    let original = fs::read(home.store_path())?;

    let output = home.run(&["policy", "validate"])?;
    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert_eq!(fs::read(home.store_path())?, original);
    Ok(())
}

#[test]
fn removed_write_and_show_commands_are_rejected() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    for command in ["new", "use", "edit", "show"] {
        let output = home.run(&["policy", command])?;
        assert_eq!(
            output.status.code(),
            Some(2),
            "{command}: {}",
            stderr(&output)
        );
    }
    assert!(!home.store_path().exists());
    Ok(())
}

#[test]
fn bare_policy_command_explains_the_three_commands() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let output = home.run(&["policy"])?;
    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert!(stdout(&output).contains("path, list, validate"));
    assert!(!home.store_path().exists());
    Ok(())
}

#[cfg(all(unix, not(target_os = "macos")))]
#[test]
fn relative_xdg_config_home_falls_back_to_home_config() -> Result<(), Box<dyn Error>> {
    let home = CliHome::new()?;
    let output = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["policy", "path"])
        .env("XDG_CONFIG_HOME", "relative-config")
        .env("HOME", &home.config)
        .output()?;
    assert_eq!(output.status.code(), Some(0), "{}", stderr(&output));
    assert_eq!(
        stdout(&output).trim(),
        home.config
            .join(".config/yosoi/policies.json")
            .to_string_lossy()
    );
    Ok(())
}
