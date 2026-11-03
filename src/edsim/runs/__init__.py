"""Public services for persisted EDsim runs, independent of the UI."""

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.report import config_fingerprint
from edsim.engine.analysis import EpisodeRecord, RunAnalysis, StepCurves, WindowMetrics
from edsim.engine.center import (
    CenterConfig,
    center_from_values,
    load_center,
    read_center_values,
    validate_center_values,
)
from edsim.runs.identifiers import validate_run_id
from edsim.runs.metrics import (
    LevelCompliance,
    WindowCompliance,
    WindowKPIs,
    window_compliance,
    window_kpis,
)
from edsim.runs.offered import OfferedWork, offered_work
from edsim.runs.service import RunConfigurationError, SimulationResult, simulate_run
from edsim.runs.store import RunInfo, RunStore
from edsim.runs.summary import CenterSummary, DurationSummary, summarize_center
from edsim.runs.variants import (
    MAX_VARIANT_NAME_LENGTH,
    CenterDifference,
    center_diff,
    list_variants,
    write_variant,
)

__all__ = [
    "ArrivalProfile",
    "CenterConfig",
    "CenterDifference",
    "CenterSummary",
    "DurationSummary",
    "EpisodeRecord",
    "LevelCompliance",
    "MAX_VARIANT_NAME_LENGTH",
    "OfferedWork",
    "RunConfigurationError",
    "RunAnalysis",
    "RunInfo",
    "RunStore",
    "SimulationResult",
    "StepCurves",
    "WindowCompliance",
    "WindowKPIs",
    "WindowMetrics",
    "center_diff",
    "center_from_values",
    "config_fingerprint",
    "list_variants",
    "load_center",
    "load_profile",
    "offered_work",
    "read_center_values",
    "simulate_run",
    "summarize_center",
    "validate_center_values",
    "validate_run_id",
    "write_variant",
    "window_compliance",
    "window_kpis",
]
