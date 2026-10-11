//! Bounded presentation of public Map outcomes.

use std::process::ExitCode;

use crate::stats::RunTimer;
use anyhow::Result;
use yosoi::{Document, map};

mod human;
mod manifest;
mod wire;

pub(super) fn document(
    outcome: &map::MapOutcome,
    seed: &str,
    profile: Option<&str>,
) -> Result<Document> {
    manifest::document(outcome, seed, profile)
}

pub(super) fn human(outcome: &map::MapOutcome, profile: Option<&str>) -> Result<()> {
    human::human(outcome, profile)
}

pub(super) fn stats(outcome: &map::MapOutcome, timer: &RunTimer) -> Result<()> {
    human::stats(outcome, timer)
}

pub(super) fn exit_code(outcome: &map::MapOutcome) -> ExitCode {
    human::exit_code(outcome)
}
