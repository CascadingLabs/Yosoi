//! Browser-native target resolution for screenshots, recordings, masks, and
//! other geometry-aware operations.
//!
//! [`BrowserTarget`] and [`BrowserTargetKind`] are VoidCrawl-owned provider
//! primitives. Higher-level selector or recipe models translate into this
//! shape at their adapter boundary. [`Page::resolve_target`] performs the CDP
//! round-trips needed to resolve one target into a CSS-pixel rectangle.
//!
//! ## Design: typed *responses*, not exceptions, for "nothing here"
//!
//! [`TargetResolution`] has three outcomes —
//! [`Resolved`](TargetResolution::Resolved),
//! [`Empty`](TargetResolution::Empty),
//! [`Ambiguous`](TargetResolution::Ambiguous) — and all three are `Ok(...)`.
//! A selector that matches nothing, or a kind this module doesn't resolve to a
//! rectangle (`jsonld`, `regex` — see below), is exactly as valid an outcome as
//! a match: the caller decides what "nothing here" means for their workflow
//! instead of catching an exception. `Err` is reserved for genuine infra
//! failures (a CDP call failed, the page evaluated to a JS exception) — never
//! for "no match."
//!
//! [`Page::screenshot`](crate::Page::screenshot)'s convenience `selector`
//! option is the one place this gets converted to an `Err`: a screenshot
//! fundamentally needs a rectangle, so `Empty`/`Ambiguous` there become
//! actionable typed errors ([`VoidCrawlError::ElementNotVisible`] /
//! [`VoidCrawlError::AmbiguousSelector`]) rather than silently cropping an
//! arbitrary target.
//!
//! ## Per-kind resolution
//!
//! | kind | resolution |
//! |---|---|
//! | `css` | `document.querySelectorAll(value)` |
//! | `xpath` | `document.evaluate(value, ...)` ordered node snapshot |
//! | `attr` | same as `css`; `name` is metadata (which attribute holds the datum), not part of the DOM query |
//! | `global_id` | same as `css`, filtered to elements whose `id` starts with `name` (the shared ID-token prefix) when `name` is set |
//! | `role` | `Accessibility.queryAXTree` role + accessible name (exact match, `nth`-disambiguated) — the same semantics as [`Page::click_by_role`](crate::Page::click_by_role) |
//! | `visual` | exact 1x1 CSS-pixel box at `(x, y)` — no invented hit-radius |
//! | `jsonld` | always [`Empty`](TargetResolution::Empty) — a JSON-LD value lives in a `<script>` tag, which has no render box; this bbox surface is inherently visual, so it doesn't attempt to resolve non-visual data |
//! | `regex` | always [`Empty`](TargetResolution::Empty) — a raw-HTML text match has no canonical DOM element; not resolved to a visual target |
//!
//! For `css`/`xpath`/`attr`/`global_id`/`role`, candidates are filtered to
//! *visible* ones first — attached to the DOM, non-zero-area, and neither
//! `display:none` nor `visibility:hidden` — before uniqueness is judged:
//! zero visible candidates is `Empty`, exactly one is `Resolved`, and two or
//! more resolve via `nth` (0-based) or are `Ambiguous` without it.

use serde::{Deserialize, Serialize};

use crate::{
    error::{Result, VoidCrawlError},
    page::Bbox,
};

/// Browser target strategies understood by VoidCrawl geometry operations.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserTargetKind {
    Css,
    Xpath,
    Regex,
    Jsonld,
    Attr,
    GlobalId,
    Role,
    Visual,
}

/// A provider-native browser target for geometry-aware operations.
///
/// The flat shape keeps the engine-to-Yosoi boundary compact. Which fields are
/// meaningful depends on `kind` (see the module table). `nth` is 0-based,
/// matching [`Page::click_by_role`](crate::Page::click_by_role)'s convention.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrowserTarget {
    #[serde(rename = "type")]
    pub kind: BrowserTargetKind,
    #[serde(default)]
    pub value: String,
    #[serde(default)]
    pub regex: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub nth: Option<u32>,
    #[serde(default)]
    pub x: Option<f64>,
    #[serde(default)]
    pub y: Option<f64>,
}

impl BrowserTarget {
    /// Whether this target kind can resolve to visual geometry.
    pub const fn supports_geometry(&self) -> bool {
        !matches!(
            self.kind,
            BrowserTargetKind::Jsonld | BrowserTargetKind::Regex
        )
    }

    /// Validate the target shape before any browser/CDP resolution.
    ///
    /// Reasons are static so invalid caller input is never reflected in an
    /// error. Optional `name` remains supported for compatibility, but when
    /// supplied it must identify something.
    pub fn validate(&self) -> Result<()> {
        let requires_value = !matches!(self.kind, BrowserTargetKind::Visual);
        if requires_value && self.value.is_empty() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "browser_target",
                reason: "target kind requires a non-empty selector value",
            });
        }
        if self.name.as_deref().is_some_and(str::is_empty) {
            return Err(VoidCrawlError::InvalidInput {
                operation: "browser_target",
                reason: "target name must be non-empty when supplied",
            });
        }

        match self.kind {
            BrowserTargetKind::Visual => {
                let (Some(x), Some(y)) = (self.x, self.y) else {
                    return Err(VoidCrawlError::InvalidInput {
                        operation: "browser_target",
                        reason: "visual target requires both x and y coordinates",
                    });
                };
                if !x.is_finite() || !y.is_finite() {
                    return Err(VoidCrawlError::InvalidInput {
                        operation: "browser_target",
                        reason: "visual target coordinates must be finite",
                    });
                }
                if x < 0.0 || y < 0.0 {
                    return Err(VoidCrawlError::InvalidInput {
                        operation: "browser_target",
                        reason: "visual target coordinates must be non-negative",
                    });
                }
                if self.nth.is_some() {
                    return Err(VoidCrawlError::InvalidInput {
                        operation: "browser_target",
                        reason: "visual target does not support nth",
                    });
                }
            }
            BrowserTargetKind::Jsonld | BrowserTargetKind::Regex if self.nth.is_some() => {
                return Err(VoidCrawlError::InvalidInput {
                    operation: "browser_target",
                    reason: "non-visual target does not support nth",
                });
            }
            _ => {
                if self.x.is_some() || self.y.is_some() {
                    return Err(VoidCrawlError::InvalidInput {
                        operation: "browser_target",
                        reason: "coordinates are only supported by visual targets",
                    });
                }
            }
        }
        Ok(())
    }
}

/// The outcome of resolving a [`BrowserTarget`] to a rectangle.
///
/// All three variants are a normal, successful `Ok(...)`. The module-level
/// contract explains why no match is a typed response rather than an error.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum TargetResolution {
    /// Exactly one unique, visible target was resolved.
    Resolved { bbox: Bbox },
    /// The selector is well-formed but nothing usable matched: zero
    /// elements, a matched element that's hidden/zero-area/detached, an
    /// out-of-viewport `visual` point, or a kind (`jsonld`, `regex`) this
    /// module never resolves to a rectangle.
    Empty { reason: String },
    /// Two or more visible candidates matched and `nth` wasn't given to
    /// pick one.
    Ambiguous { candidates: usize, reason: String },
}

/// Compatibility alias for the pre-CAS-321 name.
#[deprecated(note = "use BrowserTargetKind")]
pub type SelectorKind = BrowserTargetKind;
/// Compatibility alias for the pre-CAS-321 name.
#[deprecated(note = "use BrowserTarget")]
pub type SelectorEntry = BrowserTarget;
/// Compatibility alias for the pre-CAS-321 name.
#[deprecated(note = "use TargetResolution")]
pub type SelectorResolution = TargetResolution;

/// Build the JS expression that gathers this selector's raw DOM candidates,
/// as a JS array of `Element`s — before visibility filtering. `None` for
/// kinds with no DOM candidate-gathering step (`role`, `visual`, `jsonld`,
/// `regex` — each of those is handled without this helper).
pub(crate) fn candidates_js(entry: &BrowserTarget) -> Option<String> {
    match entry.kind {
        BrowserTargetKind::Css | BrowserTargetKind::Attr => Some(format!(
            "Array.from(document.querySelectorAll({:?}))",
            entry.value
        )),
        BrowserTargetKind::GlobalId => {
            let base = format!("Array.from(document.querySelectorAll({:?}))", entry.value);
            match &entry.name {
                Some(prefix) => Some(format!(
                    "{base}.filter(el => (el.id || '').startsWith({prefix:?}))"
                )),
                None => Some(base),
            }
        }
        BrowserTargetKind::Xpath => Some(format!(
            "(() => {{ \
               const r = document.evaluate({:?}, document, null, \
                 XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); \
               const out = []; \
               for (let i = 0; i < r.snapshotLength; i++) out.push(r.snapshotItem(i)); \
               return out; \
             }})()",
            entry.value
        )),
        BrowserTargetKind::Role
        | BrowserTargetKind::Visual
        | BrowserTargetKind::Jsonld
        | BrowserTargetKind::Regex => None,
    }
}

/// Wrap a candidate-gathering expression (from [`candidates_js`]) in the
/// shared visibility filter + rect-extraction tail. Returns a JS array of
/// `{x, y, width, height}` (CSS pixels, viewport-relative — the same frame
/// [`Bbox`] already uses) for every *visible* candidate, in DOM order:
/// attached to the document, non-zero area, and neither `display:none` nor
/// `visibility:hidden`.
pub(crate) fn visible_rects_js(candidates_expr: &str) -> String {
    format!(
        "(() => {{ \
           const els = {candidates_expr}; \
           return els.filter(el => {{ \
             if (!el || !el.isConnected) return false; \
             const style = window.getComputedStyle(el); \
             if (!style || style.display === 'none' || style.visibility === 'hidden') return false; \
             const r = el.getBoundingClientRect(); \
             return r.width > 0 && r.height > 0; \
           }}).map(el => {{ \
             const r = el.getBoundingClientRect(); \
             return {{ x: r.x, y: r.y, width: r.width, height: r.height }}; \
           }}); \
         }})()"
    )
}

/// A raw `{x, y, width, height}` rect as returned by [`visible_rects_js`],
/// before rounding into the integer-pixel [`Bbox`] the screenshot crop path
/// wants.
#[derive(Debug, Clone, Copy, Deserialize)]
pub(crate) struct RawRect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

impl RawRect {
    /// Round to the integer CSS-pixel [`Bbox`] `Page::screenshot`'s crop
    /// path expects. Floors the origin and ceils the extent so the crop
    /// never clips a fractional-pixel edge of the target.
    pub(crate) fn to_bbox(self) -> Bbox {
        let x = self.x.floor().max(0.0);
        let y = self.y.floor().max(0.0);
        let width = (self.x + self.width - x).ceil().max(1.0);
        let height = (self.y + self.height - y).ceil().max(1.0);
        Bbox {
            x: css_pixel_u32(x),
            y: css_pixel_u32(y),
            width: css_pixel_u32(width),
            height: css_pixel_u32(height),
        }
    }
}

fn css_pixel_u32(value: f64) -> u32 {
    if !value.is_finite() || value <= 0.0 {
        return 0;
    }
    format!("{value:.0}").parse().unwrap_or(u32::MAX)
}

/// Pick the resolved outcome from a set of visible-candidate rects and an
/// optional `nth`. Shared by every DOM-candidate kind (`css`, `xpath`,
/// `attr`, `global_id`) — `role` has its own AX-specific version of this
/// same logic in `page.rs` since it disambiguates AX nodes, not rects.
pub(crate) fn pick_resolution(
    total_matches: usize,
    visible: &[RawRect],
    nth: Option<u32>,
    describe: impl Fn() -> String,
) -> TargetResolution {
    if visible.is_empty() {
        let reason = if total_matches == 0 {
            format!("{} matched no elements", describe())
        } else {
            format!(
                "{} matched {total_matches} element(s), but none are visible \
                 (hidden, zero-area, or detached)",
                describe()
            )
        };
        return TargetResolution::Empty { reason };
    }
    if let Some(n) = nth {
        return usize::try_from(n)
            .ok()
            .and_then(|index| visible.get(index))
            .map_or_else(
                || TargetResolution::Empty {
                    reason: format!(
                        "nth={n} out of range: {} visible match(es) for {}",
                        visible.len(),
                        describe()
                    ),
                },
                |rect| TargetResolution::Resolved {
                    bbox: rect.to_bbox(),
                },
            );
    }
    match visible {
        [rect] => TargetResolution::Resolved {
            bbox: rect.to_bbox(),
        },
        matches => TargetResolution::Ambiguous {
            candidates: matches.len(),
            reason: format!(
                "{} visible matches for {}; pass `nth` to disambiguate",
                matches.len(),
                describe()
            ),
        },
    }
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

    fn rect(x: f64, y: f64, w: f64, h: f64) -> RawRect {
        RawRect {
            x,
            y,
            width: w,
            height: h,
        }
    }

    fn target(kind: BrowserTargetKind) -> BrowserTarget {
        BrowserTarget {
            kind,
            value: "target".into(),
            regex: None,
            name: None,
            nth: None,
            x: None,
            y: None,
        }
    }

    #[test]
    fn validation_matrix_rejects_invalid_target_shapes() {
        let mut cases = Vec::new();

        let mut empty_css = target(BrowserTargetKind::Css);
        empty_css.value.clear();
        cases.push((empty_css, "target kind requires a non-empty selector value"));

        let mut empty_name = target(BrowserTargetKind::Role);
        empty_name.name = Some(String::new());
        cases.push((empty_name, "target name must be non-empty when supplied"));

        cases.push((
            target(BrowserTargetKind::Visual),
            "visual target requires both x and y coordinates",
        ));

        let mut non_finite = target(BrowserTargetKind::Visual);
        non_finite.x = Some(f64::NAN);
        non_finite.y = Some(1.0);
        cases.push((non_finite, "visual target coordinates must be finite"));

        let mut negative = target(BrowserTargetKind::Visual);
        negative.x = Some(-1.0);
        negative.y = Some(1.0);
        cases.push((negative, "visual target coordinates must be non-negative"));

        let mut visual_nth = target(BrowserTargetKind::Visual);
        visual_nth.x = Some(1.0);
        visual_nth.y = Some(1.0);
        visual_nth.nth = Some(0);
        cases.push((visual_nth, "visual target does not support nth"));

        let mut regex_nth = target(BrowserTargetKind::Regex);
        regex_nth.nth = Some(0);
        cases.push((regex_nth, "non-visual target does not support nth"));

        let mut css_coordinates = target(BrowserTargetKind::Css);
        css_coordinates.x = Some(1.0);
        cases.push((
            css_coordinates,
            "coordinates are only supported by visual targets",
        ));

        for (entry, reason) in cases {
            match entry.validate() {
                Err(VoidCrawlError::InvalidInput {
                    operation,
                    reason: actual,
                }) => {
                    assert_eq!(operation, "browser_target");
                    assert_eq!(actual, reason);
                }
                other => panic!("expected InvalidInput, got {other:?}"),
            }
        }
    }

    #[test]
    fn validation_preserves_documented_optional_name_compatibility() {
        for kind in [
            BrowserTargetKind::Attr,
            BrowserTargetKind::GlobalId,
            BrowserTargetKind::Role,
        ] {
            assert!(
                target(kind).validate().is_ok(),
                "{kind:?} name remains optional"
            );
        }
    }

    #[test]
    #[allow(deprecated)]
    fn legacy_selector_type_names_remain_source_compatible() {
        let kind: SelectorKind = BrowserTargetKind::Css;
        let target: SelectorEntry = BrowserTarget {
            kind,
            value: "h1".into(),
            regex: None,
            name: None,
            nth: None,
            x: None,
            y: None,
        };
        let resolution: SelectorResolution = TargetResolution::Empty {
            reason: "test".into(),
        };

        assert_eq!(target.kind, BrowserTargetKind::Css);
        assert!(matches!(resolution, TargetResolution::Empty { .. }));
    }

    #[test]
    fn candidates_js_css_and_attr_use_plain_query_selector_all() {
        let css = BrowserTarget {
            kind: BrowserTargetKind::Css,
            value: "h1".into(),
            regex: None,
            name: None,
            nth: None,
            x: None,
            y: None,
        };
        let js = candidates_js(&css).expect("css produces a candidate expression");
        assert!(js.contains("querySelectorAll"));
        assert!(js.contains("\"h1\""));
    }

    #[test]
    fn candidates_js_global_id_filters_by_prefix() {
        let entry = BrowserTarget {
            kind: BrowserTargetKind::GlobalId,
            value: "tr.athing".into(),
            regex: None,
            name: Some("score_".into()),
            nth: None,
            x: None,
            y: None,
        };
        let js = candidates_js(&entry).expect("global_id produces a candidate expression");
        assert!(js.contains("startsWith"));
        assert!(js.contains("\"score_\""));
    }

    #[test]
    fn candidates_js_role_visual_jsonld_regex_are_none() {
        for kind in [
            BrowserTargetKind::Role,
            BrowserTargetKind::Visual,
            BrowserTargetKind::Jsonld,
            BrowserTargetKind::Regex,
        ] {
            let entry = BrowserTarget {
                kind,
                value: String::new(),
                regex: None,
                name: None,
                nth: None,
                x: None,
                y: None,
            };
            assert!(
                candidates_js(&entry).is_none(),
                "{kind:?} should have no DOM candidate step"
            );
        }
    }

    #[test]
    fn pick_resolution_zero_matches_is_empty_with_zero_reason() {
        let outcome = pick_resolution(0, &[], None, || "css \"h1\"".into());
        match outcome {
            TargetResolution::Empty { reason } => assert!(reason.contains("matched no elements")),
            other => panic!("expected Empty, got {other:?}"),
        }
    }

    #[test]
    fn pick_resolution_matches_but_none_visible_is_empty_with_visibility_reason() {
        let outcome = pick_resolution(3, &[], None, || "css \".x\"".into());
        match outcome {
            TargetResolution::Empty { reason } => {
                assert!(reason.contains("none are visible"), "got: {reason}");
            }
            other => panic!("expected Empty, got {other:?}"),
        }
    }

    #[test]
    fn pick_resolution_single_visible_is_resolved() {
        let outcome = pick_resolution(1, &[rect(1.0, 2.0, 10.0, 20.0)], None, || "x".into());
        match outcome {
            TargetResolution::Resolved { bbox } => {
                assert_eq!(
                    bbox,
                    Bbox {
                        x: 1,
                        y: 2,
                        width: 10,
                        height: 20
                    }
                );
            }
            other => panic!("expected Resolved, got {other:?}"),
        }
    }

    #[test]
    fn pick_resolution_multiple_without_nth_is_ambiguous() {
        let outcome = pick_resolution(
            2,
            &[rect(0.0, 0.0, 5.0, 5.0), rect(10.0, 10.0, 5.0, 5.0)],
            None,
            || "css \".x\"".into(),
        );
        match outcome {
            TargetResolution::Ambiguous { candidates, .. } => assert_eq!(candidates, 2),
            other => panic!("expected Ambiguous, got {other:?}"),
        }
    }

    #[test]
    fn pick_resolution_multiple_with_nth_resolves_that_index() {
        let outcome = pick_resolution(
            2,
            &[rect(0.0, 0.0, 5.0, 5.0), rect(10.0, 10.0, 6.0, 7.0)],
            Some(1),
            || "css \".x\"".into(),
        );
        match outcome {
            TargetResolution::Resolved { bbox } => {
                assert_eq!(
                    bbox,
                    Bbox {
                        x: 10,
                        y: 10,
                        width: 6,
                        height: 7
                    }
                );
            }
            other => panic!("expected Resolved, got {other:?}"),
        }
    }

    #[test]
    fn pick_resolution_nth_out_of_range_is_empty() {
        let outcome = pick_resolution(1, &[rect(0.0, 0.0, 5.0, 5.0)], Some(5), || {
            "css \".x\"".into()
        });
        match outcome {
            TargetResolution::Empty { reason } => assert!(reason.contains("out of range")),
            other => panic!("expected Empty, got {other:?}"),
        }
    }

    #[test]
    fn raw_rect_to_bbox_rounds_outward() {
        let bbox = RawRect {
            x: 1.2,
            y: 2.8,
            width: 10.1,
            height: 5.9,
        }
        .to_bbox();
        // origin floors to 1,2; far edge is 1.2+10.1=11.3 -> ceil width from
        // floored origin = ceil(11.3 - 1) = 11; 2.8+5.9=8.7 -> ceil(8.7-2)=7.
        assert_eq!(
            bbox,
            Bbox {
                x: 1,
                y: 2,
                width: 11,
                height: 7
            }
        );
    }
}
