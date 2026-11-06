"""Create complete, reproducible runs before publishing them to disk."""

import shutil
import stat
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
from edsim.engine.report import (
    ProfilesParameters,
    RunParameters,
    write_episodes_csv,
    write_ground_truth_days_csv,
)
from edsim.profiles.config import load_profiles
from edsim.runs.identifiers import validate_run_id
from edsim.runs.store import FORMAT_VERSION, RunInfo


class RunConfigurationError(ValueError):
    """An original configuration cannot be read or its saved copy is invalid."""


def _copy_configuration(source: str | Path, destination: Path) -> None:
    """Classify original read failures without concealing destination write errors."""
    try:
        data = Path(source).read_bytes()
    except OSError as error:
        raise RunConfigurationError(f"{source}: {error}") from error
    destination.write_bytes(data)


def _load_configuration[T](loader: Callable[[Path], T], original: str | Path, copy: Path) -> T:
    """Validate a saved configuration, keeping the original path in diagnostics."""
    try:
        return loader(copy)
    except ValueError as error:
        raise RunConfigurationError(f"{original}: {error}") from error


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
    profiles: str | Path | None = None,
    clock: Callable[[], datetime] = _utc_now,
    timer: Callable[[], float] = perf_counter,
) -> SimulationResult:
    """Simulate from exact configuration copies and atomically publish a run.

    With ``profiles``, the path of a ``perfiles.toml``, the run uses the
    clinical model: the file is copied to the run as ``perfiles.toml`` and
    loaded from the copy, like the center and the arrival profile; the episodes
    CSV is the clinical one, the invariants are checked with the profiles (the
    turnaround of each round against the shift band of its order) and
    ``run.json`` records the model, the original path and the fingerprint of
    the copy. Without it, the provisional model, as before. ``profile`` is
    always the arrival profile.

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
        # Observe normal mkdir permissions without changing the process-wide umask.
        mode_reference = temporary / ".permissions"
        mode_reference.mkdir()
        temporary.chmod(stat.S_IMODE(mode_reference.stat().st_mode))
        mode_reference.rmdir()
        center_copy, profile_copy = temporary / "centro.toml", temporary / "llegadas.toml"
        _copy_configuration(center, center_copy)
        _copy_configuration(profile, profile_copy)
        center_config = _load_configuration(load_center, center, center_copy)
        arrival_profile = _load_configuration(load_profile, profile, profile_copy)
        center_fingerprint = config_fingerprint(center_copy)
        profile_fingerprint = config_fingerprint(profile_copy)
        clinical_profiles, profiles_parameters = None, None
        if profiles is not None:
            profiles_copy = temporary / "perfiles.toml"
            _copy_configuration(profiles, profiles_copy)
            clinical_profiles = _load_configuration(load_profiles, profiles, profiles_copy)
            profiles_parameters = ProfilesParameters(
                profiles=str(profiles), profiles_fingerprint=config_fingerprint(profiles_copy)
            )
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
                profiles=clinical_profiles,
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
            result.ground_truth.episodes,
            temporary / "ground_truth_episodios.csv",
            parameters,
            profiles_parameters,
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
                profiles=clinical_profiles,
            )
        )
        analysis = analyze_run(events, center_config, days, warmup_days)
        model = {}  # the provisional model is the default of RunInfo
        if profiles_parameters is not None:
            model = {
                "model": "clinico",
                "clinical_profiles_path": profiles_parameters.profiles,
                "clinical_profiles_fingerprint": profiles_parameters.profiles_fingerprint,
            }
        info = RunInfo(
            format_version=FORMAT_VERSION,
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
            **model,
        )
        info.write(temporary / "run.json")
        _check_destination(destination)
        temporary.rename(destination)
        return SimulationResult(info=info, analysis=analysis, violations=violations)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
