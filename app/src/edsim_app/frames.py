"""Present public run metadata as Spanish tables without importing Streamlit."""

from collections.abc import Sequence
from datetime import datetime

import pandas as pd
from pandas.io.formats.style import Styler

from edsim.engine.events import TIMEZONE
from edsim.runs import RunInfo

COLUMNS = (
    "Ejecución",
    "Variante del centro",
    "Fecha de creación",
    "Días",
    "Calentamiento (días)",
    "Semilla",
    "Huella del centro",
    "Llegadas por día",
    "Invariantes",
    "Origen",
)


def runs_frame(runs: Sequence[RunInfo]) -> pd.DataFrame:
    """Convert catalog metadata without changing its order or numeric values."""
    return pd.DataFrame(
        [
            (
                info.run_id,
                info.variant,
                datetime.fromisoformat(info.created_at)
                .astimezone(TIMEZONE)
                .strftime("%d/%m/%Y %H:%M:%S"),
                info.days,
                info.warmup_days,
                info.seed,
                info.center_fingerprint[:8],
                info.arrivals_per_day,
                "correctas"
                if info.invariant_violations == 0
                else f"{info.invariant_violations} violaciones",
                "app" if info.origin == "app" else "CLI",
            )
            for info in runs
        ],
        columns=COLUMNS,
    )


def style_runs(frame: pd.DataFrame) -> Styler:
    """Use a decimal comma while keeping numeric columns sortable as numbers."""
    return frame.style.format({"Llegadas por día": "{:.1f}"}, decimal=",")
