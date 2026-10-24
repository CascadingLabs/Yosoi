//! Maintenance of the running CLI, respecting installation ownership.

use anyhow::{Context, Result, bail, ensure};
use clap::{Args, Subcommand};
use flate2::read::GzDecoder;
use rustls::crypto::ring::default_provider as ring_crypto_provider;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    env,
    ffi::OsStr,
    fs,
    io::{self, IsTerminal, Read, Write},
    path::{Path, PathBuf},
    str,
    time::Duration,
};
use tokio::{process::Command as AsyncCommand, time::timeout};

#[cfg(test)]
mod tests;

const RECEIPT: &str = ".yosoi-install.json";
const LOCK: &str = ".yosoi-maintenance.lock";
const RELEASES: &str = "https://github.com/CascadingLabs/Yosoi/releases";
const MAX_ARCHIVE: usize = 256 * 1024 * 1024;
const MAX_BINARY: u64 = 256 * 1024 * 1024;

#[derive(Debug, Args)]
pub struct SelfArgs {
    #[command(subcommand)]
    pub action: SelfAction,
}

#[derive(Debug, Subcommand)]
pub enum SelfAction {
    /// Update a standalone installation; show instructions for package-managed installations.
    Update {
        /// Install this exact release instead of the latest release.
        #[arg(long)]
        target_version: Option<String>,
        /// Confirm the update without an interactive prompt.
        #[arg(short = 'y', long)]
        yes: bool,
    },
    /// Remove the standalone executable; preserve configuration and saved evidence.
    Uninstall {
        /// Confirm removal without an interactive prompt.
        #[arg(short = 'y', long)]
        yes: bool,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    schema: u32,
    method: String,
    version: String,
    sha256: String,
    #[serde(default)]
    path_added: bool,
}

#[derive(Debug, PartialEq, Eq)]
enum Owner {
    Standalone(Receipt),
    Uv,
    PythonEnvironment,
    Cargo,
}

fn regular(path: &Path) -> Result<()> {
    let metadata =
        fs::symlink_metadata(path).with_context(|| format!("Inspect {}", path.display()))?;
    ensure!(
        metadata.is_file() && !metadata.file_type().is_symlink(),
        "Refusing non-regular file {}",
        path.display()
    );
    Ok(())
}

fn digest(path: &Path) -> Result<String> {
    regular(path)?;
    let mut input = fs::File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024];
    loop {
        let read = input.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(buffer.get(..read).context("Invalid read length")?);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn load_receipt(executable: &Path) -> Result<Receipt> {
    let directory = executable.parent().context("Executable has no directory")?;
    let path = directory.join(RECEIPT);
    regular(&path).context("Standalone installation receipt missing. Reinstall with the standalone installer to enable self maintenance")?;
    ensure!(
        fs::metadata(&path)?.len() <= 4096,
        "Installation receipt is too large"
    );
    let receipt: Receipt = serde_json::from_slice(&fs::read(path)?)?;
    ensure!(
        receipt.schema == 1 && receipt.method == "standalone",
        "Unknown installation receipt"
    );
    validate_version(&receipt.version)?;
    ensure!(
        receipt.sha256 == digest(executable)?,
        "Installation receipt does not match the running binary. Use the installation method that now owns this executable"
    );
    Ok(receipt)
}

fn owner(executable: &Path) -> Result<Owner> {
    regular(executable)?;
    ensure!(
        executable.file_name()
            == Some(OsStr::new(if cfg!(windows) {
                "yosoi.exe"
            } else {
                "yosoi"
            })),
        "Unknown executable name; reinstall through a supported method"
    );
    let bin = executable.parent().context("Executable has no directory")?;
    let root = bin.parent().context("Executable directory has no parent")?;
    if find_uv_installation(executable, &uv_roots())?.is_some() {
        return Ok(Owner::Uv);
    }
    // Package ownership wins over any stale standalone receipt left by a method change.
    if root.join("pyvenv.cfg").is_file() {
        return Ok(if root.join("uv-receipt.toml").is_file() {
            Owner::Uv
        } else {
            Owner::PythonEnvironment
        });
    }
    if bin.file_name() == Some(OsStr::new("bin")) && root.join(".crates2.json").exists() {
        let metadata: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(".crates2.json"))?)?;
        if metadata
            .get("installs")
            .and_then(|v| v.as_object())
            .is_some_and(|installs| {
                installs.iter().any(|(name, entry)| {
                    name.starts_with("yosoi ")
                        && entry
                            .get("bins")
                            .and_then(|v| v.as_array())
                            .is_some_and(|bins| {
                                bins.iter().any(|v| {
                                    v.as_str()
                                        == Some(if cfg!(windows) { "yosoi.exe" } else { "yosoi" })
                                })
                            })
                })
            })
        {
            return Ok(Owner::Cargo);
        }
    }
    // Older Cargo metadata and other virtual environments remain package-managed.
    ensure!(
        !root.join(".crates.toml").exists(),
        "Cargo installation metadata is present. Use `cargo install yosoi --features cli --locked` or `cargo uninstall yosoi`"
    );
    Ok(Owner::Standalone(load_receipt(executable)?))
}

fn uv_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(root) = env::var_os("UV_TOOL_DIR") {
        roots.push(PathBuf::from(root));
    }
    if let Some(root) = env::var_os("UV_STATE_DIR") {
        roots.push(PathBuf::from(root).join("tools"));
    }
    if let Some(root) = env::var_os("XDG_DATA_HOME") {
        roots.push(PathBuf::from(root).join("uv/tools"));
    }
    if let Some(home) = env::var_os("HOME") {
        roots.push(PathBuf::from(home).join(".local/share/uv/tools"));
    }
    for variable in ["APPDATA", "LOCALAPPDATA"] {
        if let Some(root) = env::var_os(variable) {
            roots.push(PathBuf::from(root).join("uv/tools"));
        }
    }
    // Unix exports are symlinks into the environment; this also handles a custom
    // tool root whose UV_TOOL_DIR is no longer set in the caller's shell.
    if let Some(root) = roots_from_environment_executable() {
        roots.push(root);
    }
    roots.sort();
    roots.dedup();
    roots
}

fn roots_from_environment_executable() -> Option<PathBuf> {
    let executable = env::current_exe().ok()?.canonicalize().ok()?;
    let environment = executable.parent()?.parent()?;
    environment
        .join("uv-receipt.toml")
        .is_file()
        .then(|| environment.parent().map(Path::to_path_buf))
        .flatten()
}

fn find_uv_installation(
    executable: &Path,
    roots: &[PathBuf],
) -> Result<Option<(PathBuf, PathBuf)>> {
    let mut found = None;
    for root in roots {
        let environment = root.join("yosoi-cli");
        let receipt_path = environment.join("uv-receipt.toml");
        if !receipt_path.is_file() {
            continue;
        }
        ensure!(
            fs::metadata(&receipt_path)?.len() <= 1024 * 1024,
            "UV receipt too large"
        );
        let receipt: toml::Value = toml::from_str(&fs::read_to_string(receipt_path)?)?;
        let Some(entries) = receipt
            .get("tool")
            .and_then(|t| t.get("entrypoints"))
            .and_then(|e| e.as_array())
        else {
            continue;
        };
        for entry in entries {
            let Some(path) = entry.get("install-path").and_then(|p| p.as_str()) else {
                continue;
            };
            let export = PathBuf::from(path);
            if export.canonicalize().ok().as_deref() != Some(executable) {
                continue;
            }
            let source = environment.join(if cfg!(windows) {
                "Scripts/yosoi.exe"
            } else {
                "bin/yosoi"
            });
            if !source.is_file()
                || (source.canonicalize()?.as_path() != executable
                    && digest(&source)? != digest(executable)?)
            {
                continue;
            }
            let bin = export
                .parent()
                .context("UV entrypoint has no directory")?
                .to_path_buf();
            let location = (root.canonicalize()?, bin);
            ensure!(
                found.as_ref().is_none_or(|prior| prior == &location),
                "Multiple UV receipts claim this executable"
            );
            found = Some(location);
        }
    }
    Ok(found)
}

fn quote_path(path: &Path) -> Result<String> {
    let path = path
        .to_str()
        .context("Installation path is not UTF-8; run the package manager manually")?;
    ensure!(
        !path.contains(['\n', '\r']),
        "Installation path contains a newline; run the package manager manually"
    );
    Ok(format!(
        "'{}'",
        if cfg!(windows) {
            path.replace('\'', "''")
        } else {
            path.replace('\'', "'\"'\"'")
        }
    ))
}

fn manager_guidance(
    executable: &Path,
    installation: &Owner,
    action: &SelfAction,
) -> Result<String> {
    let command = guidance(installation, action)?;
    match installation {
        Owner::Cargo => {
            let root = executable
                .parent()
                .and_then(Path::parent)
                .context("Cargo root missing")?;
            Ok(format!("{command} --root {}", quote_path(root)?))
        }
        Owner::Uv => {
            if let Some((root, bin)) = find_uv_installation(executable, &uv_roots())? {
                let root = quote_path(&root)?;
                let bin = quote_path(&bin)?;
                Ok(if cfg!(windows) {
                    format!("$env:UV_TOOL_DIR = {root}; $env:UV_TOOL_BIN_DIR = {bin}; {command}")
                } else {
                    format!("UV_TOOL_DIR={root} UV_TOOL_BIN_DIR={bin} {command}")
                })
            } else {
                Ok(command)
            }
        }
        _ => Ok(command),
    }
}

fn guidance(owner: &Owner, action: &SelfAction) -> Result<String> {
    let update = matches!(action, SelfAction::Update { .. });
    let version = match action {
        SelfAction::Update { target_version, .. } => target_version.as_deref(),
        SelfAction::Uninstall { .. } => None,
    };
    if let Some(version) = version {
        validate_version(version)?;
    }
    Ok(match owner {
        Owner::Uv => {
            if update {
                version.map_or_else(
                    || "uv tool upgrade yosoi-cli".into(),
                    |v| {
                        format!(
                            "uv tool install --force yosoi-cli=={}",
                            v.replace("-rc.", "rc")
                        )
                    },
                )
            } else {
                "uv tool uninstall yosoi-cli".into()
            }
        }
        Owner::Cargo => {
            if update {
                version.map_or_else(
                    || "cargo install yosoi --features cli --locked".into(),
                    |v| format!("cargo install yosoi --features cli --locked --version '={v}'"),
                )
            } else {
                "cargo uninstall yosoi".into()
            }
        }
        Owner::PythonEnvironment => {
            if update {
                "This executable belongs to a Python environment (possibly uvx). Update through that environment's package manager. For one-off use: uvx --from yosoi-cli yosoi --help".into()
            } else {
                "This executable belongs to a Python environment (possibly uvx). Remove yosoi-cli through that environment's package manager; uvx has no permanent tool installation to uninstall".into()
            }
        }
        Owner::Standalone(_) => {
            bail!("Standalone installations do not need package-manager guidance")
        }
    })
}

fn validate_version(version: &str) -> Result<()> {
    let (base, rc) = match version.split_once("-rc.") {
        Some((base, rc)) => (base, Some(rc)),
        None => (version, None),
    };
    let pieces: Vec<_> = base.split('.').collect();
    ensure!(
        pieces.len() == 3 && pieces.first() == Some(&"0"),
        "Expected a release version such as 0.3.0 or 0.3.0-rc.1"
    );
    for (index, part) in pieces.iter().enumerate().skip(1) {
        ensure!(
            !part.is_empty()
                && part.bytes().all(|c| c.is_ascii_digit())
                && (part.len() == 1 || !part.starts_with('0')),
            "Invalid release version"
        );
        let number: u32 = part.parse()?;
        ensure!(
            if index == 1 {
                (1..=100_000).contains(&number)
            } else {
                number <= 10_000
            },
            "Release version outside supported range"
        );
    }
    if let Some(rc) = rc {
        ensure!(
            !rc.starts_with('0')
                && rc.bytes().all(|c| c.is_ascii_digit())
                && rc.parse::<u32>()? > 0,
            "Invalid release candidate"
        );
    }
    Ok(())
}

#[derive(Debug, PartialEq, Eq, PartialOrd, Ord)]
enum ReleaseStage {
    Candidate(u32),
    Final,
}

fn release_order(version: &str) -> Result<(u32, u32, ReleaseStage)> {
    validate_version(version)?;
    let (base, stage) = if let Some((base, candidate)) = version.split_once("-rc.") {
        (base, ReleaseStage::Candidate(candidate.parse()?))
    } else {
        (version, ReleaseStage::Final)
    };
    let mut components = base.split('.').skip(1);
    let minor = components
        .next()
        .context("Missing minor version")?
        .parse()?;
    let patch = components
        .next()
        .context("Missing patch version")?
        .parse()?;
    Ok((minor, patch, stage))
}

fn should_update(installed: &str, target: &str, explicit: bool) -> Result<bool> {
    let installed = release_order(installed)?;
    let target = release_order(target)?;
    Ok(if explicit {
        target != installed
    } else {
        target > installed
    })
}

struct Lock {
    path: PathBuf,
    release: bool,
}
impl Lock {
    fn acquire(directory: &Path) -> Result<Self> {
        let path = directory.join(LOCK);
        fs::OpenOptions::new().write(true).create_new(true).open(&path).context("Another installer or self operation holds the maintenance lock. If it was interrupted, inspect and remove .yosoi-maintenance.lock before retrying")?;
        Ok(Self {
            path,
            release: true,
        })
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        if self.release {
            let _ = fs::remove_file(&self.path);
        }
    }
}

fn confirmation(answer: &str, default_yes: bool) -> Result<bool> {
    match answer.trim().to_ascii_lowercase().as_str() {
        "" => Ok(default_yes),
        "y" | "yes" => Ok(true),
        "n" | "no" => Ok(false),
        _ => bail!("Answer yes or no"),
    }
}

fn confirm(prompt: &str, default_yes: bool, yes: bool) -> Result<bool> {
    if yes {
        return Ok(true);
    }
    ensure!(
        io::stdin().is_terminal(),
        "Maintenance requires confirmation; use --yes in a non-interactive session"
    );
    loop {
        write!(
            io::stdout().lock(),
            "{prompt} {} ",
            if default_yes { "[Y/n]" } else { "[y/N]" }
        )?;
        io::stdout().flush()?;
        let mut answer = String::new();
        if io::stdin().read_line(&mut answer)? == 0 {
            return Ok(false);
        }
        match confirmation(&answer, default_yes) {
            Ok(answer) => return Ok(answer),
            Err(_) => writeln!(io::stderr().lock(), "Please answer yes or no.")?,
        }
    }
}

async fn download(client: &reqwest::Client, url: &str, limit: usize) -> Result<Vec<u8>> {
    let mut response = client.get(url).send().await?.error_for_status()?;
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await? {
        ensure!(
            bytes
                .len()
                .checked_add(chunk.len())
                .is_some_and(|size| size <= limit),
            "Release download exceeds size limit"
        );
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

fn platform(os: &str, arch: &str) -> Result<&'static str> {
    match (os, arch) {
        ("linux", "x86_64") => Ok("linux-x86_64"),
        ("linux", "aarch64") => Ok("linux-aarch64"),
        ("macos", "x86_64") => Ok("macos-x86_64"),
        ("macos", "aarch64") => Ok("macos-aarch64"),
        ("windows", "x86_64") => Ok("windows-x86_64"),
        _ => bail!("No prebuilt CLI release for {os}/{arch}; use Cargo"),
    }
}

fn checksum(manifest: &[u8], asset: &str) -> Result<String> {
    let rows: Vec<_> = str::from_utf8(manifest)?
        .lines()
        .filter_map(|line| line.split_once("  "))
        .filter(|(_, name)| *name == asset)
        .collect();
    ensure!(rows.len() == 1, "Missing or duplicate archive checksum");
    let (hash, _) = rows.first().context("Missing checksum")?;
    ensure!(
        hash.len() == 64
            && hash
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),
        "Invalid archive checksum"
    );
    Ok((*hash).into())
}

// Release archives have one regular ustar member. Read it without extracting paths,
// links, permissions or archive-controlled metadata into the filesystem.
fn archive_binary(compressed: &[u8], expected_hash: &str, name: &str) -> Result<Vec<u8>> {
    ensure!(
        format!("{:x}", Sha256::digest(compressed)) == expected_hash,
        "Archive checksum mismatch"
    );
    let mut archive = Vec::new();
    GzDecoder::new(compressed)
        .take(MAX_BINARY + 10241)
        .read_to_end(&mut archive)?;
    ensure!(
        u64::try_from(archive.len())? <= MAX_BINARY + 10240,
        "Release archive is too large"
    );
    let header = archive.get(..512).context("Missing tar header")?;
    let text = |range| -> Result<&str> {
        Ok(
            str::from_utf8(header.get(range).context("Invalid tar field")?)?
                .trim_matches(|c: char| c == '\0' || c.is_ascii_whitespace()),
        )
    };
    let octal = |range| -> Result<u64> { Ok(u64::from_str_radix(text(range)?, 8)?) };
    ensure!(
        text(0..100)? == name && text(345..500)?.is_empty(),
        "Unexpected archive member"
    );
    ensure!(
        header.get(156).is_some_and(|c| *c == 0 || *c == b'0'),
        "Archive member must be a regular executable"
    );
    ensure!(
        text(257..263)?.starts_with("ustar"),
        "Expected ustar release archive"
    );
    let sum: u64 = header
        .iter()
        .enumerate()
        .map(|(i, c)| {
            if (148..156).contains(&i) {
                32
            } else {
                u64::from(*c)
            }
        })
        .sum();
    ensure!(sum == octal(148..156)?, "Invalid tar header checksum");
    let length = usize::try_from(octal(124..136)?)?;
    ensure!(
        length > 0 && u64::try_from(length)? <= MAX_BINARY,
        "Invalid executable size"
    );
    let end = 512_usize
        .checked_add(length)
        .context("Archive size overflow")?;
    let padded = end
        .checked_add(511)
        .and_then(|size| size.checked_div(512))
        .and_then(|blocks| blocks.checked_mul(512))
        .context("Archive size overflow")?;
    let tail = archive.get(padded..).context("Truncated release archive")?;
    ensure!(
        tail.len() >= 1024 && tail.iter().all(|c| *c == 0),
        "Unexpected extra archive contents"
    );
    Ok(archive
        .get(512..end)
        .context("Truncated executable")?
        .to_vec())
}

fn write_receipt(path: &Path, receipt: &Receipt) -> Result<()> {
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    file.write_all(&serde_json::to_vec(receipt)?)?;
    file.sync_all()?;
    Ok(())
}

fn recheck(executable: &Path, receipt: &Receipt) -> Result<()> {
    let Owner::Standalone(current) = owner(executable)? else {
        bail!("Installation method changed during maintenance");
    };
    ensure!(
        current == *receipt,
        "Installation receipt changed during maintenance"
    );
    Ok(())
}

async fn verify_binary(path: &Path, version: &str) -> Result<()> {
    let output = timeout(
        Duration::from_secs(30),
        AsyncCommand::new(path)
            .arg("--version")
            .kill_on_drop(true)
            .output(),
    )
    .await
    .context("Downloaded CLI version check timed out")??;
    ensure!(
        output.status.success()
            && String::from_utf8(output.stdout)?.trim() == format!("yosoi {version}"),
        "Downloaded CLI version does not match selected release"
    );
    Ok(())
}

async fn stage_archive(
    directory: &Path,
    receipt: &Receipt,
    version: &str,
    compressed: &[u8],
    hash: &str,
) -> Result<(tempfile::TempDir, PathBuf)> {
    validate_version(version)?;
    let bytes = archive_binary(
        compressed,
        hash,
        if cfg!(windows) { "yosoi.exe" } else { "yosoi" },
    )?;
    let staging = tempfile::Builder::new()
        .prefix(".yosoi-update-")
        .tempdir_in(directory)?;
    let candidate = staging
        .path()
        .join(if cfg!(windows) { "yosoi.exe" } else { "yosoi" });
    fs::write(&candidate, &bytes)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&candidate, fs::Permissions::from_mode(0o755))?;
    }
    verify_binary(&candidate, version).await?;
    let next = Receipt {
        version: version.to_owned(),
        sha256: digest(&candidate)?,
        ..receipt.clone()
    };
    write_receipt(&staging.path().join(RECEIPT), &next)?;

    Ok((staging, candidate))
}

pub async fn run(args: SelfArgs) -> Result<()> {
    let executable = env::current_exe()?.canonicalize()?;
    let installation = owner(&executable)?;
    let Owner::Standalone(receipt) = installation else {
        writeln!(
            io::stdout().lock(),
            "Package-managed installation. Run:\n{}",
            manager_guidance(&executable, &installation, &args.action)?
        )?;
        return Ok(());
    };
    let directory = executable.parent().context("Executable has no directory")?;
    #[allow(unused_mut)]
    let mut _lock = Lock::acquire(directory)?;
    // owner() already verified the executable. Defer the second full-file hash
    // until confirmation so cancellation does not pay for it. Mutations still
    // recheck ownership under this lock and again at their final commit boundary.
    match args.action {
        SelfAction::Uninstall { yes } => {
            if !confirm(&format!("Remove {}?", executable.display()), false, yes)? {
                writeln!(io::stdout().lock(), "Uninstall cancelled.")?;
                return Ok(());
            }
            recheck(&executable, &receipt)?;
            uninstall(&executable, &receipt)?;
            #[cfg(windows)]
            {
                _lock.release = false;
            }
        }
        SelfAction::Update {
            target_version,
            yes,
        } => {
            let explicit_version = target_version.is_some();
            if let Some(version) = &target_version {
                validate_version(version)?;
            }
            let _ = ring_crypto_provider().install_default();
            let client = reqwest::Client::builder()
                .https_only(true)
                .connect_timeout(Duration::from_secs(15))
                .timeout(Duration::from_secs(300))
                .build()?;
            let version = if let Some(version) = target_version {
                version
            } else {
                let plan: serde_json::Value = serde_json::from_slice(
                    &download(
                        &client,
                        &format!("{RELEASES}/latest/download/release-plan.json"),
                        1024 * 1024,
                    )
                    .await?,
                )?;
                plan.get("version")
                    .and_then(|v| v.as_str())
                    .context("Release plan has no version")?
                    .to_owned()
            };
            validate_version(&version)?;
            if version == receipt.version {
                writeln!(io::stdout().lock(), "Yosoi {version} is already installed.")?;
                return Ok(());
            }
            if !should_update(&receipt.version, &version, explicit_version)? {
                writeln!(
                    io::stdout().lock(),
                    "Keeping Yosoi {}. Latest stable release {version} is not newer.",
                    receipt.version
                )?;
                return Ok(());
            }
            if !confirm(
                &format!("Update Yosoi {} to {version}?", receipt.version),
                true,
                yes,
            )? {
                writeln!(io::stdout().lock(), "Update cancelled.")?;
                return Ok(());
            }
            recheck(&executable, &receipt)?;
            let asset = format!(
                "yosoi-v{version}-{}.tar.gz",
                platform(env::consts::OS, env::consts::ARCH)?
            );
            let base = format!("{RELEASES}/download/v{version}");
            let hash = checksum(
                &download(&client, &format!("{base}/SHA256SUMS"), 1024 * 1024).await?,
                &asset,
            )?;
            let compressed = download(&client, &format!("{base}/{asset}"), MAX_ARCHIVE).await?;
            let (staging, candidate) =
                stage_archive(directory, &receipt, &version, &compressed, &hash).await?;
            replace(&executable, &receipt, &candidate, &staging)?;
            #[cfg(windows)]
            {
                staging.keep();
                _lock.release = false;
            }
            #[cfg(not(windows))]
            writeln!(io::stdout().lock(), "Updated Yosoi to {version}.")?;
        }
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace(
    executable: &Path,
    receipt: &Receipt,
    candidate: &Path,
    staging: &tempfile::TempDir,
) -> Result<()> {
    recheck(executable, receipt)?;
    let directory = executable.parent().context("Executable has no directory")?;
    let backup = directory.join(format!(".yosoi-backup-{}", uuid::Uuid::new_v4()));
    fs::hard_link(executable, &backup).context("Preserve installed executable")?;
    fs::rename(candidate, executable).context("Replace installed executable")?;
    if let Err(error) = fs::rename(staging.path().join(RECEIPT), directory.join(RECEIPT)) {
        fs::rename(&backup, executable).with_context(|| {
            format!(
                "Receipt commit and binary rollback failed; previous executable preserved at {}",
                backup.display()
            )
        })?;
        return Err(error).context("Receipt commit failed; previous executable restored");
    }
    fs::remove_file(backup).context("Update committed, but backup cleanup failed")?;
    Ok(())
}

#[cfg(not(windows))]
fn uninstall(executable: &Path, receipt: &Receipt) -> Result<()> {
    recheck(executable, receipt)?;
    let directory = executable.parent().context("Executable has no directory")?;
    fs::remove_file(executable)?;
    fs::remove_file(directory.join(RECEIPT))
        .context("Executable removed, but receipt cleanup failed")?;
    writeln!(
        io::stdout().lock(),
        "Removed {}. Configuration and saved evidence were preserved.",
        executable.display()
    )?;
    Ok(())
}

#[cfg(windows)]
fn replace(
    executable: &Path,
    receipt: &Receipt,
    candidate: &Path,
    staging: &tempfile::TempDir,
) -> Result<()> {
    launch_windows_helper(executable, receipt, Some(candidate), staging.path())?;
    // Helper owns staging after launch; it persists the result outside this directory.
    // TempDir::keep consumes ownership; caller invokes it after launch below.
    Ok(())
}

#[cfg(windows)]
fn uninstall(executable: &Path, receipt: &Receipt) -> Result<()> {
    let directory = executable.parent().context("Executable has no directory")?;
    let staging = tempfile::Builder::new()
        .prefix(".yosoi-remove-")
        .tempdir_in(directory)?;
    launch_windows_helper(executable, receipt, None, staging.path())?;
    staging.keep();
    Ok(())
}

#[cfg(any(windows, test))]
fn launch_windows_helper(
    executable: &Path,
    receipt: &Receipt,
    candidate: Option<&Path>,
    staging: &Path,
) -> Result<()> {
    use dunce::simplified;
    use std::process::{self, Command, Stdio};
    use std::{io::BufRead, sync::mpsc, thread};
    use uuid::Uuid;
    let script = staging.join("maintenance.ps1");
    let executable_label = executable.display().to_string();
    fs::write(&script, include_str!("self_command/windows-helper.ps1"))?;
    let outcome = env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .context("LOCALAPPDATA is unavailable")?
        .join("Yosoi")
        .join("maintenance");
    fs::create_dir_all(&outcome)?;
    let outcome = outcome.join(format!("{}.json", Uuid::new_v4()));
    let startup_log = outcome.with_extension("stderr.log");
    let startup_stderr = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&startup_log)?;
    let mut command = Command::new("powershell.exe");
    command
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-OutputFormat",
            "Text",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ])
        .arg(simplified(&script))
        .arg("-ParentId")
        .arg(process::id().to_string())
        .arg("-Executable")
        .arg(simplified(executable))
        .arg("-ExpectedHash")
        .arg(&receipt.sha256)
        .arg("-Staging")
        .arg(simplified(staging))
        .arg("-Outcome")
        .arg(simplified(&outcome));
    if let Some(candidate) = candidate {
        command.arg("-Candidate").arg(simplified(candidate));
    }
    fs::write(
        &outcome,
        serde_json::to_vec(
            &serde_json::json!({"status": "pending", "executable": executable_label}),
        )?,
    )?;
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(startup_stderr))
        .spawn()
        .context("Start Windows maintenance helper")?;
    let stdout = child.stdout.take().context("Helper stdout unavailable")?;
    let (send, receive) = mpsc::channel();
    thread::spawn(move || {
        let mut line = String::new();
        let result = io::BufReader::new(stdout)
            .read_line(&mut line)
            .map(|_| line);
        let _ = send.send(result);
    });
    let ready = receive.recv_timeout(Duration::from_secs(15));
    if !matches!(ready, Ok(Ok(ref line)) if line.trim() == "READY") {
        let _ = child.kill();
        let _ = child.wait();
        let mut diagnostic_bytes = Vec::new();
        fs::File::open(&startup_log)?
            .take(4096)
            .read_to_end(&mut diagnostic_bytes)?;
        let diagnostic = String::from_utf8_lossy(&diagnostic_bytes);
        let early_result = fs::read(&outcome).ok().and_then(|bytes| {
            let json = bytes
                .strip_prefix(b"\xef\xbb\xbf")
                .map_or(bytes.as_slice(), |json| json);
            serde_json::from_slice::<serde_json::Value>(json).ok()
        });
        fs::write(
            &outcome,
            serde_json::to_vec(
                &serde_json::json!({"status":"failed", "error":"Windows helper did not acknowledge startup", "diagnostic":diagnostic, "first_output":format!("{ready:?}"), "helper_result":early_result}),
            )?,
        )?;
        bail!(
            "Windows helper did not acknowledge startup; no maintenance was scheduled. See {}. Startup diagnostic: {}. First output: {ready:?}. Helper result: {early_result:?}",
            outcome.display(),
            diagnostic.trim()
        );
    }
    fs::write(
        &outcome,
        serde_json::to_vec(
            &serde_json::json!({"status":"pending", "helper_id":child.id(), "executable":executable_label}),
        )?,
    )?;
    writeln!(
        io::stdout().lock(),
        "Maintenance scheduled after Yosoi exits. Read the final result at {}.",
        outcome.display()
    )?;
    Ok(())
}
