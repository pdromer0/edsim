"""Read exact episode draws and compare complete or censored observations.

The ground truth is read here only to be shown as truth: what each episode drew,
its clinical truth and the compliance by true level. What the hospital observes
comes from the log.
"""

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Literal

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import EpisodeRecord, completed_in_window
from edsim.engine.clinical_sampler import TurnaroundShifts
from edsim.engine.events import DOOR, Event, episode_id
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.report import EPISODE_COLUMNS, PARAMETER_COLUMNS
from edsim.engine.targets import COMPLIANCE_MEASURE, true_level_compliance, true_levels
from edsim.profiles.config import TEST_TYPES, ClinicalProfiles
from edsim.runs._truth_csv import read_clinical_episodes
from edsim.runs.episodes import EpisodeSegments
from edsim.runs.metrics import WindowCompliance, _pooled_levels
from edsim.runs.results import RunReadError, read_run_header
from edsim.runs.store import RunInfo, RunStore

TRUTH_ABS_TOL_MINUTES = 1e-8
"""Fixed before measuring: 0.6 microseconds; no relative tolerance."""

TruthStatus = Literal["match", "mismatch", "partial", "pending", "unused"]


@dataclass(frozen=True, slots=True)
class TruthComparison:
    """One drawn value and its observed minutes, level or destination.

    ``drawn`` is None only for the turnaround of a clinical patient without
    tests: it has no round, so nothing was drawn for it.
    """

    field: str
    drawn: int | float | str | None
    observed: int | float | str | None
    status: TruthStatus


def _truth_row(row: dict[str, str], info: RunInfo) -> EpisodeTruth:
    expected = (
        info.center_path,
        info.center_fingerprint,
        info.profile_path,
        info.profile_fingerprint,
        str(info.days),
        str(info.warmup_days),
        str(info.seed),
        info.run_id,
    )
    for column, value in zip(PARAMETER_COLUMNS, expected, strict=True):
        if row[column] != value:
            raise ValueError(f"{column} does not match run.json")
    arrival_id = int(row["llegada"])
    if row["episodio"] != episode_id(arrival_id):
        raise ValueError("episodio does not match llegada")
    level = int(row["nivel"])
    if not 1 <= level <= 5:
        raise ValueError("nivel must be between 1 and 5")
    numeric = {}
    for column, field in (
        ("minuto_llegada", "arrival_time"),
        ("triaje", "triage_time"),
        ("valoracion", "assessment_time"),
        ("reevaluacion", "reassessment_time"),
        ("respuesta_pruebas", "test_turnaround"),
    ):
        value = float(row[column])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{column} must be finite and non-negative")
        numeric[field] = value
    if numeric["arrival_time"] >= info.days * 1440:
        raise ValueError("minuto_llegada is outside the run horizon")
    if row["pruebas"] not in ("True", "False"):
        raise ValueError("pruebas must be True or False")
    if row["destino"] not in ("alta", "ingreso"):
        raise ValueError("destino must be alta or ingreso")
    return EpisodeTruth(
        row["episodio"],
        arrival_id,
        level=level,
        needs_tests=row["pruebas"] == "True",
        admitted=row["destino"] == "ingreso",
        **numeric,
    )


def read_run_episode_truth(store: RunStore, run_id: str) -> Mapping[str, EpisodeTruth]:
    """Read exact typed CSV draws, rejecting invalid rows with file:line errors.

    Floats round-trip the writer's full representation. Boolean tokens and
    destinations are exact, not Python truthiness. Repeated run parameters
    must match metadata. The returned mapping and records are read-only.

    A clinical run (``run.json`` with model ``clinico``) has the 57 columns of
    ``CLINICAL_EPISODE_COLUMNS``; each row is read with ``episode_from_row``,
    and its profiles path and fingerprint must also match ``run.json``.
    """
    info, _ = read_run_header(store, run_id)
    if info.is_clinical:
        try:
            return read_clinical_episodes(store, run_id, info)
        except ValueError as error:
            raise RunReadError(str(error)) from error
    path = store.root / run_id / "ground_truth_episodios.csv"
    reader = None
    episodes = {}
    try:
        with store._file(run_id, "ground_truth_episodios.csv").open(
            encoding="utf-8", newline=""
        ) as source:
            reader = csv.DictReader(source, strict=True)
            if tuple(reader.fieldnames or ()) != EPISODE_COLUMNS:
                raise ValueError("invalid episode ground truth header")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("incomplete or extra CSV fields")
                truth = _truth_row(row, info)
                if truth.episode_id in episodes:
                    raise ValueError(f"duplicate episode {truth.episode_id}")
                episodes[truth.episode_id] = truth
    except (OSError, ValueError, csv.Error) as error:
        line = reader.line_num if reader is not None else 0
        where = f"{path}:{max(1, line)}" if reader is not None else str(path)
        raise RunReadError(f"{where}: {error}") from error
    return MappingProxyType(episodes)


def _check_episode(events: Sequence[Event], truth: EpisodeTruth) -> dict[str, list[Event]]:
    if not events or any(event.episode_id != truth.episode_id for event in events):
        raise ValueError("events and truth must belong to the same episode")
    by_type: dict[str, list[Event]] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)
    return by_type


def _shifts(profiles: ClinicalProfiles | None, start_date: date | None) -> TurnaroundShifts:
    if profiles is None or start_date is None:
        raise ValueError("a clinical truth needs the profiles and the start_date of its run")
    return TurnaroundShifts.from_profiles(profiles, start_date)


def compare_episode_truth(
    events: Sequence[Event],
    segments: EpisodeSegments,
    truth: EpisodeTruth,
    *,
    profiles: ClinicalProfiles | None = None,
    start_date: date | None = None,
) -> tuple[TruthComparison, ...]:
    """Compare stages using sim_time and all interrupted attention segments.

    A finished duration matches within absolute 1e-8 minutes, relative zero.
    A started stage is partial until its non-interrupted end; partial work
    exceeding its draw plus tolerance is a mismatch. Never-started stages
    are pending; reassessment and turnaround without tests are unused, and so
    is the triage time of a triage at the door (``circuito`` ``puerta``).

    With a clinical truth, ``profiles`` and ``start_date`` (those of the run)
    are required: the drawn turnaround of the round is the slowest ordered
    test, each with the factor of the shift band of the ``test_ordered`` of
    the log times its base. Before the order the band is unknown and the row
    is pending with the slowest base (factor 1).
    """
    if (
        not events
        or segments.episode_id != truth.episode_id
        or any(event.episode_id != truth.episode_id for event in events)
    ):
        raise ValueError("events, segments and truth must belong to the same episode")
    by_type = _check_episode(events, truth)
    drawn_turnaround = truth.test_turnaround
    if truth.clinical is not None:
        shifts = _shifts(profiles, start_date)
        orders = by_type.get("test_ordered", ())
        factors = shifts.factors_at(orders[0].sim_time) if orders else None
        drawn_turnaround = truth.clinical.workup.round_turnaround(factors)

    def duration(
        field: str,
        state: str,
        start: bool,
        finished: bool,
        drawn: float,
        unused: bool = False,
        observed: float | None = None,
    ) -> TruthComparison:
        if unused:
            return TruthComparison(field, drawn, None, "unused")
        if not start:
            return TruthComparison(field, drawn, None, "pending")
        if observed is None:
            observed = math.fsum(
                segment.end - segment.start
                for segment in segments.segments
                if segment.state == state
            )
        if finished:
            status = (
                "match"
                if math.isclose(observed, drawn, abs_tol=TRUTH_ABS_TOL_MINUTES, rel_tol=0)
                else "mismatch"
            )
        else:
            status = "partial" if observed <= drawn + TRUTH_ABS_TOL_MINUTES else "mismatch"
        return TruthComparison(field, drawn, observed, status)

    def assessment(
        tipo: str, field: str, state: str, drawn: float, unused: bool = False
    ) -> TruthComparison:
        started = any(
            event.payload["tipo"] == tipo for event in by_type.get("assessment_started", ())
        )
        finished = any(
            event.payload["tipo"] == tipo and not event.payload["interrumpida"]
            for event in by_type.get("assessment_ended", ())
        )
        return duration(field, state, started, finished, drawn, unused)

    started = by_type.get("triage_started", ())
    at_the_door = any(event.payload["circuito"] == DOOR for event in started)
    triage = by_type.get("triage_completed", ())
    decision = by_type.get("disposition_decided", ())
    level = triage[-1].payload["nivel"] if triage else None
    destination = decision[-1].payload["destino"] if decision else None
    # With milestone 5 the drawn destination is one of four (task 5.3); before, admitted.
    drawn_destination = (
        ("ingreso" if truth.admitted else "alta")
        if truth.outcome is None
        else truth.outcome.destination
    )
    band = segments.tests
    return (
        TruthComparison(
            "level",
            truth.level,
            level,
            "pending" if level is None else "match" if level == truth.level else "mismatch",
        ),
        duration(
            "triage_time",
            "triage",
            bool(started),
            bool(triage),
            truth.triage_time,
            at_the_door,
        ),
        assessment("inicial", "assessment_time", "assessment", truth.assessment_time),
        assessment(
            "reevaluacion",
            "reassessment_time",
            "reassessment",
            truth.reassessment_time,
            not truth.needs_tests,
        ),
        duration(
            "test_turnaround",
            "",
            band is not None,
            band is not None and band.completed,
            drawn_turnaround,
            not truth.needs_tests,
            None if band is None else band.end - band.start,
        ),
        TruthComparison(
            "destination",
            drawn_destination,
            destination,
            "pending"
            if destination is None
            else "match"
            if destination == drawn_destination
            else "mismatch",
        ),
    )


# --- The clinical truth of an episode, shown as truth (task 4.8a) -----------------------


@dataclass(frozen=True, slots=True)
class DiagnosticTestTruth:
    """One type of test of an episode, from its clinical truth.

    ``result`` is ``"normal"`` or ``"alterado"`` if the test was ordered, None
    otherwise. ``base_turnaround`` is the drawn base (factor 1), always drawn;
    ``turnaround`` is the factor of the shift band of the order times the base,
    None if the test was not ordered or the order is not in the log yet.
    """

    test: str
    ordered: bool
    result: str | None
    base_turnaround: float
    turnaround: float | None


@dataclass(frozen=True, slots=True)
class ClinicalTruthView:
    """What the clinical model drew for an episode and what the log shows of its round.

    ``round_expected`` is the slowest ``turnaround`` of the ordered tests and
    ``round_observed`` the ``test_resulted`` minus the ``test_ordered`` of the
    log; the log shows the round, not each test. Both are None without a round
    or before it happens.
    """

    episode_id: str
    severity: float
    assigned_level: int
    true_level: int
    quality: str
    jump: int
    tests: tuple[DiagnosticTestTruth, ...]
    round_expected: float | None
    round_observed: float | None


def episode_clinical_truth(
    events: Sequence[Event],
    truth: EpisodeTruth,
    *,
    profiles: ClinicalProfiles,
    start_date: date,
) -> ClinicalTruthView:
    """The clinical truth of one episode next to the round observed in its log.

    Raises:
        ValueError: If the events are not of the episode, the truth is not
            clinical, or the profiles or the start date are missing.
    """
    by_type = _check_episode(events, truth)
    if truth.clinical is None:
        raise ValueError(f"{truth.episode_id} has no clinical truth")
    shifts = _shifts(profiles, start_date)
    clinical = truth.clinical
    orders = by_type.get("test_ordered", ())
    results = by_type.get("test_resulted", ())
    factors = shifts.factors_at(orders[0].sim_time) if orders else None
    drawn_results = clinical.results
    tests = tuple(
        DiagnosticTestTruth(
            test,
            ordered,
            drawn_results.get(test),
            base,
            factors[index] * base if ordered and factors is not None else None,
        )
        for index, (test, ordered, base) in enumerate(
            zip(TEST_TYPES, clinical.workup.ordered, clinical.workup.turnarounds, strict=True)
        )
    )
    expected = clinical.workup.round_turnaround(factors) if factors is not None else None
    observed = results[0].sim_time - orders[0].sim_time if orders and results else None
    triage = clinical.triage
    return ClinicalTruthView(
        truth.episode_id,
        triage.severity,
        triage.level,
        triage.true_level,
        triage.quality,
        triage.jump,
        tests,
        expected,
        observed,
    )


def true_level_window_compliance(
    table: Sequence[EpisodeRecord],
    truth: Mapping[str, EpisodeTruth],
    first_day: int,
    end_day: int,
    *,
    measure: str = COMPLIANCE_MEASURE,
) -> WindowCompliance:
    """Manchester compliance in ``[first_day, end_day)`` with the true level of each patient.

    ``true_level_compliance`` (clock C by default) for the days, and the same
    pooled counts as ``window_compliance`` with the true level to group the
    patients and choose their maximum. It needs the clinical ground truth of
    the run, such as ``read_run_episode_truth``: it is never an observable KPI.

    Raises:
        ValueError: As ``true_level_compliance``: without a clinical truth or
            with a counted episode missing from it.
    """
    ground_truth = GroundTruth(tuple(truth.values()), ())
    daily = true_level_compliance(table, ground_truth, first_day, end_day, measure=measure)
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    return WindowCompliance(daily, _pooled_levels(daily, done, true_levels(ground_truth)))
