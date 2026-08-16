"""Immutable snapshot cursors.

Every stage used to call latest_capture(), which silently picked the newest directory.
That made the whole scoreboard float: a re-capture silently re-based every number, and
two "results" could refer to different bytes. Nothing was comparable and nothing said so.

A cursor is (target, capture_id) and it is always explicit. Resolution order:
    1. an explicit capture_id passed by the caller
    2. pins.toml — the recorded snapshot set, written by an explicit `pin` action
    3. ERROR. There is no implicit "latest".

Pinning is a deliberate operation you run once and commit. That is what makes a
measurement re-runnable against the same bytes months later.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
CAPTURES = HERE / "captures"
PINS = HERE / "pins.toml"


class CursorError(RuntimeError):
    """Raised when a snapshot cannot be identified unambiguously."""


@dataclass(frozen=True)
class Cursor:
    target: str
    capture_id: str
    path: Path

    def artifact(self, name: str) -> Path:
        p = self.path / name
        if not p.exists():
            raise CursorError(
                f"{self.target}@{self.capture_id} has no {name!r}. "
                f"Present: {sorted(x.name for x in self.path.iterdir())}"
            )
        return p

    def __str__(self) -> str:
        return f"{self.target}@{self.capture_id}"


def list_captures(target: str) -> list[str]:
    d = CAPTURES / target
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def load_pins() -> dict[str, str]:
    if not PINS.exists():
        return {}
    return dict(tomllib.loads(PINS.read_text()).get("pin", {}))


def resolve(target: str, capture_id: str | None = None) -> Cursor:
    """Resolve a cursor or raise. Never guesses."""
    available = list_captures(target)
    if not available:
        raise CursorError(f"no captures for {target!r} — run capture.py first")

    chosen = capture_id or load_pins().get(target)
    if chosen is None:
        raise CursorError(
            f"no cursor for {target!r}. Pass --capture <id> or pin it in pins.toml.\n"
            f"  available: {', '.join(available)}\n"
            f"  pin all:   uv run python cursor.py --pin-latest"
        )
    if chosen not in available:
        raise CursorError(f"{target}@{chosen} does not exist. Available: {', '.join(available)}")
    return Cursor(target=target, capture_id=chosen, path=CAPTURES / target / chosen)


def write_pins(pins: dict[str, str]) -> None:
    lines = [
        "# Immutable snapshot set. Every measurement resolves through this file.",
        "# Re-pinning re-bases every number — do it deliberately, never as a side effect.",
        "",
        "[pin]",
    ]
    lines += [f'{t} = "{c}"' for t, c in sorted(pins.items())]
    PINS.write_text("\n".join(lines) + "\n")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Inspect or set snapshot cursors.")
    ap.add_argument("--pin-latest", action="store_true", help="pin newest capture per target")
    ap.add_argument("--show", action="store_true", help="show current pins")
    args = ap.parse_args()

    if args.pin_latest:
        pins = {}
        for d in sorted(CAPTURES.iterdir()) if CAPTURES.is_dir() else []:
            caps = list_captures(d.name)
            if caps:
                pins[d.name] = caps[-1]
        write_pins(pins)
        print(f"pinned {len(pins)} targets → {PINS.name}")

    for t, c in sorted(load_pins().items()):
        print(f"  {t:<28} {c}")


if __name__ == "__main__":
    main()
