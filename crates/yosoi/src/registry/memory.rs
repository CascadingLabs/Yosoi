use std::sync::Mutex;

use super::{Backend, Change, Coordination, RegistryError, Revision, Snapshot};

pub(super) struct Memory(Mutex<Snapshot>);

impl Default for Memory {
    fn default() -> Self {
        Self(Mutex::new(Snapshot::empty()))
    }
}

impl Backend for Memory {
    fn coordination(&self) -> Coordination {
        Coordination::Instance
    }

    fn snapshot(&self) -> Result<Snapshot, RegistryError> {
        Ok(self.0.lock().map_err(|_| RegistryError::Poisoned)?.clone())
    }

    fn commit(&self, expected: &Revision, changes: &[Change]) -> Result<Snapshot, RegistryError> {
        let mut state = self.0.lock().map_err(|_| RegistryError::Poisoned)?;
        let next = state.changed(expected, changes)?;
        *state = next.clone();
        drop(state);
        Ok(next)
    }

    fn compact(&self) -> Result<(), RegistryError> {
        Ok(())
    }
}
