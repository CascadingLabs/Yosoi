//! Terminal authoring and execution over the public Map facade.
use std::{
    io::{self, Write},
    process::ExitCode,
    time::Duration,
};

use anyhow::{Context as _, Result, bail};
use clap::{Args, ValueEnum};
use tokio::signal;
use yosoi::{CancellationToken, Policy, map, policy};

use crate::{
    document_pipe,
    policy_store::PolicyStore,
    stats::RunTimer,
    stream_output::{Destination, cli_target, destination},
};

mod render;

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum MapMode {
    Pages,
    Passive,
    Combined,
}

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum RobotsChoice {
    Ignore,
    Respect,
}

#[derive(Debug, Args)]
#[allow(clippy::struct_excessive_bools)]
pub struct MapArgs {
    /// HTTP(S) seed; HTTPS is assumed when omitted.
    pub url: String,
    /// Explicitly replace page/subdomain/host choices; otherwise inherit Policy.
    #[arg(long, value_enum)]
    pub mode: Option<MapMode>,
    /// Maximum followed hyperlink depth (the seed has depth zero).
    #[arg(long)]
    pub depth: Option<u16>,
    /// Maximum total requests, including metadata and passive sources.
    #[arg(long)]
    pub max_requests: Option<u32>,
    /// Maximum discovered hosts.
    #[arg(long)]
    pub max_hosts: Option<u32>,
    /// Maximum inventoried page URLs.
    #[arg(long)]
    pub max_urls: Option<u32>,
    /// Maximum concurrent Map requests (pages and public sources).
    #[arg(long)]
    pub max_concurrency: Option<u32>,
    /// Absolute Map deadline in milliseconds.
    #[arg(long)]
    pub timeout_ms: Option<u64>,
    /// Apply or ignore robots allow/disallow rules.
    #[arg(long, value_enum)]
    pub robots: Option<RobotsChoice>,
    /// Explain the validated Policy and exit before network I/O.
    #[arg(long, conflicts_with_all = ["json", "raw", "pipe_document"])]
    pub explain: bool,
    /// Emit ordinary versioned Map JSON, including when piped.
    #[arg(long, conflicts_with_all = ["raw", "pipe_document"])]
    pub json: bool,
    /// Emit raw Map JSON bytes rather than a typed Document frame.
    #[arg(long, conflicts_with = "pipe_document")]
    pub raw: bool,
    /// Emit the Map manifest as one typed JSON Document frame.
    #[arg(long)]
    pub pipe_document: bool,
    /// Report wall time and consumed bounds on stderr.
    #[arg(short = 's', long = "stats", visible_alias = "stat")]
    pub stat: bool,
}

pub async fn run(args: MapArgs, profile: Option<&str>) -> Result<ExitCode> {
    let timer = RunTimer::start();
    let destination = if args.json || args.raw {
        Destination::Bytes
    } else if args.pipe_document {
        Destination::Document
    } else if args.explain {
        Destination::Terminal
    } else {
        destination()?
    };
    let store = PolicyStore::load()?;
    let selected = profile.or_else(|| store.active_profile());
    let mut policy = match selected {
        Some(name) => store.resolve_profile(name)?,
        None => store.current()?,
    };
    apply_overrides(&args, &mut policy)?;
    policy.validate().context("invalid Map Policy")?;
    let target = cli_target(&args.url);
    let request = map::new(&target).bind(&policy);
    request
        .validate()
        .context("invalid Map target or acquisition")?;
    if args.explain {
        let identity = policy.effective_identity()?;
        let mut stdout = io::stdout().lock();
        writeln!(stdout, "CLI version: {}", env!("CARGO_PKG_VERSION"))?;
        writeln!(
            stdout,
            "Policy profile: {}",
            selected.unwrap_or("<defaults>")
        )?;
        writeln!(
            stdout,
            "Policy identity: v{} {}",
            identity.version(),
            identity.digest()
        )?;
        serde_json::to_writer_pretty(&mut stdout, &policy)?;
        writeln!(stdout)?;
        if args.stat {
            let mut stderr = io::stderr().lock();
            timer.write_wall_time(&mut stderr)?;
            writeln!(stderr, "Map: not sent (--explain)")?;
        }
        return Ok(ExitCode::SUCCESS);
    }
    let cancellation = CancellationToken::new();
    let send = request.send_cancellable(&cancellation);
    tokio::pin!(send);
    let outcome = tokio::select! {
        result = &mut send => result,
        interrupted = signal::ctrl_c() => {
            cancellation.cancel();
            let outcome = send.await;
            interrupted.context("could not listen for Ctrl-C")?;
            outcome
        }
    }
    .context("could not execute Map")?;
    match destination {
        Destination::Terminal => {
            writeln!(io::stdout().lock(), "Map seed: {target}")?;
            render::human(&outcome, selected)?;
        }
        Destination::Bytes => {
            let document = render::document(&outcome, &target, selected)?;
            io::stdout()
                .lock()
                .write_all(document.bytes())
                .context("could not write Map JSON")?;
        }
        Destination::Document => {
            let document = render::document(&outcome, &target, selected)?;
            document_pipe::write_to(&mut io::stdout().lock(), &document)?;
        }
    }
    if args.stat {
        render::stats(&outcome, &timer)?;
    }
    Ok(render::exit_code(&outcome))
}

fn apply_overrides(args: &MapArgs, policy: &mut Policy) -> Result<()> {
    if let Some(mode) = args.mode {
        policy.map.pages = match mode {
            MapMode::Passive => policy::PageDiscovery::Disabled,
            MapMode::Pages | MapMode::Combined => policy::PageDiscovery::Explore,
        };
        policy.map.subdomains = match mode {
            MapMode::Pages => policy::Subdomains::Disabled,
            MapMode::Passive | MapMode::Combined => policy::Subdomains::Passive,
        };
        policy.map.scope.hosts = match mode {
            MapMode::Pages => policy::HostScope::SeedHost,
            MapMode::Passive | MapMode::Combined => policy::HostScope::RegistrableDomain,
        };
    }
    if let Some(depth) = args.depth {
        policy.map.limits.max_link_depth = depth;
    }
    if let Some(value) = args.max_requests {
        policy.map.limits.max_requests = policy::Budget::new(value)?;
    }
    if let Some(value) = args.max_hosts {
        policy.map.limits.max_hosts = policy::Budget::new(value)?;
    }
    if let Some(value) = args.max_urls {
        policy.map.limits.max_urls = policy::Budget::new(value)?;
    }
    if let Some(value) = args.max_concurrency {
        policy.map.limits.max_concurrency = policy::Budget::new(value)?;
    }
    if let Some(milliseconds) = args.timeout_ms {
        if milliseconds == 0 {
            bail!("--timeout-ms must be positive");
        }
        policy.map.limits.maximum_elapsed = Duration::from_millis(milliseconds);
    }
    if let Some(choice) = args.robots {
        policy.map.robots = match choice {
            RobotsChoice::Ignore => policy::Robots::Ignore,
            RobotsChoice::Respect => policy::Robots::Respect,
        };
    }
    Ok(())
}
