"""Present public run metadata as Spanish tables without importing Streamlit."""

from collections.abc import Sequence
from datetime import datetime

import pandas as pd
from pandas.io.formats.style import Styler

from edsim.engine.events import TIMEZONE
from edsim.runs import OfferedWork, RunInfo

COLUMNS = (
    "Ejecución",
    "Variante del centro",
    "Fecha de creación (UTC+1)",
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


POOL_LABELS = {"medicos": "Médicos", "boxes": "Boxes", "enfermeria_triaje": "Enfermería de triaje"}
SHIFT_LABELS = ("Mañana", "Tarde", "Noche")


def offered_frame(work: OfferedWork, pool: str) -> pd.DataFrame:
    """Average minute trapezoids and step capacities in 15-minute blocks."""
    per_minute = (work.load[pool][:-1] + work.load[pool][1:]) / 2
    return pd.DataFrame(
        {
            "Fecha y hora": pd.Timestamp(work.start_date, tz=TIMEZONE)
            + pd.to_timedelta(work.minutes[:-1:15], unit="min"),
            "Carga ofrecida": per_minute.reshape(-1, 15).mean(axis=1),
            "Capacidad": work.capacity[pool][:-1].reshape(-1, 15).mean(axis=1),
        }
    )


def utilization_frame(work: OfferedWork) -> pd.DataFrame:
    """Present core utilization values without recomputing them from the chart."""
    return pd.DataFrame(
        [
            {
                "Recurso": label,
                "Turno": shift,
                "Utilización": value,
                "Estado": "Por encima de 1"
                if value > 1
                else "Por encima de 0,85"
                if value > 0.85
                else "Hasta 0,85",
            }
            for pool, label in POOL_LABELS.items()
            for shift, value in zip(SHIFT_LABELS, work.utilization[pool], strict=True)
        ]
    )


def style_utilization(frame: pd.DataFrame) -> Styler:
    """Highlight thresholds with text and color, preserving numeric values."""
    colors = {"Por encima de 1": "#ffdddd", "Por encima de 0,85": "#fff0cc"}
    return frame.style.format({"Utilización": "{:.1%}"}, decimal=",").map(
        lambda value: f"background-color: {colors[value]}" if value in colors else "",
        subset=["Estado"],
    )
