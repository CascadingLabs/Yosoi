//! Opt-in CLI run timing shared by commands that report statistics.

use std::{io::Write, time::Instant};

use anyhow::Result;
use clap::Args;

use crate::presentation::Theme;

/// Common reporting options for CLI operations.
#[derive(Debug, Args)]
pub struct StatsArgs {
    /// Report wall time and operation totals on stderr.
    #[arg(id = "stats", short = 's', long = "stats", help_heading = "Output")]
    pub enabled: bool,
}

pub struct RunTimer {
    started: Instant,
}

impl RunTimer {
    pub fn start() -> Self {
        Self {
            started: Instant::now(),
        }
    }

    pub fn write_header(
        &self,
        output: &mut impl Write,
        operation: &str,
        theme: Theme,
    ) -> Result<()> {
        let heading = theme.heading;
        writeln!(output, "{heading}{operation} stats:{heading:#}")?;
        self.write_wall_time(output, theme)
    }

    pub fn write_wall_time(&self, output: &mut impl Write, theme: Theme) -> Result<()> {
        let label = theme.label;
        let value = theme.value;
        writeln!(
            output,
            "{label}Wall time:{label:#} {value}{:.3} s{value:#}",
            self.started.elapsed().as_secs_f64()
        )?;
        Ok(())
    }
}
