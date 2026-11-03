"""Present public run metadata as Spanish tables without importing Streamlit."""

import math
from collections.abc import Sequence
from datetime import datetime

import pandas as pd
from pandas.io.formats.style import Styler

from edsim.runs import SUMMARY_MEASURES, TIMEZONE, OfferedWork, RunInfo, RunResults, WindowKPIs

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
    """Average 15-minute blocks with UTC+1 wall times immune to browser timezone shifts."""
    per_minute = (work.load[pool][:-1] + work.load[pool][1:]) / 2
    return pd.DataFrame(
        {
            "Fecha y hora": (
                pd.Timestamp(work.start_date, tz=TIMEZONE)
                + pd.to_timedelta(work.minutes[:-1:15], unit="min")
            ).tz_localize(None),
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


def format_number(value: float | None, digits: int = 1, *, percentage: bool = False) -> str:
    """Format missing statistics and decimal commas without changing numeric data."""
    if value is None or math.isnan(value):
        return "—"
    suffix = " %" if percentage else ""
    return f"{value * 100 if percentage else value:.{digits}f}".replace(".", ",") + suffix


def kpis_frame(kpis: WindowKPIs) -> pd.DataFrame:
    """Keep numeric KPIs separate from their labels, units and display precision."""
    return pd.DataFrame(
        [
            ("Llegadas por día", kpis.arrivals_per_day, "pacientes/día", 1, False),
            ("Censo medio", kpis.census_mean, "pacientes", 2, False),
            ("Estancia media", kpis.stay_mean, "min", 1, False),
            ("Estancia p90", kpis.stay_p90, "min", 1, False),
            ("Puerta-médico media", kpis.door_to_doctor_mean, "min", 1, False),
            ("Puerta-médico p90", kpis.door_to_doctor_p90, "min", 1, False),
            ("Episodios desalojados", kpis.displaced_episodes, "episodios", 0, False),
            ("Desalojos totales", kpis.total_displacements, "desalojos", 0, False),
            ("Ingreso", kpis.admission_share, "%", 1, True),
        ],
        columns=["Indicador", "Valor", "Unidad", "Decimales", "Porcentaje"],
    )


def waits_frame(result: RunResults) -> pd.DataFrame:
    """Present level waits and integer Manchester exceedances, retaining numbers."""
    rows = []
    for metrics, compliance in zip(
        result.analysis.metrics.by_level, result.compliance.by_level, strict=True
    ):
        row = {"Nivel": metrics.level, "n": metrics.n}
        for measure, label in SUMMARY_MEASURES:
            row[f"{label.capitalize()} media (min)"] = metrics.mean[measure]
            row[f"{label.capitalize()} p90 (min)"] = metrics.p90[measure]
        row.update(
            {
                "Máximo Manchester (min)": compliance.max_wait,
                "Pacientes que superan el máximo": compliance.exceeded,
                "Superan el máximo": compliance.exceeded_share,
                "Días fuera de objetivo": compliance.share_out,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def style_waits(frame: pd.DataFrame) -> Styler:
    """Use Spanish decimal formatting and em dashes for unobserved statistics."""
    formats = {column: "{:.1f}" for column in frame if column.endswith("(min)")}
    formats.update({"Superan el máximo": "{:.1%}", "Días fuera de objetivo": "{:.1%}"})
    return frame.style.format(formats, decimal=",", na_rep="—")
