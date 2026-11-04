//! Explicit runtime file override for the Respectfulness policy registry.

use std::path::PathBuf;

use anyhow::Result;
use clap::Args;
use yosoi::registry::Registry;

#[derive(Debug, Default, Args)]
pub struct RegistryArgs {
    /// Share Respectfulness state through this local JSONL registry file.
    #[arg(long = "registry")]
    pub path: Option<PathBuf>,
}

impl RegistryArgs {
    pub fn open(&self) -> Result<Option<Registry>> {
        if let Some(path) = &self.path {
            return Ok(Some(Registry::jsonl(path)?));
        }
        Ok(None)
    }
}
