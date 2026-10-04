use std::fmt;

use serde::{
    Deserialize, Deserializer, Serialize,
    de::{Error as _, SeqAccess, Visitor},
};

use crate::PolicyError;

const MAX_FILTER_ITEMS: usize = 128;
const MAX_FILTER_STRING_BYTES: usize = 1_024;

/// URL components omitted from a Map inventory.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Filters {
    /// Query parameter names whose presence excludes a discovered URL.
    pub excluded_query_keys: Vec<String>,
    /// Path prefixes whose matching URLs are excluded.
    pub excluded_path_prefixes: Vec<String>,
}

impl Filters {
    /// Validates the number and UTF-8 size of every filter string.
    pub fn validate(&self) -> Result<(), PolicyError> {
        if self.excluded_query_keys.len() > MAX_FILTER_ITEMS
            || self.excluded_path_prefixes.len() > MAX_FILTER_ITEMS
        {
            return Err(PolicyError::TooManyMapFilters);
        }
        if self
            .excluded_query_keys
            .iter()
            .chain(&self.excluded_path_prefixes)
            .any(|value| value.len() > MAX_FILTER_STRING_BYTES)
        {
            return Err(PolicyError::MapFilterStringTooLong);
        }
        if self.excluded_path_prefixes.iter().any(String::is_empty) {
            return Err(PolicyError::EmptyMapPathPrefix);
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for Filters {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct FiltersValues {
            #[serde(default)]
            excluded_query_keys: BoundedStrings<MAX_FILTER_ITEMS>,
            #[serde(default)]
            excluded_path_prefixes: BoundedStrings<MAX_FILTER_ITEMS>,
        }

        let values = FiltersValues::deserialize(deserializer)?;
        let filters = Self {
            excluded_query_keys: values.excluded_query_keys.0,
            excluded_path_prefixes: values.excluded_path_prefixes.0,
        };
        filters.validate().map_err(D::Error::custom)?;
        Ok(filters)
    }
}

struct BoundedStrings<const MAX: usize>(Vec<String>);

impl<const MAX: usize> Default for BoundedStrings<MAX> {
    fn default() -> Self {
        Self(Vec::new())
    }
}

impl<'de, const MAX: usize> Deserialize<'de> for BoundedStrings<MAX> {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct BoundedStringsVisitor<const MAX: usize>;

        impl<'de, const MAX: usize> Visitor<'de> for BoundedStringsVisitor<MAX> {
            type Value = BoundedStrings<MAX>;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(formatter, "a sequence of at most {MAX} strings")
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut values = Vec::with_capacity(MAX.min(8));
                while let Some(value) = sequence.next_element::<String>()? {
                    if values.len() >= MAX {
                        return Err(A::Error::custom("too many Map filter strings"));
                    }
                    values.push(value);
                }
                Ok(BoundedStrings(values))
            }
        }

        deserializer.deserialize_seq(BoundedStringsVisitor::<MAX>)
    }
}
