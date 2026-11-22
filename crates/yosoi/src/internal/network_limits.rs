//! Shared native response-buffer bounds, independent of the SDK facade.

/// Page-lifetime CDP per-resource response buffer and body-read cap.
pub const NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES: usize = 8 * 1024 * 1024;
/// Page-lifetime aggregate CDP response buffer cap.
pub const NETWORK_PROVIDER_TOTAL_BUFFER_BYTES: usize = 8 * 1024 * 1024;
