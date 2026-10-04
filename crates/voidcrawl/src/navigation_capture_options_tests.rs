use super::*;

#[test]
fn options_reject_zero_bounds() {
    assert!(
        NavigationCaptureOptions {
            max_events: 0,
            ..NavigationCaptureOptions::default()
        }
        .validate()
        .is_err()
    );
    assert!(
        NavigationCaptureOptions {
            max_resources: 0,
            ..NavigationCaptureOptions::default()
        }
        .validate()
        .is_err()
    );
    assert!(
        NavigationCaptureOptions {
            max_source_bytes: 0,
            ..NavigationCaptureOptions::default()
        }
        .validate()
        .is_err()
    );
}
