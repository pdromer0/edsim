"""Read complete catalog results from their saved inputs and event log."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
from edsim.engine.events import OUTCOME_SCHEMA_VERSION, read_events
from edsim.engine.ground_truth import GroundTruth
from edsim.engine.invariants import Violation, check_invariants
from edsim.engine.outcome_metrics import WindowOutcome, window_outcome
from edsim.profiles.config import ClinicalProfiles, load_profiles
from edsim.runs._truth_csv import read_clinical_episodes, read_days
from edsim.runs.episodes import ObservedProfile, observed_profiles
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
    model is that of run.json; profiles are the clinical profiles loaded from
    the run's own copy (``perfiles.toml``), or None with the provisional model.
    observed holds the observable profile of each episode, read from the log
    and never from the ground truth (None with the provisional model).
    outcome holds the indicators of the abandonment, the destinations and the
    wait for a bed of the window (task 5.4), only with a log of version 4.
    """

    info: RunInfo
    center: CenterConfig
    start_date: date
    analysis: RunAnalysis
    kpis: WindowKPIs
    compliance: WindowCompliance
    hourly_census: NDArray[np.float64]
    violations: tuple[Violation, ...] | None
    model: Literal["provisional", "clinico"]
    profiles: ClinicalProfiles | None
    observed: Mapping[str, ObservedProfile] | None
    outcome: WindowOutcome | None = None


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


def _saved_ground_truth(
    store: RunStore, run_id: str, info: RunInfo, start_date: date
) -> GroundTruth:
    """The ground truth of a clinical run, episodes and days, read from its CSVs."""
    try:
        episodes = read_clinical_episodes(store, run_id, info)
        days = read_days(store, run_id, info, start_date)
    except ValueError as error:
        raise RunReadError(str(error)) from error
    return GroundTruth(tuple(episodes.values()), days)


def _recount(
    store: RunStore,
    info: RunInfo,
    events: list,
    center: CenterConfig,
    profiles: ClinicalProfiles | None,
    start_date: date,
) -> tuple[Violation, ...] | None:
    """Recheck the invariants only when run.json saved some violation.

    A provisional run is rechecked with its log alone, as before. A clinical
    run is rechecked as the simulation checked it: with its ground truth
    (episodes and days, needed for the shift band of each order) and its
    profiles. The SimPy count of live processes (``inside``) is not saved, so
    that comparison of ``conservation`` cannot be repeated.
    """
    if not info.invariant_violations:
        return None
    if profiles is None:
        return tuple(check_invariants(events, center))
    ground_truth = _saved_ground_truth(store, info.run_id, info, start_date)
    return tuple(check_invariants(events, center, ground_truth=ground_truth, profiles=profiles))


def read_run_results(store: RunStore, run_id: str) -> RunResults:
    """Analyze exact saved inputs without reading original paths.

    The ground truth is read only to recount the violations of a clinical run
    that saved some; it is not part of the results.
    """
    info, _ = read_run_header(store, run_id)
    center = _read_input(store, run_id, "centro.toml", load_center)
    profile = _read_input(store, run_id, "llegadas.toml", load_profile)
    profiles = (
        _read_input(store, run_id, "perfiles.toml", load_profiles) if info.is_clinical else None
    )
    events = _read_input(store, run_id, "eventos.jsonl", lambda path: list(read_events(path)))
    start, end = info.warmup_days * MINUTES_PER_DAY, info.days * MINUTES_PER_DAY
    if not completed_in_window(episode_table(events), start, end):
        raise RunAnalysisError(
            "La ventana no tiene episodios completados. "
            "El log puede haberse modificado fuera de la app."
        )
    analysis = analyze_run(events, center, info.days, info.warmup_days)
    violations = _recount(store, info, events, center, profiles, profile.start_date)
    return RunResults(
        info=info,
        center=center,
        start_date=profile.start_date,
        analysis=analysis,
        kpis=window_kpis(analysis.table, analysis.metrics),
        compliance=window_compliance(analysis.table, info.warmup_days, info.days),
        hourly_census=hourly_means_by_day(analysis.curves, "census", start, end).mean(axis=0),
        violations=violations,
        model=info.model,
        profiles=profiles,
        observed=None if profiles is None else observed_profiles(events, profiles.population),
        outcome=(
            window_outcome(analysis.table, analysis.curves, start, end)
            if info.catalog_version == OUTCOME_SCHEMA_VERSION
            else None
        ),
    )
