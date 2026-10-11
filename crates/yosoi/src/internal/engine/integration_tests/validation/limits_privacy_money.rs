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

#[test]
fn money_wire_format_preserves_the_non_negative_invariant() -> Result<(), Box<dyn Error>> {
    let positive: ys::Money = serde_json::from_str(r#"{"minor_units":450,"currency":"usd"}"#)?;
    assert_eq!(positive.minor_units(), 450);
    let debug = format!("{positive:?}");
    assert!(!debug.contains("450"));
    assert!(!debug.contains("4.50"));
    assert!(serde_json::from_str::<ys::Money>(r#"{"minor_units":-100,"currency":"usd"}"#).is_err());

    let document = ys::DocumentId::try_new("negative-zero")?;
    let item = region(0)?;
    let outcome = Product::extract(&ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(
            document.clone(),
            vec![
                finding(
                    &document,
                    "name",
                    0,
                    "/0/name",
                    "Negative zero",
                    ys::Completeness::Complete,
                    item.clone(),
                )?,
                finding(
                    &document,
                    "price",
                    1,
                    "/0/price",
                    "$-0.00",
                    ys::Completeness::Complete,
                    item,
                )?,
            ],
        )?,
    })
    .validate();
    let ys::ContractOutcome::Evaluated {
        records, issues, ..
    } = outcome
    else {
        return Err("expected evaluated negative-zero outcome".into());
    };
    assert_eq!(records.len(), 0);
    assert_eq!(issues.len(), 1);
    let issue = issues.first().ok_or("missing negative-zero record issue")?;
    assert_eq!(issue.fields.len(), 1);
    let field = issue
        .fields
        .first()
        .ok_or("missing negative-zero field issue")?;
    assert_eq!(field.field.as_str(), "price");
    assert!(matches!(
        field.kind,
        ys::FieldIssueKind::SemanticValidationFailed {
            code: ys::ValidationCode::NegativeMoney,
        }
    ));
    assert_eq!(field.evidence.len(), 1);
    assert!(matches!(
        field.evidence.first().map(ys::Finding::value),
        Some(ys::ProjectedValue::Text(value)) if value == "$-0.00"
    ));
    Ok(())
}
