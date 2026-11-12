"""Read exact episode draws and compare complete or censored observations.

The ground truth is read here only to be shown as truth: what each episode drew,
its clinical truth, its outcome (milestone 5: the patience, the destination,
also the one of whoever left, and the wait for a bed) and the indicators by
true level. What the hospital observes comes from the log.
"""

import csv
import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Literal

from edsim.engine.analysis import EpisodeRecord
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.engine.clinical import BedWaitFactors
from edsim.engine.clinical_sampler import TurnaroundShifts
from edsim.engine.events import DOOR, Event, episode_id
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.outcome_metrics import ADMISSION, KaplanMeier, kaplan_meier
from edsim.engine.report import EPISODE_COLUMNS, PARAMETER_COLUMNS
from edsim.engine.targets import (
    COMPLIANCE_MEASURE,
    MANCHESTER_MAX_WAIT,
    compliance_cases,
    compliance_from_cases,
    true_levels,
)
from edsim.profiles.config import DESTINATIONS, TEST_TYPES, ClinicalProfiles
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
    center: CenterConfig | None = None,
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

    With the outcome of milestone 5 (task 5.4), the drawn destination of whoever
    left without being seen is ``unused``: it is the one it would have had. So
    are its assessment, reassessment and turnaround (issue #105), which it
    never reached, and, if it left before its triage, its level and triage
    time.
    With ``center`` (that of the run, with ``[camas]``), two more rows:

    - ``patience``: the drawn patience against the time until the patient
      left. It matches if it left in arrival + patience or, if the deadline
      fell during its triage, at its end; ``unused`` once seen or for a level 1
      at the door, who never leave; ``pending`` while it waits unseen.
    - ``bed_wait``: the drawn base times the factor of the instant of
      ``bed_requested`` against the time in ``waiting_bed``; ``unused``
      without an admission; ``pending`` before the request (with the base,
      factor 1).
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

    left = bool(by_type.get("patient_left_wbs"))
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
    destination_row = TruthComparison(
        "destination",
        drawn_destination,
        destination,
        "unused"
        if left
        else "pending"
        if destination is None
        else "match"
        if destination == drawn_destination
        else "mismatch",
    )
    rows = (
        TruthComparison(
            "level",
            truth.level,
            level,
            "unused"
            if level is None and left
            else "pending"
            if level is None
            else "match"
            if level == truth.level
            else "mismatch",
        ),
        duration(
            "triage_time",
            "triage",
            bool(started),
            bool(triage),
            truth.triage_time,
            at_the_door or (left and not started),
        ),
        assessment("inicial", "assessment_time", "assessment", truth.assessment_time, left),
        assessment(
            "reevaluacion",
            "reassessment_time",
            "reassessment",
            truth.reassessment_time,
            left or not truth.needs_tests,
        ),
        duration(
            "test_turnaround",
            "",
            band is not None,
            band is not None and band.completed,
            drawn_turnaround,
            left or not truth.needs_tests,
            None if band is None else band.end - band.start,
        ),
        destination_row,
    )
    if truth.outcome is None or center is None:
        return rows
    return (
        *rows,
        _patience_row(by_type, truth, at_the_door),
        _bed_row(by_type, truth, center, start_date, duration),
    )


def _expected_leave(truth: EpisodeTruth, triage_end: float | None) -> float:
    """When a patient who leaves without being seen leaves (H5-4).

    At arrival + patience; if the deadline falls during its triage, when the
    triage ends.
    """
    deadline = truth.arrival_time + truth.outcome.patience
    return deadline if triage_end is None else max(deadline, triage_end)


def _patience_row(
    by_type: Mapping[str, Sequence[Event]], truth: EpisodeTruth, at_the_door: bool
) -> TruthComparison:
    patience = truth.outcome.patience
    seen = any(e.payload["tipo"] == "inicial" for e in by_type.get("assessment_started", ()))
    left = by_type.get("patient_left_wbs", ())
    if not left:
        status = "unused" if seen or at_the_door else "pending"
        return TruthComparison("patience", patience, None, status)
    triage = by_type.get("triage_completed", ())
    expected = _expected_leave(truth, triage[-1].sim_time if triage else None)
    observed = left[0].sim_time - truth.arrival_time
    matches = math.isclose(left[0].sim_time, expected, abs_tol=TRUTH_ABS_TOL_MINUTES, rel_tol=0)
    return TruthComparison("patience", patience, observed, "match" if matches else "mismatch")


def _bed_row(
    by_type: Mapping[str, Sequence[Event]],
    truth: EpisodeTruth,
    center: CenterConfig,
    start_date: date | None,
    duration,
) -> TruthComparison:
    outcome = truth.outcome
    if outcome.destination != "ingreso" or by_type.get("patient_left_wbs"):
        return TruthComparison("bed_wait", outcome.bed_base, None, "unused")
    requests = by_type.get("bed_requested", ())
    if not requests:
        return TruthComparison("bed_wait", outcome.bed_base, None, "pending")
    drawn = outcome.bed_base * _bed_factors(center, start_date).factor_at(requests[0].sim_time)
    return duration("bed_wait", "waiting_bed", True, bool(by_type.get("bed_assigned")), drawn)


def _bed_factors(center: CenterConfig, start_date: date | None) -> BedWaitFactors:
    """The factors of the wait for a bed of a run, as the sampler builds them."""
    if start_date is None:
        raise ValueError("the wait for a bed needs the start_date of its run")
    return BedWaitFactors(
        start_date, center.shift_starts, center.bed_shift_factors, center.bed_season_factors
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
    cases = compliance_cases(
        table,
        first_day,
        end_day,
        MANCHESTER_MAX_WAIT,
        measure=measure,
        level_of=true_levels(ground_truth),
    )
    daily = compliance_from_cases(cases, first_day, end_day, measure=measure)
    return WindowCompliance(daily, _pooled_levels(daily, cases))


# --- The outcome of an episode, shown as truth (task 5.4) -------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeTruthView:
    """What the outcome sampler drew for an episode next to what its log shows (H5-10).

    Attributes:
        episode_id: The episode.
        patience_z: The standard normal of the patience.
        patience: Minutes from the arrival it waits before leaving unseen.
        deadline: Arrival + patience.
        left_at: Its ``patient_left_wbs``, or None.
        left_from: Where it waited when it left, or None.
        expected_leave: If it left, when the rule makes it leave: the deadline
            or, if it fell during its triage, the end of the triage.
        destination_draws: The four Gumbel draws, in the order of
            ``DESTINATIONS``.
        destination: The destination drawn, always.
        destination_observed: The decision of the log, or None.
        counterfactual: Whether the drawn destination is the one it would have
            had: it left without being seen, so it was never decided.
        bed_z: The standard normal of the wait for a bed.
        bed_base: The wait for a bed with factor 1, drawn always.
        bed_factor: Shift times season of its ``bed_requested``, or None.
        bed_expected: ``bed_base × bed_factor``, or None without a request.
        bed_observed: ``bed_assigned`` minus ``bed_requested``, or None.
    """

    episode_id: str
    patience_z: float
    patience: float
    deadline: float
    left_at: float | None
    left_from: str | None
    expected_leave: float | None
    destination_draws: tuple[float, ...]
    destination: str
    destination_observed: str | None
    counterfactual: bool
    bed_z: float
    bed_base: float
    bed_factor: float | None
    bed_expected: float | None
    bed_observed: float | None


def episode_outcome_truth(
    events: Sequence[Event],
    truth: EpisodeTruth,
    *,
    center: CenterConfig,
    start_date: date,
) -> OutcomeTruthView:
    """The outcome drawn for one episode next to its log (milestone 5).

    Args:
        events: The events of the episode, in log order.
        truth: Its ground truth, with an outcome.
        center: The center of the run, with ``[camas]``: the factors of the
            wait for a bed.
        start_date: The date of minute 0 of the run.

    Raises:
        ValueError: If the events are not of the episode or the truth has no
            outcome.
    """
    by_type = _check_episode(events, truth)
    outcome = truth.outcome
    if outcome is None:
        raise ValueError(f"{truth.episode_id} has no outcome: it needs the milestone 5 model")
    left = by_type.get("patient_left_wbs", ())
    triage = by_type.get("triage_completed", ())
    decision = by_type.get("disposition_decided", ())
    requests = by_type.get("bed_requested", ())
    beds = by_type.get("bed_assigned", ())
    factor = _bed_factors(center, start_date).factor_at(requests[0].sim_time) if requests else None
    return OutcomeTruthView(
        episode_id=truth.episode_id,
        patience_z=outcome.patience_z,
        patience=outcome.patience,
        deadline=truth.arrival_time + outcome.patience,
        left_at=left[0].sim_time if left else None,
        left_from=left[0].payload["espera"] if left else None,
        expected_leave=(
            _expected_leave(truth, triage[-1].sim_time if triage else None) if left else None
        ),
        destination_draws=tuple(outcome.destination_draws),
        destination=outcome.destination,
        destination_observed=decision[-1].payload["destino"] if decision else None,
        counterfactual=bool(left),
        bed_z=outcome.bed_z,
        bed_base=outcome.bed_base,
        bed_factor=factor,
        bed_expected=None if factor is None else outcome.bed_base * factor,
        bed_observed=beds[0].sim_time - requests[0].sim_time if beds and requests else None,
    )


# --- Indicators of the true level (task 5.4) ---------------------------------------------

SEVERE_LEVELS = (1, 2)
"""True levels counted as severe among those who left (piece 4)."""


@dataclass(frozen=True, slots=True)
class TrueLevelLeft:
    """The abandonment of one true level.

    Attributes:
        level: True level, 1 to 5.
        arrivals: Patients of the window with that true level, also those who
            left before their triage, who have no assigned level.
        left: Of them, those who left without being seen.
    """

    level: int
    arrivals: int
    left: int

    @property
    def share(self) -> float | None:
        """``left / arrivals``; ``None`` without arrivals of the level."""
        return self.left / self.arrivals if self.arrivals else None


@dataclass(frozen=True, slots=True)
class TrueLevelAbandonment:
    """What only the ground truth tells of the abandonment (piece 4, H5-8).

    Never in the log nor in the observable indicators.

    Attributes:
        by_level: The abandonment by true level, 1 to 5.
        left: Patients of the window who left without being seen.
        severe: Of them, those of a true level in ``SEVERE_LEVELS``.
        would_be_admitted: Of them, those whose drawn destination was an
            admission: the hidden harm of the abandonment (H5-10).
    """

    by_level: tuple[TrueLevelLeft, ...]
    left: int
    severe: int
    would_be_admitted: int


def true_level_abandonment(
    table: Sequence[EpisodeRecord],
    truth: Mapping[str, EpisodeTruth],
    start: float,
    end: float,
) -> TrueLevelAbandonment:
    """The abandonment of the patients that arrive in ``[start, end)``, with their truth.

    Args:
        table: The episodes of the log, from ``episode_table``.
        truth: The ground truth of the run by ``episode_id``, with the clinical
            model and the outcome of milestone 5, such as
            ``read_run_episode_truth``.
        start: Start of the window, in minutes.
        end: End of the window.

    Raises:
        ValueError: If an episode of the window is not in the truth, or its
            truth has no clinical truth or no outcome.
    """
    arrived = [e for e in table if start <= e.arrival < end]
    levels = []
    left = []
    for e in arrived:
        t = truth.get(e.episode_id)
        if t is None:
            raise ValueError(f"{e.episode_id} is not in the ground truth")
        if t.clinical is None or t.outcome is None:
            raise ValueError(f"{e.episode_id} has no clinical truth or no outcome")
        levels.append(t.clinical.triage.true_level)
        if e.left is not None:
            left.append(t)
    return TrueLevelAbandonment(
        by_level=tuple(
            TrueLevelLeft(
                level,
                sum(lv == level for lv in levels),
                sum(
                    lv == level and e.left is not None
                    for lv, e in zip(levels, arrived, strict=True)
                ),
            )
            for level in range(1, N_LEVELS + 1)
        ),
        left=len(left),
        severe=sum(t.clinical.triage.true_level in SEVERE_LEVELS for t in left),
        would_be_admitted=sum(t.outcome.destination == "ingreso" for t in left),
    )


# --- The closing of the flow: patience, counterfactual and G (task 5.7) -------------------

LATE_LEAVE_TOLERANCE = 1e-9
"""Minutes: whoever leaves later than its patience by more than this had its deadline
overdue during the triage and leaves when it ends (H5-4)."""

PatienceGrouping = Literal["true_level", "assigned_level"]


def _outcome_truth(truth: Mapping[str, EpisodeTruth], episode_id: str) -> EpisodeTruth:
    t = truth.get(episode_id)
    if t is None:
        raise ValueError(f"{episode_id} is not in the ground truth")
    if t.clinical is None or t.outcome is None:
        raise ValueError(f"{episode_id} has no clinical truth or no outcome")
    return t


@dataclass(frozen=True, slots=True)
class PatienceGroup:
    """The Kaplan–Meier estimate of the patience of one level, with the truth beside it.

    Attributes:
        level: The level of the group, 1 to 5.
        km: The estimate: the event is leaving, in minutes since the arrival;
            seeing a doctor or still waiting at the horizon censor.
        left: Events: patients who left without being seen.
        seen: Censored because a doctor saw them: the end of the risk of leaving.
        waiting: Censored because they still waited at the horizon.
        late_leavers: Of those who left, the ones whose deadline was overdue
            during the triage: they leave when it ends, later than their
            patience, so the estimate takes their time as the patience.
        patiences: The true patiences of all the patients of the group, increasing:
            the ground truth knows them, also those of whoever saw a doctor.
    """

    level: int
    km: KaplanMeier
    left: int
    seen: int
    waiting: int
    late_leavers: int
    patiences: tuple[float, ...]

    @property
    def n(self) -> int:
        """Patients of the group."""
        return self.km.n

    def truth_survival(self, minutes: float) -> float | None:
        """Share of the group whose true patience is longer than ``minutes``.

        ``None`` without patients. It is the survival the estimate looks for.
        """
        if not self.patiences:
            return None
        return (len(self.patiences) - bisect_right(self.patiences, minutes)) / len(self.patiences)


@dataclass(frozen=True, slots=True)
class PatienceSurvival:
    """The patience of the patients that arrive in a window, by level.

    Attributes:
        by: ``true_level`` (the one the patience depends on) or
            ``assigned_level`` (what the hospital would see).
        groups: One per level, 1 to 5.
        unclassified: With ``assigned_level``, the patients without a level
            (they left before their triage) that are left out; 0 with
            ``true_level``.
    """

    by: PatienceGrouping
    groups: tuple[PatienceGroup, ...]
    unclassified: int


def patience_survival(
    table: Sequence[EpisodeRecord],
    truth: Mapping[str, EpisodeTruth],
    start: float,
    end: float,
    horizon: float,
    by: PatienceGrouping,
) -> PatienceSurvival:
    """Kaplan–Meier of the patience of the patients that arrive in ``[start, end)``.

    The time of each patient is counted from its arrival, as its patience. It is
    an event if it left without being seen (``left``); it is censored at the
    moment a doctor sees it (``first_assessment``, the end of the risk of
    leaving) or, if it still waits, at the ``horizon``.

    Raises:
        ValueError: If ``by`` is not valid, the window is not inside
            ``[0, horizon]``, an episode is not in the truth or lacks its
            clinical truth or outcome, or one departed without being seen.
    """
    if by not in ("true_level", "assigned_level"):
        raise ValueError(f"by must be 'true_level' or 'assigned_level', got {by!r}")
    if not 0 <= start < end <= horizon or not math.isfinite(horizon):
        raise ValueError(f"need 0 <= start < end <= horizon, got {start=}, {end=}, {horizon=}")
    rows: list[list[tuple[float, bool, float, bool, bool]]] = [[] for _ in range(N_LEVELS)]
    unclassified = 0
    for e in table:
        if not start <= e.arrival < end:
            continue
        t = _outcome_truth(truth, e.episode_id)
        level = t.clinical.triage.true_level if by == "true_level" else e.level
        if level is None:
            unclassified += 1
            continue
        if e.left is not None:
            minutes, event, seen = e.left - e.arrival, True, False
        elif e.first_assessment is not None:
            minutes, event, seen = e.first_assessment - e.arrival, False, True
        elif e.departure is not None:
            raise ValueError(f"{e.episode_id} departed without being seen")
        else:
            minutes, event, seen = horizon - e.arrival, False, False
        late = event and minutes > t.outcome.patience + LATE_LEAVE_TOLERANCE
        rows[level - 1].append((minutes, event, t.outcome.patience, seen, late))
    groups = []
    for level, group in enumerate(rows, start=1):
        km = kaplan_meier([r[0] for r in group], [r[1] for r in group])
        groups.append(
            PatienceGroup(
                level=level,
                km=km,
                left=sum(r[1] for r in group),
                seen=sum(r[3] for r in group),
                waiting=sum(not r[1] and not r[3] for r in group),
                late_leavers=sum(r[4] for r in group),
                patiences=tuple(sorted(r[2] for r in group)),
            )
        )
    return PatienceSurvival(by, tuple(groups), unclassified)


@dataclass(frozen=True, slots=True)
class LevelCounterfactual:
    """What the patients of one assigned level did, and what those who left would have done.

    Attributes:
        level: Assigned level, 1 to 5, or ``None`` for whoever left before its
            triage, who has none.
        stayed: Patients of the window who departed (the log gives their destination).
        stayed_admitted: Of them, those admitted.
        left: Patients who left without being seen.
        left_would_admit: Of them, those whose drawn destination was admission
            (the counterfactual: only the ground truth knows it).
        inside: Patients still inside at the horizon, in neither group.
    """

    level: int | None
    stayed: int
    stayed_admitted: int
    left: int
    left_would_admit: int
    inside: int

    @property
    def stayed_share(self) -> float | None:
        """Share of those who stayed that was admitted; ``None`` if none stayed."""
        return self.stayed_admitted / self.stayed if self.stayed else None

    @property
    def left_share(self) -> float | None:
        """Share of those who left that would have been admitted; ``None`` if none left."""
        return self.left_would_admit / self.left if self.left else None


def abandonment_counterfactual(
    table: Sequence[EpisodeRecord],
    truth: Mapping[str, EpisodeTruth],
    start: float,
    end: float,
) -> tuple[LevelCounterfactual, ...]:
    """The admission of those who stayed against that of those who left, by assigned level.

    Six rows: levels 1 to 5 and ``None`` (left before the triage). The admission
    of those who stayed is observed in the log; that of those who left is the
    destination they drew, which no hospital knows (piece 7).

    Raises:
        ValueError: If someone who left is not in the truth or has no outcome.
    """
    keys: tuple[int | None, ...] = (*range(1, N_LEVELS + 1), None)
    rows = []
    arrived = [e for e in table if start <= e.arrival < end]
    for key in keys:
        group = [e for e in arrived if e.level == key]
        left = [e for e in group if e.left is not None]
        stayed = [e for e in group if e.departure is not None]
        would = sum(
            _outcome_truth(truth, e.episode_id).outcome.destination == ADMISSION for e in left
        )
        rows.append(
            LevelCounterfactual(
                level=key,
                stayed=len(stayed),
                stayed_admitted=sum(e.destination == ADMISSION for e in stayed),
                left=len(left),
                left_would_admit=would,
                inside=len(group) - len(left) - len(stayed),
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class SeverityDestinations:
    """The destinations of the patients in one interval of the true severity G.

    Attributes:
        interval: Position of the interval, 0 the most severe, as the rows of
            ``OutcomeModel.by_severity``.
        arrivals: Patients of the window in it.
        left: Of them, those who left without being seen.
        drawn: Patients by drawn destination, all of them (the sampler's draw,
            also of those who left): what the exact shares are compared with
            when the sampler is checked.
        observed: Patients by destination in the log: only those who departed.
    """

    interval: int
    arrivals: int
    left: int
    drawn: Mapping[str, int]
    observed: Mapping[str, int]


def destinations_by_severity(
    table: Sequence[EpisodeRecord],
    truth: Mapping[str, EpisodeTruth],
    edges: Sequence[float],
    start: float,
    end: float,
) -> tuple[SeverityDestinations, ...]:
    """Drawn and observed destinations by interval of G, for the patients of a window.

    Args:
        table: The episodes of the log.
        truth: The ground truth by ``episode_id``.
        edges: Decreasing edges from ``+inf`` to ``-inf``, such as
            ``OutcomeModel.workup.severity_edges(5)``. Interval ``i`` is
            ``(edges[i + 1], edges[i]]``, the convention of ``interval_nodes``,
            so that the rows are those of ``OutcomeModel.by_severity``.
        start: Start of the window.
        end: End of the window.

    Raises:
        ValueError: If the edges are not decreasing from ``+inf`` to ``-inf``, or
            an episode of the window is not in the truth or lacks its outcome.
    """
    bounds = [float(x) for x in edges]
    if len(bounds) < 2 or bounds[0] != math.inf or bounds[-1] != -math.inf:
        raise ValueError("edges must go from +inf to -inf")
    if any(not a > b for a, b in zip(bounds, bounds[1:], strict=False)):
        raise ValueError("edges must be strictly decreasing")
    rising = bounds[::-1]
    n_intervals = len(bounds) - 1
    zero = {d: 0 for d in DESTINATIONS}
    arrivals = [0] * n_intervals
    left = [0] * n_intervals
    drawn = [dict(zero) for _ in range(n_intervals)]
    observed = [dict(zero) for _ in range(n_intervals)]
    for e in table:
        if not start <= e.arrival < end:
            continue
        t = _outcome_truth(truth, e.episode_id)
        i = n_intervals - bisect_left(rising, t.clinical.triage.severity)
        arrivals[i] += 1
        drawn[i][t.outcome.destination] += 1
        if e.left is not None:
            left[i] += 1
        elif e.departure is not None:
            observed[i][e.destination] += 1
    return tuple(
        SeverityDestinations(
            i, arrivals[i], left[i], MappingProxyType(drawn[i]), MappingProxyType(observed[i])
        )
        for i in range(n_intervals)
    )
