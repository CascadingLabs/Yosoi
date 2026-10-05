mod browser_diagnostics;
mod cli;
mod document_pipe;
mod locate_command;
mod map_command;
mod policy_command;
mod policy_store;
mod presentation;
mod progress;
mod request_command;
mod search_command;
mod stats;
mod stream_output;
mod syntax;

use std::process::ExitCode;

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    cli::run().await
}
