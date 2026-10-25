use super::*;

#[test]
fn explicit_validation_builds_simple_products_and_retains_candidates() -> Result<(), Box<dyn Error>>
{
    let extracted = Product::extract(&valid_located()?);
    assert_extracted_type(&extracted);
    let outcome = extracted.validate();
    let ys::ContractOutcome::Evaluated {
        records,
        issues,
        extraction_diagnostics,
        ..
    } = outcome
    else {
        return Err("expected evaluated outcome".into());
    };
    assert_eq!(issues.len(), 0);
    assert_eq!(extraction_diagnostics.len(), 0);
    assert_eq!(records.len(), 2);

    let first = records.first().ok_or("missing first product")?;
    assert_eq!(first.value.name, "Tea");
    assert_eq!(first.value.price, "$4.50");
    assert_eq!(first.value.subtitle, None);
    assert_eq!(first.value.categories, vec!["drinks", "pantry"]);
    assert_eq!(first.candidate.price.evidence().len(), 1);

    let second = records.get(1).ok_or("missing second product")?;
    assert_eq!(second.value.name, "Coffee");
    assert_eq!(second.value.subtitle.as_deref(), Some("Whole bean"));
    assert_eq!(second.value.categories, Vec::<String>::new());
    Ok(())
}

#[test]
fn invalid_siblings_report_distinct_runtime_issues() -> Result<(), Box<dyn Error>> {
    let document = ys::DocumentId::try_new("invalid-catalog")?;
    let valid = region(0)?;
    let missing = region(1)?;
    let excess = region(2)?;
    let unparsed = region(3)?;
    let negative = region(4)?;
    let incomplete = region(5)?;
    let findings = vec![
        finding(
            &document,
            "name",
            0,
            "/0/name",
            "Valid",
            ys::Completeness::Complete,
            valid.clone(),
        )?,
        finding(
            &document,
            "price",
            1,
            "/0/price",
            "$1.00",
            ys::Completeness::Complete,
            valid,
        )?,
        finding(
            &document,
            "name",
            2,
            "/1/name",
            "Missing price",
            ys::Completeness::Complete,
            missing,
        )?,
        finding(
            &document,
            "name",
            3,
            "/2/name/0",
            "First",
            ys::Completeness::Complete,
            excess.clone(),
        )?,
        finding(
            &document,
            "name",
            4,
            "/2/name/1",
            "Second",
            ys::Completeness::Complete,
            excess.clone(),
        )?,
        finding(
            &document,
            "price",
            5,
            "/2/price",
            "$2.00",
            ys::Completeness::Complete,
            excess,
        )?,
        finding(
            &document,
            "name",
            6,
            "/3/name",
            "Unparsed price",
            ys::Completeness::Complete,
            unparsed.clone(),
        )?,
        finding(
            &document,
            "price",
            7,
            "/3/price",
            "price on request",
            ys::Completeness::Complete,
            unparsed,
        )?,
        finding(
            &document,
            "name",
            8,
            "/4/name",
            "Negative",
            ys::Completeness::Complete,
            negative.clone(),
        )?,
        finding(
            &document,
            "price",
            9,
            "/4/price",
            "$-1.00",
            ys::Completeness::Complete,
            negative,
        )?,
        finding(
            &document,
            "name",
            10,
            "/5/name",
            "Partial",
            ys::Completeness::Partial {
                reason_code: "truncated".into(),
                lost_items: None,
            },
            incomplete.clone(),
        )?,
        finding(
            &document,
            "price",
            11,
            "/5/price",
            "$5.00",
            ys::Completeness::Complete,
            incomplete,
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
    assert_eq!(records.len(), 3);
    assert_eq!(issues.len(), 3);
    let kinds = issues
        .iter()
        .flat_map(|issue| issue.fields.iter().map(|field| &field.kind))
        .collect::<Vec<_>>();
    assert!(kinds.contains(&&ys::FieldIssueKind::MissingRequired));
    assert!(
        kinds
            .iter()
            .any(|kind| matches!(kind, ys::FieldIssueKind::ExcessCandidates { observed: 2 }))
    );
    assert!(kinds.contains(&&ys::FieldIssueKind::IncompleteEvidence));
    assert!(issues.iter().flat_map(|issue| &issue.fields).all(|field| {
        !field.evidence.is_empty() || field.kind == ys::FieldIssueKind::MissingRequired
    }));
    let debug = format!("{issues:?}");
    assert!(!debug.contains("price on request"));
    assert!(!debug.contains("Partial"));

    let ordered = issues
        .iter()
        .flat_map(|issue| issue.fields.iter())
        .map(|field| {
            let kind = match field.kind {
                ys::FieldIssueKind::MissingRequired => "missing",
                ys::FieldIssueKind::ExcessCandidates { .. } => "excess",
                ys::FieldIssueKind::IncompleteEvidence => "incomplete",
                ys::FieldIssueKind::UnsupportedProjectedValue => "unsupported",
                ys::FieldIssueKind::ConversionFailed => "conversion",
            };
            (field.field.as_str(), kind)
        })
        .collect::<Vec<_>>();
    assert_eq!(
        ordered,
        vec![
            ("price", "missing"),
            ("name", "excess"),
            ("name", "incomplete"),
        ]
    );
    let missing_price = issues.first().ok_or("missing missing-price issue")?;
    assert_eq!(missing_price.candidate.name.evidence().len(), 1);
    assert!(missing_price.candidate.price.is_absent());
    Ok(())
}
