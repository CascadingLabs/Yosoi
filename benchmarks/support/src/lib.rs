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

/// Shared engine/profile declaration used by the embedded SDK component sources.
#[path = "../../../crates/yosoi/src/browser.rs"]
pub mod browser;

// Embedded components share the same facade types as the SDK. Compile those
// facades against this crate's embedded internals so development benchmarks do
// not mix handles from two separately compiled runtime/type graphs.
#[path = "../../../crates/yosoi/src/action.rs"]
pub mod action;
#[path = "../../../crates/yosoi/src/archive.rs"]
pub mod archive;
#[path = "../../../crates/yosoi/src/assertions.rs"]
pub mod assertions;
#[path = "../../../crates/yosoi/src/automation_record.rs"]
pub mod automation_record;
#[path = "../../../crates/yosoi/src/contracts.rs"]
pub mod contracts;
#[path = "../../../crates/yosoi/src/documents.rs"]
pub mod documents;
#[path = "../../../crates/yosoi/src/expect.rs"]
pub mod expect;
#[path = "../../../crates/yosoi/src/flow.rs"]
pub mod flow;
#[path = "../../../crates/yosoi/src/locators.rs"]
pub mod locators;
#[path = "../../../crates/yosoi/src/map.rs"]
pub mod map;
#[path = "../../../crates/yosoi/src/policy.rs"]
pub mod policy;
#[path = "../../../crates/yosoi/src/prelude.rs"]
pub mod prelude;
#[path = "../../../crates/yosoi/src/request.rs"]
pub mod request;
#[path = "../../../crates/yosoi/src/search.rs"]
pub mod search;
#[path = "../../../crates/yosoi/src/session.rs"]
pub mod session;
#[path = "../../../crates/yosoi/src/surface/mod.rs"]
pub mod surface;
#[path = "../../../crates/yosoi/src/timing.rs"]
pub mod timing;
#[path = "../../../crates/yosoi/src/view.rs"]
pub mod view;

extern crate self as yosoi;

#[doc(hidden)]
#[path = "../../../crates/yosoi/src/macro_support.rs"]
pub mod __macro;

pub use crate::internal::engine::Archive;
