use crate::capture_stages_support::*;
use criterion::{BenchmarkId, Criterion, Throughput};
use std::{collections::BTreeMap, hint::black_box};
use tokio_util::sync::CancellationToken;
use yosoi_dev_support::internal::direct_http::*;
use yosoi_dev_support::internal::types::{
    ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRef, Producer,
    ProducerId, ProducerVersion, Provenance,
};

fn identities(
    body: &RetainedSource,
    complete_size: u64,
) -> (SourceArtifact, DecodedOutputIdentity) {
    let activity = ActivityId::random();
    let retained = ByteCount::new(body.bytes().len() as u64);
    let extent = if body.extent() == RetainedSourceExtent::Complete {
        ArtifactByteExtent::Complete {
            retained_bytes: retained,
        }
    } else {
        ArtifactByteExtent::truncated(
            retained,
            MeasuredCount::Known(ByteCount::new(complete_size)),
        )
        .unwrap_or_else(|e| panic!("extent: {e}"))
    };
    let availability = if body.extent() == RetainedSourceExtent::Complete {
        ArtifactAvailability::Retained
    } else {
        ArtifactAvailability::Truncated
    };
    let reason = (availability == ArtifactAvailability::Truncated).then(|| {
        yosoi_dev_support::internal::types::ReasonCode::new("benchmark.source-truncated")
            .unwrap_or_else(|e| panic!("reason: {e}"))
    });
    let producer = Producer::new(
        ProducerId::new("com.cascadinglabs.yosoi.benchmark")
            .unwrap_or_else(|e| panic!("producer: {e}")),
        ProducerVersion::new("1.0.0").unwrap_or_else(|e| panic!("version: {e}")),
    );
    let schema = yosoi_dev_support::internal::types::Schema::new(
        yosoi_dev_support::internal::types::SchemaId::new(
            "com.cascadinglabs.yosoi.benchmark.source",
        )
        .unwrap_or_else(|e| panic!("schema: {e}")),
        yosoi_dev_support::internal::types::SchemaVersion::try_from(1)
            .unwrap_or_else(|e| panic!("schema version: {e}")),
    );
    let provenance = Provenance::new(
        activity,
        producer.clone(),
        schema.clone(),
        started_at(),
        Vec::new(),
    );
    let record = ArtifactRecord::new(
        ArtifactId::try_from(1).unwrap_or_else(|e| panic!("id: {e}")),
        Some(body.digest()),
        availability,
        reason,
        provenance,
    )
    .unwrap_or_else(|e| panic!("record: {e}"));
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new("application/octet-stream").unwrap_or_else(|e| panic!("media: {e}")),
        extent,
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap_or_else(|e| panic!("metadata: {e}"));
    let source = SourceArtifact::new(metadata);
    let output_ref = DecodedSourceArtifactRef::from_untyped(ArtifactRef::new(
        activity,
        ArtifactId::try_from(2).unwrap_or_else(|e| panic!("id: {e}")),
    ));
    let output = DecodedOutputIdentity::new(
        output_ref,
        producer,
        schema,
        vec![source.reference().as_untyped()],
        source.reference(),
    )
    .unwrap_or_else(|e| panic!("identity: {e}"));
    (source, output)
}

fn assert_expected_outcome(name: &str, facts: &SourceRepresentationFacts) {
    let expected_format =
        if name.contains("html") || matches!(name, "malformed" | "sniffed" | "small-js-shell") {
            Some(SourceFormat::Html)
        } else if name.contains("xml") {
            Some(SourceFormat::Xml(XmlProfile::Generic))
        } else if name.contains("json") {
            Some(SourceFormat::Json)
        } else if name.contains("plain") || matches!(name, "windows1252" | "utf16") {
            Some(SourceFormat::PlainText)
        } else {
            None
        };
    match (expected_format, facts.classification()) {
        (Some(format), SourceClassificationOutcome::Classified(classified)) => {
            assert_eq!(classified.format(), format, "{name} classification format");
            assert_eq!(
                classified.basis(),
                if name == "sniffed" {
                    ClassificationBasis::Sniffed
                } else {
                    ClassificationBasis::Declared
                },
                "{name} classification basis"
            );
            assert_eq!(
                classified.extent(),
                if name == "medium-html-truncated" {
                    ClassificationExtent::RetainedPrefix
                } else {
                    ClassificationExtent::Complete
                },
                "{name} classification extent"
            );
        }
        (
            None,
            SourceClassificationOutcome::Unsupported {
                essence, extent, ..
            },
        ) => {
            assert_eq!(
                essence,
                if name == "unsupported" {
                    "image/gif"
                } else {
                    "application/javascript"
                }
            );
            assert_eq!(*extent, ClassificationExtent::Complete);
        }
        _ => panic!(
            "{name} unexpected classification: {:?}",
            facts.classification()
        ),
    }
    match (name, facts.decoding()) {
        (
            "unsupported",
            CharacterDecodingOutcome::NotApplicable(DecodingErrorCode::NotClassified),
        ) => {}
        (_, CharacterDecodingOutcome::Complete(view)) => {
            assert_eq!(
                view.source_truncated(),
                name == "medium-html-truncated",
                "{name} source extent"
            );
            assert!(
                !view.incomplete_terminal_sequence(),
                "{name} terminal sequence"
            );
            assert_eq!(view.replacements(), 0, "{name} replacements");
            let expected_encoding = if matches!(name, "windows1252" | "sniffed") {
                "windows-1252"
            } else if matches!(name, "utf16" | "malformed") {
                "UTF-16LE"
            } else {
                "UTF-8"
            };
            assert_eq!(
                view.encoding().canonical_name(),
                expected_encoding,
                "{name} encoding"
            );
        }
        _ => panic!("{name} unexpected decoding: {:?}", facts.decoding()),
    }
}

pub fn source_classification_character_decode(c: &mut Criterion) {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap_or_else(|e| panic!("runtime: {e}"));
    let names = [
        "small-html",
        "medium-html",
        "large-html",
        "small-xml",
        "medium-xml",
        "large-xml",
        "small-json",
        "medium-json",
        "large-json",
        "small-plain",
        "medium-plain",
        "large-plain",
        "small-js-shell",
        "medium-html-truncated",
    ];
    let mut routes = BTreeMap::new();
    for name in names {
        let f = fixture(name);
        let served = if name == "medium-html-truncated" {
            bytes(&fixture("medium-html"))
        } else {
            bytes(&f)
        };
        routes.insert(
            format!("/{name}"),
            Route::body(
                served,
                &format!("{}; charset={}", f.media_type, f.character_encoding),
                None,
            ),
        );
    }
    let malformed = vec![0xff, 0xfe, b'<', b'h', b't', b'm', b'l', b'>'];
    routes.insert(
        "/malformed".into(),
        Route::body(malformed, "text/html; charset=utf-8", None),
    );
    routes.insert(
        "/unsupported".into(),
        Route::body(b"GIF89a".to_vec(), "image/gif", None),
    );
    routes.insert(
        "/sniffed".into(),
        Route::body(
            b"<!doctype html><title>sniffed</title>".to_vec(),
            "application/octet-stream",
            None,
        ),
    );
    routes.insert(
        "/windows1252".into(),
        Route::body(
            vec![b'c', b'a', b'f', 0xe9],
            "text/plain; charset=windows-1252",
            None,
        ),
    );
    routes.insert(
        "/utf16".into(),
        Route::body(
            vec![0xff, 0xfe, b'h', 0, b'i', 0],
            "text/plain; charset=utf-16",
            None,
        ),
    );
    let server = LoopbackServer::start(routes);
    let mut group = c.benchmark_group("source_classification_character_decode");
    for name in names.into_iter().chain([
        "malformed",
        "unsupported",
        "sniffed",
        "windows1252",
        "utf16",
    ]) {
        let url = server.url(&format!("/{name}"));
        let limit = if name == "medium-html-truncated" {
            4096
        } else {
            1_000_000
        };
        let spec = if name == "medium-html-truncated" {
            capture_spec_with_limits(
                &url,
                65_536,
                limit,
                1_000_000,
                DirectHttpRedirectPolicy::Disabled,
            )
        } else {
            capture_spec(&url, limit, DirectHttpRedirectPolicy::Disabled)
        };
        let pending = runtime
            .block_on(execute_direct_http_at(
                spec,
                &CancellationToken::new(),
                started_at(),
            ))
            .unwrap_or_else(|e| panic!("execute: {e}"));
        let (outcome, _, response, _, _) = runtime
            .block_on(consume_response_body(pending, &CancellationToken::new()))
            .unwrap_or_else(|e| panic!("consume: {e}"));
        let body = outcome
            .payload()
            .retained_source()
            .unwrap_or_else(|| panic!("retained body required"));
        let retained = body.bytes().len() as u64;
        let complete_size = if name == "medium-html-truncated" {
            fixture("medium-html").uncompressed_bytes
        } else {
            retained
        };
        if name == "medium-html-truncated" {
            assert_eq!(body.extent(), RetainedSourceExtent::Truncated);
            assert_eq!(outcome.terminal(), BodyTerminal::RepresentationLimit);
            assert_eq!(retained, 4096);
            assert_eq!(
                body.bytes(),
                bytes(&fixture("medium-html"))
                    .get(..4096)
                    .unwrap_or_else(|| panic!("full prefix"))
            );
        } else {
            assert_eq!(body.extent(), RetainedSourceExtent::Complete);
        }
        let (source, output) = identities(body, complete_size);
        let media_type = response.source_media_type();
        let binding = ValidatedSourceBinding::new(body, &source)
            .unwrap_or_else(|e| panic!("preflight binding: {e}"));
        let preflight = classify_and_decode(binding, &media_type, &output, limit);
        assert_expected_outcome(name, &preflight);
        group.throughput(Throughput::Bytes(retained));
        group.bench_function(
            BenchmarkId::new("validated_binding_classify_decode", name),
            |b| {
                b.iter(|| {
                    let binding = ValidatedSourceBinding::new(black_box(body), black_box(&source))
                        .unwrap_or_else(|e| panic!("binding: {e}"));
                    let facts = classify_and_decode(
                        binding,
                        black_box(&media_type),
                        black_box(&output),
                        black_box(limit),
                    );
                    black_box(facts)
                })
            },
        );
    }
    group.finish();
}
