use std::{
    io::{self, Write},
    time::Duration,
};

use anyhow::Result;
use yosoi_engine::{Document, LocateOutcome};

use crate::{presentation::Theme, stats::RunTimer};

pub(super) struct LocateTimings {
    pub(super) input: Duration,
    pub(super) locate: Duration,
    pub(super) output: Duration,
}

pub(super) fn render_stats(
    document: &Document,
    outcome: &LocateOutcome,
    timer: &RunTimer,
    timings: &LocateTimings,
) -> Result<()> {
    let theme = Theme::stderr();
    let label = theme.label;
    let value = theme.value;
    let mut stderr = io::stderr().lock();
    timer.write_header(&mut stderr, "Locate", theme)?;
    for (name, duration) in [
        ("Input wait/read time", timings.input),
        ("Parse/query time", timings.locate),
        ("Output time", timings.output),
    ] {
        writeln!(
            stderr,
            "{label}{name}:{label:#} {value}{:.6} s{value:#}",
            duration.as_secs_f64()
        )?;
    }
    writeln!(
        stderr,
        "{label}Input bytes:{label:#} {value}{}{value:#}",
        document.byte_len()
    )?;
    let status = match outcome {
        LocateOutcome::Matched { .. } => "matched",
        LocateOutcome::NoMatch { .. } => "no_match",
        LocateOutcome::Indeterminate { .. } => "indeterminate",
        LocateOutcome::Failed { .. } => "failed",
    };
    let style = match outcome {
        LocateOutcome::Matched { .. } => theme.success,
        LocateOutcome::NoMatch { .. } | LocateOutcome::Indeterminate { .. } => theme.warning,
        LocateOutcome::Failed { .. } => theme.error,
    };
    writeln!(stderr, "{label}Outcome:{label:#} {style}{status}{style:#}")?;
    if let LocateOutcome::Matched { result } = outcome {
        writeln!(
            stderr,
            "{label}Findings:{label:#} {value}{}{value:#}",
            result.findings().len()
        )?;
        writeln!(
            stderr,
            "{label}Regions:{label:#} {value}{}{value:#}",
            result.regions().len()
        )?;
    }
    Ok(())
}
