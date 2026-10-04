//! Bounded, serial Direct HTTP fuzz smoke checks.
use std::{fs, process::Command};

use anyhow::{Context, Result, bail};

pub fn run() -> Result<()> {
    let root = super::workspace_root()?.join("fuzz");
    let available = Command::new("cargo")
        .args(["fuzz", "--help"])
        .current_dir(&root)
        .output()
        .context("failed to inspect cargo-fuzz")?;
    if !available.status.success() {
        bail!("install cargo-fuzz with `cargo install cargo-fuzz --version 0.13.1 --locked`");
    }
    let targets = [
        ("wire-and-evidence", "-max_len=16384"),
        ("http-input-boundaries", "-max_len=4096"),
        ("bounded-lifecycle", "-max_len=2560"),
    ];
    for (target, _) in targets {
        let corpus = root.join("corpus").join(target);
        fs::create_dir_all(&corpus).context("failed to create fuzz corpus")?;
        for seed in fs::read_dir(root.join("seeds").join(target))
            .with_context(|| format!("failed to read {target} seeds"))?
        {
            let seed = seed.context("failed to read fuzz seed entry")?;
            fs::copy(seed.path(), corpus.join(seed.file_name()))
                .with_context(|| format!("failed to copy {target} seed"))?;
        }
    }
    for (target, maximum_length) in targets {
        let status = Command::new("cargo")
            .args([
                "+nightly",
                "fuzz",
                "run",
                target,
                "--",
                "-runs=2000",
                maximum_length,
            ])
            .current_dir(&root)
            .env("CARGO_BUILD_JOBS", "1")
            .env("CMAKE_BUILD_PARALLEL_LEVEL", "1")
            .status()
            .with_context(|| format!("failed to start {target} fuzz smoke check"))?;
        if !status.success() {
            bail!("{target} fuzz smoke check failed with {status}");
        }
    }
    Ok(())
}
