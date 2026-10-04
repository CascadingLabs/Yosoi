//! Sealed type-directed dispatch for the public `Archive` methods.

use std::future::Future;

use crate::{Archive, ArchiveError};

pub mod sealed {
    pub trait Value {}
    pub trait Reference {}
}

/// Closed mapping from one durable value to the typed reference it writes.
///
/// Arbitrary application types cannot opt themselves into persistence:
///
/// ```compile_fail
/// use yosoi_archive::Archive;
///
/// async fn write_application_string(archive: &Archive) {
///     let value = String::from("not a Yosoi domain value");
///     let _ = archive.write(&value).await;
/// }
/// ```
///
/// External crates also cannot implement the sealed mapping:
///
/// ```compile_fail
/// use std::future::Future;
/// use yosoi_archive::{Archive, ArchiveError, ArchiveValue, PolicyArchiveRef};
///
/// struct ApplicationValue;
///
/// impl ArchiveValue for ApplicationValue {
///     type Reference = PolicyArchiveRef;
///
///     fn write_to<'a>(
///         _archive: &'a Archive,
///         _value: &'a Self,
///     ) -> impl Future<Output = Result<Self::Reference, ArchiveError>> + Send + 'a {
///         async { unreachable!() }
///     }
/// }
/// ```
#[doc(hidden)]
pub trait ArchiveValue: sealed::Value + Sized + Sync {
    type Reference: ArchiveReference<Value = Self>;

    fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> impl Future<Output = Result<Self::Reference, ArchiveError>> + Send + 'a;
}

/// Closed mapping from one Archive reference to the exact value it reads.
#[doc(hidden)]
pub trait ArchiveReference: sealed::Reference + Sized + Sync {
    type Value: ArchiveValue<Reference = Self>;

    fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> impl Future<Output = Result<Self::Value, ArchiveError>> + Send + 'a;
}
