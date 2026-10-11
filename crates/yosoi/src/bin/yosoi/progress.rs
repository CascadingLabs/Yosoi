//! A transient stderr activity indicator for interactive human output.

use std::{
    array::IntoIter,
    env, future,
    io::{self, IsTerminal as _, Write},
    iter::Cycle,
    time::Duration,
};

use clap::builder::styling::Style;
use tokio::time::{self, Interval, MissedTickBehavior};

use crate::presentation::Theme;

const FRAMES: [&str; 10] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

pub struct Spinner {
    active: Option<ActiveSpinner>,
}

struct ActiveSpinner {
    interval: Interval,
    frames: Cycle<IntoIter<&'static str, 10>>,
    message: &'static str,
    style: Style,
    drawn: bool,
}

impl Spinner {
    pub fn new(message: &'static str, human_output: bool) -> Self {
        let interactive = human_output
            && io::stdout().is_terminal()
            && io::stderr().is_terminal()
            && env::var_os("TERM").is_none_or(|term| term != "dumb");
        let active = interactive.then(|| {
            // This timer animates the display. Command completion and cancellation
            // are awaited directly by the caller, never polled by this timer.
            let mut interval = time::interval(Duration::from_millis(80));
            interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
            ActiveSpinner {
                interval,
                frames: FRAMES.into_iter().cycle(),
                message,
                style: Theme::stderr().heading,
                drawn: false,
            }
        });
        Self { active }
    }

    pub async fn tick(&mut self) {
        let Some(active) = self.active.as_mut() else {
            return future::pending().await;
        };
        active.interval.tick().await;
        let frame = active.frames.next().unwrap_or("•");
        let style = active.style;
        let mut stderr = io::stderr().lock();
        let _ = write!(
            stderr,
            "\r\x1b[2K{style}{frame}{style:#} {}",
            active.message
        );
        let _ = stderr.flush();
        active.drawn = true;
    }
}

impl Drop for Spinner {
    fn drop(&mut self) {
        if self.active.as_ref().is_some_and(|active| active.drawn) {
            let mut stderr = io::stderr().lock();
            let _ = write!(stderr, "\r\x1b[2K");
            let _ = stderr.flush();
        }
    }
}
