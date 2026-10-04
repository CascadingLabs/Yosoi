//! Validated producer, schema, operation, and reason vocabulary.

use std::{fmt, num::NonZeroU32, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

const MAX_NAME_BYTES: usize = 128;
const MAX_VERSION_BYTES: usize = 128;

/// Error returned when a namespaced identity is not canonical.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum NamespacedIdError {
    /// The identity was empty.
    #[error("namespaced identity cannot be empty")]
    Empty,

    /// The identity exceeded the shared wire bound.
    #[error("namespaced identity cannot exceed {MAX_NAME_BYTES} bytes")]
    TooLong,

    /// The identity did not begin with a lowercase ASCII letter or digit.
    #[error("namespaced identity must begin with a lowercase ASCII letter or digit")]
    InvalidStart,

    /// The identity did not end with a lowercase ASCII letter or digit.
    #[error("namespaced identity must end with a lowercase ASCII letter or digit")]
    InvalidEnd,

    /// The identity contained a character outside its canonical alphabet.
    #[error("namespaced identity allows only lowercase ASCII letters, digits, '.', '-', and '_'")]
    InvalidCharacter,

    /// The identity did not contain a namespace separator.
    #[error("namespaced identity must contain at least two dot-separated segments")]
    MissingNamespace,

    /// The identity contained an empty dot-separated namespace segment.
    #[error("namespaced identity cannot contain empty dot-separated segments")]
    EmptySegment,
}

/// Stable caller-supplied identity of a component responsible for work.
///
/// Examples include `com.cascadinglabs.voidcrawl.cdp` and
/// `com.cascadinglabs.yosoi.ax-normalizer`.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ProducerId(String);

impl ProducerId {
    /// Validates and creates a producer identity.
    pub fn new(value: impl Into<String>) -> Result<Self, NamespacedIdError> {
        let value = value.into();
        validate_namespaced_id(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical producer identity.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ProducerId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for ProducerId {
    type Err = NamespacedIdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for ProducerId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

/// Stable caller-supplied identity of an artifact representation.
///
/// Schema identity is separate from producer identity because many producer
/// versions can emit the same schema, and one producer can emit many schemas.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct SchemaId(String);

impl SchemaId {
    /// Validates and creates a schema identity.
    pub fn new(value: impl Into<String>) -> Result<Self, NamespacedIdError> {
        let value = value.into();
        validate_namespaced_id(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical schema identity.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for SchemaId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for SchemaId {
    type Err = NamespacedIdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for SchemaId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

/// Error returned when an explicit component version is not safe and bounded.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ProducerVersionError {
    /// The version was empty.
    #[error("producer version cannot be empty")]
    Empty,

    /// The version exceeded the shared wire bound.
    #[error("producer version cannot exceed {MAX_VERSION_BYTES} bytes")]
    TooLong,

    /// The version contained whitespace, control characters, or non-ASCII data.
    #[error("producer version must contain only visible non-whitespace ASCII characters")]
    InvalidCharacter,
}

/// Explicit opaque implementation version reported by a producer.
///
/// Parser, browser, kernel, firmware, and tool versions all use this type. The
/// value identifies an implementation; [`SchemaVersion`] identifies a data
/// representation and must not be substituted for it.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ProducerVersion(String);

impl ProducerVersion {
    /// Validates and creates a producer version.
    pub fn new(value: impl Into<String>) -> Result<Self, ProducerVersionError> {
        let value = value.into();
        validate_producer_version(&value)?;
        Ok(Self(value))
    }

    /// Returns the exact validated version string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ProducerVersion {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for ProducerVersion {
    type Err = ProducerVersionError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for ProducerVersion {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

/// Component and implementation version directly responsible for a value.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Producer {
    id: ProducerId,
    version: ProducerVersion,
}

impl Producer {
    /// Creates explicit producer provenance.
    pub const fn new(id: ProducerId, version: ProducerVersion) -> Self {
        Self { id, version }
    }

    /// Returns the producer identity.
    pub const fn id(&self) -> &ProducerId {
        &self.id
    }

    /// Returns the producer implementation version.
    pub const fn version(&self) -> &ProducerVersion {
        &self.version
    }
}

/// Error returned when a schema version is zero.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("schema version must be a positive integer")]
pub struct SchemaVersionError;

/// Positive revision of one particular schema.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct SchemaVersion(NonZeroU32);

impl SchemaVersion {
    /// Creates a schema version from an already validated positive integer.
    pub const fn new(value: NonZeroU32) -> Self {
        Self(value)
    }

    /// Returns the numeric schema revision.
    pub const fn get(self) -> u32 {
        self.0.get()
    }
}

impl fmt::Display for SchemaVersion {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl TryFrom<u32> for SchemaVersion {
    type Error = SchemaVersionError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        NonZeroU32::new(value).map(Self).ok_or(SchemaVersionError)
    }
}

impl From<SchemaVersion> for u32 {
    fn from(value: SchemaVersion) -> Self {
        value.get()
    }
}

/// Schema identity and revision needed to interpret a produced value.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Schema {
    id: SchemaId,
    version: SchemaVersion,
}

impl Schema {
    /// Creates an explicit schema reference.
    pub const fn new(id: SchemaId, version: SchemaVersion) -> Self {
        Self { id, version }
    }

    /// Returns the schema identity.
    pub const fn id(&self) -> &SchemaId {
        &self.id
    }

    /// Returns the schema revision.
    pub const fn version(&self) -> SchemaVersion {
        self.version
    }
}

/// Stable namespaced identity of an operation performed by an activity.
///
/// Domain crates define operation payloads; this shared identity does not create
/// an untyped dispatch channel.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct OperationId(String);

impl OperationId {
    /// Validates and creates an operation identity.
    pub fn new(value: impl Into<String>) -> Result<Self, NamespacedIdError> {
        let value = value.into();
        validate_namespaced_id(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical operation identity.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for OperationId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for OperationId {
    type Err = NamespacedIdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for OperationId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

/// Stable secret-safe explanation code used in durable evidence.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ReasonCode(String);

impl ReasonCode {
    /// Validates and creates a reason code.
    pub fn new(value: impl Into<String>) -> Result<Self, NamespacedIdError> {
        let value = value.into();
        validate_namespaced_id(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical reason code.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ReasonCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for ReasonCode {
    type Err = NamespacedIdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for ReasonCode {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

fn validate_namespaced_id(value: &str) -> Result<(), NamespacedIdError> {
    if value.is_empty() {
        return Err(NamespacedIdError::Empty);
    }
    if value.len() > MAX_NAME_BYTES {
        return Err(NamespacedIdError::TooLong);
    }

    let mut characters = value.bytes();
    let first = characters.next().ok_or(NamespacedIdError::Empty)?;
    if !is_lower_alphanumeric(first) {
        return Err(NamespacedIdError::InvalidStart);
    }
    if !value.bytes().all(|character| {
        is_lower_alphanumeric(character) || matches!(character, b'.' | b'-' | b'_')
    }) {
        return Err(NamespacedIdError::InvalidCharacter);
    }
    if !value.contains('.') {
        return Err(NamespacedIdError::MissingNamespace);
    }
    if value.split('.').any(str::is_empty) {
        return Err(NamespacedIdError::EmptySegment);
    }
    if !value.bytes().next_back().is_some_and(is_lower_alphanumeric) {
        return Err(NamespacedIdError::InvalidEnd);
    }
    Ok(())
}

fn validate_producer_version(value: &str) -> Result<(), ProducerVersionError> {
    if value.is_empty() {
        return Err(ProducerVersionError::Empty);
    }
    if value.len() > MAX_VERSION_BYTES {
        return Err(ProducerVersionError::TooLong);
    }
    if !value.bytes().all(|character| character.is_ascii_graphic()) {
        return Err(ProducerVersionError::InvalidCharacter);
    }
    Ok(())
}

const fn is_lower_alphanumeric(character: u8) -> bool {
    character.is_ascii_lowercase() || character.is_ascii_digit()
}

fn deserialize_from_string<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr,
    T::Err: fmt::Display,
{
    String::deserialize(deserializer)?
        .parse()
        .map_err(D::Error::custom)
}
