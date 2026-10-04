use super::accounting_scope::{document_scope, event_accounting, reason};
use crate as yosoi;
use crate::VoidCrawlAdapterError;
use std::sync::Arc;
use void_crawl_core as provider;

pub fn accessibility(
    value: &provider::AccessibilitySnapshot,
    at: yosoi::CaptureOffset,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    let Some(scope) = document_scope(&value.scope) else {
        return Ok(yosoi::ArtifactStagingOutcome::unavailable(reason(
            "voidcrawl.snapshot.document-epoch-unavailable",
        )?));
    };
    if matches!(value.state, provider::SnapshotState::Unavailable { .. }) {
        return Ok(yosoi::ArtifactStagingOutcome::unavailable(reason(
            "voidcrawl.accessibility.unavailable",
        )?));
    }
    let observed =
        u64::try_from(value.nodes_observed).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let retained =
        u64::try_from(value.nodes_retained).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let node_loss = observed
        .checked_sub(retained)
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let retained_bytes =
        u64::try_from(value.retained_bytes).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    if retained_bytes
        != u64::try_from(value.bytes().len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    }
    let observed_bytes = u64::try_from(
        value
            .complete_bytes
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let lost_bytes = observed_bytes
        .checked_sub(retained_bytes)
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let byte_spec = value
        .byte_report()
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
        .spec()
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let evidence = yosoi::BrowserAccessibilityEvidence {
        schema: value.payload_schema,
        schema_version: value.payload_version,
        capture_mode: value.capture_mode,
        requested_depth: value.requested_depth,
        ignored_nodes: value.ignored_node_policy,
        scope,
        at,
        nodes_observed: observed,
        nodes_retained: retained,
        nodes_lost: yosoi::LossExtent::Known(node_loss),
        bytes: yosoi::BrowserByteAccounting {
            configured_limit: byte_spec.limit().get(),
            enforcement: byte_spec.limit_scope().canonical(),
            budget_scope: byte_spec.budget_scope().canonical(),
            observed: observed_bytes,
            retained: retained_bytes,
            lost: yosoi::LossExtent::Known(lost_bytes),
            complete: matches!(value.state, provider::SnapshotState::Complete),
        },
        canonical_node_bytes: value.bytes().to_vec(),
    };
    yosoi::ArtifactStagingOutcome::structured(
        yosoi::BrowserStructuredEvidence::Accessibility(evidence),
        if node_loss == 0 && lost_bytes == 0 {
            None
        } else {
            Some(reason("voidcrawl.accessibility.bounded-loss")?)
        },
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

fn micro(value: f64, nonnegative: bool) -> Result<i64, VoidCrawlAdapterError> {
    if !value.is_finite() || (nonnegative && value < 0.0) {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    }
    format!("{:.0}", value * 1_000_000.0)
        .parse()
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
fn rect(
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<yosoi::BrowserLayoutRect, VoidCrawlAdapterError> {
    Ok(yosoi::BrowserLayoutRect {
        x_micro_css: micro(x, false)?,
        y_micro_css: micro(y, false)?,
        width_micro_css: u64::try_from(micro(width, true)?)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        height_micro_css: u64::try_from(micro(height, true)?)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
    })
}
pub(super) fn visual_layout_facts(
    visual_scope: &provider::DocumentScope,
    layout: Option<&(provider::LayoutSnapshot, yosoi::CaptureOffset)>,
) -> (
    i64,
    i64,
    yosoi::BrowserVisualLayoutCorrelation,
    Option<yosoi::CaptureOffset>,
) {
    let Some((layout, at)) = layout.filter(|(item, _)| item.scope == *visual_scope) else {
        return (
            0,
            0,
            yosoi::BrowserVisualLayoutCorrelation::Unavailable,
            None,
        );
    };
    (
        layout.layout_viewport.page_x,
        layout.layout_viewport.page_y,
        yosoi::BrowserVisualLayoutCorrelation::SameDocumentEpochOnly,
        Some(*at),
    )
}

pub fn visual(
    value: &provider::VisualSnapshot,
    layout: Option<&(provider::LayoutSnapshot, yosoi::CaptureOffset)>,
    at: yosoi::CaptureOffset,
    max_bytes: usize,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    let Some(scope) = document_scope(&value.scope) else {
        return Ok(yosoi::ArtifactStagingOutcome::unavailable(reason(
            "voidcrawl.snapshot.document-epoch-unavailable",
        )?));
    };
    if value.retained_bytes > max_bytes {
        return Ok(yosoi::ArtifactStagingOutcome::discarded(
            yosoi::BrowserByteDomain::ScreenshotPng,
            yosoi::LossExtent::Known(
                u64::try_from(value.retained_bytes)
                    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            ),
            reason("voidcrawl.visual.post-materialization-limit")?,
        ));
    }
    let (scroll_x, scroll_y, layout_correlation, paired_layout_at) =
        visual_layout_facts(&value.scope, layout);
    let fact = yosoi::BrowserVisualFact {
        scope,
        at,
        format: yosoi::BrowserVisualFormat::Png,
        width_pixels: value.image_width_pixels,
        height_pixels: value.image_height_pixels,
        viewport_width_css: value.capture_viewport.width_css_pixels().get(),
        viewport_height_css: value.capture_viewport.height_css_pixels().get(),
        scroll_x_micro_css: scroll_x
            .checked_mul(1_000_000)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?,
        scroll_y_micro_css: scroll_y
            .checked_mul(1_000_000)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?,
        device_scale_micro: u64::try_from(micro(value.device_scale_factor, true)?)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        layout_correlation,
        paired_layout_at,
    };
    let mapping = yosoi::BrowserArtifactMapping::new(
        yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Visual),
        yosoi::BrowserByteLayer::Png,
    )
    .and_then(|mapping| mapping.with_snapshot(yosoi::BrowserSnapshotObservation::visual_fact(fact)))
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    yosoi::ArtifactStagingOutcome::complete(
        mapping,
        Arc::from(value.bytes()),
        u64::try_from(value.retained_bytes).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub(super) fn runtime_byte_accounting(
    report: &provider::ObservationReport,
) -> Result<yosoi::BrowserByteAccounting, VoidCrawlAdapterError> {
    let known = |value| match value {
        provider::MeasuredCount::Known { value } => Ok(value),
        provider::MeasuredCount::Unavailable { .. } => Err(VoidCrawlAdapterError::InvalidStaging),
    };
    let observed = known(report.accounting.runtime_bytes.admitted)?;
    let retained = known(report.accounting.runtime_bytes.retained)?;
    let locally_lost = match report.accounting.runtime_bytes.dropped {
        provider::MeasuredCount::Known { value } => yosoi::LossExtent::Known(value),
        provider::MeasuredCount::Unavailable { .. } => yosoi::LossExtent::Unknown,
    };
    if retained > observed
        || matches!(locally_lost, yosoi::LossExtent::Known(value) if retained.checked_add(value) != Some(observed))
        || retained
            != u64::try_from(report.diagnostic_bytes_retained)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    }
    // A non-finished observation may have stopped before upstream runtime
    // diagnostics were delivered. Local retention accounting cannot prove that
    // no such bytes were lost.
    let lost = if matches!(
        report.termination,
        provider::ObservationTermination::Finished
    ) {
        locally_lost
    } else {
        yosoi::LossExtent::Unknown
    };
    let byte_spec = report
        .byte_report()
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
        .spec()
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    Ok(yosoi::BrowserByteAccounting {
        configured_limit: byte_spec.limit().get(),
        enforcement: byte_spec.limit_scope().canonical(),
        budget_scope: byte_spec.budget_scope().canonical(),
        observed,
        retained,
        lost,
        complete: matches!(lost, yosoi::LossExtent::Known(0)),
    })
}

fn console_level(value: &str) -> Result<yosoi::BrowserConsoleLevel, VoidCrawlAdapterError> {
    match value {
        "log" => Ok(yosoi::BrowserConsoleLevel::Log),
        "debug" => Ok(yosoi::BrowserConsoleLevel::Debug),
        "info" => Ok(yosoi::BrowserConsoleLevel::Info),
        "error" => Ok(yosoi::BrowserConsoleLevel::Error),
        "warning" => Ok(yosoi::BrowserConsoleLevel::Warning),
        "dir" => Ok(yosoi::BrowserConsoleLevel::Dir),
        "dirxml" => Ok(yosoi::BrowserConsoleLevel::DirXml),
        "table" => Ok(yosoi::BrowserConsoleLevel::Table),
        "trace" => Ok(yosoi::BrowserConsoleLevel::Trace),
        "clear" => Ok(yosoi::BrowserConsoleLevel::Clear),
        "startGroup" => Ok(yosoi::BrowserConsoleLevel::StartGroup),
        "startGroupCollapsed" => Ok(yosoi::BrowserConsoleLevel::StartGroupCollapsed),
        "endGroup" => Ok(yosoi::BrowserConsoleLevel::EndGroup),
        "assert" => Ok(yosoi::BrowserConsoleLevel::Assert),
        "profile" => Ok(yosoi::BrowserConsoleLevel::Profile),
        "profileEnd" => Ok(yosoi::BrowserConsoleLevel::ProfileEnd),
        "count" => Ok(yosoi::BrowserConsoleLevel::Count),
        "timeEnd" => Ok(yosoi::BrowserConsoleLevel::TimeEnd),
        _ => Err(VoidCrawlAdapterError::InvalidStaging),
    }
}

pub fn runtime(
    report: &provider::ObservationReport,
    armed_at: u64,
    scope: Option<yosoi::BrowserDocumentScope>,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    let known = |value| match value {
        provider::MeasuredCount::Known { value } => Ok(value),
        provider::MeasuredCount::Unavailable { .. } => Err(VoidCrawlAdapterError::InvalidStaging),
    };
    let accounting = event_accounting(
        known(report.accounting.runtime_events.admitted)?,
        known(report.accounting.runtime_events.retained)?,
        report.accounting.runtime_events.dropped,
    )?;
    let mut diagnostics = Vec::with_capacity(report.diagnostics.len());
    for diagnostic in &report.diagnostics {
        let event = report
            .events
            .iter()
            .find(|event| event.sequence == diagnostic.event_sequence)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
        let offset = armed_at
            .checked_add(event.offset_micros)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
        let kind = match &diagnostic.kind {
            provider::RuntimeDiagnosticKind::Console { level } => {
                yosoi::BrowserRuntimeDiagnosticKind::Console {
                    level: console_level(level)?,
                }
            }
            provider::RuntimeDiagnosticKind::Exception => {
                yosoi::BrowserRuntimeDiagnosticKind::Exception
            }
        };
        diagnostics.push(yosoi::BrowserRuntimeDiagnosticFact {
            sequence: diagnostic.event_sequence,
            at: yosoi::CaptureOffset::from_microseconds(offset),
            kind,
            value_type: yosoi::BrowserRuntimeValueType::RedactedText,
            complete_utf8_bytes: u64::try_from(diagnostic.complete_bytes)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            retained_utf8_bytes: u64::try_from(diagnostic.retained_bytes)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            truncated: diagnostic.truncated,
            redacted_sha256: yosoi_types::Sha256Digest::digest(diagnostic.text().bytes()),
        });
    }
    let byte_accounting = runtime_byte_accounting(report)?;
    let has_loss = !matches!(
        accounting.dropped(),
        yosoi::MeasuredCount::Known(count) if count.get() == 0
    ) || byte_accounting.lost != yosoi::LossExtent::Known(0);
    yosoi::ArtifactStagingOutcome::structured(
        yosoi::BrowserStructuredEvidence::RuntimeDiagnostics {
            scope,
            diagnostics,
            runtime_event_accounting: accounting,
            byte_accounting,
        },
        if has_loss {
            Some(reason("voidcrawl.runtime.exact-or-unknown-loss")?)
        } else {
            None
        },
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub fn layout(
    value: &provider::LayoutSnapshot,
    at: yosoi::CaptureOffset,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    let Some(scope) = document_scope(&value.scope) else {
        return Ok(yosoi::ArtifactStagingOutcome::unavailable(reason(
            "voidcrawl.snapshot.document-epoch-unavailable",
        )?));
    };
    let l = value.layout_viewport;
    let v = value.visual_viewport;
    let c = value.content_size;
    let fact = yosoi::BrowserLayoutFact {
        scope,
        at,
        layout_viewport: rect(
            l.page_x
                .to_string()
                .parse()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            l.page_y
                .to_string()
                .parse()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            l.client_width
                .to_string()
                .parse()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            l.client_height
                .to_string()
                .parse()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        )?,
        visual_viewport: rect(v.page_x, v.page_y, v.client_width, v.client_height)?,
        content: rect(c.x, c.y, c.width, c.height)?,
        device_scale_micro: value
            .device_scale_factor
            .map(|scale| {
                micro(scale, true).and_then(|v| {
                    u64::try_from(v).map_err(|_| VoidCrawlAdapterError::InvalidStaging)
                })
            })
            .transpose()?,
    };
    yosoi::ArtifactStagingOutcome::structured(yosoi::BrowserStructuredEvidence::Layout(fact), None)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
