use super::*;

#[test]
fn one_candidate_collects_all_field_issues_in_contract_order() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("multi-error")?;
    let item = region(0)?;
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(
            document.clone(),
            vec![
                finding(
                    &document,
                    "price",
                    0,
                    "/0/price",
                    "$1.00",
                    ys::Completeness::Unknown {
                        reason_code: "partial".into(),
                    },
                    item.clone(),
                )?,
                finding(
                    &document,
                    "subtitle",
                    1,
                    "/0/subtitle/0",
                    "first",
                    ys::Completeness::Complete,
                    item.clone(),
                )?,
                finding(
                    &document,
                    "subtitle",
                    2,
                    "/0/subtitle/1",
                    "second",
                    ys::Completeness::Complete,
                    item.clone(),
                )?,
                projected_finding(
                    &document,
                    "categories",
                    3,
                    "/0/categories/0",
                    ys::ProjectedValue::Json(serde_json::json!("invalid")),
                    item,
                )?,
            ],
        )?,
    };
    let ys::ContractOutcome::Evaluated { issues, .. } = Product::extract(&located).validate()
    else {
        return Err("expected evaluated outcome".into());
    };
    let issue = issues.first().ok_or("missing record issue")?;
    let fields = issue
        .fields
        .iter()
        .map(|field| field.field.as_str())
        .collect::<Vec<_>>();
    assert_eq!(fields, ["name", "price", "subtitle", "categories"]);
    assert_eq!(
        issue.fields.first().map(|field| field.evidence.len()),
        Some(0)
    );
    assert_eq!(
        issue.fields.get(1).map(|field| field.evidence.len()),
        Some(1)
    );
    assert_eq!(
        issue.fields.get(2).map(|field| field.evidence.len()),
        Some(2)
    );
    assert_eq!(
        issue.fields.get(3).map(|field| field.evidence.len()),
        Some(1)
    );
    assert!(matches!(
        Product::extract(&located).validate().require_all(),
        Err(ys::ContractIssues::Rejected {
            record_issues: 1,
            extraction_diagnostics: 0,
        })
    ));
    Ok(())
}

#[test]
fn strict_require_all_is_explicit() -> Result<(), Box<dyn Error>> {
    let products = Product::extract(&valid_located()?)
        .validate()
        .require_all()?;
    assert_eq!(products.len(), 2);

    let document = ys::DocumentId::try_new("missing")?;
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
        Product::extract(&located).validate().require_all(),
        Err(ys::ContractIssues::Rejected {
            record_issues: 1,
            ..
        })
    ));
    assert!(
        Product::extract(&ys::LocateOutcome::NoMatch {
            document_id: ys::DocumentId::try_new("no-match")?,
        })
        .validate()
        .require_all()?
        .is_empty()
    );
    assert!(matches!(
        Product::extract(&ys::LocateOutcome::Indeterminate {
            document_id: ys::DocumentId::try_new("indeterminate")?,
            completeness: ys::IncompleteEvidence::Unknown {
                reason_code: "bounded".into(),
            },
            reason_code: "bounded".into(),
        })
        .validate()
        .require_all(),
        Err(ys::ContractIssues::Indeterminate)
    ));
    assert!(matches!(
        Product::extract(&ys::LocateOutcome::Failed {
            failure: ys::LocateFailure::ParseFailed {
                code: "invalid".into(),
            },
        })
        .validate()
        .require_all(),
        Err(ys::ContractIssues::LocateFailed)
    ));
    assert!(matches!(
        Product::extract_with_limit(&valid_located()?, 0)
            .validate()
            .require_all(),
        Err(ys::ContractIssues::ExtractionRejected)
    ));
    assert!(matches!(
        Product::extract(&valid_located()?)
            .validate_with_limits(yosoi::ValidationLimits {
                max_fields: 3,
                ..yosoi::ValidationLimits::default()
            })
            .require_all(),
        Err(ys::ContractIssues::ValidationRejected)
    ));

    let diagnostic_document = ys::DocumentId::try_new("diagnostic")?;
    let wrong_region = ys::RegionLineage::new(
        ys::RegionId::try_new("offer")?,
        0,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new("/offers/0")?),
    );
    let diagnostic_located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(
            diagnostic_document.clone(),
            vec![finding(
                &diagnostic_document,
                "name",
                0,
                "/offers/0/name",
                "Tea",
                ys::Completeness::Complete,
                wrong_region,
            )?],
        )?,
    };
    assert!(matches!(
        Product::extract(&diagnostic_located)
            .validate()
            .require_all(),
        Err(ys::ContractIssues::Rejected {
            record_issues: 0,
            extraction_diagnostics: 1,
        })
    ));
    Ok(())
}

#[test]
fn validation_preserves_terminal_payloads_but_redacts_debug() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("terminal")?;
    let completeness = ys::IncompleteEvidence::Unknown {
        reason_code: "sentinel-completeness-secret".into(),
    };
    let extracted = Product::extract(&ys::LocateOutcome::Indeterminate {
        document_id: document.clone(),
        completeness: completeness.clone(),
        reason_code: "sentinel-reason-secret".into(),
    });
    let extracted_debug = format!("{extracted:?}");
    assert!(!extracted_debug.contains("terminal"));
    assert!(!extracted_debug.contains("sentinel-completeness-secret"));
    assert!(!extracted_debug.contains("sentinel-reason-secret"));
    let outcome = extracted.validate();
    assert!(matches!(
        &outcome,
        ys::ContractOutcome::Indeterminate {
            document_id,
            completeness: actual,
            reason_code,
        } if document_id == &document && actual == &completeness && reason_code == "sentinel-reason-secret"
    ));
    let debug = format!("{outcome:?}");
    assert!(!debug.contains("sentinel-completeness-secret"));
    assert!(!debug.contains("sentinel-reason-secret"));

    let no_match = Product::extract(&ys::LocateOutcome::NoMatch {
        document_id: document.clone(),
    });
    assert!(!format!("{no_match:?}").contains("terminal"));
    assert!(matches!(
        no_match.validate(),
        ys::ContractOutcome::NoMatch { document_id } if document_id == document
    ));

    let failure = ys::LocateFailure::ParseFailed {
        code: "sentinel-failure-secret".into(),
    };
    let failed = Product::extract(&ys::LocateOutcome::Failed {
        failure: failure.clone(),
    });
    assert!(!format!("{failed:?}").contains("sentinel-failure-secret"));
    let failed = failed.validate();
    assert!(matches!(
        &failed,
        ys::ContractOutcome::LocateFailed { failure: actual } if actual == &failure
    ));
    assert!(!format!("{failed:?}").contains("sentinel-failure-secret"));

    let matched = Product::extract(&valid_located()?);
    assert!(!format!("{matched:?}").contains("catalog"));

    let extracted = Product::extract_with_limit(&valid_located()?, 0);
    assert!(matches!(
        extracted.validate(),
        ys::ContractOutcome::ExtractionRejected {
            failure: ys::ExtractionFailure::LimitExceeded {
                limit: ys::ExtractionLimit::ScannedRegions,
                maximum: 0,
                observed: 2,
            }
        }
    ));
    Ok(())
}
