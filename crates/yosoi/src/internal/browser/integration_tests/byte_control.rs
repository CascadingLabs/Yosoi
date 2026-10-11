#![allow(clippy::expect_used, clippy::panic_in_result_fn)]

use crate::internal::browser as internal_browser;
use crate::internal::types as internal_types;
use std::{fs, io, path::Path};

use crate::internal::browser::{
    BrowserBudgetScope, BrowserByteAccounting, BrowserByteAccountingError, BrowserByteBudget,
    BrowserByteDomain, BrowserByteMeasurementUnavailableReason, BrowserByteReport,
    BrowserByteReportError, BrowserByteSpec, BrowserLimitScope, BrowserPayloadExtent,
    BrowserPayloadFailureReason, BrowserPayloadUnavailableReason, MeasuredBrowserBytes,
};
use crate::internal::types::{ByteCount, ByteLimit, ByteLimitError};

fn spec(limit: u64, budget_scope: BrowserBudgetScope) -> BrowserByteSpec {
    BrowserByteSpec::new(
        BrowserByteDomain::CdpDecodedBody,
        ByteLimit::try_from(limit).expect("positive limit"),
        BrowserLimitScope::RetentionAfterProviderMaterialization,
        budget_scope,
    )
}

#[test]
fn byte_limits_are_nonzero_and_round_trip() {
    assert_eq!(ByteLimit::try_from(0_u64), Err(ByteLimitError::Zero));
    let limit = ByteLimit::try_from(17_u64).expect("valid limit");
    assert_eq!(limit.get(), 17);
    assert_eq!(limit.as_usize(), Ok(17));
    assert_eq!(
        serde_json::to_string(&limit).expect("serialize limit"),
        "17"
    );
    assert!(serde_json::from_str::<ByteLimit>("0").is_err());
}

#[test]
fn provider_scope_wire_adapters_preserve_frozen_snake_case_json() {
    assert_eq!(
        serde_json::to_string(&BrowserLimitScope::RetentionAfterProviderMaterialization)
            .expect("serialize enforcement"),
        r#""retention_after_provider_materialization""#
    );
    assert_eq!(
        serde_json::to_string(&BrowserBudgetScope::CaptureAggregate)
            .expect("serialize budget scope"),
        r#""capture_aggregate""#
    );
    assert_eq!(
        BrowserLimitScope::RetentionAfterProviderMaterialization.canonical(),
        internal_types::LimitEnforcement::RetentionAfterProviderMaterialization
    );
    assert_eq!(
        BrowserBudgetScope::CaptureAggregate.canonical(),
        internal_types::BudgetScope::CaptureAggregate
    );
}

#[test]
fn exact_limit_retains_the_complete_chunk_without_overflow() {
    let mut budget = BrowserByteBudget::new(spec(4, BrowserBudgetScope::PerPayload));
    let admission = budget
        .observe_chunk(ByteCount::new(4))
        .expect("admit exact chunk");
    assert_eq!(admission.retain_prefix.get(), 4);
    assert_eq!(admission.discarded.get(), 0);
    assert!(!admission.limit_exceeded);
    let accounting = budget.accounting().expect("valid accounting");
    assert_eq!(accounting.observed().get(), 4);
    assert_eq!(accounting.retained().get(), 4);
    assert_eq!(
        accounting.discarded(),
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(0)
        }
    );
}

#[test]
fn one_byte_over_retains_an_exact_prefix() {
    let mut budget = BrowserByteBudget::new(spec(4, BrowserBudgetScope::PerPayload));
    let admission = budget
        .observe_chunk(ByteCount::new(5))
        .expect("admit over-limit chunk");
    assert_eq!(admission.retain_prefix.get(), 4);
    assert_eq!(admission.discarded.get(), 1);
    assert!(admission.limit_exceeded);
    let accounting = budget.accounting().expect("valid accounting");
    assert_eq!(accounting.observed().get(), 5);
    assert_eq!(accounting.retained().get(), 4);
}

#[test]
fn aggregate_budget_is_shared_across_chunks() {
    let mut budget = BrowserByteBudget::new(spec(5, BrowserBudgetScope::CaptureAggregate));
    let first = budget
        .observe_chunk(ByteCount::new(3))
        .expect("first chunk");
    let second = budget
        .observe_chunk(ByteCount::new(4))
        .expect("second chunk");
    assert_eq!(first.retain_prefix.get(), 3);
    assert_eq!(second.retain_prefix.get(), 2);
    assert_eq!(second.discarded.get(), 2);
    let accounting = budget.accounting().expect("valid accounting");
    assert_eq!(accounting.observed().get(), 7);
    assert_eq!(accounting.retained().get(), 5);
    assert_eq!(
        accounting.discarded(),
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(2)
        }
    );
}

#[test]
fn empty_payload_is_complete_accounting() {
    let budget = BrowserByteBudget::new(spec(1, BrowserBudgetScope::PerPayload));
    let accounting = budget.accounting().expect("empty accounting");
    assert_eq!(accounting.observed().get(), 0);
    assert_eq!(accounting.retained().get(), 0);
    assert_eq!(
        accounting.discarded(),
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(0)
        }
    );
}

#[test]
fn contradictory_accounting_is_rejected() {
    assert_eq!(
        BrowserByteAccounting::new(
            ByteCount::new(1),
            ByteCount::new(2),
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(0)
            },
        ),
        Err(BrowserByteAccountingError::RetainedExceedsObserved)
    );
    assert_eq!(
        BrowserByteAccounting::new(
            ByteCount::new(5),
            ByteCount::new(3),
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(1)
            },
        ),
        Err(BrowserByteAccountingError::KnownDiscardMismatch)
    );
    assert!(
        serde_json::from_str::<BrowserByteAccounting>(
            r#"{"observed":5,"retained":3,"discarded":{"status":"known","value":1}}"#,
        )
        .is_err(),
        "deserialization must enforce the same accounting invariants",
    );
}

#[test]
fn unknown_discard_is_preserved_without_inference() {
    let accounting = BrowserByteAccounting::new(
        ByteCount::new(5),
        ByteCount::new(3),
        MeasuredBrowserBytes::Unavailable {
            reason: internal_browser::BrowserByteMeasurementUnavailableReason::ProviderDidNotReport,
        },
    )
    .expect("unknown loss is valid");
    assert!(matches!(
        accounting.discarded(),
        MeasuredBrowserBytes::Unavailable { .. }
    ));
}

#[test]
fn reports_derive_complete_and_truncated_extent_from_one_accounting_source() {
    let complete = BrowserByteReport::from_known_extent(
        BrowserByteDomain::RenderedDomUtf8,
        None,
        ByteCount::new(4),
        ByteCount::new(4),
    )
    .expect("complete report");
    assert_eq!(complete.extent(), BrowserPayloadExtent::Complete);

    assert_eq!(
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::CdpDecodedBody,
            Some(spec(3, BrowserBudgetScope::PerPayload)),
            ByteCount::new(4),
            ByteCount::new(4),
        ),
        Err(BrowserByteReportError::Accounting(
            BrowserByteAccountingError::RetainedExceedsLimit,
        )),
    );

    let truncated = BrowserByteReport::from_known_extent(
        BrowserByteDomain::CdpDecodedBody,
        Some(spec(4, BrowserBudgetScope::PerPayload)),
        ByteCount::new(5),
        ByteCount::new(4),
    )
    .expect("truncated report");
    assert!(matches!(
        truncated.extent(),
        BrowserPayloadExtent::Truncated { .. }
    ));
    assert_eq!(truncated.accounting().retained().get(), 4);
    assert_eq!(
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::RenderedDomUtf8,
            Some(spec(4, BrowserBudgetScope::PerPayload)),
            ByteCount::new(4),
            ByteCount::new(4),
        ),
        Err(BrowserByteReportError::Accounting(
            BrowserByteAccountingError::SpecDomainMismatch
        )),
    );
}

#[test]
fn discarded_and_failed_reports_preserve_terminal_invariants_through_serde() {
    let discarded = BrowserByteReport::discarded(
        BrowserByteDomain::CdpDecodedBody,
        Some(spec(4, BrowserBudgetScope::PerPayload)),
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(7),
        },
    )
    .expect("discarded report");
    assert_eq!(discarded.accounting().retained().get(), 0);
    assert!(matches!(
        discarded.extent(),
        BrowserPayloadExtent::Discarded { .. }
    ));
    let discarded_json = serde_json::to_string(&discarded).expect("serialize discarded");
    assert_eq!(
        serde_json::from_str::<BrowserByteReport>(&discarded_json).expect("deserialize discarded"),
        discarded,
    );

    let failed = BrowserByteReport::failed(
        BrowserByteDomain::CdpDecodedBody,
        Some(spec(4, BrowserBudgetScope::PerPayload)),
        BrowserPayloadFailureReason::ProviderDisconnected,
    )
    .expect("failed report");
    assert!(matches!(
        failed.extent(),
        BrowserPayloadExtent::Failed { .. }
    ));
    let failed_json = serde_json::to_string(&failed).expect("serialize failed");
    assert_eq!(
        serde_json::from_str::<BrowserByteReport>(&failed_json).expect("deserialize failed"),
        failed,
    );
    assert!(serde_json::from_str::<BrowserByteReport>(
        r#"{"domain":"cdp_decoded_body","spec":null,"accounting":{"observed":7,"retained":1,"discarded":{"status":"known","value":6}},"extent":{"status":"discarded","observed_bytes":{"status":"known","value":6}},"additional_loss":{"status":"known","value":0}}"#
    )
    .is_err(), "discarded reports must not deserialize with retained bytes");
}

#[test]
fn canonical_reports_cover_exact_unknown_overflow_and_contradictions() {
    let zero = MeasuredBrowserBytes::Known {
        value: ByteCount::new(0),
    };
    let one = MeasuredBrowserBytes::Known {
        value: ByteCount::new(1),
    };
    let unknown = MeasuredBrowserBytes::Unavailable {
        reason: BrowserByteMeasurementUnavailableReason::CaptureEndedEarly,
    };
    let exact = BrowserByteAccounting::new(ByteCount::new(5), ByteCount::new(5), zero)
        .expect("exact accounting");

    for (discarded, additional) in [(one, zero), (zero, one), (unknown, zero), (zero, unknown)] {
        let accounting = BrowserByteAccounting::new(
            ByteCount::new(5),
            ByteCount::new(if discarded == one { 4 } else { 5 }),
            discarded,
        )
        .expect("valid accounting");
        assert_eq!(
            BrowserByteReport::new(
                BrowserByteDomain::CdpDecodedBody,
                None,
                accounting,
                BrowserPayloadExtent::Complete,
                additional,
            ),
            Err(BrowserByteReportError::ExtentMismatch),
        );
    }

    let unknown_truncation = BrowserByteReport::truncated(
        BrowserByteDomain::CdpDecodedBody,
        None,
        exact,
        unknown,
        unknown,
    )
    .expect("unknown complete extent and loss are valid");
    let json = serde_json::to_string(&unknown_truncation).expect("serialize unknown truncation");
    assert_eq!(
        serde_json::from_str::<BrowserByteReport>(&json).expect("round-trip unknown truncation"),
        unknown_truncation,
    );

    let exact_truncation = BrowserByteReport::truncated(
        BrowserByteDomain::CdpDecodedBody,
        None,
        exact,
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(7),
        },
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(2),
        },
    )
    .expect("observed plus additional loss equals complete size");
    let json = serde_json::to_string(&exact_truncation).expect("serialize exact truncation");
    assert_eq!(
        serde_json::from_str::<BrowserByteReport>(&json).expect("round-trip exact truncation"),
        exact_truncation,
    );

    for (complete, additional, expected) in [
        (5, 0, BrowserByteReportError::ExtentMismatch),
        (4, 1, BrowserByteReportError::ExtentMismatch),
        (8, 2, BrowserByteReportError::ExtentMismatch),
        (
            u64::MAX,
            u64::MAX,
            BrowserByteReportError::Accounting(BrowserByteAccountingError::Overflow),
        ),
    ] {
        assert_eq!(
            BrowserByteReport::truncated(
                BrowserByteDomain::CdpDecodedBody,
                None,
                exact,
                MeasuredBrowserBytes::Known {
                    value: ByteCount::new(complete)
                },
                MeasuredBrowserBytes::Known {
                    value: ByteCount::new(additional)
                },
            ),
            Err(expected),
        );
    }
}

#[test]
fn failed_partial_and_requested_unavailable_reports_round_trip() {
    let unknown = MeasuredBrowserBytes::Unavailable {
        reason: BrowserByteMeasurementUnavailableReason::CaptureEndedEarly,
    };
    let partial = BrowserByteAccounting::new(
        ByteCount::new(5),
        ByteCount::new(3),
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(2),
        },
    )
    .expect("partial accounting");
    let failed = BrowserByteReport::failed_with_accounting(
        BrowserByteDomain::CdpDecodedBody,
        Some(spec(4, BrowserBudgetScope::PerPayload)),
        partial,
        BrowserPayloadFailureReason::ProviderDisconnected,
        unknown,
    )
    .expect("partial failed report");
    let json = serde_json::to_string(&failed).expect("serialize partial failed report");
    assert_eq!(
        serde_json::from_str::<BrowserByteReport>(&json).expect("round trip"),
        failed
    );

    let unavailable = BrowserByteReport::unavailable_with_spec(
        BrowserByteDomain::CdpDecodedBody,
        Some(spec(4, BrowserBudgetScope::PerPayload)),
        BrowserPayloadUnavailableReason::ProviderDidNotReport,
    )
    .expect("requested unavailable report");
    assert!(unavailable.spec().is_some());
    let json = serde_json::to_string(&unavailable).expect("serialize unavailable report");
    assert_eq!(
        serde_json::from_str::<BrowserByteReport>(&json).expect("round trip"),
        unavailable,
    );
}

#[test]
fn browser_provider_depends_on_types_without_importing_capture() -> io::Result<()> {
    fn append_sources(root: &Path, source: &mut String) -> io::Result<()> {
        for entry in fs::read_dir(root)? {
            let path = entry?.path();
            if path.is_dir() {
                if path.file_name().and_then(|name| name.to_str()) != Some("integration_tests") {
                    append_sources(&path, source)?;
                }
            } else if path.extension().and_then(|extension| extension.to_str()) == Some("rs") {
                let file_name = path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or_default();
                if file_name != "integration_tests.rs"
                    && file_name != "tests.rs"
                    && !file_name.ends_with("_tests.rs")
                {
                    source.push_str(&fs::read_to_string(path)?);
                    source.push('\n');
                }
            }
        }
        Ok(())
    }

    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/internal/browser");
    let mut source = String::new();
    append_sources(&root, &mut source)?;

    for forbidden in [
        "crate::internal::direct_http",
        "crate::internal::web_capture",
    ] {
        assert!(
            !source.contains(forbidden),
            "browser provider must not depend on {forbidden}"
        );
    }
    Ok(())
}

#[test]
fn accounting_overflow_is_rejected() {
    assert_eq!(
        BrowserByteAccounting::new(
            ByteCount::new(u64::MAX),
            ByteCount::new(u64::MAX),
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(1)
            },
        ),
        Err(BrowserByteAccountingError::Overflow)
    );
}
