"""Read complete catalog results from their saved inputs and event log."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from edsim.arrivals.profile import load_profile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import (
    RunAnalysis,
    analyze_run,
    completed_in_window,
    episode_table,
    hourly_means_by_day,
)
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.events import read_events
from edsim.engine.invariants import Violation, check_invariants
from edsim.runs.metrics import WindowCompliance, WindowKPIs, window_compliance, window_kpis
from edsim.runs.store import RunInfo, RunStore


class RunReadError(ValueError):
    """A saved input cannot be read or is not valid."""


class RunAnalysisError(ValueError):
    """The saved log has no completed episodes in its observation window."""


@dataclass(frozen=True, slots=True)
class RunResults:
    """Results shared read-only by consumers; arrays must never be edited in place.

    hourly_census contains 24 clock-hour time means in the observation window.
    violations is None when the saved zero count made recalculation unnecessary;
    an empty tuple means a positive saved count was rechecked with no violations.
    """

    info: RunInfo
    center: CenterConfig
    start_date: date
    analysis: RunAnalysis
    kpis: WindowKPIs
    compliance: WindowCompliance
    hourly_census: NDArray[np.float64]
    violations: tuple[Violation, ...] | None


def read_run_header(store: RunStore, run_id: str) -> tuple[RunInfo, str]:
    """Open metadata on every call and fingerprint its exact bytes for caching."""
    try:
        store._file(run_id, "run.json")
        info = store.open(run_id)
        fingerprint = sha256(store.read_file(run_id, "run.json")).hexdigest()
    except (OSError, ValueError) as error:
        raise RunReadError(f"{store.root / run_id / 'run.json'}: {error}") from error
    return info, fingerprint


def _read_input[T](store: RunStore, run_id: str, name: str, loader: Callable[[Path], T]) -> T:
    """Wrap input failures narrowly, leaving analysis failures untouched."""
    try:
        return loader(store._file(run_id, name))
    except (OSError, ValueError) as error:
        raise RunReadError(f"{store.root / run_id / name}: {error}") from error


def read_run_results(store: RunStore, run_id: str) -> RunResults:
    """Analyze exact saved inputs without reading ground truth or original paths."""
    info, _ = read_run_header(store, run_id)
    center = _read_input(store, run_id, "centro.toml", load_center)
    profile = _read_input(store, run_id, "llegadas.toml", load_profile)
    events = _read_input(store, run_id, "eventos.jsonl", lambda path: list(read_events(path)))
    start, end = info.warmup_days * MINUTES_PER_DAY, info.days * MINUTES_PER_DAY
    if not completed_in_window(episode_table(events), start, end):
        raise RunAnalysisError(
            "La ventana no tiene episodios completados. "
            "El log puede haberse modificado fuera de la app."
        )
    analysis = analyze_run(events, center, info.days, info.warmup_days)
    violations = tuple(check_invariants(events, center)) if info.invariant_violations else None
    return RunResults(
        info=info,
        center=center,
        start_date=profile.start_date,
        analysis=analysis,
        kpis=window_kpis(analysis.table, analysis.metrics),
        compliance=window_compliance(analysis.table, info.warmup_days, info.days),
        hourly_census=hourly_means_by_day(analysis.curves, "census", start, end).mean(axis=0),
        violations=violations,
    )
