#![allow(clippy::panic_in_result_fn)] // Conformance tests use direct assertions.

use std::{collections::BTreeMap, error::Error, io};

use yosoi_documents::{
    ByteRange, DecodedTextCoordinate, Document, LocateOutcome, NativeCoordinate, Plan,
    ProjectedValue, TextRange, output, regex,
};

fn text(source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::text(
        "decoded-text-optimization.txt",
        source.as_bytes().to_vec(),
    )?)
}

fn matched(outcome: &LocateOutcome) -> Result<&[yosoi_documents::Finding], Box<dyn Error>> {
    match outcome {
        LocateOutcome::Matched { result } => Ok(result.findings()),
        other => Err(io::Error::other(format!("expected matched outcome, got {other:?}")).into()),
    }
}

fn coordinate(finding: &yosoi_documents::Finding) -> Result<DecodedTextCoordinate, Box<dyn Error>> {
    match finding.coordinate() {
        NativeCoordinate::DecodedText(coordinate) => Ok(*coordinate),
        other => {
            Err(io::Error::other(format!("expected decoded-text coordinate, got {other:?}")).into())
        }
    }
}

#[test]
fn unicode_optional_captures_preserve_bytes_scalars_and_absence() -> Result<(), Box<dyn Error>> {
    let document = text("🙂é12 34")?;
    let plan = Plan::new([output(
        "numbers",
        regex(r"(?P<prefix>é)?(?P<number>\d+)")?.captures(["prefix", "number"])?,
    )?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 2);
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::value),
        Some(&ProjectedValue::TextWithCaptures {
            text: "é12".to_owned(),
            captures: BTreeMap::from([
                ("number".to_owned(), "12".to_owned()),
                ("prefix".to_owned(), "é".to_owned()),
            ]),
        })
    );
    let first = findings
        .first()
        .ok_or_else(|| io::Error::other("first regex finding is missing"))?;
    assert_eq!(coordinate(first)?.byte_range(), ByteRange::try_new(4, 8)?);
    assert_eq!(coordinate(first)?.scalar_range(), TextRange::try_new(1, 4)?);

    assert_eq!(
        findings.get(1).map(yosoi_documents::Finding::value),
        Some(&ProjectedValue::TextWithCaptures {
            text: "34".to_owned(),
            captures: BTreeMap::from([("number".to_owned(), "34".to_owned())]),
        })
    );
    let second = findings
        .get(1)
        .ok_or_else(|| io::Error::other("second regex finding is missing"))?;
    assert_eq!(coordinate(second)?.byte_range(), ByteRange::try_new(9, 11)?);
    assert_eq!(
        coordinate(second)?.scalar_range(),
        TextRange::try_new(5, 7)?
    );
    Ok(())
}

#[test]
fn unicode_zero_width_captures_keep_empty_half_open_coordinates() -> Result<(), Box<dyn Error>> {
    let document = text("é")?;
    let plan = Plan::new([output(
        "boundaries",
        regex(r"(?P<empty>\b)")?.captures(["empty"])?,
    )?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 2);
    let first = findings
        .first()
        .ok_or_else(|| io::Error::other("first boundary is missing"))?;
    assert_eq!(coordinate(first)?.byte_range(), ByteRange::try_new(0, 0)?);
    assert_eq!(coordinate(first)?.scalar_range(), TextRange::try_new(0, 0)?);
    assert_eq!(
        first.value(),
        &ProjectedValue::TextWithCaptures {
            text: String::new(),
            captures: BTreeMap::from([("empty".to_owned(), String::new())]),
        }
    );

    let second = findings
        .get(1)
        .ok_or_else(|| io::Error::other("second boundary is missing"))?;
    assert_eq!(coordinate(second)?.byte_range(), ByteRange::try_new(2, 2)?);
    assert_eq!(
        coordinate(second)?.scalar_range(),
        TextRange::try_new(1, 1)?
    );
    assert_eq!(second.value(), first.value());
    Ok(())
}

#[test]
fn parsed_text_and_compiled_plan_can_be_reused_without_observable_drift()
-> Result<(), Box<dyn Error>> {
    let document = text("α-10 β-20")?;
    let plan = Plan::new([output(
        "pairs",
        regex(r"(?P<label>\p{Greek})-(?P<number>\d+)")?.captures(["label", "number"])?,
    )?])?;
    let parsed = document.parse()?;

    let first = parsed.locate(&plan);
    let second = parsed.locate(&plan);
    assert_eq!(first, second);

    let round_trip_plan: Plan = serde_json::from_value(serde_json::to_value(&plan)?)?;
    assert_eq!(parsed.locate(&round_trip_plan), first);
    assert_eq!(
        matched(&first)?
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::TextWithCaptures {
                text: "α-10".to_owned(),
                captures: BTreeMap::from([
                    ("label".to_owned(), "α".to_owned()),
                    ("number".to_owned(), "10".to_owned()),
                ]),
            },
            ProjectedValue::TextWithCaptures {
                text: "β-20".to_owned(),
                captures: BTreeMap::from([
                    ("label".to_owned(), "β".to_owned()),
                    ("number".to_owned(), "20".to_owned()),
                ]),
            },
        ]
    );
    Ok(())
}
