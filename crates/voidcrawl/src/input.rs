//! Humanized pointer paths for CDP mouse input (CAS-147).
//!
//! Pure, dependency-free generation of a realistic cursor trajectory between
//! two points, emitted as a sequence of `Input.dispatchMouseEvent` `MouseMoved`
//! steps before the press. The path has **non-linear (arc) curvature**, a
//! **minimum-jerk** velocity profile (slow start/stop), small **tremor**, and
//! an optional **dwell** on the target — the traits a managed challenge looks
//! for in real pointer input. No page-world JS is injected; only CDP events.
//!
//! Generation is deterministic under a seeded [`Rng`] so it can be unit-tested
//! exactly; the live path seeds from wall-clock entropy at the call site.

/// One step along a humanized path: an absolute target plus the delay to wait
/// *before* dispatching it (ms).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PathStep {
    pub x: f64,
    pub y: f64,
    pub delay_ms: u64,
}

/// Shape/timing knobs for [`humanized_path`].
#[derive(Debug, Clone, Copy)]
pub struct HumanizeOptions {
    /// Max perpendicular bow of the arc, in px (actual is randomized within ±).
    pub curve: f64,
    /// Per-step tremor amplitude, in px (damped toward the target).
    pub tremor: f64,
    /// Pause on the target before the press, in ms (a final dwell step).
    pub dwell_ms: u64,
    /// Total movement duration floor, in ms.
    pub min_duration_ms: f64,
    /// Total movement duration ceiling, in ms — keeps agent workflows bounded.
    pub max_duration_ms: f64,
}

impl Default for HumanizeOptions {
    fn default() -> Self {
        Self {
            curve: 22.0,
            tremor: 1.1,
            dwell_ms: 55,
            min_duration_ms: 120.0,
            max_duration_ms: 900.0,
        }
    }
}

/// SplitMix64 — a tiny deterministic PRNG. Avoids a `rand` dependency and makes
/// path generation reproducible from a seed (for tests).
#[derive(Debug, Clone)]
pub struct Rng(u64);

impl Rng {
    #[must_use]
    pub const fn seed(seed: u64) -> Self {
        Self(seed)
    }

    const fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Uniform in `[0, 1)`.
    fn unit(&mut self) -> f64 {
        // The 53-bit value is exactly representable as an f64. Parsing the
        // decimal integer keeps the conversion explicit and checked.
        let numerator = (self.next_u64() >> 11)
            .to_string()
            .parse::<f64>()
            .unwrap_or(0.0);
        numerator / 9_007_199_254_740_992.0
    }

    /// Uniform in `[lo, hi)`.
    fn range(&mut self, lo: f64, hi: f64) -> f64 {
        let unit = self.unit();
        unit.mul_add(hi, (-unit).mul_add(lo, lo))
    }
}

fn rounded_u64(value: f64) -> u64 {
    if !value.is_finite() || value <= 0.0 {
        return 0;
    }
    format!("{value:.0}").parse().unwrap_or_default()
}

/// Minimum-jerk easing `6t^5 - 15t^4 + 10t^3` (smootherstep): zero velocity and
/// acceleration at both ends, like a real hand starting and stopping.
fn min_jerk(t: f64) -> f64 {
    t * t * t * t.mul_add(t.mul_add(6.0, -15.0), 10.0)
}

/// Generate a humanized cursor path from `start` to `end`.
///
/// Returns at least a couple of `MouseMoved` steps (more for longer travel),
/// the **last of which lands exactly on `end`**, optionally followed by a dwell
/// step (same coords, `dwell_ms`). Total of all `delay_ms` is bounded by
/// `opts.max_duration_ms` (+ the dwell).
#[must_use]
pub fn humanized_path(
    start: (f64, f64),
    end: (f64, f64),
    opts: &HumanizeOptions,
    rng: &mut Rng,
) -> Vec<PathStep> {
    let (x0, y0) = start;
    let (x1, y1) = end;
    let (dx, dy) = (x1 - x0, y1 - y0);
    let dist = dx.hypot(dy);

    // Step count and duration both scale with distance, then clamp.
    let steps = usize::try_from(rounded_u64((dist / 9.0).round()).clamp(6, 40)).unwrap_or(40);
    let duration = dist
        .mul_add(1.6, opts.min_duration_ms)
        .clamp(opts.min_duration_ms, opts.max_duration_ms);

    // Perpendicular unit vector for the arc bow (zero for a zero-length move).
    let (nx, ny) = if dist > 1e-6 {
        (-dy / dist, dx / dist)
    } else {
        (0.0, 0.0)
    };
    let bow = rng.range(-opts.curve, opts.curve);

    let mut out = Vec::with_capacity(steps.saturating_add(1));
    let mut prev_e = 0.0_f64;
    for i in 1..=steps {
        let t = i.to_string().parse::<f64>().unwrap_or(0.0)
            / steps.to_string().parse::<f64>().unwrap_or(1.0);
        let e = min_jerk(t);
        // Arc weight peaks at the midpoint, vanishes at both ends.
        let arc = bow
            * 2.0f64
                .mul_add(e, -1.0)
                .mul_add(-2.0f64.mul_add(e, -1.0), 1.0);
        // Tremor: damped toward the target for a clean final landing.
        let damp = 0.65f64.mul_add(-e, 1.0);
        let jx = rng.range(-opts.tremor, opts.tremor) * damp;
        let jy = rng.range(-opts.tremor, opts.tremor) * damp;
        // Per-step delay follows the same min-jerk profile (fast in the middle).
        let delay = rounded_u64(((e - prev_e) * duration).max(1.0).round());
        prev_e = e;
        out.push(PathStep {
            x: nx.mul_add(arc, dx.mul_add(e, x0)) + jx,
            y: ny.mul_add(arc, dy.mul_add(e, y0)) + jy,
            delay_ms: delay,
        });
    }
    // Land exactly on target (no residual tremor on the final position).
    if let Some(last) = out.last_mut() {
        last.x = x1;
        last.y = y1;
    }
    // Optional dwell on the target before the press.
    if opts.dwell_ms > 0 {
        out.push(PathStep {
            x: x1,
            y: y1,
            delay_ms: opts.dwell_ms,
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const A: (f64, f64) = (0.0, 0.0);
    const B: (f64, f64) = (300.0, 200.0);

    #[test]
    fn seeded_generation_is_deterministic() {
        let opts = HumanizeOptions::default();
        let p1 = humanized_path(A, B, &opts, &mut Rng::seed(42));
        let p2 = humanized_path(A, B, &opts, &mut Rng::seed(42));
        assert_eq!(p1, p2);
    }

    #[test]
    fn different_seeds_differ() {
        let opts = HumanizeOptions::default();
        let p1 = humanized_path(A, B, &opts, &mut Rng::seed(1));
        let p2 = humanized_path(A, B, &opts, &mut Rng::seed(2));
        assert_ne!(p1, p2);
    }

    #[test]
    fn emits_multiple_moves_and_lands_exactly_on_target() {
        let opts = HumanizeOptions::default();
        let path = humanized_path(A, B, &opts, &mut Rng::seed(7));
        // Several moves before the press (dwell is the last step here).
        assert!(path.len() >= 6, "got {} steps", path.len());
        // The move that places the cursor on target is exact.
        let move_steps = &path[..path.len() - 1];
        assert_ne!(
            move_steps,
            [],
            "humanized path should include movement steps"
        );
        let landing = move_steps[move_steps.len() - 1];
        assert!((landing.x - B.0).abs() < 1e-9 && (landing.y - B.1).abs() < 1e-9);
    }

    #[test]
    fn duration_is_bounded() {
        let opts = HumanizeOptions::default();
        // A very long travel still stays within the ceiling (+ dwell).
        let path = humanized_path((0.0, 0.0), (5000.0, 5000.0), &opts, &mut Rng::seed(3));
        let total: u64 = path.iter().map(|s| s.delay_ms).sum();
        let ceiling = rounded_u64(opts.max_duration_ms)
            .saturating_add(opts.dwell_ms)
            .saturating_add(u64::try_from(path.len()).unwrap_or(u64::MAX));
        assert!(total <= ceiling, "total {total} > ceiling {ceiling}");
    }

    #[test]
    fn path_is_curved_not_straight() {
        // A no-tremor, fixed-bow path should bow off the straight line at the mid.
        let opts = HumanizeOptions {
            tremor: 0.0,
            dwell_ms: 0,
            ..Default::default()
        };
        let path = humanized_path(A, B, &opts, &mut Rng::seed(11));
        let mid = path[path.len() / 2];
        // Distance of the midpoint from the straight A→B line.
        let (dx, dy) = (B.0 - A.0, B.1 - A.1);
        let len = dx.hypot(dy);
        let dev = (mid.y - A.1).mul_add(-dx, (mid.x - A.0) * dy).abs() / len;
        assert!(
            dev > 1.0,
            "midpoint deviation {dev} too small — path is ~straight"
        );
    }
}
