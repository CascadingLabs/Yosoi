use super::{LifecycleError, checked_add_bytes, checked_add_events};

#[test]
fn checked_event_accounting_rejects_integer_overflow() {
    assert!(matches!(
        checked_add_events(u64::MAX, 1),
        Err(LifecycleError::EventOverflow)
    ));
}

#[test]
fn checked_byte_accounting_rejects_integer_overflow() {
    assert!(matches!(
        checked_add_bytes(u64::MAX, 1),
        Err(LifecycleError::ByteOverflow)
    ));
}
