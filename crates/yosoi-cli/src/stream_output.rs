//! Shared shell destination detection and HTTPS target shorthand.
use std::io::{self, IsTerminal as _};

#[cfg(unix)]
use anyhow::Context as _;
use anyhow::{Result, bail};

pub enum Destination {
    Terminal,
    Bytes,
    Document,
}

pub fn destination() -> Result<Destination> {
    let stdout = io::stdout();
    if stdout.is_terminal() {
        return Ok(Destination::Terminal);
    }
    #[cfg(unix)]
    {
        use rustix::fs::{FileType, fstat};
        let metadata = fstat(stdout.lock())
            .context("could not inspect stdout; choose an output mode explicitly")?;
        match FileType::from_raw_mode(metadata.st_mode) {
            FileType::Fifo | FileType::Socket => Ok(Destination::Document),
            FileType::RegularFile | FileType::CharacterDevice => Ok(Destination::Bytes),
            _ => bail!("unsupported stdout destination; choose --raw, --pipe-document, or --json"),
        }
    }
    #[cfg(not(unix))]
    bail!(
        "automatic non-terminal output routing requires Unix; choose --raw, --pipe-document, or --json"
    )
}

pub fn cli_target(value: &str) -> String {
    let has_scheme = value.split_once(':').is_some_and(|(scheme, suffix)| {
        let mut characters = scheme.chars();
        let valid_scheme = characters
            .next()
            .is_some_and(|first| first.is_ascii_alphabetic())
            && characters.all(|character| {
                character.is_ascii_alphanumeric() || matches!(character, '+' | '-' | '.')
            });
        valid_scheme
            && (suffix.starts_with("//")
                || scheme.eq_ignore_ascii_case("http")
                || scheme.eq_ignore_ascii_case("https"))
    });
    if has_scheme {
        value.to_owned()
    } else {
        format!("https://{value}")
    }
}
