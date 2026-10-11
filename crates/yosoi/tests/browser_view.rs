use std::error::Error;

use yosoi::automation_record::Observation;
use yosoi::flow::Condition;
use yosoi::view::{View, ViewError};

fn observation() -> Observation {
    Observation {
        id: "capture-1".to_owned(),
        session_id: "session-1".to_owned(),
        tab_id: "tab-1".to_owned(),
        document_epoch: 3,
        html: Some(
            "<!doctype html><html><body><main><button>One</button><button>Two</button></main></body></html>"
                .to_owned(),
        ),
        url: Some("https://example.test/".to_owned()),
        screenshot: None,
    }
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report offline View contract failures."
)]
fn view_pages_are_bounded_and_cursors_bind_to_the_capture() -> Result<(), Box<dyn Error>> {
    let capture = observation();
    let first = View::from_observation(&capture, 1)?;
    assert_eq!(first.rows().len(), 1);
    assert_eq!(first.page_size(), 1);
    assert!(first.total_rows() > 1);
    let cursor = first
        .next_cursor()
        .ok_or("expected a continuation cursor")?;
    let second = View::continue_from(&capture, cursor)?;
    assert_eq!(second.rows().len(), 1);
    let first_ordinal = first
        .rows()
        .first()
        .ok_or("first page should contain one row")?
        .ordinal();
    let second_ordinal = second
        .rows()
        .first()
        .ok_or("second page should contain one row")?
        .ordinal();
    assert!(second_ordinal > first_ordinal);

    let mut foreign = capture.clone();
    foreign.tab_id = "tab-2".to_owned();
    assert!(matches!(
        View::continue_from(&foreign, cursor),
        Err(ViewError::ForeignCursor)
    ));

    let mut stale = capture;
    stale.document_epoch += 1;
    assert!(matches!(
        View::continue_from(&stale, cursor),
        Err(ViewError::StaleCursor)
    ));
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report offline assertion contract failures."
)]
fn offline_selector_assertions_use_captured_html_only() -> Result<(), Box<dyn Error>> {
    let capture = observation();
    let view = View::from_observation(&capture, 10)?;
    assert!(view.verify_condition(
        &capture,
        &Condition::Exists {
            selector: "button".to_owned(),
        },
    )?);
    assert!(view.verify_condition(
        &capture,
        &Condition::CountAtLeast {
            selector: "button".to_owned(),
            count: 2,
        },
    )?);
    assert!(!view.verify_condition(
        &capture,
        &Condition::CountAtLeast {
            selector: "button".to_owned(),
            count: 3,
        },
    )?);
    assert!(matches!(
        view.verify_condition(
            &capture,
            &Condition::Visible {
                selector: "button".to_owned(),
            },
        ),
        Err(ViewError::UnsupportedCondition { kind: "visible" })
    ));

    let mut changed = capture;
    changed.html = Some("<p>Changed under the same capture identity</p>".to_owned());
    assert!(matches!(
        view.verify_condition(
            &changed,
            &Condition::Exists {
                selector: "p".to_owned(),
            },
        ),
        Err(ViewError::StaleObservation)
    ));
    Ok(())
}

#[test]

fn view_reports_html_unavailable_when_capture_does_not_retain_it() {
    let mut capture = observation();
    capture.html = None;
    assert!(matches!(
        View::from_observation(&capture, 10),
        Err(ViewError::HtmlUnavailable)
    ));
}
