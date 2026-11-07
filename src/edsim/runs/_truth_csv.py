"""Exact readers of the saved ground truth CSVs of a run, checked against run.json.

Private to ``edsim.runs``: ``results.py`` reads the ground truth only to recount
violations and ``truth.py`` shows it. Both use these readers, which live apart
so that ``truth.py`` can keep importing ``results.py``.
"""

import csv
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from types import MappingProxyType

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import DayRecord
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.report import (
    CLINICAL_EPISODE_COLUMNS,
    DAY_COLUMNS,
    PARAMETER_COLUMNS,
    episode_from_row,
)
from edsim.runs.store import RunInfo, RunStore

EPISODES_FILE = "ground_truth_episodios.csv"
DAYS_FILE = "ground_truth_dias.csv"


def parameter_values(info: RunInfo) -> tuple[str, ...]:
    """The eight run parameters as the CSV writers write them, in column order."""
    return (
        info.center_path,
        info.center_fingerprint,
        info.profile_path,
        info.profile_fingerprint,
        str(info.days),
        str(info.warmup_days),
        str(info.seed),
        info.run_id,
    )


def check_parameters(row: Mapping[str, str], info: RunInfo) -> None:
    """Raise ``ValueError`` if a repeated run parameter differs from run.json."""
    for column, value in zip(PARAMETER_COLUMNS, parameter_values(info), strict=True):
        if row[column] != value:
            raise ValueError(f"{column} does not match run.json")


def read_rows[T](
    store: RunStore,
    run_id: str,
    name: str,
    header: Sequence[str],
    parse: Callable[[dict[str, str], int], T],
) -> list[T]:
    """Parse every row of a saved CSV with an exact header.

    ``parse`` receives the row and its index, starting at 0. Any failure is a
    ``ValueError`` whose message starts with ``path:line``, the physical line
    of the CSV (the header is line 1), or with the path alone if the file
    cannot be opened.
    """
    path = store.root / run_id / name
    reader = None
    rows = []
    try:
        with store._file(run_id, name).open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            if tuple(reader.fieldnames or ()) != tuple(header):
                raise ValueError(f"invalid header of {name}")
            for index, row in enumerate(reader):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("incomplete or extra CSV fields")
                rows.append(parse(row, index))
    except (OSError, ValueError, KeyError, csv.Error) as error:
        where = f"{path}:{max(1, reader.line_num)}" if reader is not None else str(path)
        raise ValueError(f"{where}: {error}") from error
    return rows


def clinical_episode(row: Mapping[str, str], info: RunInfo) -> EpisodeTruth:
    """One row of the clinical episodes CSV, with its parameters and profiles checked."""
    check_parameters(row, info)
    if row["perfiles"] != info.clinical_profiles_path:
        raise ValueError("perfiles does not match run.json")
    if row["huella_perfiles"] != info.clinical_profiles_fingerprint:
        raise ValueError("huella_perfiles does not match run.json")
    truth = episode_from_row(row)
    if truth.clinical is None:
        raise ValueError("the row has no clinical truth")
    if truth.arrival_time >= info.days * MINUTES_PER_DAY:
        raise ValueError("minuto_llegada is outside the run horizon")
    return truth


def read_clinical_episodes(
    store: RunStore, run_id: str, info: RunInfo
) -> Mapping[str, EpisodeTruth]:
    """The clinical episodes CSV of a run, by episode, read-only.

    Raises:
        ValueError: With ``path:line``, if the header is not
            ``CLINICAL_EPISODE_COLUMNS``, a row is invalid (``episode_from_row``),
            its parameters, profiles path or profiles fingerprint differ from
            run.json, or an episode is repeated.
    """
    episodes: dict[str, EpisodeTruth] = {}

    def parse(row: dict[str, str], _: int) -> EpisodeTruth:
        truth = clinical_episode(row, info)
        if truth.episode_id in episodes:
            raise ValueError(f"duplicate episode {truth.episode_id}")
        episodes[truth.episode_id] = truth
        return truth

    read_rows(store, run_id, EPISODES_FILE, CLINICAL_EPISODE_COLUMNS, parse)
    return MappingProxyType(episodes)


def _integer(row: Mapping[str, str], column: str) -> int:
    text = row[column]
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{column} must be an integer, got {text!r}") from None
    if str(value) != text or value < 0:
        raise ValueError(f"{column} must be a non-negative integer, got {text!r}")
    return value


def _real(row: Mapping[str, str], column: str) -> float:
    text = row[column]
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{column} must be a number, got {text!r}") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{column} must be finite and non-negative, got {text!r}")
    return value


def read_days(
    store: RunStore, run_id: str, info: RunInfo, start_date: date
) -> tuple[DayRecord, ...]:
    """The day records of a run, as ``write_ground_truth_days_csv`` wrote them.

    Floats are read bit for bit (the writer uses ``str``, which is ``repr``).
    Day k must be row k, dated ``start_date + k`` days, and there must be one
    row per day of the run.

    Raises:
        ValueError: With ``path:line``, if the header is not ``DAY_COLUMNS``,
            a value is invalid, a parameter differs from run.json, or a day is
            missing, repeated or out of order.
    """

    def parse(row: dict[str, str], index: int) -> DayRecord:
        check_parameters(row, info)
        day = _integer(row, "dia")
        if day != index:
            raise ValueError(f"dia must be {index}, got {day}")
        text = row["fecha"]
        try:
            when = date.fromisoformat(text)
        except ValueError:
            raise ValueError(f"fecha must be an ISO date, got {text!r}") from None
        if when.isoformat() != text or when != start_date + timedelta(days=index):
            raise ValueError(f"fecha of dia {index} must be {start_date + timedelta(days=index)}")
        if index >= info.days:
            raise ValueError(f"the run has {info.days} days")
        return DayRecord(
            day=day,
            date=when,
            day_effect=_real(row, "efecto_diario"),
            expected=_real(row, "esperadas"),
            bound=_real(row, "cota"),
            candidates=_integer(row, "candidatas"),
            accepted=_integer(row, "aceptadas"),
        )

    days = read_rows(store, run_id, DAYS_FILE, DAY_COLUMNS, parse)
    if len(days) != info.days:
        raise ValueError(
            f"{store.root / run_id / DAYS_FILE}: {len(days)} days, run.json has {info.days}"
        )
    return tuple(days)
