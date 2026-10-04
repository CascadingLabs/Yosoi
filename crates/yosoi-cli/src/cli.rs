use std::process::ExitCode;
use std::{
    env,
    ffi::OsString,
    io::{self, Write},
    iter,
};

use clap::{ArgAction, CommandFactory, Parser, Subcommand, error::ErrorKind};
use clap_complete::Shell;

use crate::{locate_command, map_command, policy_command, request_command, search_command, syntax};

/// The top-level command line for Yosoi.
#[derive(Debug, Parser)]
#[command(
    name = "yosoi",
    version,
    propagate_version = true,
    disable_version_flag = true,
    about = "Yosoi command line interface"
)]
pub struct Cli {
    /// Print version information.
    #[arg(short = 'v', long = "version", short_alias = 'V', action = ArgAction::Version, global = true)]
    version: Option<bool>,
    /// Select a saved Policy profile for this operation.
    #[arg(long = "profile", global = true)]
    profile: Option<String>,
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Inspect and validate JSON-authored Policy profiles.
    Policy(policy_command::PolicyArgs),
    /// Make a web request with the selected Policy.
    Request(request_command::RequestArgs),
    /// Discover scoped pages or passive subdomains.
    Map(map_command::MapArgs),
    /// Search selected providers for a query.
    Search(search_command::SearchArgs),
    /// Locate values in a file or one typed Yosoi Document on stdin.
    Locate(locate_command::LocateArgs),
    /// Generate a shell completion script from this command tree.
    Completions { shell: Shell },
}

/// Parse the command line and print Clap's standard help or diagnostics.
pub async fn run() -> ExitCode {
    let command = Cli::command();
    let args = match syntax::normalize_args(&command, env::args_os().skip(1)) {
        Ok(args) => args,
        Err(error) => return report_syntax_error(&error),
    };
    let args = iter::once(OsString::from("yosoi")).chain(args);
    match Cli::try_parse_from(args) {
        Ok(cli) => match cli.command {
            Some(Commands::Policy(args)) => {
                if cli.profile.is_some() {
                    return report_app_error(&anyhow::anyhow!(
                        "--profile selects a Policy for an operation; use `yosoi policy validate NAME` to check a profile"
                    ));
                }
                match policy_command::run(args) {
                    Ok(()) => ExitCode::SUCCESS,
                    Err(error) => report_app_error(&error),
                }
            }
            Some(Commands::Request(args)) => {
                match request_command::run(args, cli.profile.as_deref()).await {
                    Ok(code) => code,
                    Err(error) => report_app_error(&error),
                }
            }
            Some(Commands::Map(args)) => {
                match map_command::run(args, cli.profile.as_deref()).await {
                    Ok(code) => code,
                    Err(error) => report_app_error(&error),
                }
            }
            Some(Commands::Search(args)) => {
                match search_command::run(args, cli.profile.as_deref()).await {
                    Ok(code) => code,
                    Err(error) => search_command::report_error(&error),
                }
            }
            Some(Commands::Locate(args)) => {
                match locate_command::run(&args, cli.profile.as_deref()) {
                    Ok(code) => code,
                    Err(error) => report_app_error(&error),
                }
            }
            Some(Commands::Completions { shell }) => {
                if cli.profile.is_some() {
                    return report_app_error(&anyhow::anyhow!(
                        "--profile applies to Request, Map, and Locate, not completions"
                    ));
                }
                let mut generated = Vec::new();
                let mut completion_command = Cli::command();
                clap_complete::generate(shell, &mut completion_command, "yosoi", &mut generated);
                match io::stdout().lock().write_all(&generated) {
                    Ok(()) => ExitCode::SUCCESS,
                    Err(error) => report_write_error(&error),
                }
            }
            None => {
                let mut command = command;
                match command.print_help() {
                    Ok(()) => ExitCode::SUCCESS,
                    Err(error) => report_write_error(&error),
                }
            }
        },
        Err(error) => {
            let exit_code = match error.kind() {
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion => ExitCode::SUCCESS,
                _ => ExitCode::from(2),
            };
            match error.print() {
                Ok(()) => exit_code,
                Err(write_error) => report_write_error(&write_error),
            }
        }
    }
}

fn report_app_error(error: &anyhow::Error) -> ExitCode {
    let mut stderr = io::stderr().lock();
    let _ = writeln!(stderr, "yosoi: {error:#}");
    ExitCode::FAILURE
}

fn report_syntax_error(error: &syntax::SyntaxError) -> ExitCode {
    let mut stderr = io::stderr().lock();
    let _ = writeln!(stderr, "yosoi: invalid CLI syntax definition: {error}");
    ExitCode::FAILURE
}

fn report_write_error(error: &io::Error) -> ExitCode {
    let mut stderr = io::stderr().lock();
    let _ = writeln!(stderr, "yosoi: failed to write command output: {error}");
    ExitCode::FAILURE
}

#[cfg(test)]
#[allow(clippy::panic, clippy::panic_in_result_fn)]
mod tests {
    use std::{
        error::Error,
        ffi::OsString,
        iter,
        num::{NonZeroU16, NonZeroUsize},
    };

    use clap::{CommandFactory, Parser};

    use super::{
        Cli, Commands,
        search_command::{OutputFormat, ProviderChoice},
        syntax,
    };

    #[test]
    fn command_tree_passes_clap_debug_assertions() {
        Cli::command().debug_assert();
    }

    #[test]
    fn search_help_lists_explicit_provider_and_limit_options() -> Result<(), Box<dyn Error>> {
        let mut command = Cli::command();
        let search = command
            .find_subcommand_mut("search")
            .ok_or("Search subcommand is missing")?;
        let help = search.render_help().to_string();
        for expected in [
            "QUERY",
            "--providers",
            "--stats",
            "--per-provider-limit",
            "--max-in-flight",
            "--output",
        ] {
            assert!(help.contains(expected), "missing {expected} in Search help");
        }
        Ok(())
    }

    #[test]
    fn search_parses_repeated_providers_in_order_and_keeps_case_folded_syntax()
    -> Result<(), Box<dyn Error>> {
        let command = Cli::command();
        let args = [
            "SeArCh",
            "Rust Ownership",
            "--PrOvIdErS",
            "brave,duckduckgo",
            "--PER-PROVIDER-LIMIT",
            "8",
            "--MAX-IN-FLIGHT",
            "2",
            "--OUTPUT",
            "json",
            "-s",
        ]
        .into_iter()
        .map(OsString::from);
        let normalized = syntax::normalize_args(&command, args)?;
        let cli = Cli::try_parse_from(iter::once(OsString::from("yosoi")).chain(normalized))?;
        let Some(Commands::Search(args)) = cli.command else {
            return Err("parsed command was not Search".into());
        };
        assert_eq!(args.query, "Rust Ownership");
        assert_eq!(
            args.providers,
            [ProviderChoice::Brave, ProviderChoice::DuckDuckGo]
        );
        assert_eq!(args.per_provider_limit.map(NonZeroU16::get), Some(8));
        assert_eq!(args.max_in_flight.map(NonZeroUsize::get), Some(2));
        assert_eq!(args.output, OutputFormat::Json);
        assert!(args.stats);
        Ok(())
    }

    #[test]
    fn search_provider_short_flag_and_stats_long_flag_parse_together() -> Result<(), Box<dyn Error>>
    {
        let cli = Cli::try_parse_from([
            "yosoi",
            "search",
            "query",
            "-p",
            "brave,bing",
            "--stats",
            "--profile",
            "daily",
        ])?;
        assert_eq!(cli.profile.as_deref(), Some("daily"));
        let Some(Commands::Search(args)) = cli.command else {
            return Err("parsed command was not Search".into());
        };
        assert_eq!(
            args.providers,
            [ProviderChoice::Brave, ProviderChoice::Bing]
        );
        assert!(args.stats);
        Ok(())
    }

    #[test]
    fn search_provider_list_rejects_values_outside_the_enum() {
        assert!(
            Cli::try_parse_from(["yosoi", "search", "query", "--providers", "brave,google",])
                .is_err()
        );
    }

    #[test]
    fn search_flags_can_be_omitted_for_a_saved_policy_profile() -> Result<(), Box<dyn Error>> {
        let cli = Cli::try_parse_from(["yosoi", "search", "query"])?;
        let Some(Commands::Search(args)) = cli.command else {
            return Err("parsed command was not Search".into());
        };
        assert_eq!(args.providers, Vec::<ProviderChoice>::new());
        assert_eq!(args.per_provider_limit, None);
        assert_eq!(args.max_in_flight, None);
        assert_eq!(args.output, OutputFormat::Human);
        assert!(!args.stats);
        Ok(())
    }
}
