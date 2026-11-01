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
pub use metadata::FileMetadata;
pub use read::read_file;
pub use video::VideoDocument;

pub use audio::from_archived_audio;
pub use binary::from_archived_binary;
pub use image::from_archived_image;
pub use video::from_archived_video;

#[cfg(test)]
mod tests;
