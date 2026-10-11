//! Repository release-version synchronization, without dependency resolution.
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsString,
    fs,
    io::{self, BufRead, Write},
    path::{Path, PathBuf},
};

use anyhow::{Context, Result, bail};
use toml_edit::{DocumentMut, Item, Value, value};

mod transaction;

const USAGE: &str = "usage: cargo xtask bump-version <VERSION> [--date-released YYYY-MM-DD] [--dry-run|--check] [-y|--yes]";

#[derive(Debug, PartialEq, Eq)]
enum Mode {
    Apply,
    Preview,
    Check,
}

#[derive(Debug)]
struct Options {
    version: String,
    date: Option<String>,
    mode: Mode,
    yes: bool,
}

impl Options {
    fn parse(arguments: impl Iterator<Item = OsString>) -> Result<Self> {
        let mut arguments = arguments;
        let version = arguments
            .next()
            .context(USAGE)?
            .into_string()
            .map_err(|_| anyhow::anyhow!("version must be Unicode"))?;
        semver::Version::parse(&version).context("use a full Cargo SemVer, for example 0.2.0")?;
        let mut options = Self {
            version,
            date: None,
            mode: Mode::Apply,
            yes: false,
        };
        while let Some(argument) = arguments.next() {
            match argument.to_str().context("option must be Unicode")? {
                "--dry-run" if options.mode == Mode::Apply => options.mode = Mode::Preview,
                "--check" if options.mode == Mode::Apply => options.mode = Mode::Check,
                "-y" | "--yes" if !options.yes => options.yes = true,
                "--date-released" if options.date.is_none() => {
                    options.date = Some(
                        arguments
                            .next()
                            .context("--date-released requires YYYY-MM-DD")?
                            .into_string()
                            .map_err(|_| anyhow::anyhow!("date must be Unicode"))?,
                    );
                }
                _ => bail!("{USAGE}"),
            }
        }
        if options.yes && options.mode != Mode::Apply {
            bail!("-y/--yes applies only to real runs\n{USAGE}");
        }
        Ok(options)
    }
}

pub fn run(arguments: impl Iterator<Item = OsString>) -> Result<()> {
    let options = Options::parse(arguments)?;
    execute(
        super::workspace_root()?,
        &options,
        &mut io::stdin().lock(),
        &mut io::stdout().lock(),
    )
}

fn execute(
    root: &Path,
    options: &Options,
    input: &mut impl BufRead,
    output: &mut impl Write,
) -> Result<()> {
    let changes = plan(root, &options.version, options.date.as_deref())?;
    writeln!(output, "Release version: {}", options.version)?;
    if let Some(date) = &options.date {
        writeln!(output, "CITATION.cff release date: {date}")?;
    }
    for change in &changes {
        writeln!(output, "  {}", change.path.strip_prefix(root)?.display())?;
    }
    if options.mode == Mode::Check && !changes.is_empty() {
        bail!(
            "{} files do not match the requested release metadata",
            changes.len()
        );
    }
    if options.mode != Mode::Apply || changes.is_empty() {
        writeln!(output, "{} file(s) need updating", changes.len())?;
        return Ok(());
    }
    let staged = transaction::stage(&changes)?;
    writeln!(
        output,
        "Staging check passed: {} replacement(s) prepared; originals retained.",
        changes.len()
    )?;
    if !options.yes {
        write!(output, "Apply these changes? [y/N] ")?;
        output.flush()?;
        let mut answer = String::new();
        input
            .read_line(&mut answer)
            .context("failed to read confirmation; use -y for scripting")?;
        match answer.trim().to_ascii_lowercase().as_str() {
            "y" | "yes" => {}
            "" | "n" | "no" => {
                writeln!(output, "Cancelled; release files unchanged.")?;
                return Ok(());
            }
            _ => bail!("expected yes or no; release files unchanged"),
        }
    }
    staged.commit()?;
    writeln!(output, "{} file(s) updated", changes.len())?;
    Ok(())
}

#[derive(Debug)]
struct Change {
    path: PathBuf,
    before: String,
    after: String,
}

fn manifests(directory: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
    if directory.join("Cargo.toml").is_file() {
        paths.push(directory.join("Cargo.toml"));
    }
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        if entry.file_type()?.is_dir()
            && !matches!(
                entry.file_name().to_str(),
                Some("target" | "vendor" | ".git" | ".jj")
            )
        {
            manifests(&entry.path(), paths)?;
        }
    }
    Ok(())
}

fn plan(root: &Path, version: &str, date: Option<&str>) -> Result<Vec<Change>> {
    if let Some(date) = date {
        let parsed = chrono::NaiveDate::parse_from_str(date, "%Y-%m-%d")
            .context("release date must be a valid calendar date in YYYY-MM-DD format")?;
        if date.len() != 10
            || parsed.format("%Y-%m-%d").to_string() != date
            || date.starts_with("0000")
        {
            bail!("release date must use YYYY-MM-DD with a positive four-digit year");
        }
    }
    let mut paths = vec![root.join("Cargo.toml")];
    for directory in ["crates", "benchmarks", "xtask", "fuzz"] {
        let directory = root.join(directory);
        if directory.is_dir() {
            manifests(&directory, &mut paths)?;
        }
    }
    paths.sort();
    let mut documents = Vec::new();
    let mut names = BTreeSet::new();
    for path in paths {
        let before = fs::read_to_string(&path)?;
        let document = before
            .parse::<DocumentMut>()
            .with_context(|| format!("invalid manifest {}", path.display()))?;
        if let Some(name) = document
            .get("package")
            .and_then(|p| p.get("name"))
            .and_then(Item::as_str)
        {
            names.insert(name.to_owned());
        }
        documents.push((path, before, document));
    }
    let root_manifest = documents
        .iter()
        .find(|(path, _, _)| path == &root.join("Cargo.toml"))
        .map(|(_, _, document)| document)
        .context("workspace root manifest is missing")?;
    let independent_versions = independent_package_versions(root_manifest, &documents)?;
    for (_, _, document) in &documents {
        validate_independent_requirements(document.as_item(), &independent_versions)?;
    }
    let synchronized_names = names
        .iter()
        .filter(|name| !independent_versions.contains_key(*name))
        .cloned()
        .collect::<BTreeSet<_>>();

    let mut changes = Vec::new();
    for (path, before, mut document) in documents {
        if let Some(package) = document.get_mut("package").and_then(Item::as_table_mut)
            && !package
                .get("name")
                .and_then(Item::as_str)
                .is_some_and(|name| independent_versions.contains_key(name))
            && package
                .get("version")
                .and_then(Item::as_table_like)
                .is_none_or(|v| v.get("workspace").and_then(Item::as_bool) != Some(true))
        {
            set_version(package.entry("version").or_insert(Item::None), version);
        }
        if path == root.join("Cargo.toml") {
            let package = document
                .get_mut("workspace")
                .and_then(|w| w.get_mut("package"))
                .and_then(Item::as_table_like_mut)
                .context("root manifest requires [workspace.package]")?;
            set_version(package.entry("version").or_insert(Item::None), version);
        }
        update_dependencies(document.as_item_mut(), &synchronized_names, version);
        add_change(&mut changes, path, before, document.to_string());
    }
    for lock in ["Cargo.lock", "fuzz/Cargo.lock"] {
        let path = root.join(lock);
        if !path.is_file() {
            continue;
        }
        let before = fs::read_to_string(&path)?;
        let mut document = before.parse::<DocumentMut>()?;
        let packages = document
            .get_mut("package")
            .and_then(Item::as_array_of_tables_mut)
            .context("lockfile lacks package array")?;
        let local_versions: BTreeMap<String, String> = packages
            .iter()
            .filter(|package| package.get("source").is_none())
            .filter_map(|package| {
                let name = package.get("name")?.as_str()?;
                let old_version = package.get("version")?.as_str()?;
                synchronized_names
                    .contains(name)
                    .then(|| (name.to_owned(), old_version.to_owned()))
            })
            .collect();
        for package in packages.iter_mut() {
            if package.get("source").is_none()
                && package
                    .get("name")
                    .and_then(Item::as_str)
                    .is_some_and(|name| synchronized_names.contains(name))
            {
                set_version(
                    package
                        .get_mut("version")
                        .context("lockfile package lacks version")?,
                    version,
                );
            }
            if let Some(dependencies) = package.get_mut("dependencies").and_then(Item::as_array_mut)
            {
                for dependency in dependencies.iter_mut() {
                    if let Some(text) = dependency.as_str() {
                        let parts: Vec<_> = text.split_whitespace().collect();
                        if let [name, old_version] = parts.as_slice()
                            && local_versions
                                .get(*name)
                                .is_some_and(|local| local == old_version)
                        {
                            let decor = dependency.decor().clone();
                            *dependency = Value::from(format!("{name} {version}"));
                            *dependency.decor_mut() = decor;
                        }
                    }
                }
            }
        }
        add_change(&mut changes, path, before, document.to_string());
    }
    let path = root.join("CITATION.cff");
    let before = fs::read_to_string(&path).context("release metadata requires CITATION.cff")?;
    if before
        .lines()
        .filter(|line| line.starts_with("version:"))
        .count()
        != 1
    {
        bail!("CITATION.cff must have exactly one top-level version field");
    }
    let date_count = before
        .lines()
        .filter(|line| line.starts_with("date-released:"))
        .count();
    if date.is_some() && date_count > 1 {
        bail!("CITATION.cff has duplicate top-level date-released fields");
    }
    let mut after = before
        .split_inclusive('\n')
        .map(|line| {
            if line.starts_with("version:") {
                format!(
                    "version: \"{version}\"{}",
                    if line.ends_with('\n') { "\n" } else { "" }
                )
            } else if let Some(date) = date.filter(|_| line.starts_with("date-released:")) {
                format!(
                    "date-released: {date}{}",
                    if line.ends_with('\n') { "\n" } else { "" }
                )
            } else {
                line.to_owned()
            }
        })
        .collect::<String>();
    if let Some(date) = date.filter(|_| date_count == 0) {
        if !after.ends_with('\n') {
            after.push('\n');
        }
        after.push_str("date-released: ");
        after.push_str(date);
        after.push('\n');
    }
    add_change(&mut changes, path, before, after);
    Ok(changes)
}

fn independent_package_versions(
    root_manifest: &DocumentMut,
    documents: &[(PathBuf, String, DocumentMut)],
) -> Result<BTreeMap<String, String>> {
    let Some(packages) = root_manifest
        .get("workspace")
        .and_then(|workspace| workspace.get("metadata"))
        .and_then(|metadata| metadata.get("yosoi-release"))
        .and_then(|release| release.get("independent-version-packages"))
    else {
        return Ok(BTreeMap::new());
    };
    let packages = packages.as_array().context(
        "workspace.metadata.yosoi-release.independent-version-packages must be an array",
    )?;
    let mut independent = BTreeMap::new();
    for value in packages {
        let name = value
            .as_str()
            .context("independent version package names must be strings")?;
        if independent.contains_key(name) {
            bail!("duplicate independent version package: {name}");
        }
        let mut found = None;
        for (_, _, document) in documents {
            let Some(package) = document.get("package") else {
                continue;
            };
            if package.get("name").and_then(Item::as_str) != Some(name) {
                continue;
            }
            let version = package
                .get("version")
                .and_then(Item::as_str)
                .with_context(|| {
                    format!("independent package {name} must declare an explicit version")
                })?;
            semver::Version::parse(version)
                .with_context(|| format!("independent package {name} has invalid version"))?;
            if found.replace(version.to_owned()).is_some() {
                bail!("independent package name appears in multiple manifests: {name}");
            }
        }
        let version = found.with_context(|| {
            format!("independent version package is missing from synchronized manifests: {name}")
        })?;
        independent.insert(name.to_owned(), version);
    }
    Ok(independent)
}

fn validate_independent_requirements(
    item: &Item,
    independent_versions: &BTreeMap<String, String>,
) -> Result<()> {
    let Some(table) = item.as_table_like() else {
        return Ok(());
    };
    for (key, child) in table.iter() {
        if matches!(
            key,
            "dependencies" | "dev-dependencies" | "build-dependencies"
        ) {
            let Some(dependencies) = child.as_table_like() else {
                continue;
            };
            for (alias, dependency) in dependencies.iter() {
                let Some(specification) = dependency.as_table_like() else {
                    let name = alias;
                    if let Some(version) = independent_versions.get(name) {
                        let expected = format!("={version}");
                        if dependency.as_str() != Some(expected.as_str()) {
                            bail!(
                                "dependency {name} must use the exact independent version {expected}"
                            );
                        }
                    }
                    continue;
                };
                if specification.get("workspace").and_then(Item::as_bool) == Some(true) {
                    continue;
                }
                let name = specification
                    .get("package")
                    .and_then(Item::as_str)
                    .unwrap_or(alias);
                let Some(version) = independent_versions.get(name) else {
                    continue;
                };
                let expected = format!("={version}");
                if specification.get("version").and_then(Item::as_str) != Some(expected.as_str()) {
                    bail!("dependency {name} must use the exact independent version {expected}");
                }
            }
        } else {
            validate_independent_requirements(child, independent_versions)?;
        }
    }
    Ok(())
}

fn set_version(item: &mut Item, version: &str) {
    let decor = item.as_value().map(|v| v.decor().clone());
    *item = value(version);
    if let (Some(decor), Some(value)) = (decor, item.as_value_mut()) {
        *value.decor_mut() = decor;
    }
}

fn update_dependencies(item: &mut Item, names: &BTreeSet<String>, version: &str) {
    if let Some(table) = item.as_table_like_mut() {
        for (key, item) in table.iter_mut() {
            if matches!(
                key.get(),
                "dependencies" | "dev-dependencies" | "build-dependencies"
            ) {
                if let Some(dependencies) = item.as_table_like_mut() {
                    for (alias, dependency) in dependencies.iter_mut() {
                        if let Some(spec) = dependency.as_table_like_mut() {
                            let name = spec
                                .get("package")
                                .and_then(Item::as_str)
                                .unwrap_or_else(|| alias.get());
                            if names.contains(name) && spec.get("path").is_some() {
                                // Exact requirements also admit the requested prerelease.
                                set_version(
                                    spec.entry("version").or_insert(Item::None),
                                    &format!("={version}"),
                                );
                            }
                        }
                    }
                }
            } else {
                update_dependencies(item, names, version);
            }
        }
    }
}

fn add_change(changes: &mut Vec<Change>, path: PathBuf, before: String, after: String) {
    if before != after {
        changes.push(Change {
            path,
            before,
            after,
        });
    }
}

#[cfg(test)]
fn apply(changes: &[Change]) -> Result<()> {
    transaction::stage(changes)?.commit()
}

#[cfg(test)]
mod tests;
