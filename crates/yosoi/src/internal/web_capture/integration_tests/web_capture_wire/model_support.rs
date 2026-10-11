use crate::internal::web_capture as internal_web_capture;
#[derive(Debug)]
struct CaptureParts {
    acquisition: WebAcquisitionRecord,
    environment: CaptureEnvironment,
    observation: CaptureObservation,
    capabilities: WebProviderCapabilityProfile,
    artifacts: WebArtifactManifest,
}

fn minimal_capture(capture_id: CaptureId, partial: bool) -> WebCapture {
    let parts = minimal_parts(capture_id, partial);
    let capture = WebCapture::finalize(
        parts.acquisition,
        parts.environment,
        parts.observation,
        parts.capabilities,
        parts.artifacts,
        Vec::new(),
    )
    .unwrap();
    assert_eq!(
        capture.completeness(),
        if partial {
            CaptureCompleteness::Incomplete
        } else {
            CaptureCompleteness::Complete
        }
    );
    capture
}

fn minimal_parts(capture_id: CaptureId, partial: bool) -> CaptureParts {
    let executor = producer("com.cascadinglabs.http-test");
    let started_at = timestamp("2026-09-05T00:00:00Z");
    let finished_at = timestamp("2026-09-05T00:00:01Z");
    let maximum = CaptureDeadline::try_from(1_000_000).unwrap();
    let (outcome, signal, termination) = if partial {
        (
            ActivityOutcome::Partial,
            Some(ActivitySignal::new(
                reason("capture.deadline"),
                RetryDisposition::Retryable,
            )),
            CaptureTermination::DeadlineReached {
                maximum_elapsed: maximum,
            },
        )
    } else {
        (
            ActivityOutcome::Succeeded,
            None,
            CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied),
        )
    };
    let receipt = activity_receipt(
        capture_id,
        executor.clone(),
        Vec::new(),
        Vec::new(),
        outcome,
        signal,
        started_at,
        finished_at,
    );
    CaptureParts {
        acquisition: acquisition(capture_id, receipt),
        environment: http_environment(executor.clone()),
        observation: observation(started_at, finished_at, maximum, termination),
        capabilities: WebProviderCapabilityProfile::new(
            executor,
            AcquisitionCapabilityProfile::DirectHttp,
            capabilities(ArtifactMultiplicity::Many),
        )
        .unwrap(),
        artifacts: empty_manifest(),
    }
}

fn source_capture(capture_id: CaptureId, reversed: bool) -> WebCapture {
    let parts = source_parts(capture_id, reversed);
    finalize_parts(parts)
}

fn source_capture_with_locations(
    capture_id: CaptureId,
    ids: [u32; 2],
    generated_at: [DateTime<Utc>; 2],
    lineage: ArtifactRef,
) -> WebCapture {
    let parts = source_parts_with_locations(capture_id, false, ids, generated_at, Some(lineage));
    finalize_parts(parts)
}

fn finalize_parts(parts: CaptureParts) -> WebCapture {
    finalize_result(parts, Vec::new()).unwrap()
}

fn finalize_result(
    parts: CaptureParts,
    relationships: Vec<WebArtifactRelationship>,
) -> Result<WebCapture, WebCaptureError> {
    WebCapture::finalize(
        parts.acquisition,
        parts.environment,
        parts.observation,
        parts.capabilities,
        parts.artifacts,
        relationships,
    )
}

fn source_parts(capture_id: CaptureId, reversed: bool) -> CaptureParts {
    source_parts_with_locations(
        capture_id,
        reversed,
        [1, 2],
        [
            timestamp("2026-09-05T00:00:00.250Z"),
            timestamp("2026-09-05T00:00:00.750Z"),
        ],
        None,
    )
}

fn source_parts_with_locations(
    capture_id: CaptureId,
    reversed: bool,
    ids: [u32; 2],
    generated_at: [DateTime<Utc>; 2],
    lineage: Option<ArtifactRef>,
) -> CaptureParts {
    let executor = producer("com.cascadinglabs.http-test");
    let started_at = timestamp("2026-09-05T00:00:00Z");
    let finished_at = timestamp("2026-09-05T00:00:01Z");
    let maximum = CaptureDeadline::try_from(2_000_000).unwrap();
    let derived_from = lineage.into_iter().collect::<Vec<_>>();
    let [first_id, second_id] = ids;
    let [first_time, second_time] = generated_at;
    let mut records = vec![
        source_record(
            capture_id,
            first_id,
            b"first",
            first_time,
            derived_from.clone(),
        ),
        source_record(
            capture_id,
            second_id,
            b"second",
            second_time,
            derived_from.clone(),
        ),
    ];
    if reversed {
        records.reverse();
    }
    let artifacts = records
        .iter()
        .cloned()
        .map(source_artifact)
        .collect::<Vec<_>>();
    let receipt = activity_receipt(
        capture_id,
        executor.clone(),
        derived_from,
        records,
        ActivityOutcome::Succeeded,
        None,
        started_at,
        finished_at,
    );
    CaptureParts {
        acquisition: acquisition(capture_id, receipt),
        environment: http_environment(executor.clone()),
        observation: observation(
            started_at,
            finished_at,
            maximum,
            CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied),
        ),
        capabilities: WebProviderCapabilityProfile::new(
            executor,
            AcquisitionCapabilityProfile::DirectHttp,
            capabilities(ArtifactMultiplicity::Many),
        )
        .unwrap(),
        artifacts: manifest_with_source(ArtifactFamilyResult::Complete {
            artifacts: ArtifactCollection::new(artifacts).unwrap(),
        }),
    }
}

#[allow(clippy::too_many_arguments, reason = "explicit test receipt fixture")]
fn activity_receipt(
    capture_id: CaptureId,
    producer: Producer,
    inputs: Vec<ArtifactRef>,
    outputs: Vec<ArtifactRecord>,
    outcome: ActivityOutcome,
    signal: Option<ActivitySignal>,
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
) -> CaptureReceipt {
    let receipt = ActivityReceipt::new(
        capture_id.activity_id(),
        OperationId::new("com.cascadinglabs.yosoi.web-capture").unwrap(),
        producer,
        inputs,
        outputs,
        outcome,
        signal,
        started_at,
        finished_at,
    )
    .unwrap();
    CaptureReceipt::new(capture_id, receipt).unwrap()
}

fn acquisition(capture_id: CaptureId, receipt: CaptureReceipt) -> WebAcquisitionRecord {
    let request = WebCaptureRequest::new(
        capture_id,
        RequestedWebTarget::parse("https://example.com/").unwrap(),
        internal_web_capture::WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    let resolution = CaptureResolution::new(
        Observation::Unobserved,
        Observation::Unobserved,
        Observation::Unobserved,
        Observation::Unobserved,
    )
    .unwrap();
    WebAcquisitionRecord::new(request, resolution, receipt).unwrap()
}
