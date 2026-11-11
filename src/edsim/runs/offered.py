"""Minute-by-minute offered work with finite-sample prehistory."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.signal import fftconvolve

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY, cumulative_rate, rate
from edsim.arrivals.thinning import ArrivalRecord
from edsim.checks import check_count
from edsim.engine.center import CenterConfig, require_provisional
from edsim.engine.clinical import PatientDraws, triage_duration
from edsim.engine.clinical_sampler import (
    N_SAMPLER_STREAMS,
    ClinicalSampler,
    PatientModel,
    choose_model,
)
from edsim.engine.shifts import shift_at
from edsim.engine.validation import _held_intervals, draws_sample, offered_load_by_pool
from edsim.profiles.config import N_DAY_TYPES, N_SEASONS, ClinicalProfiles
from edsim.profiles.context import context_indices
from edsim.seeds import child_streams

_POOLS = ("medicos", "boxes", "enfermeria_triaje")

OFFERED_PRIOR_CAP_DAYS = 7
"""Days before ``start_date`` over which the clinical sample is drawn and convolved."""


@dataclass(frozen=True, slots=True)
class OfferedWork:
    """Offered load in regime, not an execution starting empty.

    ``minutes`` includes both endpoints, 0 and ``days * 1440``, relative to
    ``start_date``. ``prior_days`` precede that date and are not in the arrays.
    ``load`` counts busy professionals/boxes without queues, ``capacity`` is
    the scheduled capacity at each instant, and ``utilization`` holds the
    mean load/capacity by morning, afternoon and night, in that order.
    Pool names are ``medicos``, ``boxes`` and ``enfermeria_triaje``.
    """

    start_date: date
    days: int
    prior_days: int
    minutes: NDArray[np.int64]
    load: dict[str, NDArray[np.float64]]
    capacity: dict[str, NDArray[np.int64]]
    utilization: dict[str, tuple[float, ...]]
    window_kind: Literal["offered_in_regime"] = field(default="offered_in_regime", init=False)


@dataclass(frozen=True, slots=True)
class OfferedLoad:
    """The first part of ``offered_work``: the load, without the center's staff.

    ``load`` has the busy professionals/boxes without queues of each pool at
    minutes 0..``days * 1440`` from ``start_date``, the same arrays as
    ``OfferedWork.load``; ``prior_days`` is the prehistory of the sample.
    Arrays must not be edited in place: a cached load is shared.
    """

    start_date: date
    days: int
    prior_days: int
    load: dict[str, NDArray[np.float64]]


def offered_load(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int = 7,
    *,
    sample_size: int = 50_000,
    sample_seed: int = 73_001,
    profiles: ClinicalProfiles | None = None,
) -> OfferedLoad:
    """Offered load without waits or daily random effects, from start_date.

    The slow part of ``offered_work`` (the sample and the convolution). It
    depends on the arrival profile, the clinical profiles and these fields of
    the center, never on its staff (``shift_starts``, ``triage_nurses``,
    ``doctors`` and ``boxes``), which only ``offered_work_from_load`` uses:

    - Without ``profiles`` (provisional sample): ``level_shares``,
      ``triage_time``, ``assessment_time``, ``reassessment_time``,
      ``test_turnaround`` and ``test_probability``. ``admission_probability``
      is drawn but never changes an interval.
    - With ``profiles`` (clinical sample): ``results_wait_outside``, for the
      box of the patients who leave it for the results room.
      ``admission_probability`` is passed to the sampler for the destination
      and never changes an interval.

    Sample patients with a fixed seed independent of an execution's seed.
    Reuse the engine validation's held intervals and midpoint convolution.
    Prehistory is ``max(1, ceil(maximum_sample_occupation_age / 1440))`` days,
    calculated with a profile dated earlier, preserving the actual calendar.
    It removes the empty-start truncation exactly for the finite sample. The
    maximum, and therefore the number of prior days, may grow with sample size.

    This is offered load in regime from ``profile.start_date``. A real run
    starts empty at minute 0 and has its own warmup days. With constant or
    daily-periodic arrival rates, its full-day mean equals mean arrival rate
    times sample mean occupation, up to one-minute discretization. This is
    generally only an approximation with weekly/monthly factors: work crosses
    both edges of the window. Box load excludes waits while holding a box.

    With ``profiles``, the patients come from the clinical sampler, each with
    the context of its own arrival instant (``_clinical_load``); without them,
    exactly the provisional sample above, which needs the provisional block of
    the center (``ValueError`` otherwise, before sampling).
    """
    days = check_count("days", days, 1)
    sample_size = check_count("sample_size", sample_size, 1)
    sample_seed = check_count("sample_seed", sample_seed, 0)
    if profiles is not None:
        if choose_model(center, profiles) is PatientModel.MILESTONE_5:
            # The wait for a bed blocks the box of the admitted patients: the load of
            # milestone 5 is not that of milestone 4, and it is not written yet (task 5.3).
            raise ValueError("the offered load of the milestone 5 model is not implemented yet")
        load, prior_days = _clinical_load(center, profile, days, sample_size, sample_seed, profiles)
        return OfferedLoad(profile.start_date, days, prior_days, load)
    require_provisional(center)
    draws = draws_sample(center, sample_size, seed=sample_seed)
    maximum_age = max(
        end
        for draw in draws
        for intervals in _held_intervals(draw).values()
        for _, end in intervals
    )
    prior_days = max(1, math.ceil(maximum_age / MINUTES_PER_DAY))
    previous_profile = replace(profile, start_date=profile.start_date - timedelta(days=prior_days))
    offset = prior_days * MINUTES_PER_DAY
    horizon = days * MINUTES_PER_DAY
    curves = offered_load_by_pool(previous_profile, draws, horizon=offset + horizon)
    load = {pool: curves[pool][offset : offset + horizon + 1].copy() for pool in _POOLS}
    return OfferedLoad(profile.start_date, days, prior_days, load)


def offered_work_from_load(center: CenterConfig, load: OfferedLoad) -> OfferedWork:
    """The second part of ``offered_work``: capacity and utilization with the center's staff.

    Uses only ``shift_starts``, ``triage_nurses``, ``doctors`` and ``boxes``,
    so a load computed with another center that differs only in its staff
    gives the same result as ``offered_work`` with this one.

    Shift utilization integrates load with one-minute trapezoids and divides
    by the shift's constant scheduled capacity, including night across midnight.
    The arrays of ``load`` are shared, not copied.
    """
    horizon = load.days * MINUTES_PER_DAY
    minutes = np.arange(horizon + 1, dtype=np.int64)
    shifts = np.fromiter(
        (shift_at(center.shift_starts, int(t)) for t in minutes),
        dtype=np.int64,
        count=minutes.size,
    )
    staff = {
        "medicos": center.doctors,
        "boxes": (center.boxes,) * 3,
        "enfermeria_triaje": center.triage_nurses,
    }
    capacity = {pool: np.asarray(staff[pool], dtype=np.int64)[shifts] for pool in _POOLS}
    utilization = {}
    for pool in _POOLS:
        per_minute = (load.load[pool][:-1] + load.load[pool][1:]) / 2
        utilization[pool] = tuple(
            float(per_minute[shifts[:-1] == shift].mean() / staff[pool][shift])
            for shift in range(3)
        )
    return OfferedWork(
        load.start_date, load.days, load.prior_days, minutes, load.load, capacity, utilization
    )


def offered_work(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int = 7,
    *,
    sample_size: int = 50_000,
    sample_seed: int = 73_001,
    profiles: ClinicalProfiles | None = None,
) -> OfferedWork:
    """Predict offered work without waits or daily random effects, from start_date.

    ``offered_load`` followed by ``offered_work_from_load``: see them for the
    sample, the prehistory, the fields of the center each part uses and the
    shift utilization. An editor of the staff can compute the load once and
    call ``offered_work_from_load`` for each staff.
    """
    load = offered_load(
        center,
        profile,
        days,
        sample_size=sample_size,
        sample_seed=sample_seed,
        profiles=profiles,
    )
    return offered_work_from_load(center, load)


# --- Clinical sample (task 4.8a) -----------------------------------------------------------


def _clinical_intervals(
    draws: PatientDraws, arrival: float, wait_outside: Sequence[int]
) -> dict[str, list[tuple[float, float]]]:
    """Ages at which a clinical patient who never waits holds each pool.

    As ``engine.validation._held_intervals``, with the turnaround of the round
    timed at its order (arrival + triage + assessment). A patient whose
    assigned level is in ``wait_outside`` and has a round leaves its box at the
    order and gets one back with its results: the results room is not a box.
    """
    triaged = triage_duration(draws.level, draws.triage_time)
    assessed = triaged + draws.assessment_time
    doctor = [(triaged, assessed)]
    boxes = [(triaged, assessed)]
    if draws.needs_tests:
        assert draws.clinical is not None
        results = assessed + draws.clinical.round_turnaround(arrival + assessed)
        end = results + draws.reassessment_time
        doctor.append((results, end))
        if draws.level in wait_outside:
            boxes.append((results, end))
        else:
            boxes = [(triaged, end)]
    return {"enfermeria_triaje": [(0.0, triaged)], "medicos": doctor, "boxes": boxes}


def _occupancy(held: list[tuple[float, float]], n: int) -> NDArray[np.float64]:
    """Share of ``n`` patients holding at each age k + ½, as in ``offered_load_by_pool``."""
    if not held:
        return np.zeros(1)
    a, b = np.array(held).T
    # [a, b) contains the midpoint k + ½ exactly for ceil(a − ½) <= k < ceil(b − ½).
    low = np.ceil(a - 0.5).astype(np.int64)
    high = np.ceil(b - 0.5).astype(np.int64)
    counts = np.zeros(int(high.max()) + 1, dtype=np.int64)
    np.add.at(counts, low, 1)
    np.add.at(counts, high, -1)
    occupancy = np.cumsum(counts)[:-1] / n
    return occupancy if occupancy.size else np.zeros(1)


def _context_index(times: NDArray[np.float64], start: date, starts: Sequence[int]):
    """Flat index of the context of each time, in the order of ``all_contexts``."""
    shift, day, season = context_indices(times, start, starts)
    return (shift * N_DAY_TYPES + day) * N_SEASONS + season


def _clinical_load(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int,
    sample_size: int,
    sample_seed: int,
    profiles: ClinicalProfiles,
) -> tuple[dict[str, NDArray[np.float64]], int]:
    """Offered load of a clinical sample, each patient with the context of its arrival.

    The arrival instants of the sample are drawn from λ(t) over
    ``OFFERED_PRIOR_CAP_DAYS`` days before ``start_date`` and the window (the
    inverse of the exact Λ on a one-minute grid, linear inside each minute),
    and each patient is drawn by the ``ClinicalSampler`` at its instant: its
    shift band, day type and season, and the shift band of its order. Patients
    are grouped by the context of their arrival; the occupancy of each group is
    convolved with λ(t)·1{context(t) = c} and the groups are added::

        m(j) = Σ_c Σ_k λ_c(j − k − ½) · P(a patient of context c holds at age k + ½).

    Approximation: the intervals of each patient are computed at its own
    instant, with the real shift band of its order, but its occupancy is
    applied to every instant of its context, so the band of the order may not
    match exactly when the order falls in another band than the arrival. With
    profiles without shift band factors of the turnaround it is exact in
    expectation.

    Returns the load at minutes 0..``days * 1440`` and the prehistory in days,
    ``max(1, ceil(maximum_sample_occupation_age / 1440))``, as in the
    provisional model; the convolution starts ``OFFERED_PRIOR_CAP_DAYS``
    before, which contains it.

    Raises:
        ValueError: If the prehistory exceeds ``OFFERED_PRIOR_CAP_DAYS``, or a
            context with arrivals in the prehistory or the window has no
            patient in the sample (too small a sample).
    """
    cap = OFFERED_PRIOR_CAP_DAYS * MINUTES_PER_DAY
    horizon = days * MINUTES_PER_DAY
    span = cap + horizon
    early = replace(profile, start_date=profile.start_date - timedelta(days=OFFERED_PRIOR_CAP_DAYS))
    starts = profiles.shift_band_starts
    arrival_seed, patient_seed = child_streams(sample_seed, 2)
    grid = np.arange(span + 1, dtype=float)
    cumulative = np.asarray(cumulative_rate(grid, early), dtype=float)
    u = np.sort(np.random.default_rng(arrival_seed).random(sample_size)) * cumulative[-1]
    times = np.interp(u, cumulative, grid)
    sampler = ClinicalSampler(
        profiles, early.start_date, center, child_streams(patient_seed, N_SAMPLER_STREAMS)
    )
    contexts = _context_index(times, early.start_date, starts)
    held: dict[int, dict[str, list[tuple[float, float]]]] = {}
    maximum_age = 0.0
    for i, (t, c) in enumerate(zip(times, contexts, strict=True)):
        intervals = _clinical_intervals(
            sampler(ArrivalRecord(i, float(t))), float(t), center.results_wait_outside
        )
        group = held.setdefault(int(c), {pool: [] for pool in _POOLS})
        for pool, spans in intervals.items():
            group[pool].extend(spans)
            maximum_age = max(maximum_age, *(end for _, end in spans))
    prior_days = max(1, math.ceil(maximum_age / MINUTES_PER_DAY))
    if prior_days > OFFERED_PRIOR_CAP_DAYS:
        raise ValueError(
            f"the sample needs {prior_days} days of prehistory, "
            f"more than OFFERED_PRIOR_CAP_DAYS ({OFFERED_PRIOR_CAP_DAYS})"
        )
    midpoints = np.arange(span) + 0.5
    lam = np.asarray(rate(midpoints, early), dtype=float)
    minute_contexts = _context_index(midpoints, early.start_date, starts)
    counts = np.bincount(contexts, minlength=len(starts) * N_DAY_TYPES * N_SEASONS)
    load = {pool: np.zeros(span) for pool in _POOLS}
    for c in np.unique(minute_contexts[lam > 0]):
        if counts[c] == 0:
            raise ValueError(
                f"sample_size {sample_size} is too small: no patient in context {int(c)}"
            )
        lam_c = np.where(minute_contexts == c, lam, 0.0)
        for pool in _POOLS:
            occupancy = _occupancy(held[int(c)][pool], int(counts[c]))
            load[pool] += fftconvolve(lam_c, occupancy)[:span]
    offset = cap
    return {
        pool: np.concatenate([[0.0], load[pool]])[offset : offset + horizon + 1] for pool in _POOLS
    }, prior_days
