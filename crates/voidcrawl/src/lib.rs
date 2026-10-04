//! `void_crawl_core` — a clean async CDP wrapper built on chromiumoxide.
//!
//! This crate provides `BrowserSession` and `Page` as the primary API.

/// Package version recorded by Yosoi's certified VoidCrawl adapter identity.
pub const VOID_CRAWL_VERSION: &str = env!("CARGO_PKG_VERSION");

pub mod active_navigation;
pub mod ax;
pub mod byte_control;
pub mod captcha;
pub mod challenge;
pub mod context_isolation;
pub mod cookie_jar;
pub mod document_snapshot;
pub mod environment;
pub mod error;
pub mod input;
pub mod interrupt;
mod lease;
pub mod managed_profile;
pub mod navigation_capture;
pub mod observation;
pub mod page;
pub mod profile_context;
pub mod recording;
pub mod response;
#[cfg(feature = "scanner")]
pub mod scanner;
pub mod selector;
pub mod session;
pub mod stealth;
pub mod viewport;
pub mod visual_snapshot;

// Re-export CDP types used by Yosoi's browser acquisition adapter.
pub use active_navigation::{
    ActiveNavigation, ActiveNavigationOptions, NavigationFailureReason, NavigationProgress,
    NavigationProgressAccounting, NavigationProgressKind, NavigationReport, NavigationTermination,
};
pub use byte_control::{
    BrowserBudgetScope, BrowserByteAccounting, BrowserByteAccountingError, BrowserByteAdmission,
    BrowserByteBudget, BrowserByteDomain, BrowserByteMeasurementUnavailableReason,
    BrowserByteReport, BrowserByteReportError, BrowserByteSpec, BrowserLimitScope,
    BrowserPayloadExtent, BrowserPayloadFailureReason, BrowserPayloadUnavailableReason,
    MeasuredBrowserBytes,
};
pub use captcha::{
    CaptchaInfo, CaptchaKind, WidgetRect, capture_captcha, detect_captcha, inject_captcha_token,
};
pub use challenge::{
    AttachCoordinates, ChallengeSnapshot, ChallengeStatus, DomCaptchaSnapshot, ResolutionOutcome,
    ResolutionRequest, ResolverType, captcha_is_active,
};
pub use chromiumoxide::{
    CdpMode,
    cdp::browser_protocol::{
        input::{DispatchKeyEventType, DispatchMouseEventType, MouseButton},
        network::{Cookie, CookieParam, DeleteCookiesParams},
    },
};
pub use context_isolation::{
    BrowserStateBinding, ContextCleanupReport, ContextDisposalState, IsolatedBrowserContext,
};
pub use cookie_jar::{CookieLease, CookieProvenance, LeaseScope, fork_scoped};
pub use document_snapshot::{
    AccessibilitySnapshot, AccessibilitySnapshotOptions, DocumentEpoch, DocumentFrameScope,
    DocumentScope, RenderedDomSnapshot, SnapshotState, SnapshotUnavailableReason,
};
pub use environment::{
    BrowserCaptureCapabilities, BrowserEnvironmentSnapshot, BrowserRenderingEnvironment,
    CapabilityDisabledReason, CapabilityState, CapabilityUnavailableReason,
    CapabilityUnsupportedReason, ControllerVersion, EnvironmentObservation,
    EnvironmentOmissionReason, EnvironmentUnavailableReason, InstrumentationMode,
    InstrumentationSnapshot, RendererVersion, RenderingPreferences,
};
pub use error::{
    Result, VoidCrawlError, VoidCrawlErrorCategory, VoidCrawlErrorCode, VoidCrawlErrorSummary,
};
pub use interrupt::{InterruptInfo, InterruptRegistry, InterruptRequest, InterruptState};
pub use managed_profile::{
    MAX_PROFILE_SPLIT_COPIES, ManagedProfile, ManagedProfileDescription, ManagedProfileLease,
    ManagedProfileSnapshot, ProfilePool, ProfileRegistry, ProfileStatus, ResolvedProfilePool,
    default_profile_root,
};
pub use navigation_capture::{
    BrowserBodyLayer, MainDocumentSource, NavigationCapture, NavigationCaptureOptions,
    NavigationCaptureReport, NavigationCaptureTermination, NavigationEvent, NavigationEventKind,
    NetworkExtraInfoState, ProtectedHeaders, ProtectedUrl, RedirectHop, ResourceFrameId,
    ResourceLoaderId, ResourceRecord, SourceBodyUnavailableReason,
};
pub use observation::{
    MeasuredCount, MeasurementUnavailableReason, ObservationAccounting, ObservationCheckpoint,
    ObservationCountAccounting, ObservationEvent, ObservationEventKind, ObservationOptions,
    ObservationReport, ObservationScope, ObservationTermination, ProtectedDiagnosticText,
    QuietSettlementProof, QuietWaitError, RuntimeDiagnostic, RuntimeDiagnosticKind,
};
pub use page::{
    Bbox, DownloadCapture, DownloadOutcome, Page, PageResponse, ScreenshotOptions,
    ScreenshotOutput, TabInstrumentationState,
};
pub use profile_context::ManagedProfileContext;
pub use recording::{
    Encoding, Frame, FrameFormat, MaskRegion, MaskReport, MaskSpec, RecordedRegion, Recording,
    RecordingHandle, RecordingOptions,
};
pub use response::{
    CapturedResponse, DEFAULT_MAX_RESPONSE_BYTES, DEFAULT_MAX_TOTAL_RESPONSE_BYTES,
    ResponseBodyState, ResponseCapture, ResponseCaptureLimits, ResponseCaptureReport,
    ResponseCaptureTermination,
};
#[cfg(feature = "scanner")]
pub use scanner::{DEFAULT_MAX_BYTES, ScanConfig, ScanReport, Verdict, scan_bytes, scan_path};
pub use selector::{BrowserTarget, BrowserTargetKind, TargetResolution};
pub use session::{BrowserDebugPortPolicy, BrowserMode, BrowserSession, BrowserSessionBuilder};
pub use stealth::{NavigatorWebdriverPolicy, StealthConfig};
pub use viewport::{ScrollTarget, Viewport, all_presets, preset as viewport_preset, preset_names};
pub use visual_snapshot::{
    ContentSizeMetrics, LayoutSnapshot, LayoutViewportMetrics, PairedLayoutVisualSnapshot,
    VisualCaptureRegion, VisualFormat, VisualSnapshot, VisualViewportMetrics,
};
