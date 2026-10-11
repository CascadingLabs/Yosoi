use std::fmt;

use serde::{
    Deserialize, Deserializer,
    de::{Error as SerdeDeError, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Map, Value};

use super::types::JsonParseError;

pub(super) const JSON_PARSER_DEPTH_LIMIT: u32 = 128;
const DUPLICATE_KEY_MARKER: &str = "duplicate JSON object member";

pub(super) fn scan_json_depth(bytes: &[u8], maximum: u32) -> Result<u32, JsonParseError> {
    let mut depth = 0_u32;
    let mut greatest_depth = 0_u32;
    let mut inside_string = false;
    let mut escaped = false;

    for byte in bytes.iter().copied() {
        if inside_string {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                inside_string = false;
            }
            continue;
        }

        match byte {
            b'"' => inside_string = true,
            b'{' | b'[' => {
                depth = match depth.checked_add(1) {
                    Some(depth) => depth,
                    None => {
                        return Err(JsonParseError::DepthLimitExceeded {
                            maximum: u64::from(maximum),
                            observed: u64::MAX,
                        });
                    }
                };
                greatest_depth = greatest_depth.max(depth);
                if depth > maximum {
                    return Err(JsonParseError::DepthLimitExceeded {
                        maximum: u64::from(maximum),
                        observed: u64::from(depth),
                    });
                }
            }
            b'}' | b']' if depth > 0 => {
                depth = depth.saturating_sub(1);
            }
            _ => {}
        }
    }

    Ok(greatest_depth)
}

pub(super) fn parse_unique_json(
    bytes: &[u8],
    observed_depth: u32,
) -> Result<Value, JsonParseError> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let root = UniqueJsonValue::deserialize(&mut deserializer)
        .map_err(|error| classify_json_error(&error, observed_depth))?;
    deserializer
        .end()
        .map_err(|error| classify_json_error(&error, observed_depth))?;
    Ok(root.0)
}

fn classify_json_error(error: &serde_json::Error, observed_depth: u32) -> JsonParseError {
    let message = error.to_string();
    if message.starts_with(DUPLICATE_KEY_MARKER) {
        JsonParseError::DuplicateObjectKey
    } else if error.is_eof() {
        JsonParseError::TruncatedJson
    } else if message.contains("recursion limit exceeded") {
        JsonParseError::DepthLimitExceeded {
            maximum: u64::from(JSON_PARSER_DEPTH_LIMIT),
            observed: u64::from(observed_depth).saturating_add(1),
        }
    } else {
        JsonParseError::MalformedJson
    }
}

struct UniqueJsonValue(Value);

impl<'de> Deserialize<'de> for UniqueJsonValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(UniqueJsonVisitor)
    }
}

struct UniqueJsonVisitor;

impl<'de> Visitor<'de> for UniqueJsonVisitor {
    type Value = UniqueJsonValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("one RFC 8259 JSON value with unique object member names")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(UniqueJsonValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(UniqueJsonValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(UniqueJsonValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: SerdeDeError,
    {
        let number = serde_json::Number::from_f64(value)
            .ok_or_else(|| E::custom("JSON number is not finite"))?;
        Ok(UniqueJsonValue(Value::Number(number)))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: SerdeDeError,
    {
        Ok(UniqueJsonValue(Value::String(value.to_owned())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(UniqueJsonValue(Value::String(value)))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueJsonValue(Value::Null))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueJsonValue(Value::Null))
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        UniqueJsonValue::deserialize(deserializer)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<UniqueJsonValue>()? {
            values.push(value.0);
        }
        Ok(UniqueJsonValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = Map::new();
        while let Some(name) = object.next_key::<String>()? {
            if values.contains_key(&name) {
                return Err(A::Error::custom(DUPLICATE_KEY_MARKER));
            }
            let value = object.next_value::<UniqueJsonValue>()?;
            values.insert(name, value.0);
        }
        Ok(UniqueJsonValue(Value::Object(values)))
    }
}
