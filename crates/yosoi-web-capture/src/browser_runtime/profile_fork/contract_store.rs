use super::*;

/// Durable state of a child profile's future CAS-354 lease eligibility.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileChildContractState {
    Reserved,
    Committed,
}

impl<'de> Deserialize<'de> for BrowserProfileChildContractState {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let state = String::deserialize(deserializer)?;
        match state.as_str() {
            "reserved" | "quarantined" => Ok(Self::Reserved),
            "committed" | "active" => Ok(Self::Committed),
            _ => Err(D::Error::custom(
                "unsupported managed-profile contract state",
            )),
        }
    }
}

/// Durable child identity and expiry contract for a later CAS-354 lease.
/// It carries no lease generation or provider state; CAS-354 issues each child
/// lease when its manager acquires the profile.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileChildLeaseContract {
    pub(super) identity: BrowserProfileChildIdentity,
    pub(super) lineage: BrowserProfileLineageIdentity,
    pub(super) expires_at: DateTime<Utc>,
    pub(super) state: BrowserProfileChildContractState,
}

impl BrowserProfileChildLeaseContract {
    pub const fn identity(&self) -> &BrowserProfileChildIdentity {
        &self.identity
    }

    pub const fn expires_at(&self) -> &DateTime<Utc> {
        &self.expires_at
    }

    pub const fn lease_authorized(&self) -> bool {
        matches!(self.state, BrowserProfileChildContractState::Committed)
    }
}

#[derive(Debug, Error, Clone, Copy, PartialEq, Eq)]
pub enum BrowserProfileChildContractStoreError {
    #[error("managed-profile child-contract storage is unavailable")]
    Io,
    #[error("managed-profile child-contract store is invalid")]
    InvalidStore,
    #[error("managed-profile child contract already exists")]
    Conflict,
    #[error("managed-profile child contract reservation does not match")]
    ReservationMismatch,
    #[error("managed-profile child contract is reserved or not committed")]
    NotCommitted,
    #[error("managed-profile child contract has expired")]
    Expired,
    #[error("managed-profile child contract was not found")]
    NotFound,
}

#[derive(Clone, Debug)]
pub struct BrowserProfileChildContractStore {
    path: PathBuf,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileChildContractDocument {
    version: u32,
    contracts: Vec<BrowserProfileChildLeaseContract>,
}

impl BrowserProfileChildContractStore {
    pub(crate) fn for_registry_root(registry_root: &Path) -> Self {
        Self {
            path: registry_root
                .join(".yosoi")
                .join("managed-profile-child-contracts.json"),
        }
    }

    pub(crate) fn validate_on_open(&self) -> Result<(), BrowserProfileChildContractStoreError> {
        let _lock = self.lock_file()?;
        self.load_contracts().map(|_| ())
    }

    pub(crate) fn reserve(
        &self,
        contracts: &[BrowserProfileChildLeaseContract],
    ) -> Result<(), BrowserProfileChildContractStoreError> {
        self.update(|stored| {
            let mut requested = HashSet::with_capacity(contracts.len());
            for contract in contracts {
                validate_child_contract(contract)?;
                if contract.state != BrowserProfileChildContractState::Reserved
                    || !requested.insert(contract.identity.profile_id().clone())
                    || stored.contains_key(contract.identity.profile_id())
                {
                    return Err(BrowserProfileChildContractStoreError::Conflict);
                }
            }
            for contract in contracts {
                stored.insert(contract.identity.profile_id().clone(), contract.clone());
            }
            Ok(())
        })
    }

    pub(crate) fn commit(
        &self,
        children: &[BrowserProfileChildIdentity],
    ) -> Result<(), BrowserProfileChildContractStoreError> {
        self.update(|stored| {
            for child in children {
                let contract = matching_reservation(stored, child)?;
                contract.state = BrowserProfileChildContractState::Committed;
            }
            Ok(())
        })
    }

    pub(crate) fn remove_reservations(
        &self,
        children: &[BrowserProfileChildIdentity],
    ) -> Result<(), BrowserProfileChildContractStoreError> {
        self.update(|stored| {
            for child in children {
                let Some(contract) = stored.get(child.profile_id()) else {
                    return Err(BrowserProfileChildContractStoreError::ReservationMismatch);
                };
                if contract.identity != *child
                    || contract.state != BrowserProfileChildContractState::Reserved
                {
                    return Err(BrowserProfileChildContractStoreError::ReservationMismatch);
                }
            }
            for child in children {
                stored.remove(child.profile_id());
            }
            Ok(())
        })
    }

    pub(crate) fn committed_contract(
        &self,
        profile_id: &BrowserProfileId,
        now: &DateTime<Utc>,
    ) -> Result<BrowserProfileChildLeaseContract, BrowserProfileChildContractStoreError> {
        let _lock = self.lock_file()?;
        let contracts = self.load_contracts()?;
        let contract = contracts
            .get(profile_id)
            .cloned()
            .ok_or(BrowserProfileChildContractStoreError::NotFound)?;
        if contract.state != BrowserProfileChildContractState::Committed {
            return Err(BrowserProfileChildContractStoreError::NotCommitted);
        }
        if now >= &contract.expires_at {
            return Err(BrowserProfileChildContractStoreError::Expired);
        }
        Ok(contract)
    }

    pub(crate) fn authorize_profile(
        &self,
        profile_id: &BrowserProfileId,
        now: &DateTime<Utc>,
    ) -> Result<Option<DateTime<Utc>>, BrowserProfileChildContractStoreError> {
        let _lock = self.lock_file()?;
        let contracts = self.load_contracts()?;
        let Some(contract) = contracts.get(profile_id) else {
            return Ok(None);
        };
        if contract.state != BrowserProfileChildContractState::Committed {
            return Err(BrowserProfileChildContractStoreError::NotCommitted);
        }
        if now >= &contract.expires_at {
            return Err(BrowserProfileChildContractStoreError::Expired);
        }
        Ok(Some(contract.expires_at))
    }

    fn update<T>(
        &self,
        update: impl FnOnce(
            &mut HashMap<BrowserProfileId, BrowserProfileChildLeaseContract>,
        ) -> Result<T, BrowserProfileChildContractStoreError>,
    ) -> Result<T, BrowserProfileChildContractStoreError> {
        let _lock = self.lock_file()?;
        let mut contracts = self.load_contracts()?;
        let result = update(&mut contracts)?;
        self.write_contracts(&contracts)?;
        Ok(result)
    }

    fn lock_file(&self) -> Result<File, BrowserProfileChildContractStoreError> {
        let parent = self
            .path
            .parent()
            .ok_or(BrowserProfileChildContractStoreError::InvalidStore)?;
        fs::create_dir_all(parent).map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        let lock_path = self.path.with_extension("lock");
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(lock_path)
            .map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        lock.lock()
            .map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        Ok(lock)
    }

    fn load_contracts(
        &self,
    ) -> Result<
        HashMap<BrowserProfileId, BrowserProfileChildLeaseContract>,
        BrowserProfileChildContractStoreError,
    > {
        let bytes = match fs::read(&self.path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(HashMap::new()),
            Err(_) => return Err(BrowserProfileChildContractStoreError::Io),
        };
        let document: BrowserProfileChildContractDocument = serde_json::from_slice(&bytes)
            .map_err(|_| BrowserProfileChildContractStoreError::InvalidStore)?;
        if document.version != 1 {
            return Err(BrowserProfileChildContractStoreError::InvalidStore);
        }
        let mut contracts = HashMap::with_capacity(document.contracts.len());
        for contract in document.contracts {
            validate_child_contract(&contract)?;
            if contracts
                .insert(contract.identity.profile_id().clone(), contract)
                .is_some()
            {
                return Err(BrowserProfileChildContractStoreError::InvalidStore);
            }
        }
        Ok(contracts)
    }

    fn write_contracts(
        &self,
        contracts: &HashMap<BrowserProfileId, BrowserProfileChildLeaseContract>,
    ) -> Result<(), BrowserProfileChildContractStoreError> {
        let mut contracts = contracts.values().cloned().collect::<Vec<_>>();
        contracts.sort_by(|left, right| {
            left.identity
                .profile_id()
                .as_str()
                .cmp(right.identity.profile_id().as_str())
        });
        let document = BrowserProfileChildContractDocument {
            version: 1,
            contracts,
        };
        let bytes = serde_json::to_vec_pretty(&document)
            .map_err(|_| BrowserProfileChildContractStoreError::InvalidStore)?;
        let parent = self
            .path
            .parent()
            .ok_or(BrowserProfileChildContractStoreError::InvalidStore)?;
        let mut temporary =
            NamedTempFile::new_in(parent).map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        temporary
            .write_all(&bytes)
            .map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        temporary
            .as_file()
            .sync_all()
            .map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        temporary
            .persist(&self.path)
            .map_err(|_| BrowserProfileChildContractStoreError::Io)?;
        Ok(())
    }
}

fn validate_child_contract(
    contract: &BrowserProfileChildLeaseContract,
) -> Result<(), BrowserProfileChildContractStoreError> {
    if contract.identity.lineage_id() != contract.lineage.id()
        || contract.identity.checkpoint_id() != contract.lineage.checkpoint().id()
        || contract.identity.profile_id() == contract.lineage.checkpoint().source_profile_id()
    {
        return Err(BrowserProfileChildContractStoreError::InvalidStore);
    }
    Ok(())
}

fn matching_reservation<'a>(
    stored: &'a mut HashMap<BrowserProfileId, BrowserProfileChildLeaseContract>,
    child: &BrowserProfileChildIdentity,
) -> Result<&'a mut BrowserProfileChildLeaseContract, BrowserProfileChildContractStoreError> {
    let contract = stored
        .get_mut(child.profile_id())
        .ok_or(BrowserProfileChildContractStoreError::ReservationMismatch)?;
    if contract.identity != *child || contract.state != BrowserProfileChildContractState::Reserved {
        return Err(BrowserProfileChildContractStoreError::ReservationMismatch);
    }
    Ok(contract)
}
