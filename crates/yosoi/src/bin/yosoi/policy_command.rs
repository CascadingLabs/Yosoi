//! Read-only commands for JSON-authored Policy profiles.

use std::io::{self, Write};

use anyhow::{Context as _, Result};
use clap::{Args, Subcommand};

use crate::{policy_store::PolicyStore, presentation::Theme};

#[derive(Debug, Args)]
pub struct PolicyArgs {
    #[command(subcommand)]
    pub action: Option<PolicyAction>,
}

#[derive(Debug, Subcommand)]
pub enum PolicyAction {
    /// Show the Policy store location without creating it.
    Path,
    /// List profiles saved for this CLI version.
    List,
    /// Validate a profile or the active effective Policy.
    Validate { name: Option<String> },
}

pub fn run(args: PolicyArgs) -> Result<()> {
    let theme = Theme::stdout();
    let heading = theme.heading;
    let value = theme.value;
    let success = theme.success;
    let muted = theme.muted;
    let mut stdout = io::stdout().lock();
    match args.action {
        Some(PolicyAction::Path) => {
            writeln!(stdout, "{value}{}{value:#}", PolicyStore::path()?.display())?;
        }
        Some(PolicyAction::List) => {
            let store = PolicyStore::load()?;
            let profiles = store.list_profiles();
            if profiles.is_empty() {
                writeln!(
                    stdout,
                    "{muted}No profiles for yosoi {}{muted:#}",
                    env!("CARGO_PKG_VERSION")
                )?;
            } else {
                let active = store.active_profile();
                for profile in profiles {
                    let marker = if active == Some(profile.as_str()) {
                        "*"
                    } else {
                        " "
                    };
                    writeln!(
                        stdout,
                        "{success}{marker}{success:#} {value}{profile}{value:#}"
                    )?;
                }
            }
        }
        Some(PolicyAction::Validate { name }) => {
            let store = PolicyStore::load()?;
            let selected = name.as_deref().or_else(|| store.active_profile());
            let policy = match selected {
                Some(name) => store.resolve_profile(name)?,
                None => store.current()?,
            };
            let identity = policy
                .effective_identity()
                .context("could not compute effective Policy identity")?;
            writeln!(
                stdout,
                "{success}Valid Policy{success:#} {value}'{}'{value:#} for yosoi {}: v{} {}",
                selected.unwrap_or("<defaults>"),
                env!("CARGO_PKG_VERSION"),
                identity.version(),
                identity.digest()
            )?;
        }
        None => {
            writeln!(
                stdout,
                "{heading}Policy commands:{heading:#} {value}path, list, validate{value:#}"
            )?;
            writeln!(stdout, "Run `yosoi policy --help` for details.")?;
        }
    }
    Ok(())
}
