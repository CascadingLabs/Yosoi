use super::*;

#[test]
fn repeated_candidates_have_direct_fields_and_preserve_evidence() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let first_region = region("product", 0, "/products/0")?;
    let second_region = region("product", 1, "/products/1")?;
    let findings = vec![
        finding(
            &document,
            "name",
            0,
            "/products/0/name",
            "Tea",
            ys::Completeness::Complete,
            Some(first_region.clone()),
        )?,
        finding(
            &document,
            "price",
            1,
            "/products/0/price",
            "$4.50",
            ys::Completeness::Complete,
            Some(first_region.clone()),
        )?,
        finding(
            &document,
            "categories",
            2,
            "/products/0/categories/0",
            "drinks",
            ys::Completeness::Partial {
                reason_code: "fixture_partial".into(),
                lost_items: None,
            },
            Some(first_region.clone()),
        )?,
        finding(
            &document,
            "categories",
            3,
            "/products/0/categories/1",
            "pantry",
            ys::Completeness::Complete,
            Some(first_region.clone()),
        )?,
        finding(
            &document,
            "name",
            4,
            "/products/1/name",
            "Coffee",
            ys::Completeness::Complete,
            Some(second_region.clone()),
        )?,
        finding(
            &document,
            "price",
            5,
            "/products/1/price",
            "$8.25",
            ys::Completeness::Complete,
            Some(second_region),
        )?,
    ];
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document.clone(), findings)?,
    };
    let extracted = Product::extract(&located);
    assert_eq!(extracted.candidates().len(), 2);
    assert_eq!(extracted.diagnostics().len(), 0);

    let first = extracted
        .candidates()
        .first()
        .ok_or("missing first product")?;
    assert_eq!(first.name.values().len(), 1);
    assert_eq!(first.price.values().len(), 1);
    assert!(first.subtitle.is_absent());
    assert_eq!(first.categories.values().len(), 2);
    assert_eq!(first.categories.evidence().len(), 2);
    assert!(matches!(
        first
            .categories
            .evidence()
            .first()
            .map(ys::Finding::completeness),
        Some(ys::Completeness::Partial { .. })
    ));
    let name = first
        .name
        .evidence()
        .first()
        .ok_or("missing name evidence")?;
    assert_eq!(name.document_id(), &document);
    assert_eq!(name.output_id().as_str(), "name");
    assert_eq!(name.order(), 0);
    assert_eq!(
        name.coordinate(),
        &ys::NativeCoordinate::Json(ys::JsonCoordinate::try_new("/products/0/name")?)
    );
    assert_eq!(name.value(), &ys::ProjectedValue::Text("Tea".into()));
    assert_eq!(name.completeness(), &ys::Completeness::Complete);
    assert_eq!(name.parent_region(), Some(&first_region));

    let category_values = first
        .categories
        .values()
        .filter_map(|value| match value {
            ys::ProjectedValue::Text(text) => Some(text.as_str()),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(category_values, vec!["drinks", "pantry"]);

    let product_names = extracted
        .candidates()
        .iter()
        .filter_map(|product| product.name.values().next())
        .filter_map(|value| match value {
            ys::ProjectedValue::Text(text) => Some(text.as_str()),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(product_names, vec!["Tea", "Coffee"]);
    Ok(())
}

#[test]
fn page_contract_uses_only_page_findings() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("page")?;
    let findings = vec![finding(
        &document,
        "title",
        0,
        "/title",
        "Catalog",
        ys::Completeness::Complete,
        None,
    )?];
    let extracted = PageSummary::extract(&ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    });
    let candidate = extracted
        .candidates()
        .first()
        .ok_or("missing page candidate")?;
    assert_eq!(candidate.title.values().len(), 1);
    assert!(candidate.description.is_absent());
    Ok(())
}

#[test]
fn exact_lineage_not_ordinal_groups_records() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let findings = vec![
        finding(
            &document,
            "name",
            0,
            "/left/name",
            "Left",
            ys::Completeness::Complete,
            Some(region("product", 0, "/left")?),
        )?,
        finding(
            &document,
            "name",
            1,
            "/right/name",
            "Right",
            ys::Completeness::Complete,
            Some(region("product", 0, "/right")?),
        )?,
    ];
    let extracted = Product::extract(&ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    });
    assert_eq!(extracted.candidates().len(), 2);
    Ok(())
}

#[test]
fn unrelated_outputs_are_ignored_and_wrong_lineage_is_diagnosed() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let findings = vec![
        finding(
            &document,
            "unrelated",
            0,
            "/unrelated",
            "ignored",
            ys::Completeness::Complete,
            None,
        )?,
        finding(
            &document,
            "name",
            1,
            "/offers/0/name",
            "Tea",
            ys::Completeness::Complete,
            Some(region("offer", 0, "/offers/0")?),
        )?,
    ];
    let extracted = Product::extract(&ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    });
    assert_eq!(extracted.candidates().len(), 0);
    assert!(matches!(
        extracted.diagnostics(),
        [ys::ExtractionDiagnostic::IncompatibleLineage { output }]
            if output.as_str() == "name"
    ));
    Ok(())
}

#[test]
fn locator_terminal_states_remain_distinct() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("sentinel-document-secret")?;
    let no_match = yosoi_engine::extract_contract::<Product>(&ys::LocateOutcome::NoMatch {
        document_id: document.clone(),
    });
    assert!(matches!(
        &no_match,
        yosoi_engine::ExtractorOutput::NoMatch { document_id } if document_id == &document
    ));
    assert!(!format!("{no_match:?}").contains("sentinel-document-secret"));

    let completeness = ys::IncompleteEvidence::Unknown {
        reason_code: "sentinel-completeness-secret".into(),
    };
    let indeterminate =
        yosoi_engine::extract_contract::<Product>(&ys::LocateOutcome::Indeterminate {
            document_id: document.clone(),
            completeness: completeness.clone(),
            reason_code: "sentinel-reason-secret".into(),
        });
    assert!(matches!(
        &indeterminate,
        yosoi_engine::ExtractorOutput::Indeterminate {
            document_id,
            completeness: actual,
            reason_code,
        } if document_id == &document
            && actual == &completeness
            && reason_code == "sentinel-reason-secret"
    ));
    let debug = format!("{indeterminate:?}");
    assert!(!debug.contains("sentinel-completeness-secret"));
    assert!(!debug.contains("sentinel-reason-secret"));
    assert!(!debug.contains("sentinel-document-secret"));

    let failure = ys::LocateFailure::ParseFailed {
        code: "sentinel-failure-secret".into(),
    };
    let failed = yosoi_engine::extract_contract::<Product>(&ys::LocateOutcome::Failed {
        failure: failure.clone(),
    });
    assert!(matches!(
        &failed,
        yosoi_engine::ExtractorOutput::LocateFailed { failure: actual } if actual == &failure
    ));
    assert!(!format!("{failed:?}").contains("sentinel-failure-secret"));
    Ok(())
}

#[test]
fn unrelated_outputs_do_not_consume_matching_finding_bound() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let item = region("product", 0, "/products/0")?;
    let findings = vec![
        finding(
            &document,
            "unrelated_a",
            0,
            "/unrelated/a",
            "ignored",
            ys::Completeness::Complete,
            None,
        )?,
        finding(
            &document,
            "unrelated_b",
            1,
            "/unrelated/b",
            "ignored",
            ys::Completeness::Complete,
            None,
        )?,
        finding(
            &document,
            "name",
            2,
            "/products/0/name",
            "Tea",
            ys::Completeness::Complete,
            Some(item),
        )?,
    ];
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    };
    let extracted = yosoi_engine::extract_contract_with_limits::<Product>(
        &located,
        yosoi_engine::ExtractionLimits {
            max_scanned_findings: 3,
            ..yosoi_engine::ExtractionLimits::uniform(1)
        },
    );
    assert_eq!(extracted.candidates().len(), 1);
    assert_eq!(extracted.diagnostics().len(), 0);
    Ok(())
}

#[test]
fn unrelated_outputs_still_consume_the_scan_bound() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let findings = (0_u64..3)
        .map(|order| {
            finding(
                &document,
                &format!("unrelated_{order}"),
                order,
                &format!("/unrelated/{order}"),
                "ignored",
                ys::Completeness::Complete,
                None,
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    };
    let limits = yosoi_engine::ExtractionLimits {
        max_scanned_findings: 2,
        ..yosoi_engine::ExtractionLimits::uniform(10)
    };
    super::limits::assert_limit(&located, limits, ys::ExtractionLimit::ScannedFindings, 2, 3)
}

#[test]
fn unrelated_regions_still_consume_the_region_scan_bound() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("catalog")?;
    let regions = (0_u64..3)
        .map(|ordinal| region("offer", ordinal, &format!("/offers/{ordinal}")))
        .collect::<Result<Vec<_>, _>>()?;
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new_with_regions(document, regions, Vec::new())?,
    };
    let limits = yosoi_engine::ExtractionLimits {
        max_scanned_regions: 2,
        ..yosoi_engine::ExtractionLimits::uniform(10)
    };
    super::limits::assert_limit(&located, limits, ys::ExtractionLimit::ScannedRegions, 2, 3)
}
