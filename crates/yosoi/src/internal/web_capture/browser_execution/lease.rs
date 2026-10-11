use serde::{Deserialize, Deserializer, Serialize};

use super::{
    BrowserContextLeaseId, BrowserExecutionId, BrowserExecutionManagerId, BrowserProcessGeneration,
    BrowserProcessSlotId, BrowserSessionLeaseId, BrowserTabLeaseId,
};

/// A manager-owned reservation of one reusable browser process slot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProcessSlotLease {
    manager: BrowserExecutionManagerId,
    slot: BrowserProcessSlotId,
    generation: BrowserProcessGeneration,
}

impl BrowserProcessSlotLease {
    pub const fn new(
        manager: BrowserExecutionManagerId,
        slot: BrowserProcessSlotId,
        generation: BrowserProcessGeneration,
    ) -> Self {
        Self {
            manager,
            slot,
            generation,
        }
    }

    pub const fn manager(&self) -> BrowserExecutionManagerId {
        self.manager
    }

    pub const fn slot(&self) -> BrowserProcessSlotId {
        self.slot
    }

    pub const fn generation(&self) -> BrowserProcessGeneration {
        self.generation
    }
}

impl<'de> Deserialize<'de> for BrowserProcessSlotLease {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserProcessSlotLeaseWire::deserialize(deserializer)?;
        Ok(Self::new(wire.manager, wire.slot, wire.generation))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProcessSlotLeaseWire {
    manager: BrowserExecutionManagerId,
    slot: BrowserProcessSlotId,
    generation: BrowserProcessGeneration,
}

/// One execution assigned to a manager-owned browser process slot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionLease {
    process: BrowserProcessSlotLease,
    execution: BrowserExecutionId,
}

impl BrowserExecutionLease {
    pub const fn new(process: BrowserProcessSlotLease, execution: BrowserExecutionId) -> Self {
        Self { process, execution }
    }

    pub const fn process(&self) -> &BrowserProcessSlotLease {
        &self.process
    }

    pub const fn execution(&self) -> BrowserExecutionId {
        self.execution
    }
}

impl<'de> Deserialize<'de> for BrowserExecutionLease {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserExecutionLeaseWire::deserialize(deserializer)?;
        Ok(Self::new(wire.process, wire.execution))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionLeaseWire {
    process: BrowserProcessSlotLease,
    execution: BrowserExecutionId,
}

/// One browser context reserved for a specific execution.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserContextLease {
    execution: BrowserExecutionLease,
    context: BrowserContextLeaseId,
}

impl BrowserContextLease {
    pub const fn new(execution: BrowserExecutionLease, context: BrowserContextLeaseId) -> Self {
        Self { execution, context }
    }

    pub const fn execution(&self) -> &BrowserExecutionLease {
        &self.execution
    }

    pub const fn context(&self) -> BrowserContextLeaseId {
        self.context
    }
}

impl<'de> Deserialize<'de> for BrowserContextLease {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserContextLeaseWire::deserialize(deserializer)?;
        Ok(Self::new(wire.execution, wire.context))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserContextLeaseWire {
    execution: BrowserExecutionLease,
    context: BrowserContextLeaseId,
}

/// One session reserved within a browser context lease.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserSessionLease {
    context: BrowserContextLease,
    session: BrowserSessionLeaseId,
}

impl BrowserSessionLease {
    pub const fn new(context: BrowserContextLease, session: BrowserSessionLeaseId) -> Self {
        Self { context, session }
    }

    pub const fn context(&self) -> &BrowserContextLease {
        &self.context
    }

    pub const fn session(&self) -> BrowserSessionLeaseId {
        self.session
    }
}

impl<'de> Deserialize<'de> for BrowserSessionLease {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserSessionLeaseWire::deserialize(deserializer)?;
        Ok(Self::new(wire.context, wire.session))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserSessionLeaseWire {
    context: BrowserContextLease,
    session: BrowserSessionLeaseId,
}

/// One tab reserved within a browser session lease.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserTabLease {
    session: BrowserSessionLease,
    tab: BrowserTabLeaseId,
}

impl BrowserTabLease {
    pub const fn new(session: BrowserSessionLease, tab: BrowserTabLeaseId) -> Self {
        Self { session, tab }
    }

    pub const fn session(&self) -> &BrowserSessionLease {
        &self.session
    }

    pub const fn tab(&self) -> BrowserTabLeaseId {
        self.tab
    }
}

impl<'de> Deserialize<'de> for BrowserTabLease {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserTabLeaseWire::deserialize(deserializer)?;
        Ok(Self::new(wire.session, wire.tab))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserTabLeaseWire {
    session: BrowserSessionLease,
    tab: BrowserTabLeaseId,
}
