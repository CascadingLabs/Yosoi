//! Divan allocation evidence for provider-neutral browser payload stages.
//! Divan's [`AllocProfiler`] reports allocation operations, total allocated bytes, and
//! maximum live allocator bytes on the synchronous benchmark thread; it makes no timing claim.

use divan::{AllocProfiler, Bencher, black_box};
use yosoi_dev_support::internal::types::Sha256Digest;
use yosoi_dev_support::internal::web_capture::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityEvidence,
    BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema, BrowserBudgetScope,
    BrowserByteAccounting, BrowserDocumentEpoch, BrowserDocumentScope, BrowserExtraInfoEvidence,
    BrowserFrameId, BrowserLayoutFact, BrowserLayoutRect, BrowserLimitEnforcement,
    BrowserObservationFact, BrowserObservationKind, BrowserResourceAccounting, BrowserResourceFact,
    BrowserResourceId, BrowserResourceOutcome, BrowserRuntimeDiagnosticFact,
    BrowserRuntimeDiagnosticKind, BrowserRuntimeValueType, BrowserStructuredEvidence,
    CaptureOffset, EventAccounting, EventCount, LossExtent, MeasuredCount,
};

#[global_allocator]
static ALLOCATOR: AllocProfiler = AllocProfiler::system();

#[derive(Clone, Copy, Debug)]
enum EvidenceCase {
    AxPayloadBytes(usize),
    NetworkResourcesAndEvents(u64),
    RuntimeDiagnosticsAndEventBytes {
        diagnostics: u64,
        utf8_bytes_per_diagnostic: u64,
    },
    Layout,
}

fn main() {
    divan::main();
}

fn byte_accounting(retained: u64) -> Option<BrowserByteAccounting> {
    Some(BrowserByteAccounting {
        configured_limit: retained.checked_add(1)?,
        enforcement: BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
        budget_scope: BrowserBudgetScope::PerPayload,
        observed: retained,
        retained,
        lost: LossExtent::Known(0),
        complete: true,
    })
}

fn event_accounting(retained: u64) -> Option<EventAccounting> {
    EventAccounting::new(
        EventCount::new(retained),
        EventCount::new(retained),
        MeasuredCount::Known(EventCount::new(0)),
    )
    .ok()
}

const fn document_scope() -> BrowserDocumentScope {
    BrowserDocumentScope {
        frame: BrowserFrameId(1),
        epoch: BrowserDocumentEpoch(1),
    }
}

const fn layout() -> BrowserStructuredEvidence {
    let viewport = BrowserLayoutRect {
        x_micro_css: 0,
        y_micro_css: 0,
        width_micro_css: 1_280_000,
        height_micro_css: 720_000,
    };
    BrowserStructuredEvidence::Layout(BrowserLayoutFact {
        scope: document_scope(),
        at: CaptureOffset::from_microseconds(10),
        layout_viewport: viewport,
        visual_viewport: viewport,
        content: BrowserLayoutRect {
            width_micro_css: 1_280_000,
            height_micro_css: 3_000_000,
            ..viewport
        },
        device_scale_micro: Some(1_000_000),
    })
}

fn ax_payload(payload_bytes: usize) -> Option<BrowserStructuredEvidence> {
    let retained = u64::try_from(payload_bytes).ok()?;
    Some(BrowserStructuredEvidence::Accessibility(
        BrowserAccessibilityEvidence {
            schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
            schema_version: 1,
            capture_mode: BrowserAccessibilityCaptureMode::FullTree,
            requested_depth: None,
            ignored_nodes: BrowserAccessibilityIgnoredNodes::Included,
            scope: document_scope(),
            at: CaptureOffset::from_microseconds(10),
            nodes_observed: 1,
            nodes_retained: 1,
            nodes_lost: LossExtent::Known(0),
            bytes: byte_accounting(retained)?,
            canonical_node_bytes: vec![b'x'; payload_bytes],
        },
    ))
}

fn network(resources_and_events: u64) -> Option<BrowserStructuredEvidence> {
    let capacity = usize::try_from(resources_and_events).ok()?;
    let mut resources = Vec::with_capacity(capacity);
    let mut events = Vec::with_capacity(capacity);
    for sequence in 0..resources_and_events {
        let resource = BrowserResourceId(sequence.checked_add(1)?);
        resources.push(BrowserResourceFact {
            id: resource,
            redirect_from: None,
            scope: Some(document_scope()),
            url: None,
            status: Some(200),
            outcome: BrowserResourceOutcome::Complete,
            from_cache: false,
            from_service_worker: false,
            encoded_data_length: Some(0),
        });
        events.push(BrowserObservationFact {
            sequence,
            at: CaptureOffset::from_microseconds(sequence),
            kind: BrowserObservationKind::RequestFinished,
            resource: Some(resource),
        });
    }
    Some(BrowserStructuredEvidence::Network {
        requested_url: None,
        final_url: None,
        redirects: Vec::new(),
        main_document: None,
        extra_info: BrowserExtraInfoEvidence::UnavailableInCurrentClient,
        resources,
        events,
        resource_accounting: BrowserResourceAccounting::new(
            resources_and_events,
            resources_and_events,
            LossExtent::Known(0),
        )
        .ok()?,
        event_accounting: event_accounting(resources_and_events)?,
    })
}

fn runtime_diagnostics(
    diagnostic_count: u64,
    utf8_bytes_per_diagnostic: u64,
) -> Option<BrowserStructuredEvidence> {
    let capacity = usize::try_from(diagnostic_count).ok()?;
    let retained_bytes = diagnostic_count.checked_mul(utf8_bytes_per_diagnostic)?;
    let mut diagnostics = Vec::with_capacity(capacity);
    for sequence in 0..diagnostic_count {
        diagnostics.push(BrowserRuntimeDiagnosticFact {
            sequence,
            at: CaptureOffset::from_microseconds(sequence),
            kind: BrowserRuntimeDiagnosticKind::Exception,
            value_type: BrowserRuntimeValueType::RedactedText,
            complete_utf8_bytes: utf8_bytes_per_diagnostic,
            retained_utf8_bytes: utf8_bytes_per_diagnostic,
            truncated: false,
            redacted_sha256: Sha256Digest::digest(sequence.to_le_bytes()),
        });
    }
    Some(BrowserStructuredEvidence::RuntimeDiagnostics {
        scope: Some(document_scope()),
        diagnostics,
        runtime_event_accounting: event_accounting(diagnostic_count)?,
        byte_accounting: byte_accounting(retained_bytes)?,
    })
}

fn evidence(case: EvidenceCase) -> Option<BrowserStructuredEvidence> {
    match case {
        EvidenceCase::AxPayloadBytes(payload_bytes) => ax_payload(payload_bytes),
        EvidenceCase::NetworkResourcesAndEvents(count) => network(count),
        EvidenceCase::RuntimeDiagnosticsAndEventBytes {
            diagnostics,
            utf8_bytes_per_diagnostic,
        } => runtime_diagnostics(diagnostics, utf8_bytes_per_diagnostic),
        EvidenceCase::Layout => Some(layout()),
    }
}

#[divan::bench(args = [
    EvidenceCase::AxPayloadBytes(1_024),
    EvidenceCase::AxPayloadBytes(16_384),
    EvidenceCase::AxPayloadBytes(262_144),
    EvidenceCase::NetworkResourcesAndEvents(1),
    EvidenceCase::NetworkResourcesAndEvents(32),
    EvidenceCase::NetworkResourcesAndEvents(512),
    EvidenceCase::RuntimeDiagnosticsAndEventBytes { diagnostics: 1, utf8_bytes_per_diagnostic: 64 },
    EvidenceCase::RuntimeDiagnosticsAndEventBytes { diagnostics: 32, utf8_bytes_per_diagnostic: 1_024 },
    EvidenceCase::RuntimeDiagnosticsAndEventBytes { diagnostics: 512, utf8_bytes_per_diagnostic: 4_096 },
    EvidenceCase::Layout,
])]
fn browser_evidence_to_canonical_json(bencher: Bencher<'_, '_>, case: EvidenceCase) {
    let Some(evidence) = evidence(case) else {
        return;
    };
    bencher.bench_local(|| {
        black_box(BrowserStructuredEvidence::to_canonical_json(black_box(
            &evidence,
        )))
    });
}

#[divan::bench(args = [
    EvidenceCase::AxPayloadBytes(1_024),
    EvidenceCase::AxPayloadBytes(16_384),
    EvidenceCase::AxPayloadBytes(262_144),
    EvidenceCase::NetworkResourcesAndEvents(1),
    EvidenceCase::NetworkResourcesAndEvents(32),
    EvidenceCase::NetworkResourcesAndEvents(512),
    EvidenceCase::RuntimeDiagnosticsAndEventBytes { diagnostics: 1, utf8_bytes_per_diagnostic: 64 },
    EvidenceCase::RuntimeDiagnosticsAndEventBytes { diagnostics: 32, utf8_bytes_per_diagnostic: 1_024 },
    EvidenceCase::RuntimeDiagnosticsAndEventBytes { diagnostics: 512, utf8_bytes_per_diagnostic: 4_096 },
    EvidenceCase::Layout,
])]
fn browser_evidence_from_json(bencher: Bencher<'_, '_>, case: EvidenceCase) {
    let Some(evidence) = evidence(case) else {
        return;
    };
    let Ok(bytes) = evidence.to_canonical_json() else {
        return;
    };
    bencher.bench_local(|| black_box(BrowserStructuredEvidence::from_json(black_box(&bytes))));
}

#[divan::bench(args = [1_024, 16_384, 262_144, 1_048_576])]
fn dom_payload_clone(bencher: Bencher<'_, '_>, size: usize) {
    let payload = vec![b'<'; size];
    bencher.bench_local(|| black_box(payload.clone()));
}

#[divan::bench(args = [1_024, 16_384, 262_144, 1_048_576])]
fn png_payload_clone(bencher: Bencher<'_, '_>, size: usize) {
    let payload = vec![0x89_u8; size];
    bencher.bench_local(|| black_box(payload.clone()));
}

#[divan::bench(args = [1_024, 16_384, 262_144, 1_048_576])]
fn dom_payload_sha256(bencher: Bencher<'_, '_>, size: usize) {
    let payload = vec![b'<'; size];
    bencher.bench_local(|| black_box(Sha256Digest::digest(black_box(&payload))));
}

#[divan::bench(args = [1_024, 16_384, 262_144, 1_048_576])]
fn png_payload_sha256(bencher: Bencher<'_, '_>, size: usize) {
    let payload = vec![0x89_u8; size];
    bencher.bench_local(|| black_box(Sha256Digest::digest(black_box(&payload))));
}
