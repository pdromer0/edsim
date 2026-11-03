"""Create complete, reproducible runs before publishing them to disk."""

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Literal

from edsim.arrivals.profile import load_profile
from edsim.arrivals.report import config_fingerprint
from edsim.engine.analysis import RunAnalysis, analyze_run
from edsim.engine.center import load_center
from edsim.engine.engine import check_horizon, default_run_id, simulate_ed
from edsim.engine.events import JsonlSink, read_events
from edsim.engine.invariants import Violation, check_invariants
from edsim.engine.report import RunParameters, write_episodes_csv, write_ground_truth_days_csv
from edsim.runs.identifiers import validate_run_id
from edsim.runs.store import RunInfo


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Persisted metadata and the complete analysis of a newly simulated run."""

    info: RunInfo
    analysis: RunAnalysis
    violations: tuple[Violation, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _check_destination(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"destination already exists: {path}")
    for parent in path.parents:
        if parent.exists():
            if not parent.is_dir():
                raise NotADirectoryError(f"not a directory: {parent}")
            break


def simulate_run(
    center: str | Path,
    profile: str | Path,
    days: int,
    seed: int,
    *,
    output_dir: str | Path,
    warmup_days: int = 2,
    run_id: str | None = None,
    origin: Literal["app", "cli"],
    variant: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
    timer: Callable[[], float] = perf_counter,
) -> SimulationResult:
    """Simulate from exact configuration copies and atomically publish a run.

    Original path strings are retained as provenance in metadata and CSVs.
    The timer covers simulate_ed and its streaming log writes only. All
    invariants are checked against the written log, ground truth and inside
    count. Violations are saved rather than treated as persistence errors.
    Exceptions, including KeyboardInterrupt, remove the temporary directory.
    """
    check_horizon(days, warmup_days)
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if run_id is None:
        run_id = default_run_id(seed)
        try:
            validate_run_id(run_id)
        except ValueError as error:
            raise ValueError(
                "default run_id is invalid; provide an explicit run_id (--run-id)"
            ) from error
    else:
        validate_run_id(run_id)
    if origin not in ("app", "cli"):
        raise ValueError("origin must be app or cli")
    variant = Path(center).stem if variant is None else variant
    if not isinstance(variant, str) or not variant:
        raise ValueError("variant must be a non-empty string")
    destination = Path(output_dir)
    _check_destination(destination)
    created_at = clock()
    if not isinstance(created_at, datetime) or created_at.utcoffset() is None:
        raise ValueError("clock must return a datetime with timezone")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}-", dir=destination.parent))
    try:
        center_copy, profile_copy = temporary / "centro.toml", temporary / "llegadas.toml"
        shutil.copyfile(center, center_copy)
        shutil.copyfile(profile, profile_copy)
        center_config = load_center(center_copy)
        arrival_profile = load_profile(profile_copy)
        center_fingerprint = config_fingerprint(center_copy)
        profile_fingerprint = config_fingerprint(profile_copy)
        events_path = temporary / "eventos.jsonl"
        with JsonlSink(events_path) as sink:
            start = timer()
            result = simulate_ed(
                center_config,
                arrival_profile,
                days,
                seed,
                sink=sink,
                warmup_days=warmup_days,
                run_id=run_id,
            )
            simulation_seconds = timer() - start
        parameters = RunParameters(
            center=str(center),
            center_fingerprint=center_fingerprint,
            profile=str(profile),
            profile_fingerprint=profile_fingerprint,
            days=days,
            warmup_days=warmup_days,
            seed=seed,
            run_id=run_id,
        )
        write_episodes_csv(
            result.ground_truth.episodes, temporary / "ground_truth_episodios.csv", parameters
        )
        write_ground_truth_days_csv(
            result.ground_truth.days, temporary / "ground_truth_dias.csv", parameters
        )
        events = list(read_events(events_path))
        violations = tuple(
            check_invariants(
                events,
                center_config,
                ground_truth=result.ground_truth,
                inside=result.inside,
            )
        )
        analysis = analyze_run(events, center_config, days, warmup_days)
        info = RunInfo(
            format_version=1,
            run_id=run_id,
            created_at=created_at.isoformat(),
            origin=origin,
            edsim_version=version("edsim"),
            seed=seed,
            days=days,
            warmup_days=warmup_days,
            variant=variant,
            center_fingerprint=center_fingerprint,
            profile_fingerprint=profile_fingerprint,
            center_path=str(center),
            profile_path=str(profile),
            invariant_violations=len(violations),
            window_arrivals=analysis.metrics.arrivals,
            simulation_seconds=simulation_seconds,
        )
        info.write(temporary / "run.json")
        _check_destination(destination)
        temporary.rename(destination)
        return SimulationResult(info=info, analysis=analysis, violations=violations)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
