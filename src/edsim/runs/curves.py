"""Exact time means, maxima and clipped steps for presentation windows."""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from edsim.engine.analysis import CURVES, StepCurves


@dataclass(frozen=True, slots=True)
class CurveBlocks:
    """Edges in minutes and one exact mean/maximum per half-open block."""

    edges: NDArray[np.float64]
    mean: NDArray[np.float64]
    maximum: NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class CurveSteps:
    """Clipped edges in minutes and the value holding between adjacent edges."""

    edges: NDArray[np.float64]
    values: NDArray[np.int64]


def _check(curves: StepCurves, name: str, start: float, end: float) -> None:
    if name not in CURVES:
        raise ValueError(f"unknown curve: {name!r}")
    if not 0 <= start < end <= curves.horizon:
        raise ValueError("need 0 <= start < end <= horizon")


def curve_steps(curves: StepCurves, name: str, start: float, end: float) -> CurveSteps:
    """Clip to [start, end), including the step already in force at start."""
    _check(curves, name, start, end)
    first = int(np.searchsorted(curves.times, start, side="right")) - 1
    stop = int(np.searchsorted(curves.times, end, side="left"))
    edges = np.concatenate(([float(start)], curves.times[first + 1 : stop], [float(end)]))
    return CurveSteps(edges, curves[name][first:stop].copy())


def curve_blocks(
    curves: StepCurves, name: str, start: float, end: float, *, block_minutes: float = 15.0
) -> CurveBlocks:
    """Integrate exact means and retain maxima, including each block's initial value.

    Times and width are minutes. A short final block uses its actual duration.
    Changes exactly at a block's right edge belong to the next block only.
    """
    _check(curves, name, start, end)
    if isinstance(block_minutes, bool) or not math.isfinite(block_minutes) or block_minutes <= 0:
        raise ValueError("block_minutes must be finite and positive")
    edges = np.append(np.arange(start, end, block_minutes, dtype=float), float(end))
    cumulative = np.concatenate(([0.0], np.cumsum(np.diff(curves.edges) * curves[name])))
    mean = np.diff(np.interp(edges, curves.edges, cumulative)) / np.diff(edges)
    first = np.searchsorted(curves.times, edges[:-1], side="right") - 1
    stop = np.searchsorted(curves.times, edges[1:], side="left")
    maximum = np.array(
        [curves[name][a:b].max() for a, b in zip(first, stop, strict=True)], dtype=np.int64
    )
    return CurveBlocks(edges, mean, maximum)
