use crate::internal::contracts::{ContractId, ContractSchemaError, FieldId};
use crate::internal::documents::OutputId;
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use sha2::{Digest as _, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::{self, Display, Formatter};

/// Portable schema version accepted by Contract construction and deserialization.
pub const CONTRACT_SCHEMA_VERSION: u32 = 1;

/// Boundary used to group located evidence into candidate records.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordScope {
    /// Group compatible findings into one page-scoped candidate record.
    Page,
    /// Group findings by repeated parent-region lineage into separate candidate records.
    Repeated,
}

/// Required number of accepted field values, enforced during validation rather than extraction.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Cardinality {
    /// Require one value; missing or multiple candidate values are field issues.
    ExactlyOne,
    /// Permit no value or one value; multiple candidates are a field issue.
    ZeroOrOne,
    /// Permit an ordered collection, including an empty collection.
    Many,
}

/// Stable semantic identity for a Contract field value type.
pub trait ContractValue {
    /// Stable scalar type identifier included in schema identity, such as `string` or `money.usd`.
    const TYPE_ID: &'static str;
}

impl ContractValue for String {
    const TYPE_ID: &'static str = "string";
}

/// Owned field meaning, cardinality, and conversion type metadata for a Contract schema.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FieldSchema {
    id: FieldId,
    description: String,
    cardinality: Cardinality,
    value_type: String,
}

impl FieldSchema {
    /// Owns field metadata after rejecting blank identity, description, or type text.
    ///
    /// `description` explains the business meaning; it does not discover a
    /// locator automatically. `cardinality` is enforced at validation, and
    /// `value_type` declares conversion vocabulary without checking runtime
    /// support here. Returns [`ContractSchemaError`] for blank required metadata.
    pub fn try_new(
        id: FieldId,
        description: impl Into<String>,
        cardinality: Cardinality,
        value_type: impl Into<String>,
    ) -> Result<Self, ContractSchemaError> {
        if id.as_str().trim().is_empty() {
            return Err(ContractSchemaError::EmptyFieldId);
        }
        let description = description.into();
        if description.trim().is_empty() {
            return Err(ContractSchemaError::EmptyFieldDescription { field: id });
        }
        let value_type = value_type.into();
        if value_type.trim().is_empty() {
            return Err(ContractSchemaError::EmptyValueType { field: id });
        }
        Ok(Self {
            id,
            description,
            cardinality,
            value_type,
        })
    }

    #[doc(hidden)]
    pub fn from_derive(
        id: &'static str,
        description: &'static str,
        cardinality: Cardinality,
        value_type: &'static str,
    ) -> Result<Self, ContractSchemaError> {
        Self::try_new(
            FieldId::from_derive(id),
            description,
            cardinality,
            value_type,
        )
    }

    /// Borrows the authored identity used to associate output findings with this field.
    pub const fn id(&self) -> &FieldId {
        &self.id
    }
    /// Borrows the field's business-meaning description, not a generated locator.
    pub fn description(&self) -> &str {
        &self.description
    }
    /// Returns the accepted-value count constraint for validation.
    pub const fn cardinality(&self) -> Cardinality {
        self.cardinality
    }
    /// Borrows the declared scalar conversion identifier without resolving an implementation.
    pub fn value_type(&self) -> &str {
        &self.value_type
    }
}

impl<'de> Deserialize<'de> for FieldSchema {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            id: FieldId,
            description: String,
            cardinality: Cardinality,
            value_type: String,
        }
        let wire = Wire::deserialize(deserializer)?;
        Self::try_new(wire.id, wire.description, wire.cardinality, wire.value_type)
            .map_err(D::Error::custom)
    }
}

/// Validated portable record schema; it defines meaning without locating or validating evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContractSchema {
    version: u32,
    id: ContractId,
    description: String,
    scope: RecordScope,
    fields: Vec<FieldSchema>,
    #[serde(skip)]
    field_index: BTreeMap<String, usize>,
}

impl ContractSchema {
    /// Owns a supported schema version, record meaning, scope, and ordered fields.
    ///
    /// Returns [`ContractSchemaError`] for an unsupported or zero version, blank
    /// Contract identity or description, an empty field collection, or duplicate
    /// field identities. Field order is retained and contributes to semantic
    /// identity. This does not acquire documents, choose locators, or check that
    /// every declared scalar type has a runtime conversion implementation.
    pub fn try_new(
        version: u32,
        id: ContractId,
        description: impl Into<String>,
        scope: RecordScope,
        fields: Vec<FieldSchema>,
    ) -> Result<Self, ContractSchemaError> {
        if version == 0 {
            return Err(ContractSchemaError::ZeroVersion);
        }
        if version != CONTRACT_SCHEMA_VERSION {
            return Err(ContractSchemaError::UnsupportedVersion { observed: version });
        }
        if id.as_str().trim().is_empty() {
            return Err(ContractSchemaError::EmptyContractId);
        }
        let description = description.into();
        if description.trim().is_empty() {
            return Err(ContractSchemaError::EmptyContractDescription);
        }
        if fields.is_empty() {
            return Err(ContractSchemaError::NoFields);
        }
        let mut seen = BTreeSet::new();
        let mut field_index = BTreeMap::new();
        for (index, field) in fields.iter().enumerate() {
            if !seen.insert(field.id.clone()) {
                return Err(ContractSchemaError::DuplicateField {
                    field: field.id.clone(),
                });
            }
            field_index.insert(field.id.as_str().to_owned(), index);
        }
        Ok(Self {
            version,
            id,
            description,
            scope,
            fields,
            field_index,
        })
    }

    #[doc(hidden)]
    pub fn from_derive(
        id: &'static str,
        description: &'static str,
        scope: RecordScope,
        fields: Vec<FieldSchema>,
    ) -> Result<Self, ContractSchemaError> {
        Self::try_new(
            CONTRACT_SCHEMA_VERSION,
            ContractId::from_derive(id),
            description,
            scope,
            fields,
        )
    }

    /// Returns the portable schema format version accepted during construction.
    pub const fn version(&self) -> u32 {
        self.version
    }
    /// Borrows the authored record identity included in semantic schema hashing.
    pub const fn id(&self) -> &ContractId {
        &self.id
    }
    /// Borrows the record's business meaning; descriptive prose is excluded from identity hashing.
    pub fn description(&self) -> &str {
        &self.description
    }
    /// Returns whether candidate grouping is page-scoped or repeated-region-scoped.
    pub const fn scope(&self) -> RecordScope {
        self.scope
    }
    /// Borrows fields in authored order; changing this order changes semantic identity.
    pub fn fields(&self) -> &[FieldSchema] {
        &self.fields
    }
    #[doc(hidden)]
    pub fn field_for_output(&self, output: &OutputId) -> Option<&FieldSchema> {
        let index = *self.field_index.get(output.as_str())?;
        self.fields.get(index)
    }

    /// Hashes semantic metadata into a stable 32-byte Contract identity.
    ///
    /// Includes format version, Contract ID, scope, ordered field IDs,
    /// cardinalities, and scalar type IDs. Contract and field descriptions are
    /// excluded, so prose changes alone do not change identity. Returns
    /// [`ContractSchemaError`] if a length cannot fit portable hash accounting.
    /// This identifies schema semantics, not a document or execution occurrence.
    pub fn identity(&self) -> Result<ContractIdentity, ContractSchemaError> {
        let mut hasher = Sha256::new();
        hasher.update(self.version.to_le_bytes());
        hash_string(&mut hasher, self.id.as_str())?;
        hasher.update([match self.scope {
            RecordScope::Page => 0,
            RecordScope::Repeated => 1,
        }]);
        hash_length(&mut hasher, self.fields.len())?;
        for field in &self.fields {
            hash_string(&mut hasher, field.id.as_str())?;
            hasher.update([match field.cardinality {
                Cardinality::ExactlyOne => 0,
                Cardinality::ZeroOrOne => 1,
                Cardinality::Many => 2,
            }]);
            hash_string(&mut hasher, &field.value_type)?;
        }
        Ok(ContractIdentity(hasher.finalize().into()))
    }
}

impl<'de> Deserialize<'de> for ContractSchema {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            version: u32,
            id: ContractId,
            description: String,
            scope: RecordScope,
            fields: Vec<FieldSchema>,
        }
        let wire = Wire::deserialize(deserializer)?;
        Self::try_new(
            wire.version,
            wire.id,
            wire.description,
            wire.scope,
            wire.fields,
        )
        .map_err(D::Error::custom)
    }
}

/// Stable SHA-256 identity of portable Contract schema semantics, displayed as lowercase hex.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct ContractIdentity([u8; 32]);

impl ContractIdentity {
    /// Borrows the exact 32 hash bytes without the hexadecimal display encoding.
    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

impl Display for ContractIdentity {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(formatter, "{byte:02x}")?;
        }
        Ok(())
    }
}

fn hash_length(hasher: &mut Sha256, length: usize) -> Result<(), ContractSchemaError> {
    let length = u64::try_from(length).map_err(|_| ContractSchemaError::LengthOverflow)?;
    hasher.update(length.to_le_bytes());
    Ok(())
}

fn hash_string(hasher: &mut Sha256, value: &str) -> Result<(), ContractSchemaError> {
    hash_length(hasher, value.len())?;
    hasher.update(value.as_bytes());
    Ok(())
}
