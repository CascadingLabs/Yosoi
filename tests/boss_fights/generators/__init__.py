"""Deterministic artifact generators for scale workloads.

A 10,000-row page is the case the body reducer exists for, but freezing one costs a
megabyte in the repository and the large-file hook rejects it. These generators are pure
functions of their parameters, so the artifact is reproducible from the manifest instead of
stored — and the same function can mint the 1,000-row control the scaling gate compares
against.
"""

from __future__ import annotations

from tests.boss_fights.generators.repeat_table import render_repeat_table

__all__ = ['render_repeat_table']
