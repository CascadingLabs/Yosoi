//! Variable CDP viewport: device dimensions, pixel ratio, mobile/touch
//! emulation, and a small table of named presets (phone/tablet/desktop) in
//! the spirit of Chrome DevTools' device toolbar.
//!
//! This module is the raw substrate: plain data plus a name → [`Viewport`]
//! lookup. Yosoi owns any higher-level presentation or contract around these
//! engine-native values.

use serde::{Deserialize, Serialize};

/// A CDP viewport/device spec: the dimensions, pixel ratio, and mobile/touch
/// identity `Page::set_viewport` applies via the `Emulation` domain.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Viewport {
    /// CSS-pixel viewport width.
    pub width: u32,
    /// CSS-pixel viewport height.
    pub height: u32,
    /// Device pixel ratio (1.0 = standard, 2.0/3.0 = Retina/HiDPI). Affects
    /// `window.devicePixelRatio` and CSS media queries correctly; does
    /// **not** upscale `Page::screenshot`'s PNG output — see that method's
    /// doc comment.
    pub device_scale_factor: f64,
    /// Whether to emulate a mobile viewport (affects meta-viewport parsing
    /// and `navigator.userAgentData.mobile`).
    pub mobile: bool,
    /// Whether to emulate touch input (`ontouchstart`,
    /// `navigator.maxTouchPoints`).
    pub has_touch: bool,
    /// UA string to present alongside this device, if any. `None` leaves
    /// whatever UA is already in effect (e.g. the session's stealth UA)
    /// untouched.
    pub user_agent: Option<String>,
}

impl Viewport {
    /// A custom desktop-style viewport: no mobile/touch emulation, DPR 1.0,
    /// UA untouched. Use [`Viewport::mobile`] for a phone/tablet-style one.
    pub const fn custom(width: u32, height: u32) -> Self {
        Self {
            width,
            height,
            device_scale_factor: 1.0,
            mobile: false,
            has_touch: false,
            user_agent: None,
        }
    }

    /// A custom mobile-style viewport: touch enabled, `mobile` flag set.
    /// Pass a `device_scale_factor` matching the real device (phones are
    /// typically 2.0-3.0) and a UA string for the spoofed platform to be
    /// coherent with `navigator.userAgentData`.
    pub fn mobile(
        width: u32,
        height: u32,
        device_scale_factor: f64,
        user_agent: impl Into<String>,
    ) -> Self {
        Self {
            width,
            height,
            device_scale_factor,
            mobile: true,
            has_touch: true,
            user_agent: Some(user_agent.into()),
        }
    }
}

/// One named entry in the device preset table.
struct Preset {
    name: &'static str,
    viewport: fn() -> Viewport,
}

macro_rules! presets {
    ($($name:literal => $mk:expr),+ $(,)?) => {
        &[$(Preset { name: $name, viewport: $mk }),+]
    };
}

/// The full preset table, in the order [`preset_names`] reports them.
///
/// Dimensions are CSS pixels (what `Emulation.setDeviceMetricsOverride`
/// wants), not raw device pixels — e.g. an iPhone 16 Pro Max is
/// 1290x2796 physical pixels at DPR 3, so its CSS viewport is 430x932.
static PRESETS: &[Preset] = presets! {
    // ── Phones ───────────────────────────────────────────────────────
    "iPhone 16 Pro Max" => || Viewport::mobile(430, 932, 3.0,
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 \
         (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"),
    "iPhone 16" => || Viewport::mobile(393, 852, 3.0,
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 \
         (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"),
    "iPhone SE" => || Viewport::mobile(375, 667, 2.0,
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 \
         (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"),
    "Pixel 7" => || Viewport::mobile(412, 915, 2.625,
        "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) \
         Chrome/128.0.0.0 Mobile Safari/537.36"),
    "Galaxy S20" => || Viewport::mobile(360, 800, 4.0,
        "Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) \
         Chrome/128.0.0.0 Mobile Safari/537.36"),
    // ── Tablets ──────────────────────────────────────────────────────
    "iPad Pro 11" => || Viewport::mobile(834, 1194, 2.0,
        "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 \
         (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"),
    "iPad Mini" => || Viewport::mobile(768, 1024, 2.0,
        "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 \
         (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"),
    "Tablet" => || Viewport::mobile(800, 1280, 2.0,
        "Mozilla/5.0 (Linux; Android 14; Tablet) AppleWebKit/537.36 (KHTML, like Gecko) \
         Chrome/128.0.0.0 Safari/537.36"),
    // ── Desktop / laptop ─────────────────────────────────────────────
    "Desktop 1080p" => || Viewport::custom(1920, 1080),
    "Desktop 1440p" => || Viewport::custom(2560, 1440),
    "Laptop" => || Viewport::custom(1366, 768),
};

/// Look up a named device preset (e.g. `"iPhone 16 Pro Max"`, `"iPad Mini"`,
/// `"Desktop 1080p"`). Matching is case-insensitive and ignores
/// leading/trailing whitespace; `None` if no preset matches.
pub fn preset(name: &str) -> Option<Viewport> {
    let needle = name.trim();
    PRESETS
        .iter()
        .find(|p| p.name.eq_ignore_ascii_case(needle))
        .map(|p| (p.viewport)())
}

/// All preset names, in table order — for building a picker UI, a CLI
/// `--help`, or an MCP `list_device_presets` response.
pub fn preset_names() -> Vec<&'static str> {
    PRESETS.iter().map(|p| p.name).collect()
}

/// All presets with their resolved [`Viewport`], in table order.
pub fn all_presets() -> Vec<(&'static str, Viewport)> {
    PRESETS.iter().map(|p| (p.name, (p.viewport)())).collect()
}

/// Where to scroll before a [`crate::internal::browser::page::Bbox`] capture.
///
/// This lets a fixed viewport be paged through and a specific on-screen region
/// be cropped from wherever it lands.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ScrollTarget {
    /// Scroll to `n` viewport-heights from the top of the page (the height
    /// of whatever viewport is active at capture time). `2.0` = "scrolled
    /// down twice" — the same amount a human hitting Page Down twice from
    /// the top would land on. Fractional values scroll partway.
    Viewports(f64),
    /// Scroll to an absolute pixel Y from the top of the page.
    Pixels(i64),
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "test harness"
)]
mod tests {
    use super::*;

    #[test]
    fn preset_lookup_is_case_insensitive_and_trims() {
        let a = preset("iPhone 16 Pro Max").expect("known preset");
        let b = preset("  iphone 16 pro max  ").expect("case-insensitive match");
        assert_eq!(a, b);
        assert!(preset("Nokia 3310 Pro").is_none());
    }

    #[test]
    fn desktop_presets_are_not_mobile() {
        let vp = preset("Desktop 1080p").expect("known preset");
        assert!(!vp.mobile);
        assert!(!vp.has_touch);
        assert_eq!((vp.width, vp.height), (1920, 1080));
    }

    #[test]
    fn phone_presets_are_mobile_with_touch_and_ua() {
        let vp = preset("Pixel 7").expect("known preset");
        assert!(vp.mobile);
        assert!(vp.has_touch);
        assert!(vp.user_agent.is_some());
    }

    #[test]
    fn preset_names_match_table_and_are_all_resolvable() {
        let names = preset_names();
        assert_eq!(names.len(), PRESETS.len());
        for name in names {
            assert!(preset(name).is_some(), "preset {name:?} should resolve");
        }
    }
}
