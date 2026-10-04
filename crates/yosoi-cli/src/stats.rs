//! Opt-in CLI run timing shared by commands that report statistics.

use std::{io::Write, time::Instant};

use anyhow::Result;

pub struct RunTimer {
    started: Instant,
}

impl RunTimer {
    pub fn start() -> Self {
        Self {
            started: Instant::now(),
        }
    }

    pub fn write_wall_time(&self, output: &mut impl Write) -> Result<()> {
        writeln!(
            output,
            "Wall time: {:.3} s",
            self.started.elapsed().as_secs_f64()
        )?;
        Ok(())
    }
}
