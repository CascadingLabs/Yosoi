#![allow(clippy::unwrap_used, reason = "committed benchmark contract test")]

use std::{collections::BTreeSet, fs, path::PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

#[derive(Debug, Deserialize)]
struct Manifest {
    schema_version: u32,
    fixtures: Vec<Fixture>,
}

#[derive(Debug, Deserialize)]
struct Fixture {
    name: String,
    file: String,
    generator: String,
    generator_version: String,
    uncompressed_bytes: u64,
    encoded_bytes: u64,
    media_type: String,
    character_encoding: String,
    content_coding: String,
    sha256: String,
    extent: String,
    route: String,
    operation: String,
    setup_excluded: String,
    cache_assumption: String,
    sensitivity: String,
    determinism: String,
    filesystem_sink: String,
}

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/web-capture/v1")
}

fn browser_fixture_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/browser-capture")
}

fn manifest() -> Manifest {
    serde_json::from_slice(&fs::read(root().join("manifest.json")).unwrap()).unwrap()
}

#[test]
fn benchmark_fixture_bytes_match_manifest_sizes_and_digests() {
    let manifest = manifest();
    assert_eq!(manifest.schema_version, 1);
    let mut names = BTreeSet::new();
    for fixture in manifest.fixtures {
        assert!(names.insert(fixture.name.clone()), "duplicate fixture name");
        let bytes = fs::read(root().join(&fixture.file)).unwrap();
        assert_eq!(
            u64::try_from(bytes.len()).unwrap(),
            fixture.encoded_bytes,
            "{}",
            fixture.name
        );
        assert_eq!(
            format!("{:x}", Sha256::digest(&bytes)),
            fixture.sha256,
            "{}",
            fixture.name
        );
        assert!(
            fixture.uncompressed_bytes >= fixture.encoded_bytes
                || fixture.content_coding == "identity"
        );
        for value in [
            fixture.generator,
            fixture.generator_version,
            fixture.media_type,
            fixture.character_encoding,
            fixture.operation,
            fixture.setup_excluded,
            fixture.cache_assumption,
            fixture.sensitivity,
            fixture.determinism,
        ] {
            assert!(
                !value.trim().is_empty(),
                "{} has empty metadata",
                fixture.name
            );
        }
        assert_eq!(fixture.filesystem_sink, "N/A (no filesystem sink exists)");
        assert!(matches!(
            fixture.extent.as_str(),
            "complete" | "representation-truncated"
        ));
        assert!(matches!(
            fixture.route.as_str(),
            "direct" | "three-hop-loopback"
        ));
    }
}

#[test]
fn independent_fixture_anchor_matches_manifest_and_truncated_prefix() {
    let anchor = fs::read_to_string(root().join("SHA256SUMS")).unwrap();
    let manifest = manifest();
    for fixture in &manifest.fixtures {
        assert!(
            anchor
                .lines()
                .any(|line| line == format!("{}  {}", fixture.sha256, fixture.file)),
            "anchor missing {}",
            fixture.name
        );
    }
    let full = fs::read(root().join("medium-html.bin")).unwrap();
    let partial = fs::read(root().join("medium-html-truncated.bin")).unwrap();
    assert_eq!(partial, full.get(..4096).unwrap());
}

#[test]
fn benchmark_fixture_matrix_covers_supported_inputs() {
    let manifest = manifest();
    let names: BTreeSet<_> = manifest
        .fixtures
        .iter()
        .map(|value| value.name.as_str())
        .collect();
    for size in ["small", "medium", "large"] {
        for format in ["html", "xml", "json", "plain"] {
            assert!(names.contains(format!("{size}-{format}").as_str()));
        }
    }
    for required in [
        "small-js-shell",
        "medium-html-gzip",
        "medium-html-br",
        "medium-html-zlib",
        "large-high-ratio-gzip",
        "medium-html-truncated",
        "small-html-redirect-chain",
    ] {
        assert!(names.contains(required), "missing {required}");
    }
}

#[test]
fn repository_measurement_layers_have_one_entry_point_and_distinct_scopes() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let manifest = fs::read_to_string(root.join("Cargo.toml")).unwrap();
    for harness in [
        "allocation_capture",
        "criterion_capture",
        "gungraun_capture",
    ] {
        assert!(manifest.contains(&format!("name = \"{harness}\"")));
    }
    let document_manifest = fs::read_to_string(root.join("document-locators/Cargo.toml")).unwrap();
    for harness in [
        "allocation_document_locators",
        "criterion_document_locators",
        "criterion_documents",
        "criterion_json",
        "document_locators",
    ] {
        assert!(document_manifest.contains(&format!("name = \"{harness}\"")));
    }

    let xtask = fs::read_to_string(root.join("../xtask/src/main.rs")).unwrap();
    for harness in [
        "allocation_document_locators",
        "criterion_document_locators",
        "criterion_documents",
        "criterion_json",
        "document_locators",
    ] {
        assert!(
            xtask.contains(&format!("\"{harness}\"")),
            "xtask does not compile {harness}"
        );
    }
    for class in [
        "benchmark check",
        "benchmark criterion",
        "benchmark deterministic",
        "benchmark allocations",
        "benchmark process",
        "benchmark heap",
        "benchmark all",
    ] {
        assert!(xtask.contains(class), "xtask omits {class}");
    }
}

#[test]
#[allow(
    clippy::cognitive_complexity,
    reason = "single contract audit intentionally checks all CAS-333 layers"
)]
fn cas_333_browser_benchmarks_are_bounded_loopback_only_and_auditable() {
    let browser_root = browser_fixture_root();
    let fixture_manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(browser_root.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(
        fixture_manifest["schema"],
        "yosoi.browser-benchmark-fixture"
    );
    assert_eq!(fixture_manifest["version"], 1);
    assert_eq!(fixture_manifest["network"], "loopback-only");
    assert_eq!(
        fixture_manifest["modes"],
        serde_json::json!(["headless", "headful-when-display-configured"])
    );
    let expected = [
        (
            "minimal",
            "minimal.html",
            139_u64,
            "b29e85cb45273cd33b518d8d221d22c8e80793b6ec5c4e79485b7d0d9b3c17a0",
        ),
        (
            "full",
            "full.html",
            244_u64,
            "da79f1155a3c5b016132773fc7f2380087718cd06451f9540d24450572f995a5",
        ),
        (
            "growth",
            "growth.html",
            32995_u64,
            "cd9ccd76306a1535db36df506dfbcec371796a7a7d91552e3523225220339015",
        ),
    ];
    for (name, file, size, digest) in expected {
        assert!(
            fixture_manifest["cases"]
                .as_array()
                .unwrap()
                .iter()
                .any(|case| {
                    case["name"] == name
                        && case["file"] == file
                        && (name == "minimal"
                            || case["artifacts"]
                                == "source-rendered-dom-ax-network-layout-visual-runtime")
                })
        );
        let bytes = fs::read(browser_root.join(file)).unwrap();
        assert_eq!(u64::try_from(bytes.len()).unwrap(), size, "{name}");
        assert_eq!(format!("{:x}", Sha256::digest(&bytes)), digest, "{name}");
    }

    let benchmark_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let harness = fs::read_to_string(benchmark_root.join("benches/criterion_browser.rs")).unwrap();
    for name in [
        "cold_process_capture_to_staged_facts",
        "warm_process_fresh_context_capture_to_staged_facts",
        "yosoi_browser_finalization_capture_setup_excluded",
        "browser_capture_plus_finalization_end_to_end",
        "Minimal",
        "Full",
        "Growth",
    ] {
        assert!(harness.contains(name), "missing browser benchmark {name}");
    }
    assert!(harness.contains("BrowserRunMode::Headful"));
    let support = fs::read_to_string(benchmark_root.join("src/browser_support.rs")).unwrap();
    for required in ["Ipv4Addr::LOCALHOST", "is_loopback()", "http://127.0.0.1"] {
        assert!(
            support.contains(required),
            "browser support omits {required}"
        );
    }
    assert!(!support.contains("https://"));

    let profile = fs::read_to_string(benchmark_root.join("src/bin/profile_browser.rs")).unwrap();
    for workload in ["Success", "Cancellation", "Deadline", "Failure"] {
        assert!(profile.contains(workload), "profile omits {workload}");
    }
    assert!(profile.contains("--concurrency"));
    assert!(profile.contains("close_latency_ms: unavailable"));
    assert!(profile.contains("unavailable_metrics"));
    assert!(profile.contains("wait_for_accepted_requests"));
    assert!(profile.contains("LoopbackResponseMode::PartialDisconnect"));
    assert!(profile.contains("cancellation.cancel()"));
    assert!(profile.contains("record.is_expected()"));
    assert!(profile.contains("one or more browser profile attempts violated"));
    assert!(!profile.contains("https://"));
}

#[test]
fn redirect_preflight_records_exact_routes_only_outside_timing() {
    let source = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("benches/criterion_capture/full.rs"),
    )
    .unwrap();
    for required in [
        "enable_request_logging",
        "take_request_paths",
        "disable_request_logging",
        "exact route sequence",
        "exact request count",
        "redirect traversal exhausted its hop limit",
    ] {
        assert!(
            source.contains(required),
            "redirect preflight omits {required}"
        );
    }
    assert!(!source.contains("black_box(server.request_count())"));
}
