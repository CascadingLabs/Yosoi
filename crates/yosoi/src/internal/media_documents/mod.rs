//! Opaque immutable media and binary file documents.

mod audio;
mod binary;
mod classify;
mod error;
mod factory;
mod file;
mod image;
mod limits;
mod metadata;
mod payload;
mod read;
mod video;

pub use audio::AudioDocument;
pub use binary::BinaryDocument;
pub use error::FileDocumentError;
pub use factory::file_from_bytes;
pub use file::FileDocument;
pub use image::ImageDocument;
pub use limits::{DEFAULT_FILE_MAX_BYTES, FileLimits, MAX_FILE_BYTES};
pub use metadata::{FileMetadata, MAX_SOURCE_BYTES};
pub use read::read_file;
pub use video::VideoDocument;

#[allow(
    clippy::redundant_pub_crate,
    reason = "The SDK keeps this module private while the development harness compiles the same source under a public internal namespace."
)]
pub(crate) use {
    audio::from_archived_audio, binary::from_archived_binary, image::from_archived_image,
    video::from_archived_video,
};

#[allow(
    unused_imports,
    clippy::redundant_pub_crate,
    reason = "Only the SDK facade consumes this shared-body factory; the development harness compiles the engine without that facade."
)]
pub(crate) use factory::file_from_shared_bytes;

#[cfg(test)]
mod tests;
