use chromiumoxide_cdp::cdp::browser_protocol::target::{SessionId, TargetId};

/// Represents a Session within the cpd.
#[derive(Debug, Clone)]
pub struct Session {
    /// Identifier for this session.
    id: SessionId,
    /// The identifier of the target this session is attached to.
    target_id: TargetId,
    /// The page target whose frame manager owns this session's events.
    owner_target_id: TargetId,
}
impl Session {
    pub fn new(id: SessionId, target_id: TargetId, owner_target_id: TargetId) -> Self {
        Self {
            id,
            target_id,
            owner_target_id,
        }
    }

    pub fn session_id(&self) -> &SessionId {
        &self.id
    }

    pub fn target_id(&self) -> &TargetId {
        &self.target_id
    }

    pub fn owner_target_id(&self) -> &TargetId {
        &self.owner_target_id
    }
}
