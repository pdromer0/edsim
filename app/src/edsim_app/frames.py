"""Present public run metadata as Spanish tables without importing Streamlit."""

import math
from collections.abc import Sequence
from datetime import datetime

import pandas as pd
from pandas.io.formats.style import Styler

from edsim.runs import (
    SUMMARY_MEASURES,
    TIMEZONE,
    OfferedWork,
    RunInfo,
    RunResults,
    WindowKPIs,
    curve_blocks,
    curve_steps,
)

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


CURVE_LABELS = {
    "census": "Censo",
    "waiting_triage": "Cola de triaje",
    "waiting_box": "Cola de box",
    "nurses_busy": "Enfermería de triaje ocupada",
    "doctors_busy": "Médicos ocupados",
    "boxes_busy": "Boxes ocupados",
}


def wall_times(result: RunResults, minutes: object) -> pd.DatetimeIndex:
    """Convert simulation minutes to UTC+1 clock time without a timezone offset."""
    return (
        pd.Timestamp(result.start_date, tz=TIMEZONE) + pd.to_timedelta(minutes, unit="min")
    ).tz_localize(None)


def curve_frame(result: RunResults, name: str, week: int) -> pd.DataFrame:
    """Present one week's supplied exact blocks and capacity steps without mutation."""
    start = week * 7 * 1440
    end = min(start + 7 * 1440, result.analysis.curves.horizon)
    blocks = curve_blocks(result.analysis.curves, name, start, end)
    rows = []
    for label, values in (("Media", blocks.mean), ("Máximo", blocks.maximum)):
        # Repeat the last value only to draw the final block all the way to its end.
        rows.extend(
            {"Fecha y hora": time, "Serie": label, "Valor": float(value)}
            for time, value in zip(
                wall_times(result, blocks.edges), [*values, values[-1]], strict=True
            )
        )
    staff_name = {"nurses_busy": "nurses_staff", "doctors_busy": "doctors_staff"}.get(name)
    if staff_name is not None:
        steps = curve_steps(result.analysis.curves, staff_name, start, end)
        rows.extend(
            {"Fecha y hora": time, "Serie": "Plantilla vigente", "Valor": int(value)}
            for time, value in zip(
                wall_times(result, steps.edges), [*steps.values, steps.values[-1]], strict=True
            )
        )
    elif name == "boxes_busy":
        rows.extend(
            {"Fecha y hora": time, "Serie": "Boxes", "Valor": result.center.boxes}
            for time in wall_times(result, [start, end])
        )
    return pd.DataFrame(rows)


def occupancy_frame(result: RunResults) -> pd.DataFrame:
    """Keep all nine core ratios, including values above one, with Spanish labels."""
    shifts = dict(zip(("morning", "afternoon", "night"), SHIFT_LABELS, strict=True))
    return pd.DataFrame(
        [
            {
                "Recurso": POOL_LABELS[value.pool],
                "Turno": shifts[value.shift],
                "Ocupación": value.ratio,
                "Etiqueta": format_number(value.ratio, percentage=True),
            }
            for value in result.analysis.metrics.occupancy
        ]
    )


def hourly_census_frame(result: RunResults) -> pd.DataFrame:
    """Expose the core's 24 hour-of-day means as a fresh presentation table."""
    return pd.DataFrame({"Hora del día": range(24), "Censo medio": result.hourly_census.copy()})


def little_frame(result: RunResults) -> pd.DataFrame:
    """Present operational laws with their original units and the CLI's product."""
    labels = {"system": "Sistema", "triage_queue": "Cola de triaje", "box_queue": "Cola de box"}
    return pd.DataFrame(
        [
            {
                "Ámbito": labels[law.name],
                "L": law.l,
                "λ (pacientes/min)": law.lam,
                "W (min)": law.w,
                "λ·W": law.lam * law.w,
                "Error relativo": law.relative_error,
            }
            for law in result.analysis.little
        ]
    )


def style_little(frame: pd.DataFrame) -> Styler:
    """Preserve numbers while matching CLI precision for L, product and error."""
    return frame.style.format(
        {
            "L": "{:.4f}",
            "λ (pacientes/min)": "{:.6f}",
            "W (min)": "{:.4f}",
            "λ·W": "{:.4f}",
            "Error relativo": "{:.2%}",
        },
        decimal=",",
    )
