"""Read exact episode draws and compare complete or censored observations."""

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from edsim.engine.events import DOOR, Event, episode_id
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.report import EPISODE_COLUMNS, PARAMETER_COLUMNS
from edsim.runs.episodes import EpisodeSegments
from edsim.runs.results import RunReadError, read_run_header
from edsim.runs.store import RunInfo, RunStore

TRUTH_ABS_TOL_MINUTES = 1e-8
"""Fixed before measuring: 0.6 microseconds; no relative tolerance."""

TruthStatus = Literal["match", "mismatch", "partial", "pending", "unused"]


@dataclass(frozen=True, slots=True)
class TruthComparison:
    """One drawn value and its observed minutes, level or destination."""

    field: str
    drawn: int | float | str
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
    """
    info, _ = read_run_header(store, run_id)
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


def compare_episode_truth(
    events: Sequence[Event], segments: EpisodeSegments, truth: EpisodeTruth
) -> tuple[TruthComparison, ...]:
    """Compare stages using sim_time and all interrupted attention segments.

    A finished duration matches within absolute 1e-8 minutes, relative zero.
    A started stage is partial until its non-interrupted end; partial work
    exceeding its draw plus tolerance is a mismatch. Never-started stages
    are pending; reassessment and turnaround without tests are unused, and so
    is the triage time of a triage at the door (``circuito`` ``puerta``).
    """
    if (
        not events
        or segments.episode_id != truth.episode_id
        or any(event.episode_id != truth.episode_id for event in events)
    ):
        raise ValueError("events, segments and truth must belong to the same episode")
    by_type = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)

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
    drawn_destination = "ingreso" if truth.admitted else "alta"
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
            truth.test_turnaround,
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
