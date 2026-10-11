//! Action-triggered browser downloads retain their arm, act, wait contract.
//!
//! ```no_run
//! # async fn f(page: &yosoi_dev_support::internal::browser::Page) -> yosoi_dev_support::internal::browser::Result<()> {
//! # use std::{path::Path, time::Duration};
//! let cap = page.arm_download(Path::new("/tmp/dl"), 100 << 20).await?;
//! page.click_by_role("button", "Download all", 0, false).await?; // the triggering action
//! let file = cap.wait(page, Duration::from_secs(120)).await?;
//! # Ok(()) }
//! ```
//! Development-only access to the SDK component sources for benchmarks and fuzzing.
//! Never a dependency of a published SDK package.
//!
//! # Archive boundaries
//!
//! Arbitrary application values cannot be written to the sealed SDK Archive:
//!
//! ```compile_fail
//! use yosoi_dev_support::internal::archive::Archive;
//!
//! async fn write_application_string(archive: &Archive) {
//!     let value = String::from("not a Yosoi domain value");
//!     let _ = archive.write(&value).await;
//! }
//! ```
//!
//! Downstream code cannot implement the Archive mapping for its own value:
//!
//! ```compile_fail
//! use std::future::Future;
//!
//! use yosoi_dev_support::internal::archive::{
//!     Archive, ArchiveError, ArchiveValue, PolicyArchiveRef,
//! };
//!
//! struct ApplicationValue;
//!
//! impl ArchiveValue for ApplicationValue {
//!     type Reference = PolicyArchiveRef;
//!
//!     fn write_to<'a>(
//!         _archive: &'a Archive,
//!         _value: &'a Self,
//!     ) -> impl Future<Output = Result<Self::Reference, ArchiveError>> + Send + 'a {
//!         async { unreachable!() }
//!     }
//! }
//! ```
//!
//! # Identity domains
//!
//! Activity and capture identities cannot be substituted for one another:
//!
//! ```compile_fail
//! use yosoi_dev_support::internal::types::{ActivityId, CaptureId};
//!
//! fn requires_capture(_: CaptureId) {}
//! requires_capture(ActivityId::random());
//! ```
//!
//! # Web capture relationships
//!
//! Artifact-family references keep their semantic types:
//!
//! ```compile_fail
//! use yosoi_dev_support::internal::web_capture::{LayoutArtifactRef, SourceArtifactRef};
//!
//! fn requires_source(_: SourceArtifactRef) {}
//! fn cannot_confuse_families(layout: LayoutArtifactRef) {
//!     requires_source(layout);
//! }
//! ```
//!
//! A requested URL does not prove the final URL observed by a producer:
//!
//! ```compile_fail
//! use yosoi_dev_support::internal::web_capture::{RequestedWebTarget, ResolvedWebUrl};
//!
//! fn requires_observed_url(_: ResolvedWebUrl) {}
//! let requested = RequestedWebTarget::parse("https://example.com").unwrap();
//! requires_observed_url(requested);
//! ```
//!
//! # Browser recording
//!
//! A one-shot recording captures frames for its configured duration:
//!
//! ```no_run
//! # async fn f(page: &yosoi_dev_support::internal::browser::Page) -> yosoi_dev_support::internal::browser::Result<()> {
//! use std::time::Duration;
//!
//! use yosoi_dev_support::internal::browser::RecordingOptions;
//!
//! let rec =
//!     page.record(RecordingOptions::default().with_max_duration(Duration::from_secs(5))).await?;
//! println!("{} frames at {:.1} fps", rec.frames_captured, rec.effective_fps());
//! # Ok(()) }
//! ```
//!
//! A recording handle can stay active while the caller drives a page:
//!
//! ```no_run
//! # async fn f(page: &yosoi_dev_support::internal::browser::Page) -> yosoi_dev_support::internal::browser::Result<()> {
//! use yosoi_dev_support::internal::browser::RecordingOptions;
//!
//! let rec = page.start_recording(RecordingOptions::default()).await?;
//! page.click_by_role("button", "Play", 0, false).await?;
//! let out = rec.stop(page).await?;
//! # Ok(()) }
//! ```
pub mod internal;
