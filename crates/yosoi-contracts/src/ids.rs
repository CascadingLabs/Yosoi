use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::fmt::{self, Display, Formatter};
use thiserror::Error;

macro_rules! checked_id {
    ($name:ident, $empty:ident) => {
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
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

checked_id!(ContractId, EmptyContractId);
checked_id!(FieldId, EmptyFieldId);

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ContractSchemaError {
    #[error("contract schema version must be greater than zero")]
    ZeroVersion,
    #[error("contract schema version {observed} is unsupported")]
    UnsupportedVersion { observed: u32 },
    #[error("contract identity cannot be empty")]
    EmptyContractId,
    #[error("field identity cannot be empty")]
    EmptyFieldId,
    #[error("contract description cannot be empty")]
    EmptyContractDescription,
    #[error("field description cannot be empty: {field}")]
    EmptyFieldDescription { field: FieldId },
    #[error("semantic field value type cannot be empty: {field}")]
    EmptyValueType { field: FieldId },
    #[error("contract must declare at least one field")]
    NoFields,
    #[error("contract field is duplicated: {field}")]
    DuplicateField { field: FieldId },
    #[error("schema input length cannot be represented as u64")]
    LengthOverflow,
}
