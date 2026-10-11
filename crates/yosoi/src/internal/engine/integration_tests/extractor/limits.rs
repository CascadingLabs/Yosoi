use super::*;
use crate::internal::engine as internal_engine;

fn located_with_regions(count: u64) -> Result<ys::LocateOutcome, Box<dyn Error>> {
    let document = ys::DocumentId::try_new(format!("catalog-{count}"))?;
    let findings = (0_u64..count)
        .map(|ordinal| {
            finding(
                &document,
                "name",
                ordinal,
                &format!("/products/{ordinal}/name"),
                "bounded",
                ys::Completeness::Complete,
                Some(region("product", ordinal, &format!("/products/{ordinal}"))?),
            )
        })
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?;
    Ok(ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    })
}

#[test]
fn default_extraction_bounds_distinct_regions() -> Result<(), Box<dyn Error>> {
    let exact = Product::extract(&located_with_regions(64)?);
    assert_eq!(exact.candidates().len(), 64);
    assert_eq!(exact.diagnostics().len(), 0);

    let located = located_with_regions(65)?;
    assert!(matches!(
        Product::extract(&located).validate(),
        ys::ContractOutcome::ExtractionRejected {
            failure: ys::ExtractionFailure::LimitExceeded {
                limit: ys::ExtractionLimit::Candidates,
                maximum: 64,
                observed: 65,
            }
        }
    ));
    Ok(())
}

#[test]
fn cross_modality_projected_values_remain_unconverted() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let item = region("product", 0, "/products/0")?;
    let finding = ys::Finding::try_new(
        document.clone(),
        ys::OutputId::try_new("name")?,
        0,
        ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new("/products/0/name")?),
        ys::ProjectedValue::Json(serde_json::json!({ "native": true })),
        ys::Completeness::Complete,
        Some(item),
    )?;
    let extracted = Product::extract(&ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, vec![finding])?,
    });
    let product = extracted.candidates().first().ok_or("missing product")?;
    assert!(matches!(
        product.name.values().next(),
        Some(ys::ProjectedValue::Json(value)) if value == &serde_json::json!({ "native": true })
    ));
    Ok(())
}

#[test]
fn extraction_rejects_each_bounded_dimension() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let first = region("product", 0, "/products/0")?;
    let second = region("product", 1, "/products/1")?;
    let findings = vec![
        finding(
            &document,
            "categories",
            0,
            "/products/0/categories/0",
            "drinks",
            ys::Completeness::Complete,
            Some(first.clone()),
        )?,
        finding(
            &document,
            "categories",
            1,
            "/products/0/categories/1",
            "pantry",
            ys::Completeness::Complete,
            Some(first),
        )?,
        finding(
            &document,
            "name",
            2,
            "/products/1/name",
            "Coffee",
            ys::Completeness::Complete,
            Some(second),
        )?,
    ];
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    };
    let generous = internal_engine::ExtractionLimits::uniform(10);

    let scanned_limit = internal_engine::ExtractionLimits {
        max_scanned_findings: 2,
        ..generous
    };
    assert_limit(
        &located,
        scanned_limit,
        ys::ExtractionLimit::ScannedFindings,
        2,
        3,
    )?;

    let value_limit = internal_engine::ExtractionLimits {
        max_values_per_field: 1,
        ..generous
    };
    assert_limit(
        &located,
        value_limit,
        ys::ExtractionLimit::ValuesPerField,
        1,
        2,
    )?;

    let candidate_limit = internal_engine::ExtractionLimits {
        max_candidates: 1,
        ..generous
    };
    assert_limit(
        &located,
        candidate_limit,
        ys::ExtractionLimit::Candidates,
        1,
        2,
    )?;

    let evidence_limit = internal_engine::ExtractionLimits {
        max_retained_evidence: 1,
        ..generous
    };
    assert_limit(
        &located,
        evidence_limit,
        ys::ExtractionLimit::RetainedEvidence,
        1,
        2,
    )?;

    let matching_limit = internal_engine::ExtractionLimits {
        max_matching_findings: 1,
        ..generous
    };
    assert_limit(
        &located,
        matching_limit,
        ys::ExtractionLimit::MatchingFindings,
        1,
        2,
    )?;

    let wrong_lineage = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(
            ys::DocumentId::try_new("wrong-lineage")?,
            vec![
                finding(
                    &ys::DocumentId::try_new("wrong-lineage")?,
                    "name",
                    0,
                    "/offers/0/name",
                    "Tea",
                    ys::Completeness::Complete,
                    Some(region("offer", 0, "/offers/0")?),
                )?,
                finding(
                    &ys::DocumentId::try_new("wrong-lineage")?,
                    "price",
                    1,
                    "/offers/0/price",
                    "$4.50",
                    ys::Completeness::Complete,
                    Some(region("offer", 0, "/offers/0")?),
                )?,
            ],
        )?,
    };
    let diagnostic_limit = internal_engine::ExtractionLimits {
        max_diagnostics: 1,
        ..generous
    };
    assert_limit(
        &wrong_lineage,
        diagnostic_limit,
        ys::ExtractionLimit::Diagnostics,
        1,
        2,
    )?;
    Ok(())
}

pub fn assert_limit(
    located: &ys::LocateOutcome,
    limits: internal_engine::ExtractionLimits,
    expected: ys::ExtractionLimit,
    expected_maximum: u64,
    expected_observed: u64,
) -> Result<(), Box<dyn Error>> {
    let extracted = internal_engine::extract_contract_with_limits::<Product>(located, limits);
    if matches!(
        extracted,
        internal_engine::ExtractorOutput::Rejected {
            failure: ys::ExtractionFailure::LimitExceeded {
                limit,
                maximum,
                observed,
            }
        } if limit == expected
            && maximum == expected_maximum
            && observed == expected_observed
    ) {
        Ok(())
    } else {
        Err(format!(
            "expected {expected:?} extraction limit at {expected_observed}/{expected_maximum}"
        )
        .into())
    }
}

#[test]
fn extraction_rejects_matching_findings_beyond_the_uniform_bound() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let item = region("product", 0, "/products/0")?;
    let findings = vec![
        finding(
            &document,
            "name",
            0,
            "/products/0/name",
            "Tea",
            ys::Completeness::Complete,
            Some(item.clone()),
        )?,
        finding(
            &document,
            "price",
            1,
            "/products/0/price",
            "$4.50",
            ys::Completeness::Complete,
            Some(item),
        )?,
    ];
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    };
    assert!(matches!(
        internal_engine::extract_contract_with_limits::<Product>(
            &located,
            internal_engine::ExtractionLimits {
                max_scanned_findings: 2,
                ..internal_engine::ExtractionLimits::uniform(1)
            },
        ),
        internal_engine::ExtractorOutput::Rejected {
            failure: ys::ExtractionFailure::LimitExceeded {
                limit: ys::ExtractionLimit::MatchingFindings,
                maximum: 1,
                observed: 2,
            }
        }
    ));
    Ok(())
}
