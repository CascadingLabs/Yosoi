//! Bounded point-in-time visual capture for an owned browser tab.

use crate::documents::ImageDocument;
#[cfg(feature = "browser")]
use crate::internal::browser::{
    Bbox,
    controller::ScreenshotOptions as ProviderScreenshotOptions,
    selector::{BrowserTarget, BrowserTargetKind},
};
use serde::{Deserialize, Serialize};

/// Semantic target strategy used to crop a screenshot to one discovered visual element.
///
/// Targets are resolved against the live page immediately before capture. A missing,
/// hidden, or ambiguous target fails the operation instead of selecting an arbitrary match.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "target", rename_all = "snake_case")]
pub enum ScreenshotTarget {
    /// Resolve one element by its accessible role and exact accessible name.
    Role {
        /// Accessibility role, such as button or heading.
        role: String,
        /// Exact accessible name of the target.
        name: String,
        /// Optional zero-based disambiguation among matching accessible elements.
        nth: Option<u32>,
    },
    /// Resolve one element through a CSS selector.
    Css(String),
    /// Resolve one element through an XPath expression.
    Xpath(String),
    /// Resolve one element through a CSS selector and retain an attribute name for provenance.
    Attr {
        /// CSS selector used to resolve the target.
        selector: String,
        /// Attribute name associated with the target.
        name: String,
    },
    /// Resolve one element whose identifier begins with this prefix.
    GlobalId {
        /// Shared identifier prefix.
        prefix: String,
    },
    /// Capture the one CSS pixel at this viewport coordinate.
    Point {
        /// Horizontal page coordinate in CSS pixels.
        x: f64,
        /// Vertical page coordinate in CSS pixels.
        y: f64,
    },
}

#[cfg(feature = "browser")]
impl ScreenshotTarget {
    fn provider_target(&self) -> Result<BrowserTarget, super::SessionError> {
        let target = match self {
            Self::Role { role, name, nth } => BrowserTarget {
                kind: BrowserTargetKind::Role,
                value: role.clone(),
                regex: None,
                name: Some(name.clone()),
                nth: *nth,
                x: None,
                y: None,
            },
            Self::Css(selector) => BrowserTarget {
                kind: BrowserTargetKind::Css,
                value: selector.clone(),
                regex: None,
                name: None,
                nth: None,
                x: None,
                y: None,
            },
            Self::Xpath(expression) => BrowserTarget {
                kind: BrowserTargetKind::Xpath,
                value: expression.clone(),
                regex: None,
                name: None,
                nth: None,
                x: None,
                y: None,
            },
            Self::Attr { selector, name } => BrowserTarget {
                kind: BrowserTargetKind::Attr,
                value: selector.clone(),
                regex: None,
                name: Some(name.clone()),
                nth: None,
                x: None,
                y: None,
            },
            Self::GlobalId { prefix } => BrowserTarget {
                kind: BrowserTargetKind::GlobalId,
                value: "*".to_owned(),
                regex: None,
                name: Some(prefix.clone()),
                nth: None,
                x: None,
                y: None,
            },
            Self::Point { x, y } => BrowserTarget {
                kind: BrowserTargetKind::Visual,
                value: String::new(),
                regex: None,
                name: None,
                nth: None,
                x: Some(*x),
                y: Some(*y),
            },
        };
        target
            .validate()
            .map_err(|_| super::SessionError::InvalidInput)?;
        Ok(target)
    }
}

/// Requested visual area for a one-shot screenshot.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum ScreenshotRegion {
    /// Capture the currently visible viewport.
    Viewport,
    /// Capture the complete scrollable page.
    FullPage,
    /// Crop a page-coordinate rectangle in CSS pixels.
    BoundingBox {
        /// Left coordinate in CSS pixels.
        x: u32,
        /// Top coordinate in CSS pixels.
        y: u32,
        /// Width in CSS pixels.
        width: u32,
        /// Height in CSS pixels.
        height: u32,
    },
    /// Resolve and crop a discovered visual target.
    Target(ScreenshotTarget),
}

/// Bounds and visual region for Work::screenshot_with.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScreenshotOptions {
    /// Requested viewport, full-page, rectangle, or semantic-target region.
    pub region: ScreenshotRegion,
    /// Maximum retained PNG payload size, bounded again by the Session policy.
    pub max_bytes: u64,
    /// Require the current document epoch to match this value before and after capture.
    ///
    /// This guards against a navigation racing a semantic-target screenshot. It does not bind
    /// a role or selector target to an older Surface observation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_document_epoch: Option<u64>,
}

impl Default for ScreenshotOptions {
    fn default() -> Self {
        Self {
            region: ScreenshotRegion::Viewport,
            max_bytes: 16_000_000,
            expected_document_epoch: None,
        }
    }
}

impl ScreenshotOptions {
    /// Selects the currently visible viewport.
    pub fn viewport_only(mut self) -> Self {
        self.region = ScreenshotRegion::Viewport;
        self
    }

    /// Selects the complete scrollable page.
    pub fn full_page(mut self) -> Self {
        self.region = ScreenshotRegion::FullPage;
        self
    }

    /// Selects a semantic target to resolve and crop at capture time.
    pub fn target(mut self, target: ScreenshotTarget) -> Self {
        self.region = ScreenshotRegion::Target(target);
        self
    }

    /// Sets the maximum PNG payload size in bytes.
    pub const fn max_bytes(mut self, maximum: u64) -> Self {
        self.max_bytes = maximum;
        self
    }

    /// Requires the current document epoch to remain unchanged across capture.
    pub const fn expected_document_epoch(mut self, epoch: u64) -> Self {
        self.expected_document_epoch = Some(epoch);
        self
    }
}

/// Resolved crop rectangle in page CSS pixels.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScreenshotBounds {
    /// Left coordinate in CSS pixels.
    pub x: u32,
    /// Top coordinate in CSS pixels.
    pub y: u32,
    /// Width in CSS pixels.
    pub width: u32,
    /// Height in CSS pixels.
    pub height: u32,
    /// Origin used for the rectangle's CSS-pixel coordinates.
    pub coordinate_space: ScreenshotCoordinateSpace,
}

/// CSS coordinate origin for a resolved screenshot rectangle.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScreenshotCoordinateSpace {
    /// Coordinates are relative to the current layout viewport.
    Viewport,
    /// Coordinates are relative to the top-left of the full document.
    Page,
}

/// Serializable capture facts kept beside the exact PNG document.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScreenshotCaptureMetadata {
    /// Unique identity for this point-in-time capture.
    pub capture_id: String,
    /// Identity of the tab source from which the PNG was obtained.
    pub source_id: String,
    /// Owning Session's retained tab identity.
    pub tab_id: String,
    /// Unix timestamp in milliseconds when capture completed, when the clock was available.
    pub captured_at_unix_ms: Option<u64>,
    /// Region requested by the caller.
    pub region: ScreenshotRegion,
    /// Width of the retained PNG in physical pixels when decoded from its header.
    pub width_pixels: Option<u32>,
    /// Height of the retained PNG in physical pixels when decoded from its header.
    pub height_pixels: Option<u32>,
    /// Current top-level document epoch when the provider could identify it.
    pub document_epoch: Option<u64>,
    /// Resolved page-coordinate crop rectangle, when the provider used one.
    pub bounds: Option<ScreenshotBounds>,
    /// CSS viewport width used to interpret bounds.
    pub viewport_width: Option<u32>,
    /// CSS viewport height used to interpret bounds.
    pub viewport_height: Option<u32>,
    /// Device scale factor applied when capturing the PNG.
    pub device_scale_factor: Option<f64>,
    /// Whether the PNG contains the complete requested region.
    pub complete: bool,
}

/// A validated immutable PNG document plus its capture coordinates and provenance.
#[derive(Clone, Debug, PartialEq)]
pub struct ScreenshotCapture {
    /// Exact retained image document, suitable for Archive storage.
    pub document: ImageDocument,
    /// Coordinates, dimensions, and source identity for this capture.
    pub metadata: ScreenshotCaptureMetadata,
}

impl ScreenshotCapture {
    /// Separates serializable capture facts from the exact image bytes.
    pub fn into_parts(self) -> (ScreenshotCaptureMetadata, ImageDocument) {
        (self.metadata, self.document)
    }
}

#[cfg(feature = "browser")]
fn provider_options(
    region: &ScreenshotRegion,
) -> Result<ProviderScreenshotOptions, super::SessionError> {
    let options = ProviderScreenshotOptions::default();
    Ok(match region {
        ScreenshotRegion::Viewport => options.viewport_only(),
        ScreenshotRegion::FullPage => options,
        ScreenshotRegion::BoundingBox {
            x,
            y,
            width,
            height,
        } => options.with_bbox(Bbox {
            x: *x,
            y: *y,
            width: *width,
            height: *height,
        }),
        ScreenshotRegion::Target(target) => options.with_selector(target.provider_target()?),
    })
}

impl super::Work {
    /// Captures one complete PNG without reacquiring Work's action lock.
    ///
    /// This internal adapter is used by automatic evidence hooks that already hold
    /// the operation lock. It still checks screenshot permission, authority, size,
    /// and document-epoch preconditions.
    pub(crate) async fn capture_screenshot_unlocked(
        &self,
        options: ScreenshotOptions,
    ) -> Result<ScreenshotCapture, super::SessionError> {
        use crate::documents::MAX_FILE_BYTES;
        #[cfg(feature = "browser")]
        use crate::documents::{FileLimits, FileMetadata, ImageDocument};

        self.authorize(super::ActionKind::Screenshot, "")?;
        let serialized =
            serde_json::to_vec(&options).map_err(|_| super::SessionError::InvalidInput)?;
        if serialized.len() > self.session.settings().maximum_input_bytes
            || options.max_bytes == 0
            || options.max_bytes > MAX_FILE_BYTES
            || matches!(
                &options.region,
                ScreenshotRegion::BoundingBox { width: 0, .. }
                    | ScreenshotRegion::BoundingBox { height: 0, .. }
            )
        {
            return Err(super::SessionError::InvalidInput);
        }
        #[cfg(feature = "browser")]
        {
            use crate::internal::browser::{DocumentEpoch, VisualCaptureRegion};
            let provider_options = provider_options(&options.region)?;
            let before_epoch = self.call(self.control.document_epoch()).await?;
            if options
                .expected_document_epoch
                .is_some_and(|expected| expected != before_epoch)
            {
                return Err(super::SessionError::InvalidInput);
            }
            let visual = self
                .call(self.control.visual_snapshot(provider_options))
                .await?;
            let after_epoch = self.call(self.control.document_epoch()).await?;
            let document_epoch = match visual.scope.epoch {
                DocumentEpoch::Known(epoch) => Some(epoch),
                DocumentEpoch::UnavailableForAttachedPage => None,
            };
            if before_epoch != after_epoch
                || document_epoch != Some(before_epoch)
                || options
                    .expected_document_epoch
                    .is_some_and(|expected| expected != after_epoch)
            {
                return Err(super::SessionError::EvidenceUnavailable);
            }
            let retained_bytes = u64::try_from(visual.bytes().len())
                .map_err(|_| super::SessionError::InvalidInput)?;
            if retained_bytes > options.max_bytes {
                return Err(super::SessionError::ResultLimit {
                    maximum: usize::try_from(options.max_bytes).unwrap_or(usize::MAX),
                });
            }
            let _capture_buffer = self.session.inner.backend.capture_buffer(retained_bytes)?;
            let capture_id = super::new_operation_id();
            let session_id = self.session.inner.backend.id();
            let metadata = FileMetadata::new()
                .with_declared_media_type("image/png")
                .map_err(|_| super::SessionError::EvidenceUnavailable)?
                .with_source("yosoi.session.tab_screenshot")
                .map_err(|_| super::SessionError::EvidenceUnavailable)?
                .with_capture_id(capture_id.clone())
                .map_err(|_| super::SessionError::EvidenceUnavailable)?
                .with_session_id(session_id)
                .map_err(|_| super::SessionError::EvidenceUnavailable)?
                .with_tab_id(self.tab_id.clone())
                .map_err(|_| super::SessionError::EvidenceUnavailable)?;
            let limits = FileLimits::new(options.max_bytes)
                .map_err(|_| super::SessionError::InvalidInput)?;
            let document = ImageDocument::from_bytes_with_metadata(
                format!("screenshot-{capture_id}"),
                visual.bytes().to_vec(),
                metadata,
                limits,
            )
            .map_err(|_| super::SessionError::EvidenceUnavailable)?;
            let coordinate_space =
                if matches!(visual.region, VisualCaptureRegion::BrowserTarget { .. }) {
                    ScreenshotCoordinateSpace::Viewport
                } else {
                    ScreenshotCoordinateSpace::Page
                };
            let capture = ScreenshotCapture {
                document,
                metadata: ScreenshotCaptureMetadata {
                    capture_id,
                    source_id: self.tab_id.clone(),
                    tab_id: self.tab_id.clone(),
                    captured_at_unix_ms: visual.generated_at_unix_ms,
                    region: options.region,
                    width_pixels: Some(visual.image_width_pixels),
                    height_pixels: Some(visual.image_height_pixels),
                    document_epoch,
                    bounds: visual.resolved_bounds.map(|bounds| ScreenshotBounds {
                        x: bounds.x,
                        y: bounds.y,
                        width: bounds.width,
                        height: bounds.height,
                        coordinate_space,
                    }),
                    viewport_width: Some(visual.capture_viewport.width_css_pixels().get()),
                    viewport_height: Some(visual.capture_viewport.height_css_pixels().get()),
                    device_scale_factor: Some(visual.device_scale_factor),
                    complete: visual.complete,
                },
            };
            Ok(capture)
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(super::SessionError::BrowserFeatureDisabled)
        }
    }

    /// Captures one complete PNG with this tab's exclusive Work authority.
    pub async fn screenshot_with(
        &self,
        options: ScreenshotOptions,
    ) -> Result<ScreenshotCapture, super::SessionError> {
        let _operation = self.operation()?;
        self.capture_screenshot_unlocked(options).await
    }
}
