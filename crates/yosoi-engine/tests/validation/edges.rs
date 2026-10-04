use super::*;

#[test]
fn projected_value_and_cardinality_edge_matrix_is_explicit() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("edge-catalog")?;
    let captures = BTreeMap::from([("label".into(), "Captured".into())]);
    let findings = vec![
        projected_finding(
            &document,
            "name",
            0,
            "/0/name",
            ys::ProjectedValue::TextWithCaptures {
                text: "Captured".into(),
                captures,
            },
            region(0)?,
        )?,
        finding(
            &document,
            "price",
            1,
            "/0/price",
            "$1.00",
            ys::Completeness::Complete,
            region(0)?,
        )?,
        projected_finding(
            &document,
            "name",
            2,
            "/1/name",
            ys::ProjectedValue::Json(serde_json::json!({ "name": "unsupported" })),
            region(1)?,
        )?,
        finding(
            &document,
            "price",
            3,
            "/1/price",
            "$2.00",
            ys::Completeness::Complete,
            region(1)?,
        )?,
        finding(
            &document,
            "name",
            4,
            "/2/name",
            "Optional excess",
            ys::Completeness::Complete,
            region(2)?,
        )?,
        finding(
            &document,
            "price",
            5,
            "/2/price",
            "$3.00",
            ys::Completeness::Complete,
            region(2)?,
        )?,
        finding(
            &document,
            "subtitle",
            6,
            "/2/subtitle/0",
            "First",
            ys::Completeness::Complete,
            region(2)?,
        )?,
        finding(
            &document,
            "subtitle",
            7,
            "/2/subtitle/1",
            "Second",
            ys::Completeness::Complete,
            region(2)?,
        )?,
        finding(
            &document,
            "name",
            8,
            "/3/name",
            "Malformed list",
            ys::Completeness::Complete,
            region(3)?,
        )?,
        finding(
            &document,
            "price",
            9,
            "/3/price",
            "$4.00",
            ys::Completeness::Complete,
            region(3)?,
        )?,
        finding(
            &document,
            "categories",
            10,
            "/3/categories/0",
            "valid",
            ys::Completeness::Complete,
            region(3)?,
        )?,
        projected_finding(
            &document,
            "categories",
            11,
            "/3/categories/1",
            ys::ProjectedValue::Json(serde_json::json!("invalid")),
            region(3)?,
        )?,
        finding(
            &document,
            "name",
            12,
            "/4/name",
            "Whitespace money",
            ys::Completeness::Complete,
            region(4)?,
        )?,
        finding(
            &document,
            "price",
            13,
            "/4/price",
            " $5.00",
            ys::Completeness::Complete,
            region(4)?,
        )?,
        finding(
            &document,
            "name",
            14,
            "/5/name",
            "Overflow money",
            ys::Completeness::Complete,
            region(5)?,
        )?,
        finding(
            &document,
            "price",
            15,
            "/5/price",
            "$92233720368547758.08",
            ys::Completeness::Complete,
            region(5)?,
        )?,
    ];
    let outcome = Product::extract(&ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    })
    .validate();
    let ys::ContractOutcome::Evaluated {
        records, issues, ..
    } = outcome
    else {
        return Err("expected evaluated outcome".into());
    };
    assert_eq!(records.len(), 1);
    assert_eq!(
        records.first().map(|record| record.value.name.as_str()),
        Some("Captured")
    );
    assert_eq!(issues.len(), 5);
    assert!(matches!(
        issues
            .first()
            .and_then(|issue| issue.fields.first())
            .map(|field| &field.kind),
        Some(ys::FieldIssueKind::UnsupportedProjectedValue)
    ));
    assert!(matches!(
        issues
            .get(1)
            .and_then(|issue| issue.fields.first())
            .map(|field| &field.kind),
        Some(ys::FieldIssueKind::ExcessCandidates { observed: 2 })
    ));
    assert!(matches!(
        issues
            .get(2)
            .and_then(|issue| issue.fields.first())
            .map(|field| &field.kind),
        Some(ys::FieldIssueKind::UnsupportedProjectedValue)
    ));
    assert!(issues.iter().skip(3).all(|issue| matches!(
        issue.fields.first().map(|field| &field.kind),
        Some(ys::FieldIssueKind::ConversionFailed)
    )));
    assert_eq!(
        issues
            .get(2)
            .map(|issue| issue.candidate.categories.evidence().len()),
        Some(2)
    );
    Ok(())
}

#[test]
fn issue_provenance_is_precise_and_budgeted_before_cloning() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("precise-provenance")?;
    let item = region(0)?;
    let invalid = projected_finding(
        &document,
        "categories",
        3,
        "/0/categories/1",
        ys::ProjectedValue::Json(serde_json::json!("invalid")),
        item.clone(),
    )?;
    let category_findings = vec![
        finding(
            &document,
            "categories",
            2,
            "/0/categories/0",
            "first",
            ys::Completeness::Complete,
            item.clone(),
        )?,
        invalid.clone(),
        finding(
            &document,
            "categories",
            4,
            "/0/categories/2",
            "last",
            ys::Completeness::Complete,
            item.clone(),
        )?,
    ];
    let mut findings = vec![
        finding(
            &document,
            "name",
            0,
            "/0/name",
            "Tea",
            ys::Completeness::Complete,
            item.clone(),
        )?,
        finding(
            &document,
            "price",
            1,
            "/0/price",
            "$1.00",
            ys::Completeness::Complete,
            item,
        )?,
    ];
    findings.extend(category_findings.clone());
    let located = ys::LocateOutcome::Matched {
        result: ys::LocateResult::try_new(document, findings)?,
    };

    let outcome = Product::extract(&located).validate_with_limits(yosoi_engine::ValidationLimits {
        max_retained_provenance: 6,
        ..yosoi_engine::ValidationLimits::default()
    });
    let ys::ContractOutcome::Evaluated { issues, .. } = outcome else {
        return Err("expected evaluated outcome".into());
    };
    let issue = issues.first().ok_or("missing record issue")?;
    assert_eq!(issue.candidate.categories.evidence(), category_findings);
    assert_eq!(issue.fields.len(), 1);
    assert_eq!(
        issue.fields.first().map(|field| field.evidence.as_slice()),
        Some([invalid].as_slice())
    );

    assert!(matches!(
        Product::extract(&located).validate_with_limits(yosoi_engine::ValidationLimits {
            max_retained_provenance: 5,
            ..yosoi_engine::ValidationLimits::default()
        }),
        ys::ContractOutcome::ValidationRejected {
            failure: ys::ValidationFailure::ProvenanceLimitExceeded {
                maximum: 5,
                observed: 6,
            }
        }
    ));
    Ok(())
}
