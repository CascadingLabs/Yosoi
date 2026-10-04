//! Shared terminal help styling. Clap owns wrapping and terminal/color detection.

use std::io;

use anstream::{AutoStream, ColorChoice};
use clap::{
    Command,
    builder::{
        Styles,
        styling::{AnsiColor, Color, RgbColor, Style},
    },
};

const LAVENDER: Style = Style::new().fg_color(Some(Color::Rgb(RgbColor(195, 167, 255))));
const BLUE: Style = Style::new()
    .fg_color(Some(Color::Rgb(RgbColor(145, 175, 255))))
    .bold();

pub const fn styles() -> Styles {
    Styles::styled()
        .header(LAVENDER.bold())
        .usage(LAVENDER.bold())
        .literal(BLUE)
        .placeholder(LAVENDER)
        .error(AnsiColor::BrightRed.on_default().bold())
        .invalid(AnsiColor::BrightRed.on_default())
        .valid(AnsiColor::BrightGreen.on_default())
        .context(Style::new().dimmed())
        .context_value(LAVENDER)
}

/// Apply the same layout throughout the command tree, including nested Policy help.
pub fn command(command: Command) -> Command {
    let examples = match command.get_name() {
        "yosoi" => Some(
            "  yosoi request https://example.com\n  yosoi map https://example.com --mode pages\n  yosoi search \"rust ownership\" --providers brave\n  yosoi locate --file page.html --format html --css \"h1\"\n\n  Explore a command with yosoi <command> --help.",
        ),
        "request" => Some(
            "  yosoi request https://example.com\n  yosoi request https://example.com --explain\n  yosoi request https://example.com --pipe-document | yosoi locate --pipe-document --css \"h1\"\n\n  Output: terminal = summary; file = raw bytes; pipe = binary Document.\n  Use --raw for page bytes or --json for an outcome summary.",
        ),
        "map" => Some(
            "  yosoi map https://example.com --mode pages\n  yosoi map https://example.com --mode passive --json",
        ),
        "search" => Some(
            "  yosoi search \"rust ownership\" --providers brave\n  yosoi search \"rust ownership\" --providers brave,bing --output json",
        ),
        "locate" => Some(
            "  yosoi locate --file page.html --format html --css \"h1\"\n  yosoi locate --file data.json --format json --json-pointer /title",
        ),
        "policy" => Some("  yosoi policy list\n  yosoi policy validate daily"),
        "completions" => {
            Some("  yosoi completions bash > yosoi.bash\n  yosoi completions fish > yosoi.fish")
        }
        _ => None,
    };
    let produces_document = matches!(command.get_name(), "request" | "map");
    let heading = LAVENDER.bold();
    let template = format!(
        "{heading}╭─ {{name}} {{version}}{heading:#}\n{{about}}\n{heading}╰────────────────────────────────────────{heading:#}\n\n{{usage-heading}} {{usage}}\n\n{{all-args}}{{after-help}}"
    );
    let mut command = command
        .styles(styles())
        .help_template(template)
        .max_term_width(100)
        .mut_args(|arg| {
            let heading = match arg.get_id().as_str() {
                "pipe_document" if produces_document => "Output",
                "stdin" | "file" | "pipe_document" | "format" => "Input",
                "acquisition" | "mode" | "robots" | "providers" => "Discovery",
                "css" | "text" | "json_path" | "json_pointer" => "Selectors",
                "timeout_ms"
                | "content_coded_bytes"
                | "representation_bytes"
                | "unicode_bytes"
                | "depth"
                | "max_requests"
                | "max_hosts"
                | "max_urls"
                | "max_concurrency"
                | "per_provider_limit"
                | "max_in_flight" => "Limits",
                "json" | "raw" | "explain" | "stats" | "output" | "document" | "attempt" => {
                    "Output"
                }
                _ => return arg,
            };
            arg.help_heading(heading)
        })
        .mut_subcommands(self::command);
    if let Some(examples) = examples {
        command = command.after_help(format!(
            "{heading}Try it{heading:#}\n{BLUE}{examples}{BLUE:#}"
        ));
    }
    command
}

/// Semantic colors for human output, selected independently for each stream.
#[derive(Clone, Copy, Debug)]
pub struct Theme {
    pub heading: Style,
    pub label: Style,
    pub value: Style,
    pub success: Style,
    pub warning: Style,
    pub error: Style,
    pub muted: Style,
}

impl Theme {
    pub const fn plain() -> Self {
        Self {
            heading: Style::new(),
            label: Style::new(),
            value: Style::new(),
            success: Style::new(),
            warning: Style::new(),
            error: Style::new(),
            muted: Style::new(),
        }
    }

    pub fn stdout() -> Self {
        Self::for_choice(AutoStream::auto(io::stdout()).current_choice())
    }

    pub fn stderr() -> Self {
        Self::for_choice(AutoStream::auto(io::stderr()).current_choice())
    }

    fn for_choice(choice: ColorChoice) -> Self {
        if choice == ColorChoice::Never {
            return Self::plain();
        }
        Self {
            heading: LAVENDER.bold(),
            label: LAVENDER,
            value: BLUE,
            success: AnsiColor::BrightGreen.on_default(),
            warning: AnsiColor::BrightYellow.on_default(),
            error: AnsiColor::BrightRed.on_default().bold(),
            muted: Style::new().dimmed(),
        }
    }

    pub fn status(self, value: &str) -> Style {
        match value {
            "results" | "completed" | "complete" | "exhausted" | "inspected" | "available" => {
                self.success
            }
            "failed" | "unavailable" => self.error,
            "empty" | "not_started" | "cancelled" | "partial" | "preview" | "indeterminate" => {
                self.warning
            }
            _ => self.value,
        }
    }
}
