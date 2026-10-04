#![allow(clippy::unwrap_used, reason = "committed benchmark contract test")]

use std::{
    collections::BTreeSet,
    env::{self, temp_dir},
    ffi::OsString,
    fs, iter,
    path::PathBuf,
    process::{Command, id as process_id},
};

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
fn independent_fixture_anchor_and_generator_check_succeed() {
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
    let status = Command::new("python3")
        .arg(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../scripts/fixtures/generate-cas-307-fixtures.py"),
        )
        .arg("--check")
        .status()
        .unwrap();
    assert!(status.success());
    let full = fs::read(root().join("medium-html.bin")).unwrap();
    let partial = fs::read(root().join("medium-html-truncated.bin")).unwrap();
    assert_eq!(partial, full.get(..4096).unwrap());
}

#[test]
fn benchmark_workload_matrix_is_complete_and_loopback_only() {
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
    let bench_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("benches");
    let mut source = fs::read_to_string(bench_root.join("criterion_capture.rs")).unwrap();
    let support_path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/support.rs");
    let support_source = fs::read_to_string(&support_path).unwrap();
    assert!(support_source.lines().count() <= 400);
    source.push_str(&support_source);
    for module in [
        "body.rs",
        "finalization.rs",
        "full.rs",
        "source.rs",
        "wire_hash.rs",
    ] {
        let path = bench_root.join("criterion_capture").join(module);
        let module_source = fs::read_to_string(&path).unwrap();
        assert!(
            module_source.lines().count() <= 400,
            "{} exceeds 400 lines",
            path.display()
        );
        source.push_str(&module_source);
    }
    for group in [
        "source_classification_character_decode",
        "capture_finalization_bundle",
        "full_capture_redirect_chain",
        "yosoi_consume_response_body_pipeline",
    ] {
        assert!(source.contains(group), "missing benchmark group {group}");
    }

    let document_benchmark_root =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("document-locators/benches");
    let locator_benchmark =
        fs::read_to_string(document_benchmark_root.join("criterion_document_locators.rs")).unwrap();
    let html_and_dom_benchmark =
        fs::read_to_string(document_benchmark_root.join("document_locators.rs")).unwrap();
    let text_benchmark =
        fs::read_to_string(document_benchmark_root.join("criterion_documents.rs")).unwrap();
    let json_benchmark =
        fs::read_to_string(document_benchmark_root.join("criterion_json.rs")).unwrap();
    let allocation_benchmark =
        fs::read_to_string(document_benchmark_root.join("allocation_document_locators.rs"))
            .unwrap();
    let benchmark_manifest = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("document-locators/Cargo.toml"),
    )
    .unwrap();
    for (name, source) in [
        ("criterion_documents", text_benchmark.as_str()),
        ("criterion_json", json_benchmark.as_str()),
        ("criterion_document_locators", locator_benchmark.as_str()),
        ("document_locators", html_and_dom_benchmark.as_str()),
        (
            "allocation_document_locators",
            allocation_benchmark.as_str(),
        ),
    ] {
        for forbidden in [
            "EvaluationLimits",
            "plan.limits()",
            ".compile(",
            ".evaluate(",
            ".project(",
            "Projection::",
            "DocumentProfile",
            "Document::try_new",
            "DecodedTextDocument",
            "ParsedHtmlDocument",
            "ParsedAccessibilityDocument",
            "RenderedDomDocument",
            "XmlDocument",
            "evaluate_",
        ] {
            assert!(
                !source.contains(forbidden),
                "{name} retains the legacy facade term {forbidden}"
            );
        }
    }
    for (name, source) in [
        ("criterion_documents", text_benchmark.as_str()),
        ("criterion_json", json_benchmark.as_str()),
        ("criterion_document_locators", locator_benchmark.as_str()),
        ("document_locators", html_and_dom_benchmark.as_str()),
    ] {
        for required in [
            "Plan::new(",
            "output(",
            "parse_with_budget(",
            ".locate(",
            "locate_with_budget(",
        ] {
            assert!(
                source.contains(required),
                "{name} does not keep parse, locate, and end-to-end paths explicit via {required}"
            );
        }
    }
    for required in ["Plan::new(", "output(", "locate_with_budget("] {
        assert!(
            allocation_benchmark.contains(required),
            "allocation benchmark does not exercise end-to-end location via {required}"
        );
    }
    assert!(!text_benchmark.contains("plan_compile"));
    assert!(!text_benchmark.contains("BenchmarkId::new(\"materialize\""));
    for phase in ["parse", "locate", "end_to_end"] {
        assert!(
            locator_benchmark.contains(&format!("document_locator/xml/{phase}")),
            "XML locator benchmark omits the {phase} phase"
        );
        assert!(
            locator_benchmark.contains(&format!("document_locator/ax/{phase}")),
            "accessibility-tree locator benchmark omits the {phase} phase"
        );
        assert!(
            html_and_dom_benchmark.contains(&format!("BenchmarkId::new(\"{phase}\"")),
            "HTML/rendered-DOM locator benchmark omits the {phase} phase"
        );
        assert!(
            json_benchmark.contains(&format!("document_locator_json_{phase}")),
            "source-JSON locator benchmark omits the {phase} phase"
        );
    }
    for group in ["document_locator_html", "document_locator_rendered_dom"] {
        assert!(
            html_and_dom_benchmark.contains(group),
            "HTML/rendered-DOM benchmark omits the {group} group"
        );
    }
    for phase in ["parse", "locate", "end_to_end"] {
        assert!(
            text_benchmark.contains(&format!("BenchmarkId::new(\"{phase}\"")),
            "decoded-text locator benchmark omits the {phase} phase"
        );
    }
    let facade_source = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../crates/yosoi/src/lib.rs"),
    )
    .unwrap();
    let public_prelude = facade_source
        .split("pub mod prelude {")
        .nth(1)
        .and_then(|source| source.split("\n}").next())
        .unwrap_or_default();
    for forbidden in [
        "EvaluationLimits",
        "EvaluationLimitValues",
        "document_locator_limits",
        "plan.limits()",
        ".compile(",
        ".evaluate(",
        "Projection",
        "CompiledOutput",
        "CompiledRegion",
        "NamedOutput",
        "OutputPlan",
        "OutputSelection",
        "PolicySnapshot",
        "ResourceBudget",
        "ResourceBudgetValues",
        "ResourceBudgetError",
        "ParsedHtmlDocument",
        "ParsedAccessibilityDocument",
        "DecodedTextDocument",
        "RenderedDomDocument",
        "XmlDocument",
    ] {
        assert!(
            !public_prelude.contains(forbidden),
            "public yosoi prelude leaks {forbidden}"
        );
    }
    for harness in [
        "criterion_documents",
        "criterion_json",
        "criterion_document_locators",
        "document_locators",
        "allocation_document_locators",
    ] {
        assert!(
            benchmark_manifest.contains(&format!("name = \"{harness}\"")),
            "document locator benchmark {harness} is not registered in the benchmark crate"
        );
    }
    assert!(
        locator_benchmark.contains("require_xml_oracles_locked"),
        "XML locator timing must refuse unlocked advanced reference oracles"
    );
    assert!(text_benchmark.contains("YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR"));
    assert!(text_benchmark.contains("env::var_os(ADVANCED_FIXTURE_DIR)"));
    assert!(text_benchmark.contains("derived/whatwg-html-standard.txt"));
    assert!(!text_benchmark.contains("advanced.is_file()"));
    assert!(html_and_dom_benchmark.contains("YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR"));
    assert!(html_and_dom_benchmark.contains("browser/wcag22/rendered-dom-v1.json"));
    for modality in [
        "html",
        "xml",
        "json",
        "rendered_dom",
        "accessibility",
        "decoded_text",
    ] {
        assert!(
            allocation_benchmark.contains(&format!("{modality}_end_to_end")),
            "allocation benchmark omits {modality}"
        );
    }
    assert!(source.contains("consume_response_body"));
    assert!(source.contains("iter_batched"));
    assert!(source.contains("127.0.0.1"));
    assert!(source.contains("is_loopback"));
    assert!(source.contains("no_proxy"));
    assert!(!source.contains("https://"));
}

#[test]
fn runner_metadata_avoids_secret_bearing_sources() {
    let runner = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../scripts/benchmarks/run-cas-307-benchmarks.sh"),
    )
    .unwrap();
    for forbidden in [
        "printenv",
        "$(hostname",
        "source .env",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ] {
        assert!(!runner.contains(forbidden), "runner contains {forbidden}");
    }
    for required in [
        "source_snapshot_commit=",
        "jj_change_id=",
        "source_snapshot_note=",
        "rustc --version",
        "criterion=0.7.0",
        "target=",
        "profile=bench",
        "features=default",
        "rustflags=",
        "os=",
        "kernel=",
        "arch=",
        "cpu_model=",
        "logical_cpu_count=",
        "cores_per_socket=",
        "sockets=",
        "installed_memory_kib=",
        "virtualization_available=",
        "virtualization_value=",
        "container=",
        "power_frequency_control=",
        "cache_control=",
        "network_control=",
        "/proc/meminfo",
        "fixture-inputs.sha256",
        "complete-capture-v1.json",
    ] {
        assert!(runner.contains(required), "runner omits {required}");
    }
    assert!(!runner.contains("revision="), "ambiguous revision metadata");
    let capture_fixture = fs::read(root().join("complete-capture-v1.json")).unwrap();
    assert_eq!(
        format!("{:x}", Sha256::digest(&capture_fixture)),
        "850ebfb78e24be61385fdef1a17531c2772472979e045bd5adeca6a52c03f204"
    );
    assert!(runner.contains("find criterion-raw"));
    assert!(runner.contains("test -f \"$staging/$estimate\""));
    assert!(runner.contains("! grep -Fq '.cas-307-staging.'"));
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

    for script in [
        "run-cas-307-benchmarks.sh",
        "run-cas-307-gungraun.sh",
        "run-cas-307-allocations.sh",
        "run-cas-307-process-metrics.sh",
        "run-cas-307-heap.sh",
    ] {
        let source = fs::read_to_string(root.join("../scripts").join(script)).unwrap();
        assert!(
            source.contains("source_snapshot_commit"),
            "{script} omits source revision"
        );
        assert!(
            source.contains("fixture-inputs.sha256"),
            "{script} omits fixture digests"
        );
        assert!(
            source.contains("complete-capture-v1.json"),
            "{script} omits capture-model fixture provenance"
        );
        assert!(
            source.contains("benchmark-result-directory.sh"),
            "{script} omits per-change result grouping"
        );
        assert!(
            source.contains("summarize-benchmark-change.py"),
            "{script} omits the change-level dashboard"
        );
        assert!(
            !source.contains("https://"),
            "{script} must not contact public networks"
        );
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

    let repository_root = benchmark_root.join("..");
    let profile_runner =
        fs::read_to_string(repository_root.join("scripts/browser/run-cas-333-profile.sh")).unwrap();
    let soak_runner =
        fs::read_to_string(repository_root.join("scripts/browser/run-cas-333-soak.sh")).unwrap();
    let sampler =
        fs::read_to_string(repository_root.join("scripts/browser/sample_process_tree.py")).unwrap();
    for required in [
        "sample_process_tree.py",
        "success cancellation deadline failure",
        "mktemp -d",
        "mv \"$staging\" \"$destination\"",
        "fixture-provider-inputs.sha256",
        "cleanup_remaining_count",
        "peak_renderer_count",
        "peak_gpu_count",
        "peak_utility_count",
        "finalization_failures",
        "cleanup_timed_out",
        "chromium_executable=",
        "chromium_sha256=",
        "chromium_version=",
        "CAS333_CHROMIUM_SHA256",
        "CAS333_CHROMIUM_VERSION",
        "testing-only Chrome distributions are prohibited",
        "export CHROME=\"$chromium_executable\"",
        "exit \"$status\"",
    ] {
        assert!(
            profile_runner.contains(required),
            "profile runner omits {required}"
        );
    }
    for required in ["concurrency_matrix=1,2,4", "sequential", "matrix-"] {
        assert!(
            soak_runner.contains(required),
            "soak runner omits {required}"
        );
    }
    for required in [
        "rss_kib",
        "pss_kib",
        "cpu_ticks",
        "fd_count",
        "threads",
        "process_count",
        "role_counts",
        "controller",
        "browser",
        "renderer",
        "gpu",
        "utility",
        "other",
        "cleanup",
        "remaining_pids",
        "orphan_pids",
        "timed_out",
        "peak",
        "unavailable",
    ] {
        assert!(
            sampler.contains(required),
            "process sampler omits {required}"
        );
    }
    for source in [&profile_runner, &soak_runner, &sampler] {
        assert!(!source.contains("https://"));
        assert!(!source.contains("printenv"));
        assert!(!source.contains("source .env"));
    }
    assert!(
        !sampler.contains("\"command\"") && !sampler.contains("'command'"),
        "process metrics must not persist command lines, which may contain secrets"
    );

    let xtask = fs::read_to_string(repository_root.join("xtask/src/main.rs")).unwrap();
    assert!(xtask.contains("benchmark browser"));
    assert!(xtask.contains("run-cas-333-browser.sh"));
    assert!(xtask.contains("criterion_browser"));
    assert!(xtask.contains("allocation_browser"));
    assert!(xtask.contains("profile_browser"));
    let all = xtask.split("\"all\" =>").nth(1).unwrap();
    assert!(!all.contains("benchmark(\"browser\")"));

    let browser_runner =
        fs::read_to_string(repository_root.join("scripts/browser/run-cas-333-browser.sh")).unwrap();
    let browser_support =
        fs::read_to_string(repository_root.join("benchmarks/src/browser_support.rs")).unwrap();
    assert!(browser_support.contains("BENCHMARK_BROWSER_CLEANUP_DEADLINE_MILLIS: u64 = 45_000"));
    assert!(!browser_runner.contains("CAS333_BROWSER_MODE=both"));
    for mode in ["native-headless", "native-headful"] {
        assert!(browser_runner.contains(mode));
    }
    for artifact_set in ["minimal", "full", "growth"] {
        assert!(browser_runner.contains(artifact_set));
    }
    assert!(browser_runner.contains("criterion-$mode-$artifact_set-output.txt"));
    assert!(browser_runner.contains("criterion-raw/$mode/$artifact_set"));
    assert!(browser_runner.contains("CAS333_ARTIFACT_SET=$artifact_set"));
    for required in [
        "xvfb-run is required for isolated native headful certification",
        "native_headful_display=Xvfb; session_type=x11; screen=1920x1080x24",
        "xvfb_run_sha256=",
        "xvfb_executable_sha256=",
        "env -u WAYLAND_DISPLAY XDG_SESSION_TYPE=x11",
        "-screen 0 1920x1080x24",
    ] {
        assert!(
            browser_runner.contains(required),
            "native headful isolation omits {required}"
        );
    }
    for required in [
        "criterion_browser",
        "allocation_browser",
        "run-cas-333-soak.sh",
        "criterion-command.txt",
        "allocation-output.txt",
        "fixture-inputs.sha256",
        "environment.txt",
        "summarize-benchmark-change.py",
        "mktemp -d",
        "resolve_chromium",
        "canonical_path",
        "chromiumoxide_detection_order",
        "identity_schema=cas333.native-browser-identity.v1",
        "chromium_executable=",
        "chromium_sha256=",
        "chromium_version=",
        "testing-only Chrome distributions are prohibited",
        "CAS-333 browser diagnostics retained at",
        "CAS333_CHANGE_ID=$container_change_id",
        "source_vcs=",
        "source_dirty=",
        "source_dirty_source_sha256=",
        "git ls-files -z -c -o --exclude-standard",
        "controller_source=vendor/chromiumoxide",
        "controller_package=",
        "controller_version=",
        "controller_upstream_revision=",
        "controller_source_sha256=",
        "generated_cdp_source=vendor/chromiumoxide_cdp",
        "generated_cdp_package=",
        "generated_cdp_version=",
        "generated_cdp_chromium_revision=r",
        "generated_cdp_v8_revision=",
        "generated_cdp_source_sha256=",
        "generated_cdp_pdl_manifest_sha256=",
        "generated_cdp_output_manifest_sha256=",
        "generated_cdp_output_sha256=",
        "CAS333_CHROMIUM_SHA256",
        "CAS333_CHROMIUM_VERSION",
        "measurement_identity=$(native_identity)",
        "refusing publication because source, controller, generated CDP, or Chromium identity changed",
    ] {
        assert!(
            browser_runner.contains(required),
            "browser runner omits {required}"
        );
    }
    let chrome_override_check = ["if test -n \"$", "{CHROME:-}\""].concat();
    assert!(
        browser_runner.find(&chrome_override_check).unwrap()
            < browser_runner.find("for name in").unwrap()
    );
    assert_eq!(
        browser_runner
            .matches("\"CHROME=$chromium_executable\"")
            .count(),
        2,
        "Criterion and the native profile matrix must each bind the canonical executable"
    );
    assert!(
        browser_runner
            .find("if test \"$measurement_identity\" != \"$(native_identity)\"")
            .unwrap()
            < browser_runner
                .find("mv \"$staging\" \"$destination\"")
                .unwrap(),
        "identity drift must be rejected before atomic publication"
    );
    assert!(!browser_runner.contains("chromium --version"));
    assert!(!browser_runner.contains("/proc/*/cmdline"));
    assert!(!browser_runner.contains("ps -eo"));
    assert!(!browser_runner.contains("printenv"));
    assert!(!browser_runner.contains("source .env"));
    assert!(!browser_runner.contains("https://"));
}

#[test]
fn cas_352_warm_browser_benchmarks_are_loopback_bounded_and_auditable() {
    let repository_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let profile =
        fs::read_to_string(repository_root.join("benchmarks/src/bin/profile_browser_execution.rs"))
            .unwrap();
    for required in [
        "capture_attempt_managed",
        "LoopbackFixture",
        "process_generation",
        "residual_processes_after_shutdown",
        "--contexts-per-process",
        "--recycle-threshold",
    ] {
        assert!(
            profile.contains(required),
            "CAS-352 profile omits {required}"
        );
    }
    assert!(!profile.contains("https://"));

    let runner =
        fs::read_to_string(repository_root.join("scripts/browser/run-cas-352-browser-execution.sh"))
            .unwrap();
    for required in [
        "one-by-one:1:1:1:1:1",
        "one-by-two:1:2:2:2:2",
        "two-by-four:2:4:2:4:4",
        "CAS352_SOAK_ITERATIONS",
        "sample_process_tree.py",
        "fixture-provider-inputs.sha256",
        "mktemp -d",
        "mv \"$staging\" \"$destination\"",
        "orphan_pids",
        "resolve_chromium",
        "chromiumoxide_detection_order",
        "chromium_executable=",
        "chromium_sha256=",
        "chromium_version=",
        "testing-only Chrome distributions are prohibited",
        "controller_crate=chromiumoxide",
        "controller_source_sha256=",
        "repository_identity yosoi",
        "repository_identity voidcrawl",
        "source_sha256=",
        "dirty_source_sha256=",
        "git ls-files -z -c -o --exclude-standard",
        "--identity-only",
        "--criterion-only",
        "--finalize",
        "identity_metadata",
        "metadata_matches_current_identity",
        "validate_soak_matrix",
        "criterion-evidence.sha256",
        "CAS352_CHROMIUM_VERSION",
        "CAS333_ARTIFACT_SET=all",
        "evidence_scope=",
        "realpath --relative-to",
    ] {
        assert!(runner.contains(required), "CAS-352 runner omits {required}");
    }
    let chrome_override_check = ["if test -n \"$", "{CHROME:-}\""].concat();
    assert!(runner.find(&chrome_override_check).unwrap() < runner.find("for name in").unwrap());
    assert!(!runner.contains("chromium --version"));
    assert!(!runner.contains("https://"));
    assert!(!runner.contains("printenv"));
    assert!(!runner.contains("source .env"));

    let xtask = fs::read_to_string(repository_root.join("xtask/src/main.rs")).unwrap();
    assert!(xtask.contains("benchmark browser-execution"));
    assert!(xtask.contains("run-cas-352-browser-execution.sh"));
    assert!(xtask.contains("profile_browser_execution"));
    assert!(xtask.contains("benchmark_contract"));
}

#[test]
fn cas_374_stealth_matrix_is_typed_bounded_and_identity_pinned() {
    let repository_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let profile =
        fs::read_to_string(repository_root.join("benchmarks/src/bin/profile_browser_stealth.rs"))
            .unwrap();
    for required in [
        "SupportedConfiguration",
        "AutomationDisclosed",
        "BoundedDisguise",
        "BrowserDebugPortPolicy::ChromeAssigned",
        "first_document",
        "same_document",
        "cross_document",
        "new_tab",
        "isolated_context",
        "attached_existing_document",
        "contract_passed",
    ] {
        assert!(
            profile.contains(required),
            "CAS-374 profile omits {required}"
        );
    }

    let runner =
        fs::read_to_string(repository_root.join("scripts/browser/run-cas-374-browser-stealth.sh")).unwrap();
    for required in [
        "expected_base_id=sha256:90ef59e3973300ec7c0ef8d3d8d0ca7f791ca6cc485a34ce2f13041c001137fd",
        "ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db",
        "container-headless container-headful",
        "supported-configuration \"$cdp\"",
        "automation-disclosed bounded-disguise",
        "for cdp in normal minimal",
        "--network none",
        "--read-only",
        "--pids-limit=512",
        "--memory=2g",
        "--cpus=1",
        "CHROME_NO_SANDBOX=0",
        "site_process_isolation=chrome_default",
        "resource_guard",
        "unsupported command-line",
        "contract_passed",
        "probe_binary_size_bytes=",
        "CAS-374 expected 8 hermetic cells",
        "--live-suite",
    ] {
        assert!(runner.contains(required), "CAS-374 runner omits {required}");
    }
    assert!(!runner.contains("Chrome for Testing"));
    assert!(!runner.contains("sleep "));

    let dockerfile = fs::read_to_string(repository_root.join("docker/browser-stealth/Dockerfile")).unwrap();
    for required in [
        "find crates/voidcrawl/src",
        "vendor/chromiumoxide/src",
        "vendor/chromiumoxide_cdp/src",
        "-exec touch {} +",
    ] {
        assert!(
            dockerfile.contains(required),
            "CAS-374 Dockerfile omits stale-cache guard {required}"
        );
    }

    let entrypoint =
        fs::read_to_string(repository_root.join("docker/browser-stealth/entrypoint.sh")).unwrap();
    for required in [
        "CHROME_NO_SANDBOX must be 0",
        "testing-only Chrome distributions are prohibited",
        "inotify_init1",
        "wait \"$sway_pid\"",
    ] {
        assert!(
            entrypoint.contains(required),
            "CAS-374 entrypoint omits {required}"
        );
    }
    assert!(!entrypoint.contains("sleep "));

    let xtask = fs::read_to_string(repository_root.join("xtask/src/main.rs")).unwrap();
    assert!(xtask.contains("benchmark browser-stealth"));
    assert!(xtask.contains("run-cas-374-browser-stealth.sh"));
    assert!(xtask.contains("profile_browser_stealth"));
}

#[test]
#[allow(
    clippy::cognitive_complexity,
    reason = "single behavioral contract covers identity, execution binding, and stale rejection"
)]
fn cas_352_identity_only_mode_proves_source_and_executable_identity() {
    use std::os::unix::fs::PermissionsExt;

    let base = temp_dir().join(format!("cas-352-identity-{}", process_id()));
    let workspace = base.join("yosoi");
    let provider = workspace.join("crates/voidcrawl");
    let vendor = workspace.join("vendor/chromiumoxide");
    fs::create_dir_all(provider.join("src")).unwrap();
    fs::create_dir_all(vendor.join("src")).unwrap();
    fs::write(provider.join("src/provider.rs"), "provider-clean\n").unwrap();
    fs::write(
        vendor.join("Cargo.toml"),
        "[package]\nname = \"chromiumoxide\"\nversion = \"9.0.0\"\n",
    )
    .unwrap();
    fs::write(vendor.join("src/lib.rs"), "controller-clean\n").unwrap();

    let git = |directory: &PathBuf, args: &[&str]| {
        let status = Command::new("git")
            .args(args)
            .current_dir(directory)
            .status()
            .unwrap();
        assert!(status.success(), "git {args:?} failed");
    };
    git(&workspace, &["init", "-q"]);
    git(
        &workspace,
        &["config", "user.email", "cas352@example.invalid"],
    );
    git(&workspace, &["config", "user.name", "CAS-352 test"]);
    git(&workspace, &["add", "."]);
    git(&workspace, &["commit", "-qm", "identity fixture"]);

    let chrome = base.join("fake-chromium");
    fs::write(&chrome, "#!/bin/sh\nprintf 'Fake Chromium 123.45.6\\n'\n").unwrap();
    let mut permissions = fs::metadata(&chrome).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&chrome, permissions).unwrap();
    let runner = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../scripts/browser/run-cas-352-browser-execution.sh");
    let run_identity = |suffix: &str| -> String {
        let destination = base.join(suffix);
        let output = Command::new(&runner)
            .arg("--identity-only")
            .arg(&destination)
            .env("CAS352_YOSOI_ROOT", &workspace)
            .env("CHROME", &chrome)
            .output()
            .unwrap();
        assert!(output.status.success(), "identity mode failed: {output:?}");
        let stdout = String::from_utf8(output.stdout).unwrap();
        assert_eq!(
            stdout,
            fs::read_to_string(destination.join("metadata.txt")).unwrap()
        );
        assert_eq!(
            fs::read_dir(&destination)
                .unwrap()
                .map(|entry| entry.unwrap().file_name())
                .collect::<Vec<_>>(),
            vec![OsString::from("metadata.txt")]
        );
        stdout
    };
    let value = |metadata: &str, key: &str| -> String {
        metadata
            .lines()
            .find_map(|line| line.strip_prefix(&format!("{key}=")))
            .unwrap_or_else(|| panic!("missing {key} in {metadata}"))
            .to_owned()
    };

    let clean = run_identity("clean");
    assert_eq!(value(&clean, "yosoi_dirty"), "clean");
    assert_eq!(value(&clean, "voidcrawl_dirty"), "clean");
    assert_eq!(value(&clean, "yosoi_revision").len(), 40);
    assert_eq!(value(&clean, "voidcrawl_revision").len(), 40);
    assert_eq!(
        value(&clean, "yosoi_revision"),
        value(&clean, "voidcrawl_revision")
    );
    assert_eq!(value(&clean, "chromium_version"), "Fake Chromium 123.45.6");
    assert_eq!(
        value(&clean, "chromium_executable"),
        chrome.canonicalize().unwrap().display().to_string()
    );
    assert_eq!(
        value(&clean, "chromium_sha256"),
        format!("{:x}", Sha256::digest(fs::read(&chrome).unwrap()))
    );
    let clean_yosoi_hash = value(&clean, "yosoi_source_sha256");
    let clean_provider_hash = value(&clean, "voidcrawl_source_sha256");
    let clean_controller_hash = value(&clean, "controller_source_sha256");
    let clean_revision = value(&clean, "yosoi_revision");

    fs::write(
        provider.join("src/provider.rs"),
        "provider-tracked-mutation\n",
    )
    .unwrap();
    let tracked = run_identity("tracked");
    assert_eq!(value(&tracked, "yosoi_dirty"), "dirty");
    assert_eq!(value(&tracked, "voidcrawl_dirty"), "dirty");
    assert_ne!(value(&tracked, "yosoi_source_sha256"), clean_yosoi_hash);
    assert_ne!(
        value(&tracked, "voidcrawl_source_sha256"),
        clean_provider_hash
    );
    assert_eq!(value(&tracked, "yosoi_revision"), clean_revision);

    fs::write(
        provider.join("src/untracked-provider.rs"),
        "provider-untracked-mutation\n",
    )
    .unwrap();
    let untracked = run_identity("untracked");
    assert_eq!(value(&untracked, "yosoi_dirty"), "dirty");
    assert_eq!(value(&untracked, "voidcrawl_dirty"), "dirty");
    assert_ne!(
        value(&untracked, "yosoi_source_sha256"),
        value(&tracked, "yosoi_source_sha256")
    );
    assert_ne!(
        value(&untracked, "voidcrawl_source_sha256"),
        value(&tracked, "voidcrawl_source_sha256")
    );
    assert_eq!(value(&untracked, "yosoi_revision"), clean_revision);

    fs::write(vendor.join("src/lib.rs"), "controller-mutated\n").unwrap();
    let controller = run_identity("controller");
    assert_eq!(value(&controller, "voidcrawl_dirty"), "dirty");
    assert_eq!(value(&controller, "yosoi_dirty"), "dirty");
    assert_ne!(
        value(&controller, "controller_source_sha256"),
        clean_controller_hash
    );
    assert_eq!(
        value(&controller, "voidcrawl_revision"),
        value(&clean, "voidcrawl_revision")
    );
    assert_ne!(
        value(&controller, "yosoi_source_sha256"),
        value(&untracked, "yosoi_source_sha256")
    );
    assert_eq!(
        value(&controller, "voidcrawl_source_sha256"),
        value(&untracked, "voidcrawl_source_sha256")
    );

    let fake_bin = base.join("fake-bin");
    fs::create_dir_all(&fake_bin).unwrap();
    let fake_cargo = fake_bin.join("cargo");
    let dollar = '$';
    let fake_cargo_script = format!(
        "#!/bin/sh\nif test \"{dollar}{{1:-}}\" = --version; then\n  printf 'fake cargo 1.0\\n'\n  exit 0\nfi\nprintf 'fake Criterion runtime CHROME=%s digest=%s version=%s\\n' \\\n  \"{dollar}{{CHROME:-missing}}\" \"{dollar}{{CAS352_CHROMIUM_SHA256:-missing}}\" \"{dollar}{{CAS352_CHROMIUM_VERSION:-missing}}\"\n"
    );
    fs::write(&fake_cargo, fake_cargo_script).unwrap();
    let mut fake_cargo_permissions = fs::metadata(&fake_cargo).unwrap().permissions();
    fake_cargo_permissions.set_mode(0o755);
    fs::set_permissions(&fake_cargo, fake_cargo_permissions).unwrap();
    let fake_path = env::join_paths(
        iter::once(fake_bin).chain(env::split_paths(&env::var_os("PATH").unwrap())),
    )
    .unwrap();
    let criterion_destination = base.join("criterion-only");
    let criterion = Command::new(&runner)
        .arg("--criterion-only")
        .arg(&criterion_destination)
        .env("CAS352_YOSOI_ROOT", &workspace)
        .env("CHROME", &chrome)
        .env("PATH", &fake_path)
        .output()
        .unwrap();
    assert!(
        criterion.status.success(),
        "criterion-only failed: {criterion:?}"
    );
    let criterion_metadata =
        fs::read_to_string(criterion_destination.join("metadata.txt")).unwrap();
    assert_eq!(
        value(&criterion_metadata, "evidence_scope"),
        "criterion-only"
    );
    for command in ["criterion-command.txt", "criterion-warm-command.txt"] {
        let command = fs::read_to_string(criterion_destination.join(command)).unwrap();
        assert!(command.contains(&format!(
            "CHROME={}",
            chrome.canonicalize().unwrap().display()
        )));
        assert!(command.contains("CAS352_CHROMIUM_SHA256="));
        assert!(command.contains("CAS352_CHROMIUM_VERSION=Fake\\ Chromium\\ 123.45.6"));
    }
    for output in ["criterion-output.txt", "criterion-warm-output.txt"] {
        assert!(
            fs::read_to_string(criterion_destination.join(output))
                .unwrap()
                .contains(&format!(
                    "CHROME={}",
                    chrome.canonicalize().unwrap().display()
                ))
        );
    }
    let criterion_hashes =
        fs::read_to_string(criterion_destination.join("criterion-evidence.sha256")).unwrap();
    for required in [
        "metadata.txt",
        "criterion-command.txt",
        "criterion-output.txt",
        "criterion-warm-command.txt",
        "criterion-warm-output.txt",
    ] {
        assert!(
            criterion_hashes.contains(required),
            "missing {required} hash"
        );
    }

    fs::write(provider.join("src/provider.rs"), "stale-after-criterion\n").unwrap();
    let stale = Command::new(&runner)
        .arg("--finalize")
        .arg(&criterion_destination)
        .env("CAS352_YOSOI_ROOT", &workspace)
        .env("CHROME", &chrome)
        .env("PATH", &fake_path)
        .output()
        .unwrap();
    assert!(!stale.status.success());
    assert!(
        String::from_utf8(stale.stderr)
            .unwrap()
            .contains("identity is stale")
    );

    fs::write(
        provider.join("src/provider.rs"),
        "provider-tracked-mutation\n",
    )
    .unwrap();
    let refinalized = Command::new(&runner)
        .arg("--finalize")
        .arg(&criterion_destination)
        .env("CAS352_YOSOI_ROOT", &workspace)
        .env("CHROME", &chrome)
        .env("PATH", &fake_path)
        .output()
        .unwrap();
    assert!(
        refinalized.status.success(),
        "refinalization failed: {refinalized:?}"
    );
    assert!(!clean.contains(".env"));
    assert!(!clean.contains("https://"));
    let _ = fs::remove_dir_all(base);
}

#[test]
#[allow(
    clippy::cognitive_complexity,
    reason = "single contract audit intentionally checks all CAS-333 layers"
)]
fn cas_333_container_contract_is_hardened_atomic_and_private() {
    let repository_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let read = |relative: &str| fs::read_to_string(repository_root.join(relative)).unwrap();
    let browser_runner = read("scripts/browser/run-cas-333-browser.sh");
    for environment in [
        "native-headless",
        "native-headful",
        "container-headless",
        "container-headful",
    ] {
        assert!(
            browser_runner.contains(environment),
            "browser orchestrator omits {environment}"
        );
    }
    assert!(browser_runner.contains("CAS333_CONTAINER_REUSE_IMAGE=1"));
    assert!(!browser_runner.contains("https://"));

    let dockerfile = read("docker/browser/Dockerfile");
    for required in [
        "FROM rust:1.98@sha256:af753e6e729c839de28010e323abc550eceaa9572bdaa765429d4f585e2e43dc AS builder",
        "FROM voidcrawl-headful:local",
        "CHROME_VERSION=153.0.8010.36",
        "CHROME_DEB_SHA256=9bb44e33031c2f2857cf36b4343051a12f93058e4b781e3c76313df87f6c8d32",
        "USER 10001:10001",
        "ENTRYPOINT [\"/usr/local/bin/cas333-entrypoint\"]",
        "seccomp-chrome.LICENSE",
        "chromium-version.txt",
        "chromium-package-sha256.txt",
        "chromium-executable-sha256.txt",
    ] {
        assert!(dockerfile.contains(required), "Dockerfile omits {required}");
    }
    assert!(!dockerfile.contains("google-chrome-stable_current"));

    let container_runner = read("scripts/browser/run-container.sh");
    for required in [
        "chromium_package_sha256",
        "chromium_executable_sha256",
        "expected_base_image_id=sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a",
        "com.cascadinglabs.yosoi.cas333.base_image_id",
        "image_inherits_base",
        "change_id.shortest(12)",
    ] {
        assert!(
            container_runner.contains(required),
            "container evidence omits {required}"
        );
    }
    let entrypoint = read("docker/browser/entrypoint.sh");
    for required in [
        "CHROME_NO_SANDBOX must be 0",
        "export CHROME_NO_SANDBOX=0",
        "export CHROME=/opt/google/chrome/chrome",
        "container Chrome version does not match the image identity",
        "container Chrome digest does not match the image identity",
        "testing-only Chrome distributions are prohibited",
        "inotify_init1",
        "inotify_add_watch",
        "timeout 15s",
        "wait \"$sway_pid\"",
    ] {
        assert!(entrypoint.contains(required), "entrypoint omits {required}");
    }
    assert!(!entrypoint.contains("sleep"));

    let context = read("scripts/browser/prepare-container-context.sh");
    for excluded in [
        ".git/", "target/", "results/", ".env", "keys/", "secrets/", "*.key", "*.pem",
    ] {
        assert!(
            context.contains(excluded),
            "container context does not exclude {excluded}"
        );
    }

    let container = read("scripts/browser/run-container.sh");
    for required in [
        "--network none",
        "--read-only",
        "--tmpfs /tmp:rw,nosuid,nodev,noexec,size=1g",
        "--shm-size=1g",
        "--memory=4g",
        "--cpus=2",
        "--pids-limit=2048",
        "--cap-drop ALL",
        "no-new-privileges:true",
        "seccomp=$root/docker/browser/seccomp-chrome.json",
        "com.cascadinglabs.yosoi.cas333.source_sha256",
        "refusing image reuse",
        "docker wait \"$container\"",
        "cgroup_cleanup_state",
        "disappeared",
        "docker_server_version",
        "chromium_version",
        "CgroupVersion",
        "DefaultRuntime",
    ] {
        assert!(
            container.contains(required),
            "container runner omits {required}"
        );
    }
    for forbidden in [
        "--privileged",
        "--network host",
        "seccomp=unconfined",
        "CHROME_NO_SANDBOX=1",
        "printenv",
        "/environ",
    ] {
        assert!(
            !container.contains(forbidden),
            "container runner permits or persists {forbidden}"
        );
    }

    let matrix = read("scripts/browser/run-container-matrix.sh");
    for required in [
        "mktemp -d",
        "mv \"$staging\" \"$destination\"",
        "success cancellation deadline failure",
        "for concurrency in 1 2 4",
        "elapsed_p50_ms",
        "elapsed_p95_ms",
        "elapsed_p99_ms",
        "cpu_usage_peak_usec",
        "memory_peak_bytes",
        "pids_peak",
        "io_peak",
        "cpu_nr_throttled_peak",
        "memory_events_peak",
        "pids_events_peak",
    ] {
        assert!(
            matrix.contains(required),
            "container matrix omits {required}"
        );
    }
    let sampler = read("scripts/browser/sample_cgroup_v2.py");
    for required in [
        "cpu.stat",
        "memory.current",
        "memory.peak",
        "memory.events",
        "pids.current",
        "pids.peak",
        "pids.events",
        "io.stat",
        "cgroup.events",
        "disappeared",
    ] {
        assert!(
            sampler.contains(required),
            "cgroup sampler omits {required}"
        );
    }
    assert!(!sampler.contains("cmdline"));
    assert!(!sampler.contains("/environ"));
    assert!(!container.contains("Config.Env"));
    assert!(!container.contains("Config.Cmd"));

    let cleanup = read("scripts/browser/cleanup-containers.sh");
    assert!(cleanup.contains("label='com.cascadinglabs.yosoi.cas333=true'"));
    assert!(cleanup.contains("--filter \"label=$label\""));
    for forbidden in [
        "docker system prune",
        "docker container prune",
        "docker rm -f",
        "docker rm --force --all",
    ] {
        assert!(
            !cleanup.contains(forbidden),
            "cleanup is not label-only: {forbidden}"
        );
    }

    let seccomp_license = read("docker/browser/seccomp-chrome.LICENSE");
    assert!(seccomp_license.contains("Apache License 2.0"));
    assert!(seccomp_license.contains("SHA-256"));
}

#[test]
fn cas_383_oopif_container_uses_regular_stable_and_hardened_runtime() {
    let repository_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let read = |relative: &str| fs::read_to_string(repository_root.join(relative)).unwrap();
    let dockerfile = read("docker/browser/Dockerfile");
    let entrypoint = read("docker/browser/entrypoint.sh");
    let runner = read("scripts/browser/run-oopif.sh");

    for required in [
        "--bin profile_browser --bin profile_oopif",
        "/usr/local/bin/cas383-profile-oopif",
        "cas383-oopif-headless",
    ] {
        assert!(
            dockerfile.contains(required) || entrypoint.contains(required),
            "CAS-383 container path omits {required}"
        );
    }
    for required in [
        "chrome_version=154.0.8037.57",
        "chrome_package_sha256=66c0645f6a19871bab2844b8537c11a0db2e7d3bea8ef85a1c7cb52a54e65a3e",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "no-new-privileges:true",
        "CHROME_NO_SANDBOX=0",
        "seccomp-chrome.json",
    ] {
        assert!(runner.contains(required), "CAS-383 runner omits {required}");
    }
    assert!(!runner.contains("Chrome for Testing"));
    assert!(!runner.contains("CHROME_NO_SANDBOX=1"));
}

#[test]
fn perf_summary_rejects_nonnumeric_counters_even_when_perf_exits_zero() {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let temporary = temp_dir().join(format!("yosoi-perf-summary-test-{}", process_id()));
    let _ = fs::remove_dir_all(&temporary);
    fs::create_dir_all(&temporary).unwrap();
    for workload in ["full", "compressed", "redirect", "truncated"] {
        fs::write(
            temporary.join(format!("time-{workload}.txt")),
            "Maximum resident set size (kbytes): 1234\n",
        )
        .unwrap();
        fs::write(temporary.join(format!("perf-{workload}.status")), "0\n").unwrap();
        let instructions = if workload == "full" {
            "<not counted>"
        } else {
            "2000"
        };
        fs::write(
            temporary.join(format!("perf-{workload}.txt")),
            format!(
                "10.5;msec;task-clock:u;;;;\n1000;;cycles:u;;;;\n{instructions};;instructions:u;;;;\n5;;cache-misses:u;;;;\n"
            ),
        )
        .unwrap();
    }
    let output = temporary.join("summary.csv");
    let status = Command::new("python3")
        .arg(workspace.join("../scripts/benchmarks/summarize-cas-307-perf.py"))
        .arg(&temporary)
        .arg("10")
        .arg(&output)
        .status()
        .unwrap();
    assert!(status.success());
    let summary = fs::read_to_string(output).unwrap();
    assert!(
        summary
            .lines()
            .any(|line| line.starts_with("full,10,1234,unavailable,"))
    );
    assert!(
        summary
            .lines()
            .any(|line| line.starts_with("compressed,10,1234,available,10.5,1000,100,"))
    );
    fs::remove_dir_all(temporary).unwrap();
}

#[test]
fn change_summary_accepts_flat_divan_benchmarks() {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let temporary = temp_dir().join(format!("yosoi-divan-summary-test-{}", process_id()));
    let _ = fs::remove_dir_all(&temporary);
    fs::create_dir_all(temporary.join("allocations")).unwrap();
    fs::write(
        temporary.join("allocations/allocation-output.txt"),
        "├─ flat_case  1 ns │ 1 ns\n\
         │  max alloc: │\n\
         │    2 │\n\
         │    3 KB │\n\
         │  alloc: │\n\
         │    4 │\n\
         │    5 KB │\n\
         │  grow: │\n\
         │    1 │\n\
         │    7 B │\n",
    )
    .unwrap();
    let status = Command::new("python3")
        .arg(workspace.join("../scripts/benchmarks/summarize-benchmark-change.py"))
        .arg(&temporary)
        .status()
        .unwrap();
    assert!(status.success());
    let summary = fs::read_to_string(temporary.join("summary.csv")).unwrap();
    assert!(summary.contains("L0,Divan AllocProfiler,flat_case,allocation_operations,4,count"));
    assert!(summary.contains("L0,Divan AllocProfiler,flat_case,total_allocated_bytes,5007,bytes"));
    assert!(summary.contains("L0,Divan AllocProfiler,flat_case,maximum_live_bytes,3000,bytes"));
    fs::remove_dir_all(temporary).unwrap();
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
