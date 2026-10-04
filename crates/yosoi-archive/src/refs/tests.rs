use std::error::Error;

use serde::de::DeserializeOwned;

use super::*;

#[test]
fn reference_text_and_serde_round_trip() -> Result<(), Box<dyn Error>> {
    assert_round_trip(&PolicyArchiveRef::new_current())?;
    assert_round_trip(&PlanArchiveRef::new_current())?;
    assert_round_trip(&ContractSchemaArchiveRef::new_current())?;
    assert_round_trip(&RequestRunArchiveRef::new_current())?;
    assert_round_trip(&DocumentArchiveRef::new_current())?;
    assert_round_trip(&EvaluationRunArchiveRef::new_current())?;
    assert_round_trip(&LocatorRunArchiveRef::new_current())?;
    assert_round_trip(&ContractRunArchiveRef::new_current())?;
    let capture_id: CaptureId = "123e4567-e89b-42d3-a456-426614174002".parse()?;
    assert_round_trip(&CaptureArchiveRef::new_current(capture_id))
}

fn assert_round_trip<R>(reference: &R) -> Result<(), Box<dyn Error>>
where
    R: Display + Eq + FromStr + Serialize + DeserializeOwned,
    R::Err: Error + 'static,
{
    let text = reference.to_string();
    if &text.parse::<R>()? != reference {
        return Err("text reference did not round trip".into());
    }
    let json = serde_json::to_string(reference)?;
    if &serde_json::from_str::<R>(&json)? != reference {
        return Err("Serde reference did not round trip".into());
    }
    Ok(())
}

#[test]
fn reference_kinds_cannot_be_reinterpreted() {
    let plan = PlanArchiveRef::new_current();
    assert!(matches!(
        plan.to_string().parse::<ContractSchemaArchiveRef>(),
        Err(ArchiveRefError::WrongKind {
            expected: "contract-schema",
            ..
        })
    ));
    assert!(matches!(
        "capture:v1:record-01".parse::<PolicyArchiveRef>(),
        Err(ArchiveRefError::WrongKind { .. })
    ));
}

#[test]
fn uuid_references_reject_noncanonical_or_non_rfc_keys() {
    assert_eq!(
        "policy:v1:../escape".parse::<PolicyArchiveRef>(),
        Err(ArchiveRefError::InvalidUuidKey { kind: "policy" })
    );
    assert_eq!(
        "policy:v01:123e4567-e89b-42d3-a456-426614174000".parse::<PolicyArchiveRef>(),
        Err(ArchiveRefError::InvalidFormat)
    );
    assert_eq!(
        "policy:v1:123e4567-e89b-42d3-0456-426614174000".parse::<PolicyArchiveRef>(),
        Err(ArchiveRefError::InvalidUuidKey { kind: "policy" })
    );
}
