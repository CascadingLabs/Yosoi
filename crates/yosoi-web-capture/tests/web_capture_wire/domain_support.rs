fn observation(
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    maximum: CaptureDeadline,
    termination: CaptureTermination,
) -> CaptureObservation {
    let policy = ObservationPolicy::new(
        ObservationLimits::new(maximum, None, None),
        SettlementPolicy::Disabled,
    );
    let window = ObservationWindow::new(
        started_at,
        finished_at,
        CaptureDuration::from_microseconds(1_000_000),
    )
    .unwrap();
    let events = EventAccounting::new(
        EventCount::new(0),
        EventCount::new(0),
        MeasuredCount::Known(EventCount::new(0)),
    )
    .unwrap();
    let bytes = ByteAccounting::new(
        ByteCount::new(0),
        ByteCount::new(0),
        MeasuredCount::Known(ByteCount::new(0)),
    )
    .unwrap();
    let terminal = TerminalObservationState::new(
        CaptureOffset::from_microseconds(1_000_000),
        events,
        bytes,
        InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
    );
    CaptureObservation::new(policy, window, terminal, termination).unwrap()
}

fn source_record(
    capture_id: CaptureId,
    id: u32,
    content: &[u8],
    generated_at: DateTime<Utc>,
    derived_from: Vec<ArtifactRef>,
) -> ArtifactRecord {
    ArtifactRecord::new(
        ArtifactId::try_from(id).unwrap(),
        Some(Sha256Digest::digest(content)),
        ArtifactAvailability::Retained,
        None,
        Provenance::new(
            capture_id.activity_id(),
            producer("com.cascadinglabs.http-test"),
            Schema::new(
                SchemaId::new("com.cascadinglabs.web.source").unwrap(),
                SchemaVersion::try_from(1).unwrap(),
            ),
            generated_at,
            derived_from,
        ),
    )
    .unwrap()
}

fn source_artifact(record: ArtifactRecord) -> SourceArtifact {
    let retained_bytes = if record.content_digest() == Some(Sha256Digest::digest(b"first")) {
        5
    } else {
        6
    };
    SourceArtifact::new(
        yosoi_web_capture::WebArtifactMetadata::new(
            record,
            MediaType::new("text/html").unwrap(),
            ArtifactByteExtent::Complete {
                retained_bytes: ByteCount::new(retained_bytes),
            },
            ArtifactSensitivity::NonSensitive,
        )
        .unwrap(),
    )
}

fn capabilities(source_multiplicity: ArtifactMultiplicity) -> WebArtifactCapabilitySet {
    WebArtifactCapabilitySet::new(
        ArtifactCapability::Supported {
            multiplicity: source_multiplicity,
        },
        unsupported("rendered-dom"),
        unsupported("accessibility-tree"),
        ArtifactCapability::Supported {
            multiplicity: ArtifactMultiplicity::Many,
        },
        ArtifactCapability::Supported {
            multiplicity: ArtifactMultiplicity::AtMostOne,
        },
        unsupported("storage"),
        unsupported("layout"),
        unsupported("visual"),
        unsupported("runtime-diagnostics"),
    )
}

fn empty_manifest() -> WebArtifactManifest {
    manifest_with_source(ArtifactFamilyResult::NotRequested)
}

fn manifest_with_source(source: ArtifactFamilyResult<SourceArtifact>) -> WebArtifactManifest {
    let not_requested = ArtifactRequest::NotRequested;
    let requests = WebArtifactRequestSet::new(
        if source.is_not_requested() {
            not_requested
        } else {
            ArtifactRequest::Optional
        },
        not_requested,
        not_requested,
        not_requested,
        not_requested,
        not_requested,
        not_requested,
        not_requested,
        not_requested,
    );
    let results = WebArtifactResults::new(
        source,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
    );
    WebArtifactManifest::new(requests, results).unwrap()
}

fn http_environment(client: Producer) -> CaptureEnvironment {
    CaptureEnvironment::Http(HttpCaptureEnvironment::new(
        client,
        EnvironmentValue::unavailable(reason("environment.not-observed")),
        EnvironmentValue::unavailable(reason("environment.not-observed")),
    ))
}

fn producer(id: &str) -> Producer {
    Producer::new(
        ProducerId::new(id).unwrap(),
        ProducerVersion::new("0.1.0").unwrap(),
    )
}

fn unsupported(name: &str) -> ArtifactCapability {
    ArtifactCapability::Unsupported {
        reason: reason(&format!("provider.unsupported-{name}")),
    }
}

fn reason(value: &str) -> ReasonCode {
    ReasonCode::new(value).unwrap()
}

fn timestamp(value: &str) -> DateTime<Utc> {
    value.parse().unwrap()
}

fn browser_execution_receipt(capture_id: CaptureId) -> BrowserExecutionReceipt {
    let process = BrowserProcessSlotLease::new(
        BrowserExecutionManagerId::random(),
        BrowserProcessSlotId::random(),
        BrowserProcessGeneration::new(NonZeroU64::MIN),
    );
    let execution = BrowserExecutionLease::new(process, BrowserExecutionId::random());
    let context = BrowserContextLease::new(execution.clone(), BrowserContextLeaseId::random());
    let session = BrowserSessionLease::new(context.clone(), BrowserSessionLeaseId::random());
    let tab = BrowserTabLease::new(session.clone(), BrowserTabLeaseId::random());
    let admission = BrowserExecutionAdmissionReceipt::new(
        BrowserExecutionScope::Independent,
        execution,
        context,
        session,
        tab,
    )
    .unwrap();
    let cleanup = BrowserExecutionCleanupReceipt::new(
        admission.clone(),
        BrowserContextCleanupDisposition::Completed,
        BrowserProcessCleanupDisposition::WarmRetained,
    );
    let terminal = BrowserExecutionTerminalReceipt::new(
        admission.clone(),
        cleanup,
        BrowserExecutionTerminalReason::Completed,
    )
    .unwrap();
    let limits = BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::MIN),
        BrowserContextTotalLimit::new(NonZeroU32::MIN),
        BrowserContextsPerProcessLimit::new(NonZeroU32::MIN),
        BrowserTabTotalLimit::new(NonZeroU32::MIN),
        BrowserTabsPerSessionLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(NonZeroU32::MIN),
        BrowserQueueWaitLimit::new(NonZeroU64::MIN),
        BrowserCleanupDeadline::new(NonZeroU64::MIN),
        BrowserRecycleThreshold::new(NonZeroU32::MIN),
    )
    .unwrap();
    let accounting =
        BrowserExecutionAccountingReceipt::terminal(admission, limits, 1, 0, 0, 0, 0, 0, 1)
            .unwrap();
    BrowserExecutionReceipt::new(capture_id, terminal, accounting).unwrap()
}

fn fixed_capture_id(last_digit: u8) -> CaptureId {
    format!("123e4567-e89b-42d3-a456-42661417400{last_digit}")
        .parse()
        .unwrap()
}
