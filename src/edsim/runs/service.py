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
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.report import config_fingerprint
from edsim.engine.analysis import OutcomeCounts, RunAnalysis, analyze_run, outcome_counts
from edsim.engine.center import CenterConfig, load_center, require_provisional
from edsim.engine.clinical_sampler import ModelChoiceError, PatientModel, choose_model
from edsim.engine.engine import check_horizon, default_run_id, simulate_ed
from edsim.engine.events import OUTCOME_SCHEMA_VERSION, JsonlSink, read_events
from edsim.engine.invariants import Violation, check_invariants
from edsim.engine.outcome_metrics import WindowOutcome, window_outcome
from edsim.engine.report import (
    ProfilesParameters,
    RunParameters,
    write_episodes_csv,
    write_ground_truth_days_csv,
)
from edsim.profiles.config import ClinicalProfiles, load_profiles
from edsim.runs.identifiers import validate_run_id
from edsim.runs.store import FORMAT_VERSION, OUTCOME_FORMAT_VERSION, RunInfo


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
    """Persisted metadata and the complete analysis of a newly simulated run.

    ``outcome_counts`` and ``outcome`` exist only with the milestone 5 model:
    how the episodes of the window end (task 5.3) and the indicators of the
    abandonment, the destinations and the wait for a bed (task 5.4).
    """

    info: RunInfo
    analysis: RunAnalysis
    violations: tuple[Violation, ...]
    outcome_counts: OutcomeCounts | None = None
    outcome: WindowOutcome | None = None


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


def _check_provisional_center(center: str | Path) -> None:
    """Fail before writing anything if the provisional model gets a center without its block,
    or one with ``[camas]`` instead of ``[destino]`` (``choose_model``).

    A center that cannot be read or is not valid is left alone: its error comes
    from the copy, as always, with the same message.
    """
    try:
        config = load_center(center)
    except (OSError, ValueError):
        return
    try:
        require_provisional(config)
    except ValueError as error:
        raise RunConfigurationError(f"{center}: {error}") from error
    # A center with [camas] is of milestone 5, even with the provisional tables (task 5.3).
    try:
        choose_model(config, None, center_file=str(center))
    except ModelChoiceError as error:
        raise RunConfigurationError(str(error)) from error


def patient_model(center: CenterConfig, profiles: ClinicalProfiles | None) -> PatientModel:
    """The model of the patients that a center and its profiles choose (H5-2, task 5.5).

    The app asks it before computing the offered load, which does not exist
    yet for milestone 5 (issue #103).

    Raises:
        RunConfigurationError: If the two files do not choose one model, with
            the message of ``choose_model``.
    """
    try:
        return choose_model(center, profiles)
    except ModelChoiceError as error:
        raise RunConfigurationError(str(error)) from error


def _check_model(center: str | Path, profiles: str | Path) -> None:
    """Fail before writing anything if the two files do not choose one clinical model.

    A milestone 5 block in only one of them (``choose_model``) is an error that
    names the missing key and its file. A file that cannot be read or is not
    valid is left alone: its error comes from the copy, as always.
    """
    try:
        center_config, clinical_profiles = load_center(center), load_profiles(profiles)
    except (OSError, ValueError):
        return
    try:
        choose_model(
            center_config, clinical_profiles, center_file=str(center), profiles_file=str(profiles)
        )
    except ModelChoiceError as error:
        raise RunConfigurationError(str(error)) from error


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
    the copy. The blocks of the profiles and of the center choose milestone 4
    or 5 (``choose_model``); with milestone 5 (task 5.3), the CSV has the
    outcome columns and ``run.json`` is of version 3, with the version of the
    catalog; a block of milestone 5 in only one of the two files is a
    ``RunConfigurationError`` before creating any folder. Without ``profiles``,
    the provisional model, as before, which needs the provisional block of the
    center (``[triaje]``, ``[duraciones]`` and ``[pruebas]``): without it,
    ``RunConfigurationError`` before creating any folder. ``profile`` is always
    the arrival profile.

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
    if profiles is None:
        _check_provisional_center(center)
    else:
        _check_model(center, profiles)
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
        model = PatientModel.PROVISIONAL
        if profiles is not None:
            profiles_copy = temporary / "perfiles.toml"
            _copy_configuration(profiles, profiles_copy)
            clinical_profiles = _load_configuration(load_profiles, profiles, profiles_copy)
            profiles_parameters = ProfilesParameters(
                profiles=str(profiles), profiles_fingerprint=config_fingerprint(profiles_copy)
            )
            try:
                model = choose_model(
                    center_config,
                    clinical_profiles,
                    center_file=str(center),
                    profiles_file=str(profiles),
                )
            except ModelChoiceError as error:  # the copies changed after _check_model
                raise RunConfigurationError(str(error)) from error
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
            outcome=model is PatientModel.MILESTONE_5,
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
        metadata = {}  # the provisional model is the default of RunInfo
        if profiles_parameters is not None:
            metadata = {
                "model": "clinico",
                "clinical_profiles_path": profiles_parameters.profiles,
                "clinical_profiles_fingerprint": profiles_parameters.profiles_fingerprint,
            }
        if model is PatientModel.MILESTONE_5:
            metadata["schema_version"] = model.schema_version
        info = RunInfo(
            format_version=(
                OUTCOME_FORMAT_VERSION if model is PatientModel.MILESTONE_5 else FORMAT_VERSION
            ),
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
            **metadata,
        )
        info.write(temporary / "run.json")
        _check_destination(destination)
        temporary.rename(destination)
        counts = outcome = None
        # The same criterion as read_run_results: the catalog of the log of the run.
        if info.catalog_version == OUTCOME_SCHEMA_VERSION:
            start, end = warmup_days * MINUTES_PER_DAY, days * MINUTES_PER_DAY
            counts = outcome_counts(events, start, end)
            outcome = window_outcome(analysis.table, analysis.curves, start, end)
        return SimulationResult(
            info=info,
            analysis=analysis,
            violations=violations,
            outcome_counts=counts,
            outcome=outcome,
        )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
