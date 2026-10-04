use std::fmt;

use super::RequestRunRecord;

impl fmt::Debug for RequestRunRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RequestRunRecord")
            .field("request_id", &self.request_id)
            .field("target_origin", &"[redacted]")
            .field("policy", &self.policy)
            .field("effective_policy", &self.effective_policy)
            .field("termination", &self.termination)
            .field("attempts", &self.attempts)
            .finish()
    }
}
