use super::*;
use crate::internal::engine as internal_engine;

#[test]
fn validation_limits_are_typed_and_explicit() -> Result<(), Box<dyn Error>> {
    let extracted = Product::extract(&valid_located()?);
    assert!(matches!(
        extracted.validate_with_limits(internal_engine::ValidationLimits {
            max_fields: 3,
            max_records: 10,
            ..internal_engine::ValidationLimits::default()
        }),
        ys::ContractOutcome::ValidationRejected {
            failure: ys::ValidationFailure::FieldLimitExceeded {
                maximum: 3,
                observed: 4,
            }
        }
    ));

    let extracted = Product::extract(&valid_located()?);
    assert!(matches!(
        extracted.validate_with_limits(internal_engine::ValidationLimits {
            max_fields: 10,
            max_records: 1,
            ..internal_engine::ValidationLimits::default()
        }),
        ys::ContractOutcome::ValidationRejected {
            failure: ys::ValidationFailure::RecordLimitExceeded {
                maximum: 1,
                observed: 2,
            }
        }
    ));

    let extracted = Product::extract(&valid_located()?);
    assert!(matches!(
        extracted.validate_with_limits(internal_engine::ValidationLimits {
            max_conversions: 6,
            ..internal_engine::ValidationLimits::default()
        }),
        ys::ContractOutcome::ValidationRejected {
            failure: ys::ValidationFailure::ConversionLimitExceeded {
                maximum: 6,
                observed: 7,
            }
        }
    ));

    let extracted = Product::extract(&valid_located()?);
    assert!(matches!(
        extracted.validate_with_limits(internal_engine::ValidationLimits {
            max_retained_provenance: 6,
            ..internal_engine::ValidationLimits::default()
        }),
        ys::ContractOutcome::ValidationRejected {
            failure: ys::ValidationFailure::ProvenanceLimitExceeded {
                maximum: 6,
                observed: 7,
            }
        }
    ));

    let document = ys::DocumentId::try_new("issue-limit")?;
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(
            document.clone(),
            vec![finding(
                &document,
                "name",
                0,
                "/products/0/name",
                "Missing price",
                ys::Completeness::Complete,
                region(0)?,
            )?],
        )?,
    };
    assert!(matches!(
        Product::extract(&located).validate_with_limits(internal_engine::ValidationLimits {
            max_issues: 0,
            ..internal_engine::ValidationLimits::default()
        }),
        ys::ContractOutcome::ValidationRejected {
            failure: ys::ValidationFailure::IssueLimitExceeded {
                maximum: 0,
                observed: 1,
            }
        }
    ));
    Ok(())
}

#[test]
fn issue_debug_redacts_document_region_and_projected_values() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("sentinel-document-secret")?;
    let region = ys::RegionLineage::new(
        ys::RegionId::try_new("product")?,
        0,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new("/sentinel-region-secret")?),
    );
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(
            document.clone(),
            vec![finding(
                &document,
                "name",
                0,
                "/sentinel-value-secret",
                "sentinel-projected-secret",
                ys::Completeness::Complete,
                region,
            )?],
        )?,
    };
    let ys::ContractOutcome::Evaluated { issues, .. } = Product::extract(&located).validate()
    else {
        return Err("expected evaluated outcome".into());
    };
    let debug = format!("{issues:?}");
    for secret in [
        "sentinel-document-secret",
        "sentinel-region-secret",
        "sentinel-value-secret",
        "sentinel-projected-secret",
    ] {
        assert!(!debug.contains(secret));
    }
    Ok(())
}
