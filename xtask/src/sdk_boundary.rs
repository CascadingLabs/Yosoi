//! Compile a real renamed SDK consumer and reject leaks of internal APIs.
use std::{env, fs, process::Command};

use anyhow::{Context, Result, bail};

enum Outcome {
    Compiles,
    Rejected(&'static str),
}

struct Case {
    name: &'static str,
    source: &'static str,
    outcome: Outcome,
}

pub fn run() -> Result<()> {
    let repository = super::workspace_root()?;
    let consumer = tempfile::Builder::new()
        .prefix("yosoi-consumer-")
        .tempdir()
        .context("failed to create temporary SDK consumer")?;
    let root = consumer.path();
    fs::create_dir(root.join("src")).context("failed to create consumer source directory")?;
    fs::copy(repository.join("Cargo.lock"), root.join("Cargo.lock"))
        .context("failed to copy workspace lockfile")?;
    // JSON string escaping is also valid for this TOML path string.
    let sdk_path = serde_json::to_string(&repository.join("crates/yosoi"))?;
    fs::write(root.join("Cargo.toml"), format!(
        "[package]\nname=\"sdk-consumer\"\nversion=\"0.0.0\"\nedition=\"2024\"\n[workspace]\n[dependencies]\nsdk={{package=\"yosoi\",path={sdk_path}}}\n"
    )).context("failed to write consumer manifest")?;
    let channel = env::var("SDK_CHECK_TOOLCHAIN").unwrap_or_else(|_| "nightly".to_owned());
    let target = repository.join(".generated/rust-reference/target");
    for case in CASES {
        fs::write(root.join("src/main.rs"), case.source)
            .with_context(|| format!("failed to write SDK case {}", case.name))?;
        let output = Command::new("cargo")
            .args([
                format!("+{channel}"),
                "check".into(),
                "--offline".into(),
                "-j".into(),
                "1".into(),
            ])
            .current_dir(root)
            .env("CARGO_TARGET_DIR", &target)
            .env("CARGO_BUILD_JOBS", "1")
            .env("RAYON_NUM_THREADS", "1")
            .output()
            .with_context(|| format!("failed to start Cargo for {}", case.name))?;
        let stderr = String::from_utf8_lossy(&output.stderr);
        match case.outcome {
            Outcome::Compiles if !output.status.success() => {
                bail!("SDK case {} failed: {stderr}", case.name);
            }
            Outcome::Rejected(expected) => {
                // A signal or infrastructure failure is not a visibility rejection.
                if output.status.code() != Some(101) || !stderr.contains(expected) {
                    bail!(
                        "SDK case {} expected a compiler rejection containing `{expected}`, got {}: {stderr}",
                        case.name,
                        output.status
                    );
                }
            }
            Outcome::Compiles => {}
        }
        println!("PASS {}", case.name);
    }
    consumer
        .close()
        .context("failed to clean up SDK consumer")?;
    Ok(())
}

const CASES: &[Case] = &[
    Case {
        name: "SDK-only renamed dependency and Contract derive",
        source: r#"use sdk::prelude as ys;
#[derive(ys::Contract)]
#[ys(id="heading",description="Heading",root=ys::locator::css("main"))]
struct Heading { #[ys(description="Heading",locator=ys::locator::css("h1").text())] text:String }
fn main() -> Result<(),Box<dyn std::error::Error>> {
 let document=ys::Document::html("page",b"<main><h1>SDK</h1></main>".to_vec())?;
 let _=Heading::locate(&document)?;
 let policy=ys::Policy::default();
 let _=ys::request::new("https://example.com").bind(&policy).validate()?;
 let _=ys::map::new("https://example.com").bind(&policy);
 Ok(())
}"#,
        outcome: Outcome::Compiles,
    },
    Case {
        name: "implementation module is private to the SDK",
        source: "use sdk::internal::engine::Document; fn main() {}",
        outcome: Outcome::Rejected("private"),
    },
    Case {
        name: "no archive namespace",
        source: "use sdk::archived; fn main() {}",
        outcome: Outcome::Rejected("archived"),
    },
    Case {
        name: "no provider namespace",
        source: "use sdk::projection; fn main() {}",
        outcome: Outcome::Rejected("projection"),
    },
    Case {
        name: "no execution namespace",
        source: "use sdk::request::execution; fn main() {}",
        outcome: Outcome::Rejected("execution"),
    },
    Case {
        name: "request implementation module is private",
        source: "use sdk::request::authoring; fn main() {}",
        outcome: Outcome::Rejected("private"),
    },
    Case {
        name: "response implementation field is private",
        source: "fn inspect(r: sdk::request::Response) { let _=r.inner; } fn main() {}",
        outcome: Outcome::Rejected("private"),
    },
    Case {
        name: "Map implementation field is private",
        source: "fn inspect(r: sdk::map::MapOutcome) { let _=r.inner; } fn main() {}",
        outcome: Outcome::Rejected("private"),
    },
    Case {
        name: "borrowed SDK document has no archive accessor",
        source: "fn inspect(d: sdk::documents::DocumentRef<'_>) { let _=d.archive_value(); } fn main() {}",
        outcome: Outcome::Rejected("archive_value"),
    },
    Case {
        name: "no namespace-specific policy prelude",
        source: "use sdk::policy::prelude; fn main() {}",
        outcome: Outcome::Rejected("prelude"),
    },
    Case {
        name: "no namespace-specific document prelude",
        source: "use sdk::documents::prelude; fn main() {}",
        outcome: Outcome::Rejected("prelude"),
    },
    Case {
        name: "SDK document does not expose engine storage",
        source: r#"fn main() -> Result<(),Box<dyn std::error::Error>> { let d=sdk::documents::Document::html("p",b"<p/>".to_vec())?; let _=d.archive_value(); Ok(()) }"#,
        outcome: Outcome::Rejected("archive_value"),
    },
    Case {
        name: "SDK document inner field is private",
        source: r#"fn main() -> Result<(),Box<dyn std::error::Error>> { let d=sdk::documents::Document::html("p",b"<p/>".to_vec())?; let _=d.inner; Ok(()) }"#,
        outcome: Outcome::Rejected("private"),
    },
    Case {
        name: "SDK requests do not expose custom internal executors",
        source: "fn main() { let _=sdk::request::PageRequest::send_with; }",
        outcome: Outcome::Rejected("send_with"),
    },
];
