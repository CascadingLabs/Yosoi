use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::fmt::{self, Display, Formatter};
use thiserror::Error;

macro_rules! checked_id {
    ($name:ident, $empty:ident, $docs:literal) => {
        #[doc = $docs]
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Owns nonblank authored identity text without normalizing its spelling.
            ///
            /// Returns [`ContractSchemaError`] for all-whitespace input. Original
            /// case and whitespace are retained and affect identity comparison.
            pub fn try_new(value: impl Into<String>) -> Result<Self, ContractSchemaError> {
                let value = value.into();
                if value.trim().is_empty() {
                    Err(ContractSchemaError::$empty)
                } else {
                    Ok(Self(value))
                }
            }
            #[doc(hidden)]
            pub fn from_derive(value: &'static str) -> Self {
                Self(value.to_owned())
            }
            /// Borrows the original validated identity spelling for matching and hashing.
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl Display for $name {
            fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
                self.0.fmt(formatter)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                Self::try_new(String::deserialize(deserializer)?).map_err(D::Error::custom)
            }
        }
    };
}

checked_id!(
    ContractId,
    EmptyContractId,
    "Authored identity distinguishing one record Contract schema from another."
);
checked_id!(
    FieldId,
    EmptyFieldId,
    "Authored field identity associating locator outputs with Contract field evidence."
);

/// Portable Contract metadata rejected during construction, deserialization, or identity hashing.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ContractSchemaError {
    /// Schema format version is zero rather than a supported positive version.
    #[error("contract schema version must be greater than zero")]
    ZeroVersion,
    /// Schema format version is not the currently supported portable version.
    #[error("contract schema version {observed} is unsupported")]
    UnsupportedVersion {
        /// Supplied portable schema format version.
        observed: u32,
    },
    /// Authored Contract identity contains no non-whitespace text.
    #[error("contract identity cannot be empty")]
    EmptyContractId,
    /// Authored field identity contains no non-whitespace text.
    #[error("field identity cannot be empty")]
    EmptyFieldId,
    /// Business-meaning description for the record contains no usable text.
    #[error("contract description cannot be empty")]
    EmptyContractDescription,
    /// A field has no usable business-meaning description.
    #[error("field description cannot be empty: {field}")]
    EmptyFieldDescription {
        /// Identifier of the field missing its description.
        field: FieldId,
    },
    /// A field has no nonblank scalar conversion type identifier.
    #[error("semantic field value type cannot be empty: {field}")]
    EmptyValueType {
        /// Identifier of the field missing its scalar type vocabulary.
        field: FieldId,
    },
    /// The Contract schema declares no fields to extract or validate.
    #[error("contract must declare at least one field")]
    NoFields,
    /// More than one field declares the same authored identity.
    #[error("contract field is duplicated: {field}")]
    DuplicateField {
        /// Repeated field identifier that would make evidence association ambiguous.
        field: FieldId,
    },
    /// A string or field-collection length cannot fit portable u64 identity accounting.
    #[error("schema input length cannot be represented as u64")]
    LengthOverflow,
}
