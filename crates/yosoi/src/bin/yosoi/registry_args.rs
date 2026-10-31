//! Runtime Registry selection is separate from the portable Policy profile.

use std::path::PathBuf;

use anyhow::Result;
use clap::Args;
use yosoi::registry::Registry;

#[derive(Debug, Default, Args)]
pub struct RegistryArgs {
    /// Share Respectfulness state through this local JSONL registry file.
    #[arg(long = "registry", conflicts_with = "registry_global")]
    pub path: Option<PathBuf>,
    /// Use the standard per-user JSONL registry instead of isolated memory.
    #[arg(long, conflicts_with = "path")]
    pub registry_global: bool,
}

impl RegistryArgs {
    pub fn open(&self) -> Result<Option<Registry>> {
        if let Some(path) = &self.path {
            return Ok(Some(Registry::jsonl(path)?));
        }
        if self.registry_global {
            return Ok(Some(Registry::global_jsonl()?));
        }
        Ok(None)
    }
}
